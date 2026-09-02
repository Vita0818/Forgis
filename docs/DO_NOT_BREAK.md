# DO_NOT_BREAK

## 外部依赖优先与禁止功能兜底（Vitemis 强制规则）

本项目继承 `/Users/vita/Vitemis/docs/DEPENDENCY_POLICY.md`。本节是强制约束，不是建议。

- 当用户指定、仓库已经采用，或经许可证、provenance、安全与平台审查可采用的外部依赖提供同等能力时，必须直接集成该依赖的官方 API 或官方扩展点。
- 不得自行重写同等能力，不得新增替代 adapter、shim、compatibility layer、wrapper、proxy、facade、协议翻译层、parallel backend、preview backend、shadow implementation 或“先兜底、以后再换”的实现。
- 本地代码只允许保留官方 API 必需的最薄生命周期、类型、权限、配置和 bundle 接线；不得重新实现、解释、扩展或替代依赖的核心能力。
- exact 依赖因版本、构建、签名、许可证、平台、安全或官方 API 限制无法接入时，必须停止该能力、明确失败、报告 blocker 并请求用户决定；不得静默降级、切换 legacy/另一 provider/backend、使用 cache/mock/简化路径或继续交付不完整替代实现。
- 现有 fallback、adapter 或重复实现不构成先例，后续不得扩展。安全 fail-closed 与明确要求的旧数据解码/迁移不是功能兜底，但必须保持最窄范围，不能演化成备用产品实现。
- 只有用户针对 exact 依赖、exact 范围和退出条件作出的新明文决定才能例外。

本文列出不可破坏的工程禁区、数据格式、协议、路径和回归要求。修改前必须确认不违反下列任一条目。

## IntatisCodexRuntime 唯一production内核边界

- Intatis是Forgis的只读同级上游checkout；只能通过`../Intatis`公开SwiftPM product接入，禁止修改、vendor或patch其源码。
- 唯一production Agent入口是`forgis-runtime` → `CodexAppServerSession` → exact `codex app-server`。本地Python `run`只能`execve` handoff；workflow不得调用`agent/tool_loop.py`。
- workflow固定Intatis commit与`xcode-27` runner，并只在runner临时目录运行Intatis官方runtime builder/validator。不得接受system/PATH Codex、不同version/derivation或另一backend。
- Mac App只能按`Contents/Resources/CodexRuntime/{architecture}`官方布局嵌入完整validated root；不得只复制裸binary、丢弃manifest/hash/SBOM/notices，或在shipping bundle中使用override/env/PATH。
- `target_subdir`必须是Codex唯一workspace-write根。source、target root、config和task不得进入写根；post-run guardrails继续强制复核。
- 旧Python AgentLoop/FileToolSandbox/DeepSeek transport只可由测试显式注入client，不得从production入口触达，不得成为失败fallback。
- 依赖缺失、API major不匹配、runtime缺失、版本/derivation错误、provider不支持native Responses tool shape或visual能力无official接线时必须明确停止。
- Mac UI必须直接使用`IntatisCodexRuntime` v1 session/event/approval/interrupt/usage API；不得恢复独立Chat Completions client、`URLSession`模型调用、`--forgis-chat-smoke`或mock migration数据。
- 所有runtime/turn测试默认必须离线；doctor与session smoke不得发送turn，必须报告`network_requests=0`。

## 工程禁区

- 不执行破坏性 Git 操作（`reset --hard`/`clean -fd`/`checkout .`/强推到目标分支）。
- 未经用户明文要求具体 Git 操作，不 add、不 commit、不 push、不创建 PR；编辑、整理、修复、验证或准备工作都不等于提交请求。
- 若用户要求提交，只提交当前 Git root 中与本任务相关的文件；不得递归进入、暂存、提交或推送子仓库、submodule、nested Git repo 或依赖 checkout。
- 不覆盖用户未提交文件。
- 不把真实 secret 写入源码/测试/报告/文档/PR body/fixture。
- 不绕过 target_subdir 写入边界、read-only config/task、source-repo 只读、secret 扫描、report bounding。
- 不把 Forgis 扩展成任意 shell 执行器。
- 不把平台迁移智能硬编码进 Forgis 核心。
- 不在Mac UI内实现Agent loop、App Server协议、provider transport或文件工具；UI只能把workspace/route/gate交给Intatis，并投影官方事件。依赖失败必须停止，不得切回legacy/Python/Chat/MCP/另一provider。
- 不修改Intatis源仓库；runtime payload只可由官方builder产出到临时目录，或由validated kit复制到App build product，不得写入Forgis源码树。
- 不把 Qwen 扩展成代码 Agent（不读源码/改文件/运行命令/接收 secret）。
- 不把 reference-only 视觉指导当完整真实渲染验收。
- 无显式 `QWEN_API_KEY` 不得发起 Qwen 真实 HTTP。
- 不上传 legacy diagnostics/完整 diff/源码/未脱敏 model 输出。

## 数据格式禁区

- **`FORGIS_CONFIG.yml`**：字段集 + 默认值（`agent/forgis_config.py` 管理）。
- **`ResolvedConfig.env()`**：输出 env 变量名。
- **`visual_validation`**：仅允许字段，禁 secret/key/base/model/path/evidence-root。
- **`FORGIS_VISUAL_*`**：9 个 env/output surface 名。
- **`FORGIS_RUN_REPORT.json`**：新内核写`forgis.run_report.v7.0`并保留`visual_validation` block；legacy renderer v6只供旧fixture/tests。
- **Codex runtime result**：`forgis.codex_runtime_result.v1`。
- **`FORGIS_MIGRATION_PLAN.json`**：写 `v5.0`，读 `v4.8`/`v3.9`/`v3.8`/`v3.7`。
- **PR body**：30000 chars 标准，3000 chars 短。

## 协议禁区

- production迁移内核只允许Intatis/Codex原生Responses wire；不得翻译Chat Completions、添加proxy或provider fallback。
- Mac产品界面不得出现独立Chat Completions产品面；Migration composer只能向当前Intatis session发送turn。
- `api_base`/`base_url` 别名（不可同时用）。
- legacy tests中的`deepseek_agent.py` tool schema仍须与`file_tools.py invoke()`匹配，但该surface不得重新进入production。
- `model_env` 仅 env 名。
- Mac Responses credential只能来自Forgis identity派生的macOS Keychain generic-password item或显式env fallback；UserDefaults只能保存非secret workspace/route/gate偏好。不得把credential写入argv、task、projection、operation log、report、fixture、FORGIS_CONFIG或UserDefaults。
- Mac离线smoke只允许`--forgis-codex-runtime-smoke`，且只能start/thread-start/shutdown，必须`network_requests=0`。不得重新添加HTTP/provider smoke入口。
- `success_checks` = `path_exists` XOR `command`。
- `build_command`/`test_command` = YAML 数组（非 shell 字符串）。
- `validation_commands` argv mapping 推荐；legacy 字符串经 `bash -lc`（有 warning）。

## 路径禁区

- `FORGIS_CONFIG.yml` 在目标仓根。
- `FORGIS_TASK.md` 在目标仓根。
- `target_subdir` 默认 `target-output`。
- `run_log_path` 默认 `{target_subdir}/FORGIS_LOG.md`。
- 虚拟路径：`task`/`config`/`source/`/`target/`/`target_subdir/`。
- 视觉证据：`visual-evidence/<run_id>/<target_repo_slug>/{reference,actual,qwen}`。

## 回归要求

- 文档任务：`git diff --check` + `git status --short`。
- Python 逻辑：相关窄测试（`tests/test_forgis_config.py` 等）。
- `validation_commands`/visual/Qwen/tool/report/schema/security 改动各有明确测试覆盖要求。
- Shell 脚本：`bash -n`。

## 不可降级项

- 三重真实运行 gate 不得放宽。
- 文件工具虚拟路径沙箱不得放行危险路径。
- `command_runner` allowlist 不得扩展为任意 shell。
- Qwen 不得读源码/改文件/运行命令/接收 secret。
- 报告/PR body 必须脱敏 + 截断。
- `guidance_completed` 与 `full_rendered_validation` 必须区分。

## 验证要求

- `python3 -m py_compile agent/*.py`
- `python3 -m unittest`（或窄测试）
- `bash -n agent/create_pr.sh` / `bash -n agent/build_target.sh`
- `swift build --product ForgisMac`与Xcode bundle build；Mac UI/runtime改动还必须运行bundle `--forgis-codex-runtime-smoke`
- `git diff --check`
- 文档任务未运行构建/测试时须声明。
