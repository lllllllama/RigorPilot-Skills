"""A deterministic teaching check, not a scientific model evaluation."""
import json
from pathlib import Path

asset = Path("ready.json")
if not asset.exists():
    raise SystemExit("missing asset: ready.json")
values = json.loads(asset.read_text(encoding="utf-8"))["values"]
if values != [1, 2, 3] or sum(values) != 6:
    raise SystemExit("verification failed: unexpected asset contents")
print("verified: sum=6")
