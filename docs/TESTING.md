# 构建与测试说明

最近自查日期：2026-06-23

## 环境要求

- Python 3.11：GitHub Actions workflow 使用 `actions/setup-python@v5` 且 `python-version: "3.11"`。
- Python 依赖：`requirements.txt` 当前只有 `PyYAML>=6.0.2`。
- Shell：`agent/build_target.sh` 和 `agent/create_pr.sh` 使用 bash。
- Git/GitHub CLI：真实 PR 创建路径依赖 `git` 和 `gh`，在 `agent/create_pr.sh` 中使用。
- GitHub Actions secrets：真实运行依赖 `FORGIS_TARGET_TOKEN`、`FORGIS_SOURCE_TOKEN` 和模型 secret 环境变量。不要在文档或配置中写入真实值。
- v7.0 模型 client 测试只使用 mock HTTP，不真实调用任何 API。OpenAI-compatible API key 只能通过 `model_env` 指向环境变量名；异常、日志、报告和 fixture 不得包含真实 secret 值、Authorization header、raw provider response 或完整模型输出。
- v6.0 视觉闭环测试不需要真实 Qwen API key。`visual_validation` 配置不得包含真实 token、API key、截图文件路径、evidence root 或本地敏感路径；`reference_screenshot_dirs` / `actual_screenshot_dirs` 只能是目标仓库相对目录。`agent/qwen_vision.py` 的 provider transport 在测试中必须 mock。真实 Qwen 调用只允许在运行时显式提供 `QWEN_API_KEY`，可选 `QWEN_API_BASE` 和 `QWEN_VISION_MODEL`，这些值不得写入报告。

## 依赖安装方式

GitHub Actions 中的安装方式：

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

本地开发可使用同样命令。是否使用虚拟环境由开发者决定，`.venv/` 和 `venv/` 已被 `.gitignore` 忽略。

仓库外临时 venv 示例：

```bash
python3 -m venv /tmp/forgis-v7-local-venv
/tmp/forgis-v7-local-venv/bin/python -m pip install -r requirements.txt
```

## 构建命令

仓库没有传统 package build。当前验证工作流中的语法构建检查为：

```bash
python -m py_compile agent/forge.py agent/forgis_config.py agent/resolve_config.py agent/guardrails.py agent/write_run_log.py agent/model_env.py agent/deepseek_agent.py agent/openai_compatible_client.py agent/cli.py agent/file_tools.py agent/tool_loop.py
```

发布检查清单中还建议：

```bash
python3 -m py_compile agent/*.py
bash -n agent/create_pr.sh
bash -n agent/build_target.sh
```

v6.0 Phase 3-4 新增 Python 模块后，应至少运行：

```bash
python3 -m py_compile agent/*.py
```

## 单元测试命令

当前 CI 运行：

```bash
python -m unittest tests/test_forgis_config.py tests/test_openai_compatible_client.py tests/test_v7_cli_config.py tests/test_v7_local_cli.py tests/test_v7_local_smoke.py
```

`RELEASE_NOTES.md` 的 release checklist 写的是：

```bash
python3 -m unittest
```

两者都来自项目文件。若需要最接近 CI，请优先运行 `python -m unittest tests/test_forgis_config.py tests/test_openai_compatible_client.py tests/test_v7_cli_config.py tests/test_v7_local_cli.py tests/test_v7_local_smoke.py`。

v7.0 第一阶段的新增测试点：

- `tests/test_openai_compatible_client.py` 覆盖 Chat Completions request schema、base URL 拼接、model/tools/tool_choice、timeout、HTTP error 脱敏、invalid JSON、missing choices、malformed message/tool_calls、API key 不出现在异常或 repr、DeepSeek shim 兼容。
- `tests/test_v7_cli_config.py` 覆盖 `agent_backend: deepseek` 兼容、`agent_backend: openai-compatible` alias、`base_url` alias、`request_timeout_seconds`、env var 缺失错误只显示 env 名、CLI help/dry-run、command allowlist 未放宽、`validation_commands` 没被改成 shell bypass。
- `tests/test_v7_local_cli.py` 覆盖 `python -m agent.cli help`、`doctor`、`run --config`、summary output、外部 config 解析、缺少 API key 错误脱敏、examples config 解析、DeepSeek shim 兼容。
- `tests/test_v7_local_smoke.py` 覆盖 `python -m agent.cli smoke --workdir ...` 的本地 dry-run 闭环，不需要 API key、不调用 API、不写 target。
- 所有 v7 API 测试必须 mock HTTP，不真实访问 provider。

v6.0 视觉闭环的配置解析和视觉基础设施测试点集中在 `tests/test_forgis_config.py`：

- 不写 `visual_validation` 时使用兼容默认值。
- `enabled` 仅允许 `auto`、`true`、`false`。
- `provider` 本轮仅允许 `qwen`。
- `mode` 默认 `reference_guidance`，仅允许 `reference_guidance` 或 `compare`。
- `reference_screenshot_dirs` / `actual_screenshot_dirs` 必须是目标仓库相对目录列表，拒绝绝对路径、`..`、`.git` 和 secret-like path。
- `max_visual_iterations` 仅允许整数 `0..2`。
- `require_reference_first`、`require_actual_for_full_validation` 和 `upload_visual_artifact` 必须是 YAML boolean。
- `visual_validation` 内未知字段必须失败，避免 API key、secret 或本地路径混入配置。
- `FORGIS_VISUAL_*` env/output 只包含脱敏控制值。
- `agent/visual_evidence.py` 创建 `reference/actual/qwen` 目录，拒绝 source/target/home/secret-like runtime root，校验图片扩展名，计算 `REFERENCE_AND_ACTUAL` / `REFERENCE_ONLY` / `ACTUAL_ONLY` / `NO` 状态。
- `agent/qwen_vision.py` 缺少 API key 时返回 blocker；inspect/compare 成功路径用 mock；provider failure 和 invalid response 不泄露 API key、图片 bytes 或 base64；单元测试不真实访问网络。
- `list_visual_references`、`inspect_visual_reference`、`inspect_visual_actual`、`compare_visual_screenshots` 存在于 `agent/deepseek_agent.py` schema，说明明确只处理图片/视觉，不叫 `run_qwen`。
- `FileToolSandbox` 分发 `list_visual_references`、`inspect_visual_reference`、`inspect_visual_actual`、`compare_visual_screenshots`，接受合法图片，拒绝绝对路径、`..`、非图片、secret-like 文件名和源码/文本文件；配置的 reference screenshot dirs 可读不可写。
- `visual_validation.enabled=false` 时视觉工具返回 disabled blocker；缺少 provider/API key 时返回 blocker，不崩溃。
- run report JSON 始终包含 `visual_validation` 块；reference-guided migration、`guidance_completed`、`full_rendered_validation=false`、reference-only、reference+actual+compare、provider blocker、no reference screenshots blocker、gate incomplete、auto 关键词判定和 controller-level smoke 都有测试。
- PR body 包含短 Visual Validation 摘要，并保持脱敏、有界，不包含 provider raw response、secret、headers、base64 或图片 bytes。

## 集成测试命令

当前没有独立集成测试目录。`.github/workflows/validate-forgis.yml` 包含一个 controller smoke test，会临时创建 `tmp/source`、`tmp/target`、写入最小 `FORGIS_CONFIG.yml` 和 `FORGIS_TASK.md`，再运行：

```bash
python agent/forge.py \
  --source "$GITHUB_WORKSPACE/tmp/source" \
  --target "$GITHUB_WORKSPACE/tmp/target" \
  --target-repo "owner/target-repo" \
  --summary-output "$GITHUB_WORKSPACE/tmp/run_summary.md"
```

本地 CLI dry-run smoke 可使用：

```bash
python -m agent.cli doctor
python -m agent.cli smoke --workdir /tmp/forgis-smoke

python -m agent.cli run \
  --source "$PWD/tmp/source" \
  --target "$PWD/tmp/target" \
  --target-repo "owner/target-repo" \
  --config examples/FORGIS_CONFIG.local.smoke.yml \
  --summary-output /tmp/forgis-summary.md \
  --dry-run
```

该命令仍受 `FORGIS_CONFIG.yml` 的 dry-run/real-run gate 约束，不应写 source，不应绕过 `target_subdir`。

真实 OpenAI-compatible 本地运行只应由用户手动设置 env 后执行，测试不得运行：

```bash
export FORGIS_MODEL_API_KEY="..."
python -m agent.cli run \
  --source /path/to/source \
  --target /path/to/target \
  --target-repo local/my-migration \
  --config examples/FORGIS_CONFIG.local.openai-compatible.yml \
  --summary-output /tmp/forgis-summary.md
```

本轮未运行该 smoke test。

## UI 测试命令

不适用。当前项目没有前端 UI 或客户端 UI。v6.0 只允许模型使用目标仓库中用户提供的 reference/actual screenshot 目录进行受控视觉工具调用；测试默认不调用真实 Qwen，运行时只有显式 `QWEN_API_KEY` 才能调用 provider。仍不自动截图、不上传 artifacts。

## 静态检查 / lint / format

当前未发现 ruff、black、mypy、prettier、eslint 或类似配置。已确认的静态/格式检查只有：

```bash
git diff --check
bash -n agent/build_target.sh
bash -n agent/create_pr.sh
```

`git diff --check` 是本轮要求的验证命令之一。

## 手动验证矩阵

- 配置解析：最小 `FORGIS_CONFIG.yml`、未知字段、缺失 task、非法路径、真实运行 gate。
- Visual validation config：默认值、`mode` 枚举、reference/actual screenshot dirs 路径校验、合法枚举、非法 provider、iteration 越界、严格 boolean、未知字段失败、env/output 不含 Qwen secret。
- Visual evidence：runtime 目录结构、target repo slug、安全路径拒绝、图片扩展名 allow/deny、状态分类、summary 脱敏序列化。
- Qwen adapter：missing key、mock inspect、mock compare、mock failure、invalid response、安全 blocker、非法路径拒绝、单元测试无真实网络。
- Visual tools/report/gate：schema、`list_visual_references`、sandbox dispatch、reference dirs 可读不可写、disabled/provider blocker、reference-only guidance limitation、reference+actual compare completed、auto 模式 required 判定、`NO_REFERENCE_SCREENSHOTS_FOUND`、`VISUAL_REPORT_INCOMPLETE`、run report / PR body 脱敏摘要。
- Dry run：`dry_run=true` 时不调用模型、不写目标仓库、不 push/PR。
- OpenAI-compatible model config：`agent_backend` alias、`api_base` / `base_url`、`model`、`request_timeout_seconds`、`model_env`、错误脱敏和 DeepSeek shim。
- Tool sandbox：读 source/target、写 `target_subdir`、拒绝 source 写入、拒绝 target root 写入、拒绝 symlink 和 secret-like 路径。
- Build/test feedback：未配置时 skipped，安全命令成功/失败/超时/拒绝时返回结构化摘要。
- Repair loop：失败后要求 diff/build/test gate，超过 attempts 时停止。
- Staged translation：overview/per_file/stabilization gate，feed/write/compare/revise 微阶段，过早 final summary 拒绝。
- Migration plan：计划生成、持久化、resume、人工 switch、人工 status update、audit summary。
- Reports：Markdown/JSON 截断、脱敏、schema 版本、fixture active/blocked/deferred/completed。
- GitHub workflow：read-only snapshots、target scope、dry-run clean、secret leak、fallback branch、PR body 过长重试。

## 常见失败原因

- 目标仓库没有 `FORGIS_CONFIG.yml` 或文件为空。
- `FORGIS_CONFIG.yml` 含未知字段，例如历史文档提到但当前不支持的字段。
- `visual_validation` 内包含未知字段、API key、token、截图文件路径、evidence root、非法 screenshot dir 或非 boolean 的 `require_reference_first` / `require_actual_for_full_validation` / `upload_visual_artifact`。
- `target_repo` 被写入配置，而不是通过 workflow input 或 CLI 参数传入。
- `target_subdir`、`run_log_path`、task 路径使用绝对路径、`..`、`.git` 或逃逸目标仓库根。
- `dry_run=false` 但 `confirm_real_run` 不是 true。
- 真实运行时 `model_env` 映射缺失或对应 secret 环境变量不存在。
- build/test command 使用 shell 字符串、glob、危险命令或未在 allowlist 中的命令。
- Agent 只写 run log 或 cache，没有产生 meaningful target output。
- Guardrail 检测到 source 仓库被修改、config/task 被改、target_subdir 外有变更，或 secret 值写入输出。

## 本轮是否实际运行命令

上一轮 v6.0 reference guidance 调整曾运行：

- `python3 -m unittest tests/test_forgis_config.py`：134 个测试通过。
- `python3 -m unittest`：134 个测试通过。
- `python3 -m py_compile agent/*.py`：通过。
- `git diff --check`：通过。
- `git status --short`：列出本轮修改文件，结果以最终报告为准。

本轮未修改 shell 脚本，因此未运行 `bash -n agent/build_target.sh` / `bash -n agent/create_pr.sh`。
