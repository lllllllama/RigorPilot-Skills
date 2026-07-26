# Commands

## Setup

```bash
# [adapted]
# platforms: windows, macos, linux
python -m venv .venv
# [adapted]
# platforms: windows
.\.venv\Scripts\Activate.ps1
# [adapted]
# platforms: macos, linux
source .venv/bin/activate
# [documented]
# platforms: windows, macos, linux
python -m pip install -r requirements.txt
```

## Assets

```bash
# [inferred]
# Prepare datasets assets under /home/user/demo/first/artifacts/assets/datasets before the documented run.
# [inferred]
# Prepare data assets under /home/user/demo/first/artifacts/assets/data before the documented run.
# [inferred]
# Prepare checkpoints assets under /home/user/demo/first/artifacts/assets/checkpoints before the documented run.
# [inferred]
# Prepare weights assets under /home/user/demo/first/artifacts/assets/weights before the documented run.
# [inferred]
# Prepare cache assets under /home/user/demo/first/artifacts/assets/cache before the documented run.
# [inferred]
# Prepare .cache assets under /home/user/demo/first/artifacts/assets/.cache before the documented run.
# [documented]
# Asset hint from README.md: miniseg_b0.pth, //github.com/miniseg-lab/miniseg/releases/download/v1.0/miniseg_b0.pth
# [documented]
# Asset hint from README.md: miniseg_b1.pth, //github.com/miniseg-lab/miniseg/releases/download/v1.0/miniseg_b1.pth
# [documented]
# Asset hint from README.md: miniseg_b1_city.pth, //github.com/miniseg-lab/miniseg/releases/download/v1.0/miniseg_b1_city.pth
```

## Main run

```bash
# [documented]
python tools/eval.py --config configs/miniseg_b0_ade20k.yaml --checkpoint checkpoints/miniseg_b0.pth
```

## Verification

```bash
# [inferred]
# Add metric check, artifact check, or smoke verification command here.
```

## Notes

- README path: /home/user/demo/miniseg/README.md
- Detected top-level entries: .git, LICENSE, README.md, assets, configs, miniseg, requirements.txt, tools
- Environment plan source: requirements.txt
- Detected environment file `requirements.txt`.
- Fell back to a virtualenv plus requirements installation plan.
- Main run label: documented from README (code_block), section `Evaluation`
- Planned skill chain: repo-intake-and-plan, env-and-assets-bootstrap, minimal-run-and-audit
