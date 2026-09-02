# Forgis 项目常驻上下文

## 外部依赖优先与禁止功能兜底（Vitemis 强制规则）

本项目继承 `/Users/vita/Vitemis/docs/DEPENDENCY_POLICY.md`。本节是强制约束，不是建议。

- 当用户指定、仓库已经采用，或经许可证、provenance、安全与平台审查可采用的外部依赖提供同等能力时，必须直接集成该依赖的官方 API 或官方扩展点。
- 不得自行重写同等能力，不得新增替代 adapter、shim、compatibility layer、wrapper、proxy、facade、协议翻译层、parallel backend、preview backend、shadow implementation 或“先兜底、以后再换”的实现。
- 本地代码只允许保留官方 API 必需的最薄生命周期、类型、权限、配置和 bundle 接线；不得重新实现、解释、扩展或替代依赖的核心能力。
- exact 依赖因版本、构建、签名、许可证、平台、安全或官方 API 限制无法接入时，必须停止该能力、明确失败、报告 blocker 并请求用户决定；不得静默降级、切换 legacy/另一 provider/backend、使用 cache/mock/简化路径或继续交付不完整替代实现。
- 现有 fallback、adapter 或重复实现不构成先例，后续不得扩展。安全 fail-closed 与明确要求的旧数据解码/迁移不是功能兜底，但必须保持最窄范围，不能演化成备用产品实现。
- 只有用户针对 exact 依赖、exact 范围和退出条件作出的新明文决定才能例外。

本文件继承 `/Users/vita/Vitemis/AGENTS.md` 中的 Vitemis 通用 Agent 规则。若本文件与通用规则冲突，在不违反系统和用户指令的前提下，以更具体、更严格的项目规则为准。

本文是 AI Agent 每轮进入本仓库时的入口文件。执行任何代码修改、配置修改、构建脚本修改或测试源码修改之前，必须先按顺序阅读并核对下列文档：

0. `/Users/vita/Vitemis/AGENTS.md`
1. `docs/CURRENT_STATE.md`
2. `docs/PROJECT_MAP.md`
3. `docs/ARCHITECTURE.md`
4. `docs/DO_NOT_BREAK.md`
5. `docs/TESTING.md`
6. `docs/NEXT_TARGET.md`（如果存在）

额外必读（涉及视觉模式时）：
- `docs/QWEN_VISUAL_MODE.md`（Qwen Visual Evidence Mode 契约，修改 visual_validation/qwen_vision/visual_evidence 前）

参考文档（非核心运行逻辑）：
- `docs/DS_GUIDE_Swift_Kotlin.md`（SwiftUI→Kotlin/Compose 迁移策略参考）

如果文档与源码、工程配置、测试或脚本冲突，必须以当前源码和配置为准，并在最终报告中明确指出冲突位置和采用源码为准的原因。

> 已知冲突：`RELEASE_NOTES.md`冻结在v5.0、legacy Python renderer/fixtures为`forgis.run_report.v6.0`；当前Swift/Intatis内核写`forgis.run_report.v7.0`。以当前production源码为准。

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

本仓库是以Intatis公开`IntatisCodexRuntime` v1为唯一production Agent内核的本地代码迁移助手，外加v7.3 `ForgisMac` SwiftUI壳。`forgis-runtime` Swift executable直接拥有Codex App Server session/turn/events/approval生命周期；Python `agent/`只保留配置、migration plan、guardrail、validation、report/PR控制面。`agent.cli run`以`os.execve`替换进程进入Swift内核，旧`tool_loop`在无显式测试client注入时不可用，不得成为fallback。ForgisMac最低平台为macOS 26，并在build product中按Intatis官方布局嵌入validated exact runtime root；Intatis源码仓库全程只读。

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

- 入口：`.github/workflows/migrate.yml`（xcode-27，固定Intatis commit并直接运行`forgis-runtime`）、`agent/cli.py`（配置/control-plane；`run`只做execve handoff）、`Apps/ForgisRuntimeCLI/Sources/ForgisRuntimeCLI.swift`（唯一Agent kernel CLI）、`Apps/ForgisMac/Sources/ForgisMacApp.swift`（v7.3 Mac `@main`）。
- Intatis内核边界：`Package.swift`的`ForgisRuntimeCLI`直接链接`IntatisCore` / `IntatisProtocol` / `IntatisProviders` / `IntatisCodexRuntime`；它构造`ResponsesRuntimeRoute`、`CodexRuntimeConfiguration`和`CodexAppServerSession`。不得修改/复制Intatis源码，不得重写App Server协议，不得添加Python/Chat/MCP/另一provider fallback。
- 配置解析：`agent/forgis_config.py`（`ResolvedConfig`/`VisualValidationConfig`/`StagedTranslationConfig`，支持字段、默认值、路径校验、真实运行 gate）。
- production Agent链：config/control-plane → `forgis-runtime` → `CodexAppServerSession` → exact `codex app-server --stdio`；`target_subdir`是唯一workspace-write根，source与target其余部分在写沙箱外。旧`agent/tool_loop.py`、`deepseek_agent.py`、`file_tools.py`只保留legacy测试与历史解码，不得从production入口调用。
- Mac产品界面直接持有`CodexAppServerSession`并投影原生message/tool/approval/usage事件；旧独立Chat Completions UI/client/smoke与`MockForgisData`已删除。UI不得添加另一provider、HTTP client或runtime fallback。
- 安全校验：`agent/guardrails.py`（snapshot-readonly/check-readonly/check-secret-leaks）、`agent/validate_target_output.py`、`agent/model_env.py`（env 名映射，不存真实 secret）。
- 真实运行 gate：`dry_run=false` + `run_agent=true` + `confirm_real_run=true` 三者同时满足。
- v6.0视觉模式源码/fixtures仍保留legacy回归；production Codex v1尚无Forgis Qwen official dynamic-tool接线，因此显式required视觉任务fail closed，不得调用旧Python视觉工具。
- 迁移单元与计划：`agent/migration_units.py`（`MigrationUnit`/`MigrationPlan`）、`agent/migration_state.py`、`agent/plan_audit.py`、`agent/staged_translation.py`、`agent/source_inventory.py`（`SourceUnit`）。
- 报告 schema：CLI新内核写`forgis.run_report.v7.0`与`forgis.codex_runtime_result.v1`；Mac UI也写同一v7 report，并将UI projection与报告保存在Forgis派生的owner-only Application Support runtime root。migration plan仍写`forgis.migration_plan.v5.0`并兼容旧读版本。
- 测试基准：172 tests，含`tests/test_codex_runtime_cutover.py`的exact version/derivation/offline session smoke；所有runtime smoke必须`network_requests=0`，不得调用真实provider。

## 文档索引

- `docs/PROJECT_MAP.md`：目录地图、关键文件、入口、配置、测试、资源和生成物说明。
- `docs/ARCHITECTURE.md`：总体架构、模块边界、数据流、状态流、安全机制和风险。
- `docs/CURRENT_STATE.md`：当前Swift/Intatis内核、legacy兼容面、未完成项、风险和工作区状态。
- `docs/TESTING.md`：环境、依赖、构建、测试、lint/format、手动验证矩阵。
- `docs/DO_NOT_BREAK.md`：不可破坏的格式、路径、协议、安全边界和回归要求。
- `docs/NEXT_TARGET.md`：临时下一目标记录；目标完成或不再有效后删除。
- `docs/QWEN_VISUAL_MODE.md`：Qwen Visual Evidence Mode 契约（reference-guided workflow、provider 边界、reference-first 规则、证据状态、报告字段、runtime gate、真实 transport 启用条件）。
- `docs/DS_GUIDE_Swift_Kotlin.md`：SwiftUI 到 Kotlin/Compose 迁移风险与策略参考，不是 Forgis 核心运行逻辑。

## 完成标准

完成任何任务前应：

- 说明本轮实际阅读/检查过哪些源码、配置或测试。
- 只修改任务范围内文件。
- 保留用户已有改动。
- 运行与改动风险匹配的检查。最少应考虑 `git diff --check`；代码改动通常还应运行 `python3 -m unittest tests/test_forgis_config.py` 或更窄测试。
- 检查 `git status --short`，明确哪些文件是本轮改动。
- 将本轮已完成的持久性改动及时回写到相关项目文档；若无需更新文档，最终报告说明原因。
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
