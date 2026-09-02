# 架构说明

## 外部依赖优先与禁止功能兜底（Vitemis 强制规则）

本项目继承 `/Users/vita/Vitemis/docs/DEPENDENCY_POLICY.md`。本节是强制约束，不是建议。

- 当用户指定、仓库已经采用，或经许可证、provenance、安全与平台审查可采用的外部依赖提供同等能力时，必须直接集成该依赖的官方 API 或官方扩展点。
- 不得自行重写同等能力，不得新增替代 adapter、shim、compatibility layer、wrapper、proxy、facade、协议翻译层、parallel backend、preview backend、shadow implementation 或“先兜底、以后再换”的实现。
- 本地代码只允许保留官方 API 必需的最薄生命周期、类型、权限、配置和 bundle 接线；不得重新实现、解释、扩展或替代依赖的核心能力。
- exact 依赖因版本、构建、签名、许可证、平台、安全或官方 API 限制无法接入时，必须停止该能力、明确失败、报告 blocker 并请求用户决定；不得静默降级、切换 legacy/另一 provider/backend、使用 cache/mock/简化路径或继续交付不完整替代实现。
- 现有 fallback、adapter 或重复实现不构成先例，后续不得扩展。安全 fail-closed 与明确要求的旧数据解码/迁移不是功能兜底，但必须保持最窄范围，不能演化成备用产品实现。
- 只有用户针对 exact 依赖、exact 范围和退出条件作出的新明文决定才能例外。

最近自查日期：2026-09-02

## 总体架构

### 当前production Agent架构（2026-09-01全量切换）

Forgis的唯一production迁移内核是Intatis公开`IntatisCodexRuntime` v1与固定派生
`codex-cli 0.145.0-intatis.4`。Swift `forgis-runtime`直接拥有App Server process、session、thread、turn、
events、approval与shutdown；Codex拥有agent loop、context、native tools、sandbox和auto-review。Forgis不
实现JSON-RPC、Responses translator、第二tool loop或runtime fallback。

```text
FORGIS_CONFIG / task / selected unit
  -> Python control plane（解析、plan、guardrails；不调用模型）
  -> execve forgis-runtime
  -> IntatisCodexRuntime v1
  -> exact codex app-server --stdio
  -> native Responses route（仅真实用户运行时）
  -> target_subdir native workspace-write
  -> Forgis v7 report + validation/guardrail/PR control plane
```

本地CLI和GitHub Actions都进入同一Swift executable。workflow固定Intatis commit并在`xcode-27` runner临时
目录中调用Intatis官方build/validator生成exact arm64 runtime；Mac App build phase则从只读runtime kit校验
并复制active-architecture root到build product的官方资源路径。测试只运行doctor与start/thread-start/
shutdown offline smoke，不发送turn，`network_requests=0`。

权限边界通过官方workspace表达：`target_subdir`是唯一workspace-write根；source repo、target root、config
与task位于写根外。模型只收到路径和task文本，所有代码/命令能力来自Codex native tools。旧Python
`FileToolSandbox`和command allowlist不再是production模型工具面，但post-run guardrails仍独立验证source
clean、target scope、read-only inputs和secret leaks。

显式`visual_validation.enabled=true`当前因Intatis v1没有Forgis Qwen official dynamic-tool接线而fail
closed；禁止退回旧Python视觉工具。Mac产品UI与CLI都直接使用同一Intatis v1内核；旧独立Chat
Completions UI/client/smoke已删除，不能承担fallback。

### 历史架构记录（非production）

以下段落记录v7.1–v7.3早期Python Agent与最小Intatis接线状态，仅用于理解legacy tests，不覆盖上节当前production架构。

Forgis 曾是一个 Python CLI/Agent 工具，外加 v7.3 Mac SwiftUI 壳。Python 核心读取目标仓库配置与任务文件并调用非streaming Chat Completions；这些模型/tool-loop行为现已退出production。

2026-09-01新增的Intatis边界仅存在于ForgisMac：SwiftPM和Xcode主target以本地path
`../Intatis`直接链接公开`IntatisCore` / `IntatisCodexRuntime` v1，并将最低平台同步为macOS 26。
`ForgisCodexRuntimeBootstrap`只在进程入口校验v1 host contract并安装`Forgis` product identity。
该早期阶段尚未创建session/route/runtime bundle；现已由上节全量切换取代。Intatis checkout始终只读。

以下旧Python运行方式仅作历史/测试结构说明，不是当前production调用链：

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
- Legacy Agent调用层：`agent/openai_compatible_client.py`与`agent/deepseek_agent.py`只服务历史fixture和显式测试client注入，不在CLI或Mac production入口。
- Mac runtime UI层：`ForgisRuntimeSession.swift`直接构造`ResponsesRuntimeRoute`、`CodexRuntimeConfiguration`与`CodexAppServerSession`，消费官方event stream并提供approval、interrupt、usage和连续turn；`ForgisRuntimeViews.swift`只做presentation；`ForgisRuntimeStorage.swift`只做host identity派生的配置、credential引用、projection和report生命周期。该层不实现App Server协议、tool loop、provider HTTP或fallback。
- 共享Codex宿主编译边界：`Apps/ForgisMac/Sources/ForgisCodexRuntimeBootstrap.swift`只负责API-major fail-closed与进程级host identity安装；session/provider/UI projection由上述Mac runtime UI层通过公开v1 API完成，不得塞回bootstrap或重写transport。
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
- `ForgisWorkspaceConfiguration` / `ForgisProviderConfiguration`：Mac UI的显式source/target/task/write-root、native Responses route/model/adapter和credential env引用；不保存credential值。
- `ForgisRuntimeViewModel`：Mac UI唯一session owner，投影`CodexRuntimeEvent`到有界message/activity/approval/usage状态，并维护三重real-run gate。
- `ForgisRuntimePreferencesStore` / `ForgisRuntimeCredentialStore`：前者通过Intatis host identity派生的UserDefaults key只保存非secret配置；后者通过派生Keychain service保存bearer credential。
- `ForgisRuntimeFileStore`：在Forgis Application Support下创建0700 runtime root，保存有界UI projection、operation log和`forgis.run_report.v7.0`，不写source或target。
- `RunReportWriteResult` / report JSON：`agent/run_report.py` 输出 `forgis.run_report.v6.0`，包含常驻 `visual_validation` 块。
- Migration plan JSON：`agent/migration_plan_store.py` 输出 `forgis.migration_plan.v5.0`，并兼容读取 v4.8、v3.9、v3.8、v3.7。

## 关键业务链路

### Legacy默认tool loop（测试注入专用）

1. `resolve_config()` 固定读取目标仓库根目录 `FORGIS_CONFIG.yml`。
2. `run_tool_loop()` 先加载 skills 和 migration plan。
3. 若 `dry_run=true` 或有效 `run_agent=false`，返回 skipped result，不调用模型。
4. 若执行，创建 `FileToolSandbox`、`RuntimeController`、`RepairLoopController`。
5. 配置的模型每轮返回 tool calls 或 final summary。
6. 工具调用经 `sandbox.invoke()` 执行，结果写回 message history，并同步 runtime/repair/migration plan 状态。
7. final summary 前可能被 repair loop gate 阻止，要求先 diff 或 build/test。
8. 完成或达到 max iterations 后，生成 repair report、run report、migration plan、status env、operation log。

### Legacy staged translation（测试/历史plan metadata）

`execution_mode=staged_translation` 时，`tool_loop.py` 转入 `agent/staged_translation.py`。该模式先扫描 source inventory，然后按 `overview`、`per_file`、`stabilization` 推进。per-file 阶段可强制 `feed`、`write`、`readonly_compare`、`revise` 微阶段。控制器会阻止过早 final summary，并限制 overview、feed、compare 等阶段只能写 staged progress artifacts 或 compare reports。

### GitHub Actions 真实运行

`.github/workflows/migrate.yml`先构建exact Intatis runtime与Swift host，再直接运行`forgis-runtime`。真实push/PR仍只在`dry_run=false`、`run_agent=true`、`confirm_real_run=true`且guardrails、validation、secret leak检查成功时发生。`agent/create_pr.sh`不force push；远程目标分支已存在时仍使用fallback head。

### Qwen Visual Evidence Mode 链路

v6.0 建立契约、配置解析、证据目录/状态 helper、mock-first provider adapter、受控视觉工具、report/PR 字段和 runtime gate。首选链路是 reference-guided migration：用户把 reference screenshots 放在目标仓库配置目录中，模型先调用 `list_visual_references`，再对关键截图调用 `inspect_visual_reference`，DeepSeek / 主 Agent 根据 Qwen 视觉结构、层级、颜色、字体、间距、圆角和组件关系反馈修改目标代码。actual screenshots 与 `compare_visual_screenshots` 只在用户已提供目标渲染截图时作为可选增强。主 Agent 仍负责代码修改、构建、测试和最终报告；Qwen 不读源码、不运行命令、不改文件。

## 数据流、请求流和状态流

- 配置流：目标仓库 `FORGIS_CONFIG.yml` 或本地 CLI `--config` -> `resolve_config.py` / `agent.cli` -> `ResolvedConfig.env()` -> GitHub Actions env 或本地 tool loop。v7.1 local config 的 `local_*` 字段只供 CLI 定位本地 source/target/target_repo，不保存 secret。
- 本地迁移流：`agent.cli init` 写显式 output config；`status` 解析 config 并加载或生成有界 migration unit summary；`run --unit` 通过 existing migration plan switch 选择一个 active unit，再进入 dry-run 或 gated real tool loop；`resume` 只读取 persisted migration state 并输出下一步，不调用模型或 shell。
- 视觉配置/证据流：`visual_validation` -> `VisualValidationConfig` -> `FORGIS_VISUAL_*` env/output；`list_visual_references` 从 `reference_screenshot_dirs` 返回合法图片虚拟路径；visual inspect/compare tool call -> `FileToolSandbox` 虚拟路径校验 -> runtime `visual-evidence/<run_id>/<target_repo_slug>/reference|actual|qwen` 目录创建 -> `qwen_vision` mockable adapter -> `RuntimeController` 视觉状态（含 `guidance_completed` / `full_rendered_validation`）-> `FORGIS_RUN_REPORT.md/json` 和 PR body 视觉摘要。
- 任务流：目标仓库 task file -> `deepseek_agent.initial_messages()` 中提示模型先读取 `task`。
- production模型请求流：CLI或Mac UI -> `CodexAppServerSession.runTurn()` -> exact App Server native Responses wire。旧`DeepSeekClient`/`OpenAICompatibleClient`只供legacy tests，不在任何产品入口。
- Mac UI请求流：Settings显式workspace/route/gate -> Keychain credential或配置env fallback -> `ForgisRuntimeViewModel` -> `CodexAppServerSession.events/start/runTurn/resolveApproval/interruptCurrentTurn`。UI不构造HTTP request、不翻译Responses、不调用Chat Completions；dry run在credential解析和workspace创建前结束。
- production文件访问流：Codex native tool -> native sandbox，以`target_subdir`为workspace-write；Forgis post-run guardrail独立复核。旧`FileToolSandbox`流仅为legacy测试。
- 状态流：工具结果 -> `RuntimeController.observe_tool_result()`、`RepairLoopController.observe_tool_result()`、migration plan runtime fields -> report/status outputs。
- 报告流：runtime state + operation log -> `repair_report`、`run_report`、`FORGIS_MIGRATION_PLAN.json`、GitHub Step Summary、target `FORGIS_LOG.md`。

## 网络、本地存储、后台任务

- 网络：只有用户完成Mac UI三重real-run gate并按下Start/Send，或CLI/GitHub进入同一真实gate后，Intatis child App Server才可能调用配置的native Responses route。Settings保存、provider配置、App启动、构建、doctor和offline smoke不发送网络请求。仓库checkout/push/PR由GitHub Actions和`gh`/`git`完成；Qwen仍只有显式`QWEN_API_KEY`与官方能力可用时才允许调用，当前Mac/production Codex v1没有该接线。
- 本地存储：目标仓库输出只允许写入`target_subdir`。Mac runtime、UI projection、operation log和v7报告位于Forgis identity派生的owner-only Application Support root；非secret workspace/route偏好写UserDefaults，bearer credential写Keychain或只从显式env读取。secret不写源码、报告、projection、fixture或日志。
- 后台任务：没有常驻 daemon。所有任务由 CLI 或 GitHub Actions step 驱动。

## UI 与业务逻辑分层

Mac UI推荐入口是`Forgis.xcodeproj`，target/scheme为`ForgisMac`；`Package.swift`保留轻量SwiftPM build entry。当前UI只保留Migration、Reports和Settings：Migration是Intatis原生event thread，Reports读取真实v7产物，Settings配置真实workspace/route/gate/credential。视觉架构由`ForgisDesign.swift`集中提供：system window canvas、Material结构面、Liquid Glass功能控制、SF Symbols以及serif/system/monospaced层级。assistant final直接落在canvas，user/system/error使用有界表面，commentary使用次级文字。完整视觉契约见`docs/FORGIS_MAC_DESIGN_LANGUAGE.md`。

由于Intatis公开package的最低平台为macOS 26，ForgisMac的SwiftPM、Xcode deployment target和生成
Info.plist最低系统均为26.0；旧13–15视觉fallback源码没有在本次最小依赖接线中删除或重写，但不再属于
当前shipping deployment范围。

Settings只保存非secret workspace与native Responses route；没有“测试provider”HTTP旁路。Migration在三重gate后直接启动Intatis，显示流式消息、tool item、approval和usage；Stop调用官方interrupt，后续输入复用同一session。dry run明确不启动runtime、不读credential、不创建write root。GUI不解析YAML scheduler；CLI/GitHub继续拥有`FORGIS_CONFIG.yml`和migration-plan控制面。

## 平台相关与共享代码边界

Forgis 核心保持平台无关。SwiftUI、Compose、HarmonyOS 相关内容位于 `skills/` 和 `docs/DS_GUIDE_Swift_Kotlin.md`，用于任务上下文和人工参考，不应硬编码到 `agent/` 的核心逻辑中。

## 安全、鉴权、权限和文件访问

- `model_env` 只映射环境变量名，`model_env.py` 校验缺失但不打印真实 secret。OpenAI-compatible client 的异常、repr、日志和 report 字段不得包含 API key、Authorization header、raw provider response 或完整模型输出。
- Mac UI只显示Keychain/env/no-auth状态和env name；credential仅交给`ResponsesRuntimeRoute`，不得写argv、task、UserDefaults、projection、report、operation log、源码、测试或fixture。错误和runtime event在投影前必须按active credential脱敏并截断。
- 外部 `--config` 是只读运行输入；路径不得包含 secret-like 段，不得位于 source repo 内，模型只能通过虚拟路径 `config` 读取它，写工具不能修改它。
- `visual_validation` 不允许 API key、token、API base、model name、截图文件路径或证据根目录字段；只允许 target-repo-relative `reference_screenshot_dirs` / `actual_screenshot_dirs` 作为只读目录输入，未知字段直接失败。
- `guardrails.py check-secret-leaks` 会扫描 `target_subdir` 是否写入配置映射中的 secret 值。
- 文件工具拒绝绝对路径、`..`、`.git`、secret-like 路径、symlink 写入、source 写入、target root 写入、workflow 文件写入。
- `run_command` 只允许保守基础命令，且 cwd 必须在 `target_subdir` 内。
- `run_build` / `run_tests` 只运行配置数组命令，profile 目前只允许安全 Python `py_compile` / `unittest` 类命令。
- `validation_commands` 新配置应使用 argv mapping，并由 `agent/build_target.sh` 通过 `command_runner.py` allowlist 执行。旧字符串仍以 `bash -lc` 兼容运行并打印 warning，不应出现在新示例或本地 full migration 配置中。
- CLI与Mac UI都已启动Codex session/turn能力；没有真实provider调用测试、没有协议translator或fallback。Chat Completions URL由Mac/CLI本地配置验证明确拒绝。

## 当前架构风险或不确定点

- 旧式字符串 `validation_commands` 仍存在兼容风险；新增测试覆盖 argv allowlist 和 shell bypass 拒绝。后续可以考虑将旧字符串从 warning 升级为 strict reject。
- 测试集中在单个 6000 行左右的 `tests/test_forgis_config.py`，定位方便但维护成本高。
- `rules/` 目录为空且未确认使用。
- staging、migration plan、report、repair loop 的状态字段很多，新增字段时容易漏掉 env、report、fixture 和测试。
- 视觉模式后续接入截图采集和 artifact 上传风险较高：不得把 Qwen 变成代码 Agent，不得上传源码或 secret，不得把 reference-only guidance 当完整真实渲染验收，不得用无效桌面截图冒充 actual app screenshot。Phase 8+ 接入 screenshot acquisition 前必须继续保持 mock-first 测试。
- README 存在历史版本说明，当前行为应以 `agent/` 源码、workflow 和 `RELEASE_NOTES.md` v5.0 为准。
