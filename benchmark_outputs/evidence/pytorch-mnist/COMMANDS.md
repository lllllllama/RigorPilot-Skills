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
# Prepare datasets assets under D:\test_projects\ai-paper-reproduction-skill\tmp\external-benchmark-runs\pytorch-mnist-20260904T180018Z-44808\artifacts\assets\datasets before the documented run.
# [inferred]
# Prepare data assets under D:\test_projects\ai-paper-reproduction-skill\tmp\external-benchmark-runs\pytorch-mnist-20260904T180018Z-44808\artifacts\assets\data before the documented run.
# [inferred]
# Prepare checkpoints assets under D:\test_projects\ai-paper-reproduction-skill\tmp\external-benchmark-runs\pytorch-mnist-20260904T180018Z-44808\artifacts\assets\checkpoints before the documented run.
# [inferred]
# Prepare weights assets under D:\test_projects\ai-paper-reproduction-skill\tmp\external-benchmark-runs\pytorch-mnist-20260904T180018Z-44808\artifacts\assets\weights before the documented run.
# [inferred]
# Prepare cache assets under D:\test_projects\ai-paper-reproduction-skill\tmp\external-benchmark-runs\pytorch-mnist-20260904T180018Z-44808\artifacts\assets\cache before the documented run.
# [inferred]
# Prepare .cache assets under D:\test_projects\ai-paper-reproduction-skill\tmp\external-benchmark-runs\pytorch-mnist-20260904T180018Z-44808\artifacts\assets\.cache before the documented run.
```

## Main run

```bash
# [documented]
python main.py
```

## Verification

```bash
# [inferred]
python - <<'PY'
import pathlib
print(pathlib.Path('train_outputs/status.json').exists())
PY
```

## Notes

- README path: D:\test_projects\ai-paper-reproduction-skill\tmp\external-benchmark-runs\pytorch-mnist-20260904T180018Z-44808\repo\mnist\README.md
- Detected top-level entries: README.md, main.py, requirements.txt
- Environment plan source: requirements.txt
- Detected environment file `requirements.txt`.
- Fell back to a virtualenv plus requirements installation plan.
- Main run label: documented from README (code_block), section `Basic MNIST Example`
- Planned skill chain: repo-intake-and-plan, env-and-assets-bootstrap, analyze-project, run-train
