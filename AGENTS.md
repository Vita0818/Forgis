# Forgis 项目常驻上下文

本文件继承 `/Users/vita/Vitemis/AGENTS.md` 中的 Vitemis 通用 Agent 规则。若本文件与通用规则冲突，在不违反系统和用户指令的前提下，以更具体、更严格的项目规则为准。

本文是 AI Agent 每轮进入本仓库时的入口文件。执行任何代码修改、配置修改、构建脚本修改或测试源码修改之前，必须先按顺序阅读并核对下列文档：

0. `/Users/vita/Vitemis/AGENTS.md`
1. `docs/CURRENT_STATE.md`
2. `docs/PROJECT_MAP.md`
3. `docs/ARCHITECTURE.md`
4. `docs/DO_NOT_BREAK.md`
5. `docs/TESTING.md`

额外必读（涉及视觉模式时）：
- `docs/QWEN_VISUAL_MODE.md`（Qwen Visual Evidence Mode 契约，修改 visual_validation/qwen_vision/visual_evidence 前）

参考文档（非核心运行逻辑）：
- `docs/DS_GUIDE_Swift_Kotlin.md`（SwiftUI→Kotlin/Compose 迁移策略参考）

如果文档与源码、工程配置、测试或脚本冲突，必须以当前源码和配置为准，并在最终报告中明确指出冲突位置和采用源码为准的原因。

> 已知冲突：`RELEASE_NOTES.md` 冻结在 v5.0（`forgis.run_report.v5.0`），但源码已到 v7.2，`CURRENT_STATE.md`/`ARCHITECTURE.md`/`DO_NOT_BREAK.md` 记录 run report schema 实为 `v6.0`（含 visual 字段）。以源码为准。

## 工作目录检查

每轮开始先在项目根目录执行：

```sh
pwd
git rev-parse --show-toplevel
git status --short
```

要求：

- `pwd` 与 `git rev-parse --show-toplevel` 必须指向同一个仓库根目录：`/Users/vita/Vitemis/Forgis`。
- 如果当前目录不是 Git root，停止修改，只报告路径问题。
- 读取 `git status --short` 后，先区分用户已有改动与本轮计划改动；不得覆盖、回退或清理用户已有改动。

## 修改边界

本仓库是 Python CLI/Agent 本地代码迁移助手（含受控文件工具运行时）+ v7.2 `ForgisMac` SwiftUI 壳。主体代码在 `agent/`，行为大量由 `tests/test_forgis_config.py`（~6000 行）覆盖。

未来常规任务可以按用户要求修改业务源码；但在只要求项目自查或文档更新的任务中，只允许修改：

- `AGENTS.md`
- `docs/` 下的项目说明文档

除非用户明确要求，不要修改：

- `agent/`（`*.py` / `*.sh`）
- `Apps/ForgisMac/`
- `.github/workflows/`
- `tests/`
- `skills/` / `prompts/` / `rules/`
- `requirements.txt`
- `examples/`

## 禁止事项

- 不执行破坏性 Git 操作：`git reset --hard`、`git clean -fd`、`git checkout .`、强制 push、删除用户未提交文件。
- 未经用户明文要求具体 Git 操作，不 add、不 commit、不 push、不创建 PR；编辑、整理、修复、验证或准备工作都不等于提交请求。
- 若用户要求提交，只提交当前 Git root 中与本任务相关的文件；不得递归进入、暂存、提交或推送子仓库、submodule、nested Git repo 或依赖 checkout。
- 不引入新依赖，不改构建脚本，不改测试源码，除非任务明确要求。
- 不把真实 secret、token、证书私钥、账号密码、shared secret、个人隐私路径写入源码、测试 fixture、报告或文档。
- 不绕过 `target_subdir` 写入边界、read-only config/task 边界、source repo 只读边界、secret 扫描或 report bounding。
- 不把 Forgis 扩展成任意 shell 执行器。`run_command`/`run_build`/`run_tests` 的命令 allowlist 是核心安全面。
- 不把平台迁移智能硬编码进 Forgis 核心。迁移策略应来自目标仓库任务文件、可选 skills 和项目上下文。
- 不把 Qwen Visual Evidence Mode 扩展成代码 Agent。Qwen 只能作为视觉理解 provider，不得读取源码、修改文件、运行命令或接收 secret/token/证书/私钥/完整源码/图片 bytes/base64。
- 不把 reference-only 视觉指导当成完整真实渲染验收；报告和 PR body 必须区分 `guidance_completed` 与 `full_rendered_validation`。
- 不得在无显式 `QWEN_API_KEY` 时发起 Qwen 真实 HTTP。
- 不得上传 legacy diagnostics、完整 diff、源码或未脱敏 model 输出。

## 项目理解要求

修改前至少确认：

- 入口：`.github/workflows/migrate.yml`（GH Actions，输入仅 `target_repo`）、`agent/cli.py`（v7.1 本地 CLI：`help`/`doctor`/`smoke`/`init`/`status`/`run --unit`/`resume`）、`Apps/ForgisMac/Sources/ForgisMacApp.swift`（v7.2 Mac `@main`，mock/fixture）。
- 配置解析：`agent/forgis_config.py`（`ResolvedConfig`/`VisualValidationConfig`/`StagedTranslationConfig`，支持字段、默认值、路径校验、真实运行 gate）。
- 默认 tool loop：`agent/forge.py` → `agent/resolve_config.py` → `agent/tool_loop.py`（`ToolLoopResult`）→ `agent/file_tools.py`（`FileToolSandbox`）→ `agent/guardrails.py` + `agent/validate_target_output.py` → `agent/run_report.py` + `agent/migration_plan_store.py`。
- 模型客户端：`agent/openai_compatible_client.py`（非流式 Chat Completions）；`agent/deepseek_agent.py`（DeepSeek shim，默认 model `deepseek-v4-pro`）。
- 工具沙箱：`agent/file_tools.py`（list/tree/read/file_exists/search/git_status/git_diff/mkdir/write/append/delete/edit/apply_patch/run_command/run_build/run_tests，虚拟路径，拒绝对绝对路径/`..`/`.git`/secret-like/symlink/source 写入/target-root 写入/workflow 写入）。
- 安全校验：`agent/guardrails.py`（snapshot-readonly/check-readonly/check-secret-leaks）、`agent/validate_target_output.py`、`agent/model_env.py`（env 名映射，不存真实 secret）。
- 真实运行 gate：`dry_run=false` + `run_agent=true` + `confirm_real_run=true` 三者同时满足。
- v6.0 视觉模式闭环：`docs/QWEN_VISUAL_MODE.md`、`skills/qwen_visual_mode.md`、`agent/visual_evidence.py`、`agent/qwen_vision.py`、`agent/file_tools.py` 的 `list_visual_references`/三个 inspect/compare 工具、`agent/runtime_controller.py` 的视觉状态/gate、`agent/run_report.py`/`agent/pr_body.py` 的视觉摘要。当前已支持 reference-guided migration、受控视觉工具、mock-first Qwen provider、显式 env 下真实 Qwen HTTP transport、report/PR 字段和防假验收 gate；仍不含自动截图、artifact 上传、多 provider 或任意 shell。
- 迁移单元与计划：`agent/migration_units.py`（`MigrationUnit`/`MigrationPlan`）、`agent/migration_state.py`、`agent/plan_audit.py`、`agent/staged_translation.py`、`agent/source_inventory.py`（`SourceUnit`）。
- 报告 schema：`forgis.run_report.v6.0`（含 `visual_validation` block）、`forgis.migration_plan.v5.0`（写 v5.0，读 v4.8/v3.9/v3.8/v3.7）。
- 测试基准：`tests/test_forgis_config.py`（~6000 行，134 tests）+ `tests/test_openai_compatible_client.py` + `tests/test_v7_*.py`。修改前先读相关测试。

## 文档索引

- `docs/PROJECT_MAP.md`：目录地图、关键文件、入口、配置、测试、资源和生成物说明。
- `docs/ARCHITECTURE.md`：总体架构、模块边界、数据流、状态流、安全机制和风险。
- `docs/CURRENT_STATE.md`：当前真实状态（v7.2/v7.1/v6.0）、已有能力、未完成项、风险、工作区状态。
- `docs/TESTING.md`：环境、依赖、构建、测试、lint/format、手动验证矩阵。
- `docs/DO_NOT_BREAK.md`：不可破坏的格式、路径、协议、安全边界和回归要求。
- `docs/QWEN_VISUAL_MODE.md`：Qwen Visual Evidence Mode 契约（reference-guided workflow、provider 边界、reference-first 规则、证据状态、报告字段、runtime gate、真实 transport 启用条件）。
- `docs/DS_GUIDE_Swift_Kotlin.md`：SwiftUI 到 Kotlin/Compose 迁移风险与策略参考，不是 Forgis 核心运行逻辑。

## 完成标准

完成任何任务前应：

- 说明本轮实际阅读/检查过哪些源码、配置或测试。
- 只修改任务范围内文件。
- 保留用户已有改动。
- 运行与改动风险匹配的检查。最少应考虑 `git diff --check`；代码改动通常还应运行 `python3 -m unittest tests/test_forgis_config.py` 或更窄测试。
- 检查 `git status --short`，明确哪些文件是本轮改动。
- 若未运行构建或测试，必须在最终报告中说明原因。

## 最终报告格式

最终报告建议包含：

1. `MODEL_CHECK_RESULT`：当前模型名称；无法确认时写无法确认。
2. `PATH_CHECK_RESULT`：`pwd`、Git root、是否匹配预期。
3. `FILES_WRITTEN`：新增/修改文件。
4. `PROJECT_AUDIT_SUMMARY`：识别到的项目结构、主要模块和关键链路。
5. `DOCS_CONTENT_SUMMARY`：各文档内容摘要。
6. `VALIDATION_RESULT`：实际运行命令与结果。
7. `UNCERTAINTIES`：无法确认、需要人工确认的点。
8. `NEXT_RECOMMENDED_ACTION`：下一步建议；不要自动继续改业务源码。
