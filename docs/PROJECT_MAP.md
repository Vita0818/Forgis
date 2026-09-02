# 项目地图

最近自查日期：2026-09-02

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
├── Apps/
│   ├── ForgisRuntimeCLI/
│   │   └── Sources/ForgisRuntimeCLI.swift
│   └── ForgisMac/
│       └── Sources/
│           ├── ForgisMacApp.swift
│           ├── ForgisCodexRuntimeBootstrap.swift
│           ├── ForgisCodexRuntimeSmoke.swift
│           ├── ForgisRootView.swift
│           ├── ForgisDesign.swift
│           ├── ForgisModels.swift
│           ├── ForgisComponents.swift
│           ├── ForgisRuntimeSession.swift
│           ├── ForgisRuntimeStorage.swift
│           ├── ForgisRuntimeViews.swift
│           └── ForgisViews.swift
├── Forgis.xcodeproj/
│   ├── project.pbxproj
│   └── xcshareddata/xcschemes/ForgisMac.xcscheme
├── docs/
│   ├── DS_GUIDE_Swift_Kotlin.md
│   ├── ARCHITECTURE.md
│   ├── CURRENT_STATE.md
│   ├── DO_NOT_BREAK.md
│   ├── FORGIS_MAC_DESIGN_LANGUAGE.md
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
├── examples/
│   └── local_migration_fixture/
├── tmp/
├── README.md
├── README.zh-CN.md
├── RELEASE_NOTES.md
├── Package.swift
├── Package.resolved
├── requirements.txt
└── AGENTS.md
```

`reports/`、`tmp/`、`.DS_Store` 等由 `.gitignore` 排除，不应视为源码入口。`rules/profiles/` 与 `rules/stacks/` 当前没有可见规则文件，含义需要后续确认。

## 关键目录职责

- `agent/`：Forgis Python/shell产品控制面。包括配置解析、local init/status/resume、migration plan、guardrails、validation、报告、PR body和workflow辅助；`run`只做`execve` handoff。旧DeepSeek/tool-loop/file-tool实现仅保留测试与历史解码，无production入口。
- `Apps/ForgisRuntimeCLI/Sources/`：唯一production Agent kernel CLI。直接使用Intatis v1启动/resume session、运行turn、处理events/approval/usage、输出runtime result与run report；没有Python AgentLoop或协议fallback。
- `Apps/ForgisMac/Sources/`：Mac SwiftUI产品界面，直接持有Intatis v1 session并投影message/tool/approval/usage/turn；build product嵌入exact Codex runtime root并提供零网络App Server session smoke。旧独立Chat HTTP client和mock数据已删除。
- `Forgis.xcodeproj/`：主target最低macOS 26，通过本地package reference `../Intatis`直接链接Core/Protocol/Providers/CodexRuntime四个公开product，并以build phase验证/嵌入exact runtime root。推荐命令行构建使用仓库外DerivedData。
- `.github/workflows/`：两条workflow都运行在`xcode-27`，checkout固定Intatis commit并构建Swift host；主迁移workflow只调用`forgis-runtime`，验证workflow运行exact offline smoke与Python控制面测试。
- `skills/`：仓库本地可注入的短技能文档。`agent/skill_loader.py` 只允许从仓库本地 `skills/*.md` 读取安全 slug。
- `prompts/`：Agent 系统提示词。`agent/deepseek_agent.py` 优先读取 `prompts/system_agent_v3.md`，失败时回落到内置 legacy prompt。
- `tests/`：unittest 测试套件和报告 fixture。历史核心行为集中在 `tests/test_forgis_config.py`；v7.0 新增 client/CLI/config 窄测试文件。
- `tests/fixtures/reports/`：run report / migration plan audit 的 active、blocked、completed、deferred 状态 fixture。
- `docs/`：项目说明与迁移参考文档。`DS_GUIDE_Swift_Kotlin.md` 是迁移策略参考，不是运行时自动规则。
- `reports/`：生成报告目录占位或本地输出位置，当前未发现跟踪文件。
- `tmp/`：本地烟测和临时输出，按 `.gitignore` 视为生成物。
- `rules/`：当前仅有空目录结构，未能确认运行时是否使用，标记为需要后续确认。

## 关键文件清单

- `Package.swift`：最低macOS 26；导出`ForgisMac`与`forgis-runtime`，后者直接依赖Intatis公开Core/Protocol/Providers/CodexRuntime v1 products。
- `Package.resolved`：SwiftPM根解析锁；固定Intatis manifest所声明远程依赖的实际revision/version。本地Intatis path本身不进入锁文件。
- `Forgis.xcodeproj/project.pbxproj`：Xcode project，包含 macOS app target `ForgisMac`，bundle id `com.Vita0818.ForgisMac`，deployment target macOS 26.0，generated Info.plist，无 entitlements，并直接链接同一两个Intatis product。
- `Forgis.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved`：Xcode工程自己的SwiftPM解析锁，与根SwiftPM锁分别由对应构建入口维护。
- `Forgis.xcodeproj/xcshareddata/xcschemes/ForgisMac.xcscheme`：shared scheme，使 Xcode 和 `xcodebuild -scheme ForgisMac` 能直接找到 Mac app target。
- `Apps/ForgisMac/Sources/ForgisMacApp.swift`：SwiftUI `@main` 入口和 `WindowGroup`，默认窗口1100×760；启动时先安装共享runtime host identity，再检查只启动/关闭session且零网络的`--forgis-codex-runtime-smoke`。普通App启动不自动启动runtime或发送turn。
- `Apps/ForgisRuntimeCLI/Sources/ForgisRuntimeCLI.swift`：production内核入口；以`target_subdir`为workspace-write根，读取task/source只读上下文，构造route/session，处理turn/events/approval并写v7 report。
- `Apps/ForgisMac/Sources/ForgisCodexRuntimeBootstrap.swift`：进程级v1 API-major与`Forgis` identity安装。
- `Apps/ForgisMac/Sources/ForgisCodexRuntimeSmoke.swift`：从App bundle启动exact runtime的零turn/零provider离线smoke。
- `Apps/ForgisMac/Sources/ForgisRootView.swift`：三栏主界面组合，左栏Migration/Reports/Settings，中央为真实runtime thread或报告/设置，右栏为section-aware inspector；content/detail共享动态system canvas。
- `Apps/ForgisMac/Sources/ForgisDesign.swift`：system semantic color、system canvas、serif/system/monospaced 字体、Material card、Liquid Glass/bordered fallback、40pt composer metrics 和 page header。
- `Apps/ForgisMac/Sources/ForgisModels.swift`：真实workspace/provider/run gate、runtime message/activity/usage、v7 report与UI projection数据模型；不包含mock运行数据。
- `Apps/ForgisMac/Sources/ForgisComponents.swift`：`StatusPill`、单行 `SafetyStrip`、`PathLabel`、`InfoRow` 等小组件。
- `Apps/ForgisMac/Sources/ForgisRuntimeSession.swift`：Mac UI唯一runtime owner。验证workspace/task/route与三重gate，直接构造Intatis session，消费events、处理approval/interrupt/usage并驱动连续turn；拒绝Chat Completions URL且无fallback。
- `Apps/ForgisMac/Sources/ForgisRuntimeStorage.swift`：Forgis identity派生的UserDefaults key、Keychain credential与owner-only Application Support runtime/report/projection存储。secret不进入projection/report/defaults。
- `Apps/ForgisMac/Sources/ForgisRuntimeViews.swift`：真实Migration thread、原生assistant streaming、approval card、Stop/follow-up composer和运行状态呈现。
- `Apps/ForgisMac/Sources/ForgisViews.swift`：Migration/Reports/Settings导航、真实v7 report列表与详情、workspace/route/gate/credential设置和section-aware inspector。
- `docs/FORGIS_MAC_DESIGN_LANGUAGE.md`：ForgisMac 当前视觉层级、字体、表面、组件、兼容 fallback 与安全边界契约。
- `agent/forgis_config.py`：解析 `FORGIS_CONFIG.yml`、支持字段、默认值、路径安全、真实运行 gate、`ResolvedConfig.env()` 输出。
- `agent/forge.py`：旧控制器入口，校验 source/target 目录并输出运行摘要；保留既有参数形式。
- `agent/cli.py`：本地control-plane入口；`init/status/resume`保留，`run`解析/持久化unit后用`os.execve`替换为`forgis-runtime`，无返回fallback。
- `agent/resolve_config.py`：GitHub Actions 中解析目标仓库配置并写入 `$GITHUB_ENV` / `$GITHUB_OUTPUT`。
- `agent/openai_compatible_client.py` / `agent/deepseek_agent.py` / `agent/file_tools.py`：legacy测试与历史实现；不在production迁移入口调用。
- `agent/tool_loop.py`：legacy测试loop；无显式`client_factory`的real run立即拒绝，不能成为新内核fallback。
- `agent/staged_translation.py`：`execution_mode=staged_translation` 的控制器，按 overview、per_file、stabilization 和微阶段 gate 推进。
- `agent/file_tools.py`：虚拟路径沙箱和工具实现。读 `source/`、`target/`、`target_subdir/`，写入仅限 `target_subdir`；`visual_validation.reference_screenshot_dirs` / `actual_screenshot_dirs` 是目标仓库只读截图输入目录，即使位于 `target_subdir` 内也不得被写工具修改。
- `agent/command_runner.py`：保守命令 allowlist。基础命令和 build/test profile 都在这里限制。
- `agent/build_runner.py` / `agent/build_feedback.py`：配置驱动 build/test 执行与失败摘要、脱敏。
- `agent/guardrails.py`：read-only snapshot、target scope、source clean、dry-run clean、secret leak 检查。
- `agent/validate_target_output.py`：目标输出快照、meaningful change 与 `success_checks` 验证。
- `agent/model_env.py`：`model_env` JSON 解析、环境变量映射与缺失 secret 检查，避免打印真实值。
- `agent/visual_evidence.py`：v6.0 Phase 3 视觉证据目录/状态 helper，负责 runtime 目录结构、状态枚举、阻塞原因、图片路径校验和可序列化摘要。不调用 Qwen，不读源码，不写业务文件。
- `agent/qwen_vision.py`：v6.0 Qwen provider adapter。缺少 API key 时安全 blocker；显式 `QWEN_API_KEY` 下可用标准库 HTTP transport；测试通过 mock `_post_qwen_vision_payload` 或 HTTP 层，返回有界脱敏 `QwenVisionResult`。
- `Apps/ForgisRuntimeCLI/Sources/ForgisRuntimeCLI.swift`写`forgis.run_report.v7.0`；`agent/run_report.py`的v6 renderer只供legacy fixtures/tests。两者都保留`visual_validation` block。
- `agent/migration_units.py`、`agent/migration_scheduler.py`、`agent/migration_state.py`、`agent/migration_plan_store.py`、`agent/plan_audit.py`：迁移单元、计划持久化、状态转换、resume 与 audit summary。
- `agent/repair_loop.py`、`agent/repair_report.py`、`agent/runtime_controller.py`：修复循环状态机、报告渲染与运行时观测状态。
- `agent/source_inventory.py`：源仓库扫描、过滤生成物/二进制/secret-like 文件、按优先级排序。
- `agent/skill_loader.py`：本地技能选择、加载、长度限制和 secret-like 内容检查。
- `docs/QWEN_VISUAL_MODE.md`：v6.0 Qwen Visual Evidence Mode 契约文档，说明 reference-guided migration、provider 边界、reference-first、证据状态、证据目录、mock-first provider adapter、真实 transport 启用条件、视觉 tool schema、report/PR 字段和 runtime gate。
- `skills/qwen_visual_mode.md`：可显式注入主 Agent 的短 skill，只记录 Qwen 视觉 provider 的安全边界。
- `agent/build_target.sh`：GitHub Actions 中运行 `validation_commands` 的脚本，作用域限定在目标仓库 `target_subdir`。v7.1 新增 argv mapping 路径，复用 `command_runner.py` allowlist；旧字符串保留兼容 warning。
- `agent/create_pr.sh`：真实运行后的 target branch 准备、提交、push 和 PR 创建。已有远程分支时改用 fallback branch，避免 force push。
- `agent/pr_body.py`：有界 PR body 生成，超长时可生成 short body；从 run report 中摘取脱敏 Visual Validation 摘要。
- `.github/workflows/migrate.yml`：完整运行工作流。
- `.github/workflows/validate-forgis.yml`：验证工作流，包含 py_compile、unittest、bash syntax、controller smoke test、`git diff --check`。

## 入口文件

- 手动 GitHub Actions 入口：`.github/workflows/migrate.yml`，输入只有 `target_repo`。
- 配置解析入口：`python forgis/agent/resolve_config.py --target ... --target-repo ...`。
- 控制器入口：`python forgis/agent/forge.py --source ... --target ... --target-repo ...`。
- 唯一模型循环入口：`forgis-runtime run ...`（Swift/Intatis）；直接执行`python agent/tool_loop.py`的real run被拒绝。
- 目标输出验证入口：`python forgis/agent/validate_target_output.py snapshot|validate ...`。
- guardrail 入口：`python forgis/agent/guardrails.py snapshot-readonly|check-readonly|check-target-scope|check-source-clean|check-dry-run-clean|check-secret-leaks ...`。
- 本地测试入口：`python3 -m unittest tests/test_forgis_config.py tests/test_openai_compatible_client.py tests/test_v7_cli_config.py tests/test_v7_local_cli.py tests/test_v7_local_smoke.py`。

## 配置文件

- `requirements.txt`：当前仅声明 `PyYAML>=6.0.2`。
- `.gitignore`：忽略 Python 缓存、虚拟环境、`.env`、日志、`reports/`、`forgis-runtime/`、`tmp/`、证书和 secrets 目录。
- 目标仓库运行配置默认是目标仓库根目录的 `FORGIS_CONFIG.yml`；本地 CLI 可用 `--config` 指向仓库外配置文件。v7.1 local config 可额外包含 `local_source_path`、`local_target_path`、`local_target_repo`，供 `status`、`run --unit`、`resume` 不依赖 GitHub Actions 输入。`agent/forgis_config.py` 拒绝未知字段和 secret-like config path。
- 目标仓库任务文件默认 `FORGIS_TASK.md`，可由 `task_prompt_path` 指定，但必须位于目标仓库根内且非空。
- production模型配置固定`agent_backend: codex-app-server`、`api_format: responses`，并支持`request_adapter: openai-compatible|openrouter|openai`、`api_base` / `base_url`、`model`和单一`model_env` credential引用。历史backend/api-format名称仅窄解码，不选择旧runtime。
- v7.1 `validation_commands` 推荐形态是 `- argv: ["python3", "--version"]` 或其它 allowlist 内 argv 数组。旧字符串仍可解析并由 `build_target.sh` 兼容运行，但会 warning。
- v6.0 `visual_validation` 配置块包含 `enabled`、`provider`、`mode`、`reference_screenshot_dirs`、`actual_screenshot_dirs`、`max_visual_iterations`、`require_reference_first`、`require_actual_for_full_validation`、`upload_visual_artifact`。默认 `mode=reference_guidance`，`reference_screenshot_dirs` / `actual_screenshot_dirs` 默认为空以保持兼容。
- v6.0 已接通 reference-guided migration、`list_visual_references`、视觉工具 schema、`FileToolSandbox` 分发、runtime visual state/gate、run report / PR body 视觉字段和显式 env 下的 Qwen HTTP transport。仍不自动截图、不上传 visual artifact、不支持多 provider。

## 测试目录

- `tests/test_forgis_config.py`：覆盖配置解析、工作流约束、工具沙箱、staged translation、migration plan、report、guardrails、PR body 等。
- `tests/test_openai_compatible_client.py`：覆盖 v7.0 client request schema、URL 拼接、timeout、HTTP/JSON/shape 错误脱敏和 DeepSeek shim 兼容。
- `tests/test_v7_cli_config.py`：覆盖 v7.0 config 字段、backend alias、env 缺失、CLI help/dry-run、command allowlist 和 `validation_commands` 回归。
- `tests/test_v7_local_cli.py`：覆盖 `doctor`、`run --config`、summary output、缺失 env 错误脱敏、examples config 解析和 DeepSeek shim 本地配置兼容。
- `tests/test_v7_local_smoke.py`：覆盖 `python -m agent.cli smoke --workdir ...` 的 dry-run 本地闭环、不调用 API、不写 target。
- `tests/test_v7_local_init_status.py`：覆盖 v7.1 `init` 生成 local config、不写 source/target、`status` 读取 config 和 secret 不泄露。
- `tests/test_v7_local_migration_flow.py`：覆盖 v7.1 `run --unit`、dry-run 不调用 API/不写 target、resume active/blocked/pending/no-task 和 examples fixture smoke。
- `tests/test_v7_validation_commands.py`：覆盖 `validation_commands` argv 解析、allowlist 执行、shell bypass 拒绝、旧字符串 warning，以及 DeepSeek/openai-compatible/Qwen 配置兼容。
- `tests/fixtures/reports/*.json`：报告 fixture 和 golden-like 样本。
- `tests/__init__.py`：测试包标记文件。

## 资源目录

- `skills/*.md`：本地技能文本，包括 `migration_general`、`swiftui_to_compose`、`swiftui_to_harmonyos`、`ui_style_preservation`、`build_repair`、`qwen_visual_mode`。
- `prompts/system_agent_v3.md`：运行时系统提示词。
- `docs/DS_GUIDE_Swift_Kotlin.md`：SwiftUI 到 Kotlin/Compose 迁移风险文档。
- `docs/QWEN_VISUAL_MODE.md`：Qwen Visual Evidence Mode 的长期维护说明。当前 v6.0 已接入 reference guidance、受控视觉工具、报告字段、gate 和真实 provider transport；自动截图采集、artifact 上传和多 provider 仍未实现。
- `examples/FORGIS_CONFIG.local.openai-compatible.yml`：文件名为历史兼容，内容已是native Responses/Codex模板，只通过env引用credential。
- `examples/FORGIS_CONFIG.local.smoke.yml`：无 API key dry-run smoke 模板。
- `examples/local_migration_fixture/`：v7.1 最小本地迁移 fixture，包含 toy SwiftUI-style source、toy target task 和小型 target-output 文件，不包含 secret 或外部依赖。

## 生成物和缓存目录

- `tmp/`：本地烟测、临时 manifest、bundle、log 片段。当前工作区存在但被忽略。
- `reports/`：当前为空目录，`.gitignore` 只保留可能的 `.gitkeep`，但本轮未发现跟踪文件。
- `forgis-runtime/`：GitHub Actions 运行时目录，被忽略；v5.0 artifact 只上传 `forgis-runtime/reports/**`。
- Python `__pycache__/`、`.venv/`、`venv/`、`.env`、secret/cert 文件都属于禁止扫描或禁止提交对象。

## 不确定项

- `rules/profiles/` 与 `rules/stacks/` 当前为空，未在已读源码中发现明确加载逻辑。标记为 `需要后续确认`。
- `reports/` 目录当前为空且被忽略，是否需要保留 `.gitkeep` 未能从当前跟踪文件确认。
- README 提到的某些历史版本章节用于说明演进，不一定代表当前新增能力；以 `agent/` 源码和 `RELEASE_NOTES.md` v5.0 为准。
