# 当前状态

最近自查日期：2026-09-02

## 2026-09-02 Mac产品UI全量切换

ForgisMac已从静态/mock壳与独立Chat Completions客户端全量切到Intatis公开
`IntatisCodexRuntime` v1。默认产品入口现在是Migration工作台；App直接构造
`ResponsesRuntimeRoute`、`CodexRuntimeConfiguration`和`CodexAppServerSession`，消费原生流式
assistant message、tool item、approval、interrupt、usage、turn result和runtime error。旧
`ForgisChatModels` / `ForgisChatService` / `ForgisChatStorage` / `ForgisChatSmoke` /
`ForgisChatViews`以及`MockForgisData`已从源码与Xcode target删除，不存在HTTP Chat fallback。

- Settings选择真实source、target、task和`target_subdir`，配置native Responses route/model/adapter、
  Keychain或env credential引用，并保留`dry_run` / `run_agent` / `confirm_real_run`三重gate。
- dry run只做只读输入验证并写skipped v7报告；不启动Intatis、不解析credential、不创建
  `target_subdir`、不发送网络请求。
- real run只有三重gate成立后才创建严格target子目录作为唯一workspace-write根，并直接运行同一
  Intatis session。UI提供用户审批、session级审批、拒绝、取消turn、主动中断和后续连续对话。
- Forgis只持久化有界脱敏的UI projection、operation items和`forgis.run_report.v7.0`到由
  `IntatisHostApplicationIdentity(name: "Forgis")`派生的owner-only Application Support runtime root；
  credential只存在Keychain/env与Intatis child process内存，不进入UserDefaults、报告或投影。
- App仍按官方资源布局嵌入exact runtime。SwiftPM与Xcode构建、bundle offline session smoke和
  Migration/Settings/Reports运行态视觉检查通过；验证未发送任何turn或provider请求。

## 2026-09-01 产品Agent Runtime全量切换

所有production迁移Agent入口现已切到Intatis公开`IntatisCodexRuntime` v1与exact
`codex-cli 0.145.0-intatis.4`。新增SwiftPM executable `forgis-runtime`，直接构造
`ResponsesRuntimeRoute`、`CodexRuntimeConfiguration`、`CodexAppServerSession`并消费原生events、approval、
usage和tool item。Codex拥有agent loop、context、native file/patch/command tools、sandbox和auto-review；
Forgis只保留task/workspace/credential引用、session storage、输出投影和产品guardrails。

- 本地`python -m agent.cli run`只解析Forgis配置与migration unit，然后用`os.execve`替换进程进入Swift
  CLI；成功handoff后没有Python返回路径。
- `.github/workflows/migrate.yml`运行在官方`xcode-27` runner，checkout固定Intatis commit
  `e8ba63554daa57455193772c6ba0abe08f04c0a0`，在runner临时目录通过Intatis官方脚本构建/校验exact
  arm64 runtime，再直接执行Swift kernel。workflow不再调用`agent/tool_loop.py`。
- `target_subdir`直接作为唯一`workspace-write`根；source repo、target root、config和task都在写根外。
  运行后仍由既有guardrail验证source clean、target scope、read-only inputs和secret leaks。
- 旧`agent/tool_loop.py`只允许测试显式注入`client_factory`；无注入的real run明确报错。旧DeepSeek/
  Chat Completions Agent代码不再有production入口，也不是fallback。
- ForgisMac build phase按Intatis官方layout静态校验并把active-architecture Codex runtime root复制到App
  build product；`--forgis-codex-runtime-smoke`真实执行start/thread-start/shutdown且不发送turn，输出
  `network_requests=0`。2026-09-02起Mac产品UI也直接使用该内核，旧独立Chat表面已删除。
- 新内核输出`forgis.codex_runtime_result.v1`与`forgis.run_report.v7.0`。migration plan、validation、PR和
  target long-term log仍是Forgis产品控制面。

限制必须如实保留：本轮没有调用任何真实provider API；显式`visual_validation.enabled=true`因共享v1尚无
Qwen official dynamic-tool接线而fail closed，绝不回退旧Python/Qwen Agent工具；本地runtime kit也不是已
Developer ID签名/公证的发行制品，正式distribution closure仍未完成。

## 2026-09-01 IntatisCodexRuntime 最小依赖接线（已被上节全量切换取代）

以下两段仅保留同日早期状态记录，不描述当前production行为。

ForgisMac 的 SwiftPM 与 Xcode 主 target 已通过只读本地路径 `../Intatis` 直接链接公开
`IntatisCore` / `IntatisCodexRuntime` v1 product，并把最低平台同步为 macOS 26。新增
`ForgisCodexRuntimeBootstrap`，在 App 入口构造任何共享对象前校验
`CodexRuntimeHostContract.publicAPIMajorVersion == 1`，随后只安装
`IntatisHostApplication.configure(name: "Forgis")`。SwiftPM 与 Xcode 各自保存解析锁文件。

这是编译与产品身份边界，不是运行时切换：当前不创建`CodexAppServerSession`、不启动或复制
`codex` executable、不配置Responses route、不注册dynamic tools，也不修改现有Mac AI Chat、Python
CLI/Agent、Qwen或文件沙箱。Intatis仓库保持只读；缺失、不兼容或无法构建时必须明确失败，禁止在
Forgis内增加App Server wrapper、旧runtime fallback或另一backend。

## 当前工作区状态摘要

启动前检查结果：

```text
pwd: <PROJECT_ROOT>
git root: <PROJECT_ROOT>
git status --short: 以当前 checkout 和任务最终报告为准，不在常驻文档中固化临时修改清单
```

Mac UI现已提供真实workspace/task/route选择、Migration session、原生event/approval/usage投影、持久化Reports和Settings；不再展示mock migration units或独立AI Chat。Mac target为macOS 26并嵌入exact Codex runtime build resource。local CLI继续保留`init/status/resume`控制面，`run`全量handoff到Swift/Intatis；GUI与CLI共享同一Intatis/Codex内核，但各自拥有独立session runtime root。历史backend名称只归一化到同一Codex内核。本轮验证没有发送真实turn或provider请求；Qwen visual、自动截图、artifact upload与正式signed distribution仍按既有限制处理。

## 当前项目已实现能力

- 目标仓库配置解析：默认读取目标仓库根目录 `FORGIS_CONFIG.yml`；本地 CLI 可用 `--config` 显式读取外部配置文件。未知字段失败，必填 `source_repo`、`target_branch`，`target_repo` 由 workflow/CLI 输入。
- 运行开关：真实模型执行需要 `dry_run=false`、`run_agent=true`、`confirm_real_run=true` 同时成立。
- production模型调用：CLI与Mac UI都只接受native Responses route并交给Intatis Codex App Server；legacy backend/api-format配置名仅窄解码后归一到`codex-app-server`/`responses`。旧Python Chat Completions client只保留legacy测试代码，不存在Mac产品入口。
- 本地 CLI：`agent/cli.py` 支持 `python -m agent.cli help`、`doctor`、`smoke`、`init`、`status`、`run --config ... --unit ...`、`resume`，并继续兼容旧式 `run --source ... --target ... --target-repo ... [--config ...] [--dry-run]`。本地 config 可记录 `local_source_path`、`local_target_path`、`local_target_repo`，但只保存 env var 名，不保存 secret 值。
- Mac UI：`Forgis.xcodeproj` 是当前推荐打开方式，target/scheme 为 `ForgisMac`。`Apps/ForgisMac/Sources/`提供真实Migration、Reports和Settings。Migration直接显示Intatis assistant/tool/approval/usage/turn状态并支持Stop和后续turn；Settings选择source/target/task/write root与native Responses route，Keychain只保存bearer credential，UserDefaults只保存非secret配置；Reports读取App自身实际写出的v7报告。视觉层继续使用system semantic colors、system canvas、Material、Liquid Glass、SF Symbols和serif/system/monospaced字体分层。
- Intatis共享宿主：Mac bundle、Swift CLI、本地CLI handoff与GitHub Actions均已接通；offline session smoke通过。
- production工具/沙箱：由Codex native tools与native workspace sandbox拥有，`target_subdir`是唯一写根。下列旧Python工具名只保留legacy fixtures/tests，不再发布给production模型。
- build/test feedback：可选 `build_command`、`test_command` 参数数组，经保守 allowlist 执行，输出会截断和脱敏。
- repair loop：可配置有限修复尝试、diff/build/test gate、事件和报告。
- staged translation：支持 overview、per_file、stabilization 阶段和 per-file 微阶段 gate。
- local skills：支持从仓库本地 `skills/*.md` 自动或显式选择并注入短指导。
- Qwen Visual Evidence Mode：v6源码/fixtures与报告字段保留；production Codex v1尚无official dynamic-tool接线，显式required视觉任务fail closed，auto模式只报告未调用与limitation。
- migration scheduler / plan：支持 source inventory、unit 类型和优先级、计划持久化、resume、人工 active unit switch、人工 unit status update、audit summary。本地 `run --unit` 通过 existing plan state 显式选择一个 unit；默认不自动运行 all-units。
- validation commands：新配置推荐 `validation_commands: [{argv: [...]}]`，由 `command_runner.py` allowlist 校验并由 `agent/build_target.sh` 以 `shell=False` 路径执行。旧字符串仍兼容，但会打印 warning。
- 报告：支持 `FORGIS_RUN_REPORT.md`、`FORGIS_RUN_REPORT.json`、`FORGIS_MIGRATION_PLAN.json`，v5.0 schema 已冻结。
- GitHub Actions：`migrate.yml` 编排完整运行，`validate-forgis.yml` 做本仓库验证。
- PR 创建：真实运行后可提交、push、创建 PR。若远程目标分支已存在，使用 fallback branch，避免 force push。

## 当前未完成能力

以下不是臆测路线图，而是 README/RELEASE_NOTES 明确列为 v5.0 非目标或当前未实现的能力：

- 完整 Claude Code parity。
- 多 migration unit 自动连续执行。
- 模型控制的 plan 重排。
- 复杂 RAG。
- 外部 skill 下载或从业务仓库加载 skills。
- 任意 shell 访问。
- Aider 后端。
- 跨语言 build adapter、真实 UI 控制台。
- 上传 legacy runtime diagnostics artifacts、业务源码、完整 diff、secret、未脱敏模型输出或 target repository snapshot。
- 真实外部Responses provider兼容性、正式签名/公证runtime发行包、Qwen visual dynamic-tool接线仍未验证或完成。Mac workspace/task/route选择和Intatis UI执行链已经完成，但本轮只做离线验证，未用真实credential发送turn。
- 自动截图、adb/hdc/Windows/macOS 截图、visual artifact 上传、多 provider 视觉、UI dashboard。当前视觉闭环依赖用户在目标仓库提供 reference screenshots；actual screenshots 可选。真实 Qwen transport 只有显式提供 `QWEN_API_KEY` 时才会调用，单元测试仍使用 mock，不联网。
- Mac UI不解析`FORGIS_CONFIG.yml`或Python migration-plan scheduler；GUI使用自己的显式workspace/route表单与Intatis session，CLI/GitHub仍使用YAML控制面。两者都遵守同一write-root、credential、gate和report schema，但GUI不会冒充已接入CLI plan状态。

## 当前已知 bug / 风险

- 旧式字符串 `validation_commands` 仍会通过 `bash -lc` 兼容运行，并打印 warning；新文档和示例必须使用 argv mapping。不要把旧字符串用于新增本地 full migration 配置。
- `tests/test_forgis_config.py` 覆盖面广但文件很大，新增行为时容易漏读相关测试块。
- `agent/forgis_config.py`、`agent/tool_loop.py`、`agent/staged_translation.py` 字段和状态面较宽，新增字段需要同时更新 env/output、report、tests、README、常驻文档和 fixture。
- Responses providers 的endpoint与native tool shape存在差异；Mac UI和CLI都只把exact route交给Intatis/Codex，Chat Completions URL在本地验证阶段明确拒绝。错误、projection和report必须有界脱敏，不得加入协议translator或另一transport。
- `visual_validation` 已驱动受控视觉工具、报告字段和 runtime gate。缺少 API key、provider 不可用或找不到 reference screenshots 时必须写 blocker；reference-only 可完成视觉迁移指导，但必须写 limitation，不能被当成完整真实渲染验收。真实 transport 的风险集中在 env 管理与 provider response 脱敏，测试必须保持 mock-first。
- README 和 README.zh-CN 包含多个历史版本章节，容易误读为当前新增能力。当前行为应以源码、workflow 和 `RELEASE_NOTES.md` v5.0 为准。
- `rules/` 目录当前为空，运行时含义未确认。
- ForgisMac现在要求macOS 26与同级`../Intatis` checkout；本地path dependency不会固定Intatis commit，因此消费的是该路径当前源码。两个仓库必须保持独立Git边界，Forgis构建不得写入Intatis。

## 当前优先级建议

- 修改配置字段或运行 gate 时，先从 `agent/forgis_config.py` 和配置测试入手。
- 后续若继续扩展，下一步才考虑可选截图 acquisition adapters；不要直接实现 artifact 上传、多 provider、UI dashboard、任意 shell 或 all-units 自动执行。
- 修改工具权限或路径行为时，先读 `agent/file_tools.py`、`agent/command_runner.py`、`agent/guardrails.py` 和相关测试。
- 修改报告或 migration plan 时，同步 fixture、schema 文档和 PR body/report 测试。
- 修改 GitHub Actions 时，同步 `.github/workflows/validate-forgis.yml` 中的 workflow 结构测试。

## 文档可信度说明

本轮文档基于实际读取的目录结构、README、RELEASE_NOTES、workflow、核心 `agent/` 源码、skills、prompt、测试清单和 fixture。v6.0 视觉闭环的实际验证命令以本轮最终报告和 `docs/TESTING.md` 为准。

## 源码与旧文档冲突记录

- README 中存在历史版本说明；若与当前源码冲突，以 `agent/` 源码和 `.github/workflows/` 为准。
- 历史文档/legacy renderer仍会提到run report v5/v6；当前Swift内核写`forgis.run_report.v7.0`，legacy v6 fixtures继续用于旧数据/投影回归。
