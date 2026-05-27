# 构建与测试说明

最近自查日期：2026-05-26

## 环境要求

- Python 3.11：GitHub Actions workflow 使用 `actions/setup-python@v5` 且 `python-version: "3.11"`。
- Python 依赖：`requirements.txt` 当前只有 `PyYAML>=6.0.2`。
- Shell：`agent/build_target.sh` 和 `agent/create_pr.sh` 使用 bash。
- Git/GitHub CLI：真实 PR 创建路径依赖 `git` 和 `gh`，在 `agent/create_pr.sh` 中使用。
- GitHub Actions secrets：真实运行依赖 `FORGIS_TARGET_TOKEN`、`FORGIS_SOURCE_TOKEN` 和模型 secret 环境变量。不要在文档或配置中写入真实值。

## 依赖安装方式

GitHub Actions 中的安装方式：

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

本地开发可使用同样命令。是否使用虚拟环境由开发者决定，`.venv/` 和 `venv/` 已被 `.gitignore` 忽略。

## 构建命令

仓库没有传统 package build。当前验证工作流中的语法构建检查为：

```bash
python -m py_compile agent/forge.py agent/forgis_config.py agent/resolve_config.py agent/guardrails.py agent/write_run_log.py agent/model_env.py agent/deepseek_agent.py agent/file_tools.py agent/tool_loop.py
```

发布检查清单中还建议：

```bash
python3 -m py_compile agent/*.py
bash -n agent/create_pr.sh
bash -n agent/build_target.sh
```

注意：本轮未运行上述构建命令。

## 单元测试命令

当前 CI 运行：

```bash
python -m unittest tests/test_forgis_config.py
```

`RELEASE_NOTES.md` 的 release checklist 写的是：

```bash
python3 -m unittest
```

两者都来自项目文件。若需要最接近 CI，请优先运行 `python -m unittest tests/test_forgis_config.py`。

## 集成测试命令

当前没有独立集成测试目录。`.github/workflows/validate-forgis.yml` 包含一个 controller smoke test，会临时创建 `tmp/source`、`tmp/target`、写入最小 `FORGIS_CONFIG.yml` 和 `FORGIS_TASK.md`，再运行：

```bash
python agent/forge.py \
  --source "$GITHUB_WORKSPACE/tmp/source" \
  --target "$GITHUB_WORKSPACE/tmp/target" \
  --target-repo "owner/target-repo" \
  --summary-output "$GITHUB_WORKSPACE/tmp/run_summary.md"
```

本轮未运行该 smoke test。

## UI 测试命令

不适用。当前项目没有前端 UI 或客户端 UI。

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
- Dry run：`dry_run=true` 时不调用 DeepSeek、不写目标仓库、不 push/PR。
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
- `target_repo` 被写入配置，而不是通过 workflow input 或 CLI 参数传入。
- `target_subdir`、`run_log_path`、task 路径使用绝对路径、`..`、`.git` 或逃逸目标仓库根。
- `dry_run=false` 但 `confirm_real_run` 不是 true。
- 真实运行时 `model_env` 映射缺失或对应 secret 环境变量不存在。
- build/test command 使用 shell 字符串、glob、危险命令或未在 allowlist 中的命令。
- Agent 只写 run log 或 cache，没有产生 meaningful target output。
- Guardrail 检测到 source 仓库被修改、config/task 被改、target_subdir 外有变更，或 secret 值写入输出。

## 本轮是否实际运行命令

本轮实际运行的是项目自查和文档验证命令，包括：

- `pwd`
- `git rev-parse --show-toplevel`
- `git status --short`
- 多个只读 `find`、`rg`、`sed`、`wc`、`git ls-files`
- 文档写入后的 `git diff --check`
- 文档写入后的 `git status --short`
- 文档写入后的 `find docs -maxdepth 1 -type f | sort`
- 文档写入后的 `sed -n '1,220p' AGENTS.md`

本轮未运行构建或测试。
