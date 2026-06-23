# 项目地图

最近自查日期：2026-06-23

## 顶层目录树

```text
.
├── .github/workflows/
│   ├── migrate.yml
│   └── validate-forgis.yml
├── agent/
│   ├── cli.py
│   ├── openai_compatible_client.py
│   ├── visual_evidence.py
│   └── qwen_vision.py
├── docs/
│   ├── DS_GUIDE_Swift_Kotlin.md
│   ├── ARCHITECTURE.md
│   ├── CURRENT_STATE.md
│   ├── DO_NOT_BREAK.md
│   ├── PROJECT_MAP.md
│   ├── QWEN_VISUAL_MODE.md
│   └── TESTING.md
├── prompts/
│   └── system_agent_v3.md
├── reports/
├── rules/
│   ├── profiles/
│   └── stacks/
├── skills/
├── tests/
│   ├── fixtures/reports/
│   ├── test_forgis_config.py
│   ├── test_openai_compatible_client.py
│   └── test_v7_cli_config.py
├── tmp/
├── README.md
├── README.zh-CN.md
├── RELEASE_NOTES.md
├── requirements.txt
└── AGENTS.md
```

`reports/`、`tmp/`、`.DS_Store` 等由 `.gitignore` 排除，不应视为源码入口。`rules/profiles/` 与 `rules/stacks/` 当前没有可见规则文件，含义需要后续确认。

## 关键目录职责

- `agent/`：Forgis 核心 Python 和 shell 运行时。包括配置解析、OpenAI-compatible client、DeepSeek compatibility shim、本地 CLI、受控文件工具、tool loop、staged translation、guardrails、报告、PR body 和 GitHub Actions 辅助脚本。
- `.github/workflows/`：CI 与主运行工作流。`migrate.yml` 是真实 Forgis 运行链路，`validate-forgis.yml` 是本仓库脚本验证链路。
- `skills/`：仓库本地可注入的短技能文档。`agent/skill_loader.py` 只允许从仓库本地 `skills/*.md` 读取安全 slug。
- `prompts/`：Agent 系统提示词。`agent/deepseek_agent.py` 优先读取 `prompts/system_agent_v3.md`，失败时回落到内置 legacy prompt。
- `tests/`：unittest 测试套件和报告 fixture。历史核心行为集中在 `tests/test_forgis_config.py`；v7.0 新增 client/CLI/config 窄测试文件。
- `tests/fixtures/reports/`：run report / migration plan audit 的 active、blocked、completed、deferred 状态 fixture。
- `docs/`：项目说明与迁移参考文档。`DS_GUIDE_Swift_Kotlin.md` 是迁移策略参考，不是运行时自动规则。
- `reports/`：生成报告目录占位或本地输出位置，当前未发现跟踪文件。
- `tmp/`：本地烟测和临时输出，按 `.gitignore` 视为生成物。
- `rules/`：当前仅有空目录结构，未能确认运行时是否使用，标记为需要后续确认。

## 关键文件清单

- `agent/forgis_config.py`：解析 `FORGIS_CONFIG.yml`、支持字段、默认值、路径安全、真实运行 gate、`ResolvedConfig.env()` 输出。
- `agent/forge.py`：旧控制器入口，校验 source/target 目录并输出运行摘要；保留既有参数形式。
- `agent/cli.py`：v7.0 本地 CLI 入口，支持 `python -m agent.cli help`、`doctor`、`smoke` 与 `run --source ... --target ... --target-repo ... [--config ...] [--dry-run]`，复用现有 config resolver 和 tool loop。
- `agent/resolve_config.py`：GitHub Actions 中解析目标仓库配置并写入 `$GITHUB_ENV` / `$GITHUB_OUTPUT`。
- `agent/openai_compatible_client.py`：v7.0 非 streaming OpenAI-compatible Chat Completions client，负责 URL 拼接、request schema、timeout、脱敏错误和 response/tool_call shape 校验。
- `agent/deepseek_agent.py`：系统提示词、工具 schema、DeepSeek public API compatibility shim。底层 HTTP 通过 `OpenAICompatibleClient`；v6.0 视觉工具包括 `list_visual_references`、`inspect_visual_reference`、`inspect_visual_actual`、`compare_visual_screenshots`。
- `agent/tool_loop.py`：默认 tool loop 主流程，处理 dry-run/run-agent gate、工具调用、runtime state、repair loop、report 和 migration plan。
- `agent/staged_translation.py`：`execution_mode=staged_translation` 的控制器，按 overview、per_file、stabilization 和微阶段 gate 推进。
- `agent/file_tools.py`：虚拟路径沙箱和工具实现。读 `source/`、`target/`、`target_subdir/`，写入仅限 `target_subdir`；`visual_validation.reference_screenshot_dirs` / `actual_screenshot_dirs` 是目标仓库只读截图输入目录，即使位于 `target_subdir` 内也不得被写工具修改。
- `agent/command_runner.py`：保守命令 allowlist。基础命令和 build/test profile 都在这里限制。
- `agent/build_runner.py` / `agent/build_feedback.py`：配置驱动 build/test 执行与失败摘要、脱敏。
- `agent/guardrails.py`：read-only snapshot、target scope、source clean、dry-run clean、secret leak 检查。
- `agent/validate_target_output.py`：目标输出快照、meaningful change 与 `success_checks` 验证。
- `agent/model_env.py`：`model_env` JSON 解析、环境变量映射与缺失 secret 检查，避免打印真实值。
- `agent/visual_evidence.py`：v6.0 Phase 3 视觉证据目录/状态 helper，负责 runtime 目录结构、状态枚举、阻塞原因、图片路径校验和可序列化摘要。不调用 Qwen，不读源码，不写业务文件。
- `agent/qwen_vision.py`：v6.0 Qwen provider adapter。缺少 API key 时安全 blocker；显式 `QWEN_API_KEY` 下可用标准库 HTTP transport；测试通过 mock `_post_qwen_vision_payload` 或 HTTP 层，返回有界脱敏 `QwenVisionResult`。
- `agent/run_report.py`：`FORGIS_RUN_REPORT.md/json` 渲染与安全写入，schema 为 `forgis.run_report.v6.0`，始终包含 `visual_validation` 块。
- `agent/migration_units.py`、`agent/migration_scheduler.py`、`agent/migration_state.py`、`agent/migration_plan_store.py`、`agent/plan_audit.py`：迁移单元、计划持久化、状态转换、resume 与 audit summary。
- `agent/repair_loop.py`、`agent/repair_report.py`、`agent/runtime_controller.py`：修复循环状态机、报告渲染与运行时观测状态。
- `agent/source_inventory.py`：源仓库扫描、过滤生成物/二进制/secret-like 文件、按优先级排序。
- `agent/skill_loader.py`：本地技能选择、加载、长度限制和 secret-like 内容检查。
- `docs/QWEN_VISUAL_MODE.md`：v6.0 Qwen Visual Evidence Mode 契约文档，说明 reference-guided migration、provider 边界、reference-first、证据状态、证据目录、mock-first provider adapter、真实 transport 启用条件、视觉 tool schema、report/PR 字段和 runtime gate。
- `skills/qwen_visual_mode.md`：可显式注入主 Agent 的短 skill，只记录 Qwen 视觉 provider 的安全边界。
- `agent/build_target.sh`：GitHub Actions 中运行 `validation_commands` 的脚本，作用域限定在目标仓库 `target_subdir`。
- `agent/create_pr.sh`：真实运行后的 target branch 准备、提交、push 和 PR 创建。已有远程分支时改用 fallback branch，避免 force push。
- `agent/pr_body.py`：有界 PR body 生成，超长时可生成 short body；从 run report 中摘取脱敏 Visual Validation 摘要。
- `.github/workflows/migrate.yml`：完整运行工作流。
- `.github/workflows/validate-forgis.yml`：验证工作流，包含 py_compile、unittest、bash syntax、controller smoke test、`git diff --check`。

## 入口文件

- 手动 GitHub Actions 入口：`.github/workflows/migrate.yml`，输入只有 `target_repo`。
- 配置解析入口：`python forgis/agent/resolve_config.py --target ... --target-repo ...`。
- 控制器入口：`python forgis/agent/forge.py --source ... --target ... --target-repo ...`。
- 默认模型循环入口：`python forgis/agent/tool_loop.py --source ... --target ... --target-repo ...`。
- 目标输出验证入口：`python forgis/agent/validate_target_output.py snapshot|validate ...`。
- guardrail 入口：`python forgis/agent/guardrails.py snapshot-readonly|check-readonly|check-target-scope|check-source-clean|check-dry-run-clean|check-secret-leaks ...`。
- 本地测试入口：`python3 -m unittest tests/test_forgis_config.py tests/test_openai_compatible_client.py tests/test_v7_cli_config.py tests/test_v7_local_cli.py tests/test_v7_local_smoke.py`。

## 配置文件

- `requirements.txt`：当前仅声明 `PyYAML>=6.0.2`。
- `.gitignore`：忽略 Python 缓存、虚拟环境、`.env`、日志、`reports/`、`forgis-runtime/`、`tmp/`、证书和 secrets 目录。
- 目标仓库运行配置默认是目标仓库根目录的 `FORGIS_CONFIG.yml`；本地 CLI 可用 `--config` 指向仓库外配置文件。`agent/forgis_config.py` 拒绝未知字段和 secret-like config path。
- 目标仓库任务文件默认 `FORGIS_TASK.md`，可由 `task_prompt_path` 指定，但必须位于目标仓库根内且非空。
- v7.0 模型配置支持 `agent_backend: deepseek`、`agent_backend: openai-compatible`、`api_base` / `base_url`、`api_format: openai-compatible`、`model`、`request_timeout_seconds` 和 `model_env`。API key 只能通过 env 映射注入，不应写入配置。
- v6.0 `visual_validation` 配置块包含 `enabled`、`provider`、`mode`、`reference_screenshot_dirs`、`actual_screenshot_dirs`、`max_visual_iterations`、`require_reference_first`、`require_actual_for_full_validation`、`upload_visual_artifact`。默认 `mode=reference_guidance`，`reference_screenshot_dirs` / `actual_screenshot_dirs` 默认为空以保持兼容。
- v6.0 已接通 reference-guided migration、`list_visual_references`、视觉工具 schema、`FileToolSandbox` 分发、runtime visual state/gate、run report / PR body 视觉字段和显式 env 下的 Qwen HTTP transport。仍不自动截图、不上传 visual artifact、不支持多 provider。

## 测试目录

- `tests/test_forgis_config.py`：覆盖配置解析、工作流约束、工具沙箱、staged translation、migration plan、report、guardrails、PR body 等。
- `tests/test_openai_compatible_client.py`：覆盖 v7.0 client request schema、URL 拼接、timeout、HTTP/JSON/shape 错误脱敏和 DeepSeek shim 兼容。
- `tests/test_v7_cli_config.py`：覆盖 v7.0 config 字段、backend alias、env 缺失、CLI help/dry-run、command allowlist 和 `validation_commands` 回归。
- `tests/test_v7_local_cli.py`：覆盖 `doctor`、`run --config`、summary output、缺失 env 错误脱敏、examples config 解析和 DeepSeek shim 本地配置兼容。
- `tests/test_v7_local_smoke.py`：覆盖 `python -m agent.cli smoke --workdir ...` 的 dry-run 本地闭环、不调用 API、不写 target。
- `tests/fixtures/reports/*.json`：报告 fixture 和 golden-like 样本。
- `tests/__init__.py`：测试包标记文件。

## 资源目录

- `skills/*.md`：本地技能文本，包括 `migration_general`、`swiftui_to_compose`、`swiftui_to_harmonyos`、`ui_style_preservation`、`build_repair`、`qwen_visual_mode`。
- `prompts/system_agent_v3.md`：运行时系统提示词。
- `docs/DS_GUIDE_Swift_Kotlin.md`：SwiftUI 到 Kotlin/Compose 迁移风险文档。
- `docs/QWEN_VISUAL_MODE.md`：Qwen Visual Evidence Mode 的长期维护说明。当前 v6.0 已接入 reference guidance、受控视觉工具、报告字段、gate 和真实 provider transport；自动截图采集、artifact 上传和多 provider 仍未实现。
- `examples/FORGIS_CONFIG.local.openai-compatible.yml`：真实本地 OpenAI-compatible 模板，只通过 env 注入 API key。
- `examples/FORGIS_CONFIG.local.smoke.yml`：无 API key dry-run smoke 模板。

## 生成物和缓存目录

- `tmp/`：本地烟测、临时 manifest、bundle、log 片段。当前工作区存在但被忽略。
- `reports/`：当前为空目录，`.gitignore` 只保留可能的 `.gitkeep`，但本轮未发现跟踪文件。
- `forgis-runtime/`：GitHub Actions 运行时目录，被忽略；v5.0 artifact 只上传 `forgis-runtime/reports/**`。
- Python `__pycache__/`、`.venv/`、`venv/`、`.env`、secret/cert 文件都属于禁止扫描或禁止提交对象。

## 不确定项

- `rules/profiles/` 与 `rules/stacks/` 当前为空，未在已读源码中发现明确加载逻辑。标记为 `需要后续确认`。
- `reports/` 目录当前为空且被忽略，是否需要保留 `.gitkeep` 未能从当前跟踪文件确认。
- README 提到的某些历史版本章节用于说明演进，不一定代表当前新增能力；以 `agent/` 源码和 `RELEASE_NOTES.md` v5.0 为准。
