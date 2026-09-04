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
python -m pip install -e .
```

## Assets

```bash
# [inferred]
# Prepare datasets assets under D:\test_projects\ai-paper-reproduction-skill\tmp\external-benchmark-runs\micrograd-20260904T175907Z-50148\artifacts\assets\datasets before the documented run.
# [inferred]
# Prepare data assets under D:\test_projects\ai-paper-reproduction-skill\tmp\external-benchmark-runs\micrograd-20260904T175907Z-50148\artifacts\assets\data before the documented run.
# [inferred]
# Prepare checkpoints assets under D:\test_projects\ai-paper-reproduction-skill\tmp\external-benchmark-runs\micrograd-20260904T175907Z-50148\artifacts\assets\checkpoints before the documented run.
# [inferred]
# Prepare weights assets under D:\test_projects\ai-paper-reproduction-skill\tmp\external-benchmark-runs\micrograd-20260904T175907Z-50148\artifacts\assets\weights before the documented run.
# [inferred]
# Prepare cache assets under D:\test_projects\ai-paper-reproduction-skill\tmp\external-benchmark-runs\micrograd-20260904T175907Z-50148\artifacts\assets\cache before the documented run.
# [inferred]
# Prepare .cache assets under D:\test_projects\ai-paper-reproduction-skill\tmp\external-benchmark-runs\micrograd-20260904T175907Z-50148\artifacts\assets\.cache before the documented run.
```

## Main run

```bash
# [documented]
python -m pytest
```

## Verification

```bash
# [inferred]
# Add metric check, artifact check, or smoke verification command here.
```

## Notes

- README path: D:\test_projects\ai-paper-reproduction-skill\tmp\external-benchmark-runs\micrograd-20260904T175907Z-50148\repo\README.md
- Detected top-level entries: .git, .gitignore, LICENSE, README.md, demo.ipynb, gout.svg, micrograd, moon_mlp.png, puppy.jpg, setup.py, test, trace_graph.ipynb
- Environment plan source: setup.py
- Detected environment file `setup.py`.
- Detected a setup.py-based editable install flow.
- Main run label: documented from README (code_block), section `Running tests`
- Planned skill chain: repo-intake-and-plan, env-and-assets-bootstrap, analyze-project, minimal-run-and-audit
