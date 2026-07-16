# AGENTS.md

本文是 docs 级 Codex 入口 shim。项目事实和项目专属要求应写在项目自己的根入口或项目内文档中。

开始工作前必须先读：

1. `/Users/vita/Vitemis/AGENTS.md`
2. `../AGENTS.md`（如果存在）

基本规则：

- Codex 是主工作者，只能按用户任务和项目边界修改文件。
- 已完成的持久性改动必须及时回写到相关项目文档；若无需更新文档，最终报告说明原因。
- 使用 `docs/NEXT_TARGET.md` 记录下一目标；目标完成或不再有效后删除该文件。
- Git 版本控制默认只读；编辑、整理、修复、验证或准备工作都不等于提交请求。只有用户当前任务明文要求具体 Git 操作时，Codex 才可按要求执行对应的非破坏性 Git 操作。若用户要求提交，只提交当前 Git root 中与本任务相关的文件；不得递归进入、暂存、提交或推送子仓库、submodule、nested Git repo 或依赖 checkout。
- 不得读取、打印、摘要或写入密钥、token、证书、Keychain、`.env` 等敏感信息。
- 若与项目根入口冲突，采用更严格的规则。

报告要求：

- Codex 报告只能写入 `../codex-report/`。
- 报告文件名必须采用 `MM_DD_YY-HH_MM-xxxx.md`，例如 `06_30_26-21_45-permission-audit.md`。
- 报告正文必须先写 `MODEL_CHECK_RESULT`。除非项目根入口另有硬性模型门禁，模型字段只用于记录，不因模型版本号不匹配而停止。
- 报告建议包含：`MODEL_CHECK_RESULT`、`PATH_CHECK_RESULT`、`FILES_WRITTEN`、`SUMMARY`、`VALIDATION_RESULT`、`UNCERTAINTIES`、`NEXT_RECOMMENDED_ACTION`。
