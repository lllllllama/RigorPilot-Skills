<!-- rigorpilot:repro:begin kind="banner" section="__banner__" occurrence="1" status="partial" risk="none" -->

# 📄 README · RigorPilot annotations

🟡 `partial` · `training` · `trusted` · [SUMMARY](../repro_outputs/SUMMARY.md) · [COMMANDS](../repro_outputs/COMMANDS.md) · [LOG](../repro_outputs/LOG.md) · [status.json](../repro_outputs/status.json) · [train status](../train_outputs/status.json)

Section coverage: 🟣 1 (1 sections) · score 0.25

<sub>🟢 success · 🔵 not executed · ⚪ read only · 🟡 partial / assets missing · 🔴 blocked · 🟣 decision needed — original content unchanged; its relative links resolve against the repo root.</sub>

<sub>original_sha256: `21c0721b44a37f18277d655d91a087e81651dc4a1849fc778b91075b741d32f6` · round-trip: verified</sub>

---

<!-- rigorpilot:repro:end -->
# Basic MNIST Example

```bash
pip install -r requirements.txt
python main.py
# CUDA_VISIBLE_DEVICES=2 python main.py  # to specify GPU id to ex. 2
```
<!-- rigorpilot:repro:begin kind="section" section="Basic MNIST Example" occurrence="1" status="decision" risk="high" -->

> [!IMPORTANT]
> 🟣 **Startup verified · fuller training needs your explicit approval**
> Command: `python main.py`
> Blocker: The run exceeded the 60-second monitoring window.
> Observed metrics: `loss=0.038893`
> Suggested next: Review `train_outputs/status.json`, then decide whether to authorize a fuller training reproduction run. Planned command: `python main.py`. Estimated duration: unknown; likely hours to multi-day on the full dataset until a bounded schedule is confirmed.
> <sub>Evidence: [SUMMARY](../repro_outputs/SUMMARY.md) · [COMMANDS](../repro_outputs/COMMANDS.md) · [LOG](../repro_outputs/LOG.md) · [status.json](../repro_outputs/status.json) · [train status](../train_outputs/status.json) · tier: execution</sub>

<!-- rigorpilot:repro:end -->
