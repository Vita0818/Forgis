# 工程禁区

最近自查日期：2026-06-23

## 不得破坏的用户数据格式

- 目标仓库 `FORGIS_CONFIG.yml` 字段集合和默认值由 `agent/forgis_config.py` 管理。新增、改名或删除字段必须同步 README、测试和 workflow。
- `ResolvedConfig.env()` 输出的环境变量名被 `.github/workflows/migrate.yml`、shell 脚本和报告链路使用，不得随意改名。
- `visual_validation` 只允许 `enabled`、`provider`、`mode`、`reference_screenshot_dirs`、`actual_screenshot_dirs`、`max_visual_iterations`、`require_reference_first`、`require_actual_for_full_validation`、`upload_visual_artifact`。不得新增 secret、API key、API base、model name、截图文件路径或 evidence root 字段，除非先完成后续阶段设计和测试。
- `FORGIS_VISUAL_VALIDATION_ENABLED`、`FORGIS_VISUAL_VALIDATION_PROVIDER`、`FORGIS_VISUAL_VALIDATION_MODE`、`FORGIS_VISUAL_REFERENCE_SCREENSHOT_DIRS_JSON`、`FORGIS_VISUAL_ACTUAL_SCREENSHOT_DIRS_JSON`、`FORGIS_VISUAL_MAX_ITERATIONS`、`FORGIS_VISUAL_REQUIRE_REFERENCE_FIRST`、`FORGIS_VISUAL_REQUIRE_ACTUAL_FOR_FULL_VALIDATION`、`FORGIS_VISUAL_UPLOAD_ARTIFACT` 是 v6.0 稳定脱敏 env/output 表面，不得写入 secret 值。
- `FORGIS_RUN_REPORT.json` schema 当前为 `forgis.run_report.v6.0`，必须始终包含 `visual_validation` 块。
- `FORGIS_MIGRATION_PLAN.json` schema 当前写出为 `forgis.migration_plan.v5.0`，读取兼容 `v4.8`、`v3.9`、`v3.8`、`v3.7`。
- `ToolLoopResult.as_dict()`、`write_status()` 输出字段、report fixture 字段被测试覆盖，新增字段要保证脱敏和有界。
- PR body 必须保持有界，标准 body 当前限制 30000 字符，short body 当前限制 3000 字符。

## 不得破坏的文件路径约定

- 目标配置默认是目标仓库根目录 `FORGIS_CONFIG.yml`。本地 CLI `--config` 可以显式指定外部配置文件，但该路径必须是只读运行输入，不能位于 source repo 内，不能包含 secret-like 路径段，不能成为写工具目标。
- 目标任务文件默认 `FORGIS_TASK.md`，可配置但必须在目标仓库根内。
- `target_subdir` 默认 `target-output`，必须是目标仓库内非根相对路径。
- `run_log_path` 默认 `{target_subdir}/FORGIS_LOG.md`，必须位于 `target_subdir` 内。
- 模型工具虚拟路径约定：`task`、`config`、`source/`、`target/`、`target_subdir/`。
- 写工具只能修改 `target_subdir` 内文件，且不能修改 source、target root、config/task、`.github/workflows`。
- report 和 migration plan 输出目录必须在 Forgis runtime root 下，不能位于 source/target checkout、Desktop、Downloads、Documents 或 secret-like 路径。
- 视觉证据目录必须位于 Forgis runtime workspace 下；不得写入 source repo、target repo 或业务源码目录，不得覆盖旧截图。当前目录结构由 `agent/visual_evidence.py` 规划为 `visual-evidence/<run_id>/<target_repo_slug>/reference|actual|qwen`。
- `visual_validation.reference_screenshot_dirs` / `actual_screenshot_dirs` 是目标仓库只读截图输入目录。它们可以位于 target root 或 `target_subdir` 内，但 write/edit/delete/apply_patch/mkdir 不得修改这些目录或其内容。

## 不得破坏的 API / 路由 / 协议 / 存储结构

- 模型 client 使用非 streaming OpenAI-compatible chat completions，payload 包含 `model`、`messages`、可选 `tools`、可选 `tool_choice`。`agent_backend: deepseek` 必须继续兼容，`agent_backend: openai-compatible` 只作为通用 alias，不得引入 provider 私有协议。
- `api_base` 和 `base_url` 是同一 endpoint 配置的 alias；不得在同一配置中设置两个不同值。Chat Completions URL 拼接不得重复 `/v1` 或 `/chat/completions`，也不得泄露 API key。
- Tool schema 名称和参数由 `agent/deepseek_agent.py` 定义，`agent/file_tools.py` 按同名 `invoke()`。改动任一边必须同步另一边和测试。
- `model_env` 是 runtime env name 到 secret env name 的映射，只允许环境变量名，不允许真实 secret 值。
- `python -m agent.cli doctor` 和 `python -m agent.cli smoke` 不得真实调用模型 API。`smoke` 只允许在用户指定或系统临时 workdir 下创建 dry-run fixture。
- `request_timeout_seconds` 是模型请求超时控制值，必须有安全默认值和上限；不得用配置绕过 dry-run/real-run gate。
- `success_checks` 支持 `path_exists` 或 `command`，每个 mapping 只能包含其中一个。
- `build_command` 和 `test_command` 是非空 YAML 参数数组，不是 shell 字符串。
- `validation_commands` 是字符串列表，由 `agent/build_target.sh` 在 `target_subdir` 下执行。不要和 build/test command array 混淆。
- Qwen Visual Evidence Mode v6.0 已接入 reference-guided migration、受控 tool schema、sandbox dispatch、Qwen provider transport、run report / PR body 视觉摘要和 runtime gate。Qwen 是视觉理解 provider，不是代码 Agent；不得让 Qwen 读取源码、修改文件、运行命令或替代构建/测试。
- `agent/qwen_vision.py` 只有在显式提供 `QWEN_API_KEY` 时才允许真实 HTTP 调用；单元测试必须通过 mock 替换 `_post_qwen_vision_payload` 或 HTTP 层。不得把 API key、headers、base64 原图、完整 response dump 或图片 bytes 写进异常、报告或 result。
- 视觉工具只接受 Forgis 虚拟图片路径，并由 `agent/visual_evidence.py` 校验图片扩展名和 secret-like/source-like 路径。不得改成任意绝对路径或任意文件上传。
- `agent/run_report.py` 和 `agent/pr_body.py` 只能写有界、脱敏的视觉摘要；不得写 provider raw response、headers、API key、图片 bytes/base64 或完整路径。

## 不得绕过的安全机制

- 真实运行必须同时满足 `dry_run=false`、`run_agent=true`、`confirm_real_run=true`。
- source 仓库必须保持只读。
- target repo outside `target_subdir` 必须保持只读，除非由 workflow 明确处理 PR/log 等允许范围。
- config 和 task 文件必须通过 snapshot/hash 验证保持只读。
- dry run 不得写 target。
- secret leak check 必须扫描 `model_env` 对应 secret 值是否写入 `target_subdir`。
- 命令执行不得开启任意 shell 权限。`run_command` 和 build/test feedback 必须经过 `command_runner.py`。
- 本地 CLI 不得新增 shell runner，也不得让 `--config` 或 `smoke` 绕过 `command_runner.py`、dry-run gate、source readonly 或 `target_subdir` 写入边界。
- 报告、日志、PR body、migration plan 必须脱敏、截断、禁止完整 diff/source/model output 泄露。
- OpenAI-compatible HTTP error、invalid JSON、missing choices、malformed message/tool_calls 等错误必须脱敏，不能打印 API key、Authorization header、cookie、raw provider response 或完整模型输出。
- 不得向 Qwen 或任何视觉 provider 发送源码、secret、token、`.env`、证书、私钥、provisioning profile、完整仓库快照或私有本地配置。
- 不得把 reference-only 视觉指导当作完整真实渲染验收；报告和 PR body 必须区分 `guidance_completed` 与 `full_rendered_validation`。
- 找不到配置的 reference screenshots 时必须写 `NO_REFERENCE_SCREENSHOTS_FOUND` 或等价 blocker，不得声称视觉指导完成。
- 用户人工视觉反馈优先于 Qwen 相似判断。用户指出 UI 不像、颜色/布局/质感不对时，必须按缺陷处理。

## 不得随意重构的核心模块

- `agent/forgis_config.py`：配置字段、默认值、路径安全、运行 gate。
- `agent/openai_compatible_client.py`：v7.0 模型 HTTP transport，必须保持非 streaming、可 mock、脱敏、有界，不得引入 provider-specific hacks 或真实网络单测。
- `docs/QWEN_VISUAL_MODE.md` 与 `skills/qwen_visual_mode.md`：v6.0 视觉模式安全契约。
- `agent/visual_evidence.py`：视觉证据目录、状态、阻塞原因、图片路径校验和摘要模型。
- `agent/qwen_vision.py`：Qwen provider adapter，必须保持可 mock、脱敏、有界；缺少显式 `QWEN_API_KEY` 时必须安全返回 blocker，不得真实联网。
- `agent/file_tools.py`：虚拟路径和写入边界。
- `agent/command_runner.py`：命令 allowlist。
- `agent/tool_loop.py`：默认模型循环、状态、report 和 migration plan 串联。
- `agent/staged_translation.py`：分阶段 gate 和 staged artifacts 规则。
- `agent/guardrails.py` 与 `agent/validate_target_output.py`：CI 安全和输出验证。
- `agent/run_report.py` 与 `agent/migration_plan_store.py`：v5.0 schema 和脱敏/截断边界。
- `.github/workflows/migrate.yml`：真实运行 gate、guardrails、artifact 和 PR 创建顺序。
- `agent/create_pr.sh`：fallback branch 和无 force push 语义。

## 不得删除或覆盖的资源

- `prompts/system_agent_v3.md`：当前系统提示词来源。
- `skills/*.md`：本地技能库，必须保持安全 slug 和短文档形态。
- `tests/fixtures/reports/*.json`：报告行为 fixture。
- `docs/DS_GUIDE_Swift_Kotlin.md`：迁移策略参考文档。
- `docs/QWEN_VISUAL_MODE.md`、`skills/qwen_visual_mode.md`：视觉 provider 边界和 reference-first 规则。
- README、README.zh-CN、RELEASE_NOTES：用户和 release 说明来源。

## 不得引入的架构倒退

- 不要把 target-stack、业务项目规则或特定平台迁移策略硬编码进 Forgis 核心。
- 不要让模型读写任意本地路径。
- 不要让模型修改 source repo、target root、workflow、config 或 task。
- 不要把 secret 值写入 env output、logs、reports、PR body 或 fixture。
- 不要把 Qwen 扩展成能读源码、改文件、运行命令的 Agent。
- 不要绕过已接入的 visual runtime gate；`REFERENCE_ONLY` 可作为 reference-guided migration，但不得被写成完整真实渲染验收；`ACTUAL_ONLY`、`NO` 或 provider blocker 都不得被写成完整视觉验收。
- 不要把已实现的 Qwen HTTP transport 扩展成自动截图、artifact 上传、多 provider 或任意文件上传；这些必须先有 Phase 8+ 设计和额外回归测试。
- 不要让 `agent/qwen_vision.py` 支持任意文件上传；只接受经过 `agent/visual_evidence.py` 校验的图片路径和简短 goal。
- 不要上传 legacy runtime diagnostics artifact、完整 diff、业务源码或未脱敏模型输出。
- 不要 force push 到目标分支。
- 不要把本地 skills 扩展成外部下载或业务仓库读取，除非先设计安全边界和测试。

## 修改前必须阅读的关键源码位置

- 配置或 README 示例：`agent/forgis_config.py`、`README.md`、`README.zh-CN.md`、`tests/test_forgis_config.py`。
- 视觉模式：`docs/QWEN_VISUAL_MODE.md`、`skills/qwen_visual_mode.md`、`agent/forgis_config.py`、`agent/visual_evidence.py`、`agent/qwen_vision.py`、`tests/test_forgis_config.py`。
- Tool schema 或文件权限：`agent/deepseek_agent.py`、`agent/file_tools.py`、`tests/test_forgis_config.py`。
- 命令执行：`agent/command_runner.py`、`agent/build_runner.py`、`agent/build_target.sh`。
- Guardrails：`agent/guardrails.py`、`agent/validate_target_output.py`、`.github/workflows/migrate.yml`。
- 模型调用：`agent/openai_compatible_client.py`、`agent/deepseek_agent.py`、`agent/model_env.py`、`agent/tool_loop.py`.
- Staged translation：`agent/staged_translation.py`、`agent/source_inventory.py`。
- Migration plan：`agent/migration_units.py`、`agent/migration_scheduler.py`、`agent/migration_state.py`、`agent/migration_plan_store.py`、`agent/plan_audit.py`。
- Reports：`agent/run_report.py`、`agent/repair_report.py`、`tests/fixtures/reports/*.json`。
- PR flow：`agent/create_pr.sh`、`agent/pr_body.py`。

## 回归验证要求

- 文档-only 修改：至少运行 `git diff --check`，并检查 `git status --short`。
- Python 逻辑修改：运行相关窄测试，通常至少 `python3 -m unittest tests/test_forgis_config.py`；v7.0 模型/CLI 修改还应运行 `python3 -m unittest tests/test_openai_compatible_client.py tests/test_v7_cli_config.py`；发布前运行 `python3 -m py_compile agent/*.py`。
- `visual_validation` 配置修改：必须覆盖默认值、`enabled` 枚举、`provider=qwen`、`mode` 枚举、reference/actual screenshot dirs 路径校验、iteration 范围、严格 boolean、未知字段失败、env/output 不含 Qwen secret 值。
- 视觉证据修改：必须覆盖 runtime 目录结构、source/target/home/secret-like 路径拒绝、图片扩展名 allow/deny、状态分类、摘要脱敏序列化。
- Qwen adapter 修改：必须覆盖缺少 API key、mock inspect、mock compare、mock failure、异常脱敏、非法图片路径拒绝、invalid response 安全失败，以及单元测试不真实联网。
- 视觉工具 / report / gate 修改：必须覆盖 tool schema 存在、`list_visual_references` 配置目录发现、reference dirs 可读不可写、虚拟路径拒绝绝对路径和 `..`、非图片/secret-like/source 文件拒绝、`enabled=false` disabled blocker、provider blocker、reference-only guidance、reference+actual compare completed、`guidance_completed` / `full_rendered_validation` 区分、report JSON `visual_validation` 常驻块和 PR body 脱敏摘要。
- Shell 脚本修改：运行 `bash -n agent/build_target.sh` 和/或 `bash -n agent/create_pr.sh`。
- Workflow 修改：阅读并更新 `tests/test_forgis_config.py` 中 workflow 断言，必要时运行完整 unittest。
- Report/schema 修改：更新 fixture 和 schema 相关断言，确认脱敏、截断和 artifact 范围。
- 安全边界修改：增加负向测试，覆盖路径逃逸、secret-like 路径、symlink、dry-run、target scope 和 source clean。
