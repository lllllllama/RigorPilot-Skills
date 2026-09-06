"""Single-trial, single-owner durable accounting; no provider or credential access.

Reservations gate dispatch and actual provider usage gates subsequent actions.
This is reservation_plus_post_response_stop, not an absolute billing guarantee.
The caller owns the directory exclusively: this is not a multiprocess lock,
campaign-wide accountant, authenticated audit log, or subscription quota reader.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import time


LIMIT_KEYS = {"max_total_tokens", "max_model_calls", "max_tool_calls", "max_seconds"}
USAGE_KEYS = {"input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"}
MAX_LEDGER_BYTES = 2 * 1024**2


class BudgetStop(RuntimeError):
    """Dispatch must stop; retained evidence must not be retried or discarded."""


def _integer(value: object, minimum: int = 0) -> bool:
    return type(value) is int and value >= minimum


def _finite(value: object) -> bool:
    try:
        return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)
    except OverflowError:
        return False


def _object(pairs: list[tuple]) -> dict:
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate ledger key")
        value[key] = item
    return value


def _request_id(value: object) -> bool:
    return isinstance(value, str) and 0 < len(value) <= 128 and value.isascii() and all(
        char.isalnum() or char in "-_.:" for char in value)


class BudgetLedger:
    def __init__(self, path: Path, limits: dict, clock=time.time):
        if (not isinstance(limits, dict) or set(limits) != LIMIT_KEYS
                or not all(_integer(value, 1) for value in limits.values())):
            raise ValueError("limits require exactly four positive integer token/call/time caps")
        self.path, self.limits, self.clock = Path(path), dict(limits), clock
        self.status, self.reason, self.unknown = "active", None, False
        self.model_calls = self.tool_calls = self.known_tokens = 0
        self.usage = {key: 0 for key in sorted(USAGE_KEYS)}
        self.pending, self.request_ids = {}, set()
        self.sequence, self.expected_bytes = 0, 0
        self.started_at = self.last_at = None
        if self.path.is_symlink() or (hasattr(self.path, "is_junction") and self.path.is_junction()):
            raise ValueError("ledger must not be linked")
        if self.path.exists():
            if not self.path.is_file() or self.path.stat().st_size > MAX_LEDGER_BYTES:
                raise BudgetStop("ledger is not a bounded regular file; evidence retained")
            data = self.path.read_bytes()
            if not data or not data.endswith(b"\n"):
                raise BudgetStop("ledger is empty or truncated; evidence retained")
            try:
                for line in data.splitlines():
                    self._apply(json.loads(line, object_pairs_hook=_object))
            except (ValueError, TypeError, KeyError, UnicodeError) as error:
                raise BudgetStop("invalid ledger history; evidence retained") from error
            self.expected_bytes = len(data)
            if self.pending and self.status == "active":
                self._append("unknown", reason="recovered pending request: outcome and usage are unknown")
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._append("created", limits=self.limits, exclusive=True)

    def _now(self) -> float:
        value = self.clock()
        if not _finite(value):
            raise ValueError("clock must return a finite numeric timestamp")
        return float(value)

    def _apply(self, event: dict) -> None:
        if (not isinstance(event, dict) or not _integer(event.get("sequence"))
                or event["sequence"] != self.sequence or not _finite(event.get("at"))):
            raise ValueError("invalid event identity or timestamp")
        kind = event.get("type")
        fields = {
            "created": {"limits"}, "reserved": {"request_id", "input_reservation", "max_output_tokens"},
            "settled": {"request_id", "usage"}, "tool": set(),
            "unknown": {"reason"}, "stopped": {"reason"},
        }
        if kind not in fields or set(event) != {"sequence", "at", "type"} | fields[kind]:
            raise ValueError("invalid event fields")
        if self.status != "active" or (self.sequence == 0) != (kind == "created"):
            raise ValueError("event is outside the active ledger lifecycle")
        if kind == "created":
            if (not isinstance(event["limits"], dict) or set(event["limits"]) != LIMIT_KEYS
                    or not all(_integer(value, 1) for value in event["limits"].values())
                    or event["limits"] != self.limits):
                raise ValueError("recovery limits differ from the original limits")
            self.started_at = event["at"]
        elif kind == "reserved":
            request = event["request_id"]
            incoming, outgoing = event["input_reservation"], event["max_output_tokens"]
            if (not _request_id(request) or request in self.request_ids or self.pending
                    or not _integer(incoming, 1) or not _integer(outgoing, 1)
                    or self.model_calls >= self.limits["max_model_calls"]
                    or self.known_tokens + incoming + outgoing > self.limits["max_total_tokens"]):
                raise ValueError("invalid reservation history")
            self.pending[request] = {"input_reservation": incoming, "max_output_tokens": outgoing,
                                     "reserved_tokens": incoming + outgoing}
            self.request_ids.add(request)
            self.model_calls += 1
        elif kind == "settled":
            if event["request_id"] not in self.pending or not self._valid_usage(event["usage"]):
                raise ValueError("invalid settlement history")
            for key in self.usage:
                amount = event["usage"].get(key, 0)
                self.usage[key] += amount
                self.known_tokens += amount
            del self.pending[event["request_id"]]
            if self.known_tokens > self.limits["max_total_tokens"]:
                self.status, self.reason = "stopped", "provider usage exceeded token cap; no further actions"
        elif kind == "tool":
            if self.pending or self.tool_calls >= self.limits["max_tool_calls"]:
                raise ValueError("invalid tool dispatch history")
            self.tool_calls += 1
        else:
            if not isinstance(event["reason"], str) or not event["reason"] or len(event["reason"]) > 1024:
                raise ValueError("invalid stop reason")
            self.status, self.reason = "stopped", event["reason"]
            self.unknown = kind == "unknown"
        self.last_at = event["at"]
        self.sequence += 1

    def _append(self, kind: str, *, exclusive: bool = False, **fields) -> None:
        event = {"sequence": self.sequence, "at": self._now(), "type": kind, **fields}
        payload = (json.dumps(event, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
        if self.expected_bytes + len(payload) > MAX_LEDGER_BYTES:
            raise BudgetStop("ledger size limit reached; no further dispatch")
        if not exclusive and (self.path.is_symlink() or self.path.stat().st_size != self.expected_bytes):
            raise BudgetStop("ledger changed outside this owner; no further dispatch")
        try:
            with self.path.open("xb" if exclusive else "ab") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
        except OSError as error:
            self.status, self.reason = "stopped", "ledger durability failed; no further dispatch"
            self.unknown = self.unknown or bool(self.pending)
            raise BudgetStop(self.reason) from error
        self._apply(event)
        self.expected_bytes += len(payload)

    @staticmethod
    def _valid_usage(usage: object) -> bool:
        return (isinstance(usage, dict) and {"input_tokens", "output_tokens"} <= set(usage) <= USAGE_KEYS
                and all(_integer(value) for value in usage.values()))

    def _stop(self, reason: str, *, unknown: bool = False) -> None:
        if self.status == "active":
            self._append("unknown" if unknown else "stopped", reason=reason)
        raise BudgetStop(self.reason or reason)

    def check(self) -> None:
        if self.status != "active":
            raise BudgetStop(self.reason)
        now = self._now()
        if now < self.last_at:
            self._stop("clock moved backwards; elapsed budget cannot be trusted", unknown=bool(self.pending))
        if now - self.started_at >= self.limits["max_seconds"]:
            self._stop("trial time cap reached", unknown=bool(self.pending))

    def reserve(self, request_id: str, input_reservation: int, max_output_tokens: int) -> None:
        self.check()
        if (not _request_id(request_id) or not _integer(input_reservation, 1)
                or not _integer(max_output_tokens, 1)):
            raise ValueError("request ID and positive integer input/output reservations are required")
        if self.pending:
            self._stop("another request is pending; usage is unknown", unknown=True)
        if request_id in self.request_ids:
            self._stop("request ID already dispatched; automatic replay refused")
        if self.model_calls >= self.limits["max_model_calls"]:
            self._stop("model call cap reached")
        if self.known_tokens + input_reservation + max_output_tokens > self.limits["max_total_tokens"]:
            self._stop("token reservation cap reached")
        self._append("reserved", request_id=request_id, input_reservation=input_reservation,
                     max_output_tokens=max_output_tokens)

    def settle(self, request_id: str, usage: dict) -> None:
        # Settle an in-flight response before checking elapsed time so known
        # billable usage is retained even when the response arrives too late.
        if self.status != "active":
            raise BudgetStop(self.reason)
        if not _request_id(request_id) or request_id not in self.pending:
            self._stop("settlement has an unknown request ID", unknown=True)
        if not self._valid_usage(usage):
            self._stop("provider usage is missing, malformed, or has unsupported fields", unknown=True)
        self._append("settled", request_id=request_id, usage=usage)
        self.check()

    def mark_unknown(self, reason: str) -> None:
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 1024:
            raise ValueError("unknown outcome requires a short nonempty public reason")
        self._stop(reason, unknown=True)

    def stop(self, reason: str) -> None:
        """Persist and return; later check/dispatch raises BudgetStop.

        Unresolved reservations remain unknown. Returning normally lets callers
        record the rest of a failure report without a second exception.
        """
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 1024:
            raise ValueError("stop requires a short nonempty public reason")
        if self.status == "active":
            self._append("unknown" if self.pending else "stopped", reason=reason)

    def tool_call(self) -> None:
        self.check()
        if self.pending:
            self._stop("cannot dispatch a tool before usage settlement", unknown=True)
        if self.tool_calls >= self.limits["max_tool_calls"]:
            self._stop("tool call cap reached")
        self._append("tool")

    def snapshot(self) -> dict:
        complete = not self.unknown and not self.pending
        elapsed = max(0, (self.last_at if self.status == "stopped" else self._now()) - self.started_at)
        return {"scope": "single_trial", "enforcement": "reservation_plus_post_response_stop",
                "limits": dict(self.limits), "status": self.status, "reason": self.reason,
                "known_tokens": self.known_tokens, "tokens_used": self.known_tokens if complete else None,
                "usage_complete": complete, "usage_unknown": self.unknown, "usage": dict(self.usage),
                "model_calls": self.model_calls, "tool_calls": self.tool_calls,
                "pending": {key: dict(value) for key, value in self.pending.items()},
                "reserved_tokens": sum(value["reserved_tokens"] for value in self.pending.values()),
                "elapsed_seconds": elapsed, "remaining_seconds": max(0, self.limits["max_seconds"] - elapsed),
                "budget_compliant": None if not complete else (
                    self.known_tokens <= self.limits["max_total_tokens"] and elapsed <= self.limits["max_seconds"])}
