# 架构说明

最近自查日期：2026-06-23

## 总体架构

Forgis 是一个 Python CLI/Agent 工具。它本身不内置具体平台迁移智能，而是读取目标仓库或 v7.1 local config 的配置与任务文件，在满足真实运行开关时调用非 streaming OpenAI-compatible Chat Completions，并把受控文件工具交给模型使用。`agent_backend: deepseek` 仍是默认兼容路径，`agent_backend: openai-compatible` 是通用 alias。v7.1 新增本地 init/status/run-one-unit/resume/report 最小闭环，但不新增 server、GUI、streaming、多 Agent 或 shell runner。v6.0 已为 Qwen Visual Evidence Mode 接入 reference-guided migration、受控视觉工具、报告字段、runtime gate 和显式 env 下的安全 provider transport；Qwen 仍只是视觉理解 provider，不是核心迁移智能，也不是第二个代码 Agent。

核心运行方式：

1. GitHub Actions 或本地 `python -m agent.cli run` 接收 `target_repo`；v7.1 local config 可保存 `local_source_path`、`local_target_path`、`local_target_repo`，让 `status`、`run --unit`、`resume` 不依赖 GitHub Actions。
2. checkout Forgis 仓库、目标仓库和只读 source 仓库。
3. `agent/resolve_config.py` 解析目标仓库 `FORGIS_CONFIG.yml`，输出环境变量和 workflow outputs。
4. `agent/forge.py` 做 source/target 目录与配置校验，生成运行摘要。
5. `agent/tool_loop.py` 根据 `dry_run`、`run_agent`、`confirm_real_run`、`execution_mode` 决定跳过、默认 tool loop 或 staged translation。
6. `agent/file_tools.py` 提供虚拟路径文件工具，写入限制在目标仓库 `target_subdir`。
7. guardrails、target validation、report、log、PR 创建按 workflow 顺序执行。

## 模块边界

- 配置层：`agent/forgis_config.py` 是所有运行配置的单一解析源。它定义支持字段、默认值、路径约束、`ResolvedConfig` 和 GitHub Actions env/output。
- 工作流入口层：`.github/workflows/migrate.yml` 编排 checkout、config resolve、guardrails、tool loop、validation、log、PR、artifact。`.github/workflows/validate-forgis.yml` 只验证本仓库脚本。`agent/cli.py` 提供本地 `help`、`doctor`、`smoke`、`init`、`status`、`run --unit`、`resume`，不新增权限。
- Agent 调用层：`agent/openai_compatible_client.py` 提供非 streaming Chat Completions HTTP transport；`agent/deepseek_agent.py` 提供系统提示词、tool schema 和 DeepSeek-compatible public API shim。
- 工具沙箱层：`agent/file_tools.py` 实现所有模型可调用工具，并强制虚拟路径、symlink、防 secret-like 路径、写入范围和 workflow 文件保护。
- 命令执行层：`agent/command_runner.py`、`agent/build_runner.py`、`agent/build_feedback.py` 限制命令 allowlist、执行 build/test、生成脱敏摘要。v7.1 `validation_commands` 的 argv mapping 也复用这个 allowlist；旧 shell string 仅兼容 warning。
- 控制器层：`agent/tool_loop.py` 处理默认循环、运行时状态、repair loop、migration plan、report 写入。`agent/staged_translation.py` 处理分阶段控制模式。
- 安全校验层：`agent/guardrails.py`、`agent/validate_target_output.py`、`agent/model_env.py` 负责 read-only、scope、dry-run、secret leak、meaningful output、环境变量映射。
- 报告层：`agent/run_report.py`、`agent/repair_report.py`、`agent/write_run_log.py`、`agent/pr_body.py` 输出有界、脱敏报告和 PR body。
- 迁移计划层：`agent/migration_units.py`、`agent/migration_scheduler.py`、`agent/migration_state.py`、`agent/migration_plan_store.py`、`agent/plan_audit.py` 管理 migration unit、状态转换、持久化、resume 和 audit summary。
- 本地知识层：`skills/` 和 `agent/skill_loader.py` 只注入仓库本地短文档，不扩大工具权限。
- 视觉证据层：`docs/QWEN_VISUAL_MODE.md` 和 `skills/qwen_visual_mode.md` 记录 Qwen 视觉 provider 边界；`agent/forgis_config.py` 解析 `visual_validation` 控制块；`agent/visual_evidence.py` 处理证据目录、状态、图片路径安全和摘要；`agent/qwen_vision.py` 提供可 mock 且可真实调用的 provider adapter；`agent/deepseek_agent.py` 暴露 `list_visual_references`、`inspect_visual_reference`、`inspect_visual_actual`、`compare_visual_screenshots` tool schema；`agent/file_tools.py` 负责配置目录发现、虚拟图片路径校验、只读 reference/actual screenshot 目录保护和 provider adapter 调用；`agent/runtime_controller.py` 记录视觉状态并执行 auto required 判定/gate；`agent/run_report.py` / `agent/pr_body.py` 写有界视觉摘要。当前仍没有自动截图、artifact 上传或多 provider。

## 主要数据模型

- `ResolvedConfig`：位于 `agent/forgis_config.py`，承载 source/target repo、路径、运行开关、模型 backend、`api_base` / `base_url`、`request_timeout_seconds`、命令、report、skills、migration scheduler、staged translation 等配置。
- `VisualValidationConfig`：位于 `agent/forgis_config.py`，承载 `enabled`、`provider`、`mode`、`reference_screenshot_dirs`、`actual_screenshot_dirs`、`max_visual_iterations`、`require_reference_first`、`require_actual_for_full_validation`、`upload_visual_artifact`。当前驱动 reference guidance、视觉工具启用判断、provider 名称、runtime gate 和报告字段，但不包含 API key、model、API base、截图文件路径或 evidence root；Qwen key/base/model 只能来自显式 runtime env。
- `VisualEvidencePaths` / `VisualEvidenceSummary`：位于 `agent/visual_evidence.py`，承载 runtime 证据目录和脱敏视觉摘要。
- `QwenVisionResult`：位于 `agent/qwen_vision.py`，承载 provider、mode、summary、findings、limitations、blocker 等有界结果。
- `StagedTranslationConfig` 及其子配置：位于 `agent/forgis_config.py`，控制 overview、per_file、stabilization 和微阶段 gate。
- `FileToolSandbox`：位于 `agent/file_tools.py`，维护 source root、target root、target_subdir、config/task 路径、工具调用计数和操作日志。
- `ToolLoopResult`：位于 `agent/tool_loop.py`，记录是否执行、状态、summary、迭代数、工具调用数、operation log、runtime state、report 路径和 migration plan 字段。
- `RuntimeController`：位于 `agent/runtime_controller.py`，记录读写、diff、命令、build/test、repair、skills、migration plan 等观测状态。
- `MigrationUnit` / `MigrationPlan`：位于 `agent/migration_units.py`，支持 unit 类型、状态、优先级、路径、失败摘要、changed paths 和合法状态转换。
- `SourceUnit`：位于 `agent/source_inventory.py`，表示 staged translation 或 scheduler 中的源文件单元。
- `RunReportWriteResult` / report JSON：`agent/run_report.py` 输出 `forgis.run_report.v6.0`，包含常驻 `visual_validation` 块。
- Migration plan JSON：`agent/migration_plan_store.py` 输出 `forgis.migration_plan.v5.0`，并兼容读取 v4.8、v3.9、v3.8、v3.7。

## 关键业务链路

### 默认 tool loop

1. `resolve_config()` 固定读取目标仓库根目录 `FORGIS_CONFIG.yml`。
2. `run_tool_loop()` 先加载 skills 和 migration plan。
3. 若 `dry_run=true` 或有效 `run_agent=false`，返回 skipped result，不调用模型。
4. 若执行，创建 `FileToolSandbox`、`RuntimeController`、`RepairLoopController`。
5. 配置的模型每轮返回 tool calls 或 final summary。
6. 工具调用经 `sandbox.invoke()` 执行，结果写回 message history，并同步 runtime/repair/migration plan 状态。
7. final summary 前可能被 repair loop gate 阻止，要求先 diff 或 build/test。
8. 完成或达到 max iterations 后，生成 repair report、run report、migration plan、status env、operation log。

### staged translation

`execution_mode=staged_translation` 时，`tool_loop.py` 转入 `agent/staged_translation.py`。该模式先扫描 source inventory，然后按 `overview`、`per_file`、`stabilization` 推进。per-file 阶段可强制 `feed`、`write`、`readonly_compare`、`revise` 微阶段。控制器会阻止过早 final summary，并限制 overview、feed、compare 等阶段只能写 staged progress artifacts 或 compare reports。

### GitHub Actions 真实运行

`.github/workflows/migrate.yml` 中真实 push/PR 只在 `dry_run=false`、`run_agent=true`、`confirm_real_run=true` 且 guardrails、validation、secret leak 检查成功时发生。`agent/create_pr.sh` 不 force push。如果 `origin/$TARGET_BRANCH` 已存在，会使用 `${TARGET_BRANCH}-run-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}` 作为实际 push/PR head。

### Qwen Visual Evidence Mode 链路

v6.0 建立契约、配置解析、证据目录/状态 helper、mock-first provider adapter、受控视觉工具、report/PR 字段和 runtime gate。首选链路是 reference-guided migration：用户把 reference screenshots 放在目标仓库配置目录中，模型先调用 `list_visual_references`，再对关键截图调用 `inspect_visual_reference`，DeepSeek / 主 Agent 根据 Qwen 视觉结构、层级、颜色、字体、间距、圆角和组件关系反馈修改目标代码。actual screenshots 与 `compare_visual_screenshots` 只在用户已提供目标渲染截图时作为可选增强。主 Agent 仍负责代码修改、构建、测试和最终报告；Qwen 不读源码、不运行命令、不改文件。

## 数据流、请求流和状态流

- 配置流：目标仓库 `FORGIS_CONFIG.yml` 或本地 CLI `--config` -> `resolve_config.py` / `agent.cli` -> `ResolvedConfig.env()` -> GitHub Actions env 或本地 tool loop。v7.1 local config 的 `local_*` 字段只供 CLI 定位本地 source/target/target_repo，不保存 secret。
- 本地迁移流：`agent.cli init` 写显式 output config；`status` 解析 config 并加载或生成有界 migration unit summary；`run --unit` 通过 existing migration plan switch 选择一个 active unit，再进入 dry-run 或 gated real tool loop；`resume` 只读取 persisted migration state 并输出下一步，不调用模型或 shell。
- 视觉配置/证据流：`visual_validation` -> `VisualValidationConfig` -> `FORGIS_VISUAL_*` env/output；`list_visual_references` 从 `reference_screenshot_dirs` 返回合法图片虚拟路径；visual inspect/compare tool call -> `FileToolSandbox` 虚拟路径校验 -> runtime `visual-evidence/<run_id>/<target_repo_slug>/reference|actual|qwen` 目录创建 -> `qwen_vision` mockable adapter -> `RuntimeController` 视觉状态（含 `guidance_completed` / `full_rendered_validation`）-> `FORGIS_RUN_REPORT.md/json` 和 PR body 视觉摘要。
- 任务流：目标仓库 task file -> `deepseek_agent.initial_messages()` 中提示模型先读取 `task`。
- 模型请求流：`tool_loop.py` / `staged_translation.py` -> `DeepSeekClient.chat()` compatibility facade -> `OpenAICompatibleClient.chat()` -> normalized Chat Completions endpoint。非 streaming，仅发送 `model`、`messages`、可选 `tools`、可选 `tool_choice`。
- 文件访问流：模型 tool call -> `FileToolSandbox` -> source/target/target_subdir 虚拟路径解析 -> 文件读写或 git/command 工具。
- 状态流：工具结果 -> `RuntimeController.observe_tool_result()`、`RepairLoopController.observe_tool_result()`、migration plan runtime fields -> report/status outputs。
- 报告流：runtime state + operation log -> `repair_report`、`run_report`、`FORGIS_MIGRATION_PLAN.json`、GitHub Step Summary、target `FORGIS_LOG.md`。

## 网络、本地存储、后台任务

- 网络：默认模型链路在 `OpenAICompatibleClient.chat()` 中调用 OpenAI-compatible Chat Completions API。仓库 checkout、push、PR 由 GitHub Actions 和 `gh`/`git` 完成。`agent/qwen_vision.py` 只有在显式提供 `QWEN_API_KEY` 时才调用 Qwen HTTP transport；单元测试通过 mock 替换底层函数或 HTTP 层，不真实联网。
- 本地存储：目标仓库输出只允许写入 `target_subdir`。运行报告和 migration plan 写入 Forgis runtime workspace 下的安全输出目录，不能写到 source/target checkout、Desktop、Downloads、Documents 或 secret-like 路径。`python -m agent.cli smoke` 只在用户指定或系统临时 workdir 下创建 source/target/config/runtime。
- 后台任务：没有常驻 daemon。所有任务由 CLI 或 GitHub Actions step 驱动。

## UI 与业务逻辑分层

本项目没有前端 UI。唯一用户可见界面是 CLI 输出、GitHub Actions logs、GitHub Step Summary、PR body、Markdown/JSON 报告和目标仓库 run log。

## 平台相关与共享代码边界

Forgis 核心保持平台无关。SwiftUI、Compose、HarmonyOS 相关内容位于 `skills/` 和 `docs/DS_GUIDE_Swift_Kotlin.md`，用于任务上下文和人工参考，不应硬编码到 `agent/` 的核心逻辑中。

## 安全、鉴权、权限和文件访问

- `model_env` 只映射环境变量名，`model_env.py` 校验缺失但不打印真实 secret。OpenAI-compatible client 的异常、repr、日志和 report 字段不得包含 API key、Authorization header、raw provider response 或完整模型输出。
- 外部 `--config` 是只读运行输入；路径不得包含 secret-like 段，不得位于 source repo 内，模型只能通过虚拟路径 `config` 读取它，写工具不能修改它。
- `visual_validation` 不允许 API key、token、API base、model name、截图文件路径或证据根目录字段；只允许 target-repo-relative `reference_screenshot_dirs` / `actual_screenshot_dirs` 作为只读目录输入，未知字段直接失败。
- `guardrails.py check-secret-leaks` 会扫描 `target_subdir` 是否写入配置映射中的 secret 值。
- 文件工具拒绝绝对路径、`..`、`.git`、secret-like 路径、symlink 写入、source 写入、target root 写入、workflow 文件写入。
- `run_command` 只允许保守基础命令，且 cwd 必须在 `target_subdir` 内。
- `run_build` / `run_tests` 只运行配置数组命令，profile 目前只允许安全 Python `py_compile` / `unittest` 类命令。
- `validation_commands` 新配置应使用 argv mapping，并由 `agent/build_target.sh` 通过 `command_runner.py` allowlist 执行。旧字符串仍以 `bash -lc` 兼容运行并打印 warning，不应出现在新示例或本地 full migration 配置中。
- v7.0 不新增 streaming、Responses API、local server/gateway、council、多 Agent、自动截图、GUI、Keychain、`~/.config` 默认配置或 provider-specific private protocol。

## 当前架构风险或不确定点

- 旧式字符串 `validation_commands` 仍存在兼容风险；新增测试覆盖 argv allowlist 和 shell bypass 拒绝。后续可以考虑将旧字符串从 warning 升级为 strict reject。
- 测试集中在单个 6000 行左右的 `tests/test_forgis_config.py`，定位方便但维护成本高。
- `rules/` 目录为空且未确认使用。
- staging、migration plan、report、repair loop 的状态字段很多，新增字段时容易漏掉 env、report、fixture 和测试。
- 视觉模式后续接入截图采集和 artifact 上传风险较高：不得把 Qwen 变成代码 Agent，不得上传源码或 secret，不得把 reference-only guidance 当完整真实渲染验收，不得用无效桌面截图冒充 actual app screenshot。Phase 8+ 接入 screenshot acquisition 前必须继续保持 mock-first 测试。
- README 存在历史版本说明，当前行为应以 `agent/` 源码、workflow 和 `RELEASE_NOTES.md` v5.0 为准。
