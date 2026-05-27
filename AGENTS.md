# Codex 项目常驻上下文

本文件是未来 Codex 进入本仓库后的第一入口。开始任何修改前，先确认自己在项目 Git root，并按顺序阅读下列文档和必要源码。

## 必读顺序

未来 Codex 在任何代码、配置、构建脚本、测试或文档修改前，必须先阅读：

1. `docs/CURRENT_STATE.md`
2. `docs/PROJECT_MAP.md`
3. `docs/ARCHITECTURE.md`
4. `docs/DO_NOT_BREAK.md`
5. `docs/TESTING.md`

若这些文档与当前源码冲突，必须以源码为准，并在最终报告中指出冲突位置和处理方式。

## 工作目录检查

开始工作前必须在项目根目录执行并记录结果：

```bash
pwd
git rev-parse --show-toplevel
git status --short
```

只有当 `pwd` 与 `git rev-parse --show-toplevel` 指向同一个项目根目录时，才允许继续修改。若不匹配，停止修改并说明问题。

## 修改边界

- 本仓库是 Forgis Python CLI/Agent 工具，主体代码在 `agent/`。
- 常规功能修改应优先定位到相关 `agent/*.py`、`agent/*.sh`、`.github/workflows/*.yml`、`tests/test_forgis_config.py` 或文档。
- 修改前先读相关测试。该项目大量行为由 `tests/test_forgis_config.py` 覆盖，不要只看实现文件。
- 新增运行能力、配置字段、报告字段、工具权限或工作流步骤时，必须同步更新 README、测试和常驻文档。
- 仅在用户明确要求时执行 commit、push、创建 PR。

## 禁止事项

- 不得执行破坏性 Git 操作，例如 `git reset --hard`、`git clean -fd`、`git checkout .`、强制 push。
- 不得删除或覆盖用户未提交文件。
- 不得把真实 secret、token、证书私钥、账号密码、shared secret、个人隐私路径写入源码、测试 fixture、报告或文档。
- 不得绕过 `target_subdir` 写入边界、read-only config/task 边界、source repo 只读边界、secret 扫描或 report bounding。
- 不得把 Forgis 扩展成任意 shell 执行器。`run_command`、`run_build`、`run_tests` 的命令 allowlist 是核心安全面。
- 不得把平台迁移智能硬编码进 Forgis 核心。迁移策略应来自目标仓库任务文件、可选 skills 和项目上下文。

## 项目理解要求

处理问题时至少确认：

- 入口：`agent/forge.py`、`agent/resolve_config.py`、`agent/tool_loop.py`、`.github/workflows/migrate.yml`。
- 配置解析：`agent/forgis_config.py`，尤其是支持字段、默认值、路径校验、真实运行 gate。
- 工具沙箱：`agent/file_tools.py`、`agent/command_runner.py`、`agent/build_runner.py`。
- 安全校验：`agent/guardrails.py`、`agent/validate_target_output.py`、`agent/model_env.py`。
- 报告与迁移计划：`agent/run_report.py`、`agent/migration_plan_store.py`、`agent/migration_units.py`、`agent/migration_state.py`、`agent/plan_audit.py`。
- 分阶段模式：`agent/staged_translation.py`、`agent/source_inventory.py`。
- 测试基准：`tests/test_forgis_config.py` 和 `tests/fixtures/reports/*.json`。

## 文档索引

- `docs/PROJECT_MAP.md`：目录地图、关键文件、入口、配置、测试、资源和生成物说明。
- `docs/ARCHITECTURE.md`：总体架构、模块边界、数据流、状态流、安全机制和风险。
- `docs/CURRENT_STATE.md`：当前真实状态、已有能力、未完成项、风险、工作区状态。
- `docs/TESTING.md`：环境、依赖、构建、测试、lint/format、手动验证矩阵。
- `docs/DO_NOT_BREAK.md`：不可破坏的格式、路径、协议、安全边界和回归要求。
- `docs/DS_GUIDE_Swift_Kotlin.md`：SwiftUI 到 Kotlin/Compose 迁移风险与策略参考，不是 Forgis 核心运行逻辑。

## 完成标准

完成任何任务前应：

- 确认修改范围符合用户要求。
- 运行与改动风险匹配的检查。最少应考虑 `git diff --check`；代码改动通常还应运行 `python3 -m unittest tests/test_forgis_config.py` 或更窄测试。
- 检查 `git status --short`，明确哪些文件是本轮改动。
- 若未运行构建或测试，必须在最终报告中说明原因。

## 最终报告格式

最终报告应包含：

- `PATH_CHECK_RESULT`：`pwd`、Git root、是否匹配。
- `FILES_CHANGED`：列出本轮新增或修改文件。
- `SUMMARY`：简述实际改动。
- `VALIDATION`：列出实际运行的命令及结果。
- `UNCERTAINTIES`：列出不确定项、源码与文档冲突或需要后续人工确认的部分。
