# DO_NOT_BREAK

本文列出不可破坏的工程禁区、数据格式、协议、路径和回归要求。修改前必须确认不违反下列任一条目。

## 工程禁区

- 不执行破坏性 Git 操作（`reset --hard`/`clean -fd`/`checkout .`/强推到目标分支）。
- 未经用户明文要求具体 Git 操作，不 add、不 commit、不 push、不创建 PR；编辑、整理、修复、验证或准备工作都不等于提交请求。
- 若用户要求提交，只提交当前 Git root 中与本任务相关的文件；不得递归进入、暂存、提交或推送子仓库、submodule、nested Git repo 或依赖 checkout。
- 不覆盖用户未提交文件。
- 不把真实 secret 写入源码/测试/报告/文档/PR body/fixture。
- 不绕过 target_subdir 写入边界、read-only config/task、source-repo 只读、secret 扫描、report bounding。
- 不把 Forgis 扩展成任意 shell 执行器。
- 不把平台迁移智能硬编码进 Forgis 核心。
- 不把 Mac AI Chat 扩展成带文件工具的代码 Agent；它只能做无工具、非 streaming Chat Completions，不得写 source/target/config/report。
- 不把 Qwen 扩展成代码 Agent（不读源码/改文件/运行命令/接收 secret）。
- 不把 reference-only 视觉指导当完整真实渲染验收。
- 无显式 `QWEN_API_KEY` 不得发起 Qwen 真实 HTTP。
- 不上传 legacy diagnostics/完整 diff/源码/未脱敏 model 输出。

## 数据格式禁区

- **`FORGIS_CONFIG.yml`**：字段集 + 默认值（`agent/forgis_config.py` 管理）。
- **`ResolvedConfig.env()`**：输出 env 变量名。
- **`visual_validation`**：仅允许字段，禁 secret/key/base/model/path/evidence-root。
- **`FORGIS_VISUAL_*`**：9 个 env/output surface 名。
- **`FORGIS_RUN_REPORT.json`**：schema `forgis.run_report.v6.0`（始终含 `visual_validation` block）。注：`RELEASE_NOTES.md` 旧记 v5.0，以源码 v6.0 为准。
- **`FORGIS_MIGRATION_PLAN.json`**：写 `v5.0`，读 `v4.8`/`v3.9`/`v3.8`/`v3.7`。
- **PR body**：30000 chars 标准，3000 chars 短。

## 协议禁区

- 非流式 OpenAI 兼容 Chat Completions。
- Mac AI Chat 也必须保持非流式 Chat Completions；不得引入 SSE streaming 或 Responses API。
- `api_base`/`base_url` 别名（不可同时用）。
- `deepseek_agent.py` 的 tool schema 名必须与 `file_tools.py invoke()` 匹配。
- `model_env` 仅 env 名。
- Mac AI Chat API key 只能来自 macOS Keychain generic-password item 或 runtime env fallback；UserDefaults 只能保存非 secret provider/model/API base/env 名/auth/timeout 偏好。不得把 API key 写入源码、日志、report、fixture、FORGIS_CONFIG 或 UserDefaults。
- `--forgis-chat-smoke` 只能复用 Mac AI Chat 的非 streaming client；默认应访问 localhost mock endpoint，不得接受 raw API key CLI 参数，不得读写 source/target/config/report。
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
- `git diff --check`
- 文档任务未运行构建/测试时须声明。
