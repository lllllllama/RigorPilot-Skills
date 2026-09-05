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
# Prepare datasets assets under D:\test_projects\ai-paper-reproduction-skill\tmp\external-benchmark-runs\mingpt-20260904T175952Z-47668\artifacts\assets\datasets before the documented run.
# [inferred]
# Prepare data assets under D:\test_projects\ai-paper-reproduction-skill\tmp\external-benchmark-runs\mingpt-20260904T175952Z-47668\artifacts\assets\data before the documented run.
# [inferred]
# Prepare checkpoints assets under D:\test_projects\ai-paper-reproduction-skill\tmp\external-benchmark-runs\mingpt-20260904T175952Z-47668\artifacts\assets\checkpoints before the documented run.
# [inferred]
# Prepare weights assets under D:\test_projects\ai-paper-reproduction-skill\tmp\external-benchmark-runs\mingpt-20260904T175952Z-47668\artifacts\assets\weights before the documented run.
# [inferred]
# Prepare cache assets under D:\test_projects\ai-paper-reproduction-skill\tmp\external-benchmark-runs\mingpt-20260904T175952Z-47668\artifacts\assets\cache before the documented run.
# [inferred]
# Prepare .cache assets under D:\test_projects\ai-paper-reproduction-skill\tmp\external-benchmark-runs\mingpt-20260904T175952Z-47668\artifacts\assets\.cache before the documented run.
# [documented]
# Asset hint from README.md: https://github.com/openai/gpt-2),, https://arxiv.org/abs/1706.03762),
# [documented]
# Asset hint from README.md: https://github.com/openai/gpt-2)
# [documented]
# Asset hint from README.md: https://github.com/huggingface/transformers), https://github.com/huggingface/transformers/tree/master/examples/pytorch/language-modeling).
```

## Main run

```bash
# [documented]
python -m unittest discover tests
```

## Verification

```bash
# [inferred]
# Add metric check, artifact check, or smoke verification command here.
```

## Notes

- README path: D:\test_projects\ai-paper-reproduction-skill\tmp\external-benchmark-runs\mingpt-20260904T175952Z-47668\repo\README.md
- Detected top-level entries: .git, .gitignore, LICENSE, README.md, demo.ipynb, generate.ipynb, mingpt, mingpt.jpg, projects, setup.py, tests
- Environment plan source: setup.py
- Detected environment file `setup.py`.
- Detected a setup.py-based editable install flow.
- Main run label: documented from README (code_block), section `Unit tests`
- Planned skill chain: repo-intake-and-plan, env-and-assets-bootstrap, analyze-project, minimal-run-and-audit
