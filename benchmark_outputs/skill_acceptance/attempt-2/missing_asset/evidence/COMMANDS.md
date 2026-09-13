# 命令记录

`documented`、`adapted` 和 `inferred` 表示来源，不表示已经执行。`not_run` 表示未执行；运行状态和证据记录实际尝试，不等同于科研结果验收通过。

## 环境准备建议

以下是环境准备建议，未执行。使用前请确认其是否适用于选定目标；不代表必须新建环境或安装依赖。

```bash
# [inferred]
# execution_status: not_run
# platforms: windows, macos, linux
python -m venv .venv
# [inferred]
# execution_status: not_run
# platforms: windows
.\.venv\Scripts\Activate.ps1
# [inferred]
# execution_status: not_run
# platforms: macos, linux
source .venv/bin/activate
```

## 资源观察

以下仅为观察记录，未执行资源准备。缺少常见目录不等于缺少必需资源。完整清单见 artifacts/assets/asset_manifest.json。

```bash
# [documented]
# execution_status: not_run
# 来自 README.md 的资源线索：config.json；准备前先确认是否与选定命令相关。
```

## 主命令

记录的执行状态：`failed`。具体结果请检查对应的运行状态文件与日志。

```bash
# [documented]
# execution_status: failed
# execution_evidence: D:\test_projects\ai-paper-reproduction-skill\repro_outputs\skill-acceptance-20260913-v2\missing_asset\evidence\_runtime\20260913T114527Z-a0de8630\state.json
python evaluate.py
```

## 验证

单独验证命令的执行状态：`not_run`。内置结果比较另见备注和 status.json。

```bash
# No command recorded.
```

## 环境提示（不自动构成阻塞）

保留环境规划器的原始观察。修改环境前应检查这些提示；它们不证明选定命令无法运行。

- No top-level environment specification file was found.

## 备注

- README 路径：D:\test_projects\ai-paper-reproduction-skill\repro_outputs\skill-acceptance-20260913-v2\missing_asset\repo\README.md
- 检测到的顶层条目：README.md, config.json, evaluate.py, prepare_data.py
- Defaulted to a virtualenv fallback because no environment file was detected.
- 主运行标签：来自 README 的 documented（code_block），章节 `Evaluation`
- Planned skill chain: repo-intake-and-plan, env-and-assets-bootstrap, minimal-run-and-audit
- 未执行单独的验证命令。内置指标比较状态为 `mismatched`；期望值与容差见 `status.json.result_match`。
