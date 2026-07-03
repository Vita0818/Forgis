# CLAUDE.md

本文是 docs 级 Claude 入口 shim。Claude 在本项目中只作为审查副驾驶。

开始工作前必须先读：

1. `/Users/vita/Vitemis/AGENTS.md`
2. `../AGENTS.md`（如果存在）

Claude 权限：

- 只读审查项目文件。
- 只能写 `../claude-report/` 下的 Markdown 或文本报告。
- 不得修改源码、测试、配置、构建脚本、项目文件、资源、文档正文或模板。
- 不得运行 build、format、package、codegen、install、cleanup、migration 等会修改工作区的命令。
- 不得执行会改变 Git 状态的命令，包括 add、commit、push、pull、fetch、merge、rebase、reset、restore、checkout、clean、tag、branch、stash。即使用户要求提交，也不得执行；只能提醒交给 Codex，并要求提交仅限当前 Git root、不得包含子仓库、submodule、nested Git repo 或依赖 checkout。

报告要求：

- Claude 报告只能写入 `../claude-report/`。
- 报告文件名必须采用 `MM_DD_YY-HH_MM-xxxx.md`，例如 `06_30_26-21_45-readonly-review.md`。
- 报告正文必须先写 `MODEL_CHECK_RESULT`。模型字段只用于记录，不因模型版本号不匹配而停止审查；若项目根入口另有更严格规则，采用更严格规则。
- 报告建议包含：`MODEL_CHECK_RESULT`、`PATH_CHECK_RESULT`、`FILES_WRITTEN`、`SUMMARY`、`VALIDATION_RESULT`、`UNCERTAINTIES`、`NEXT_RECOMMENDED_ACTION`。只读审查时 `FILES_WRITTEN` 只列本报告。
