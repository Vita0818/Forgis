# 当前状态

最近自查日期：2026-05-29

## 当前工作区状态摘要

启动前检查结果：

```text
pwd: <PROJECT_ROOT>
git root: <PROJECT_ROOT>
git status --short: 本轮存在 v6.0 未提交修改，具体文件以最终报告和 `git status --short` 为准
```

v6.0 视觉闭环工作在已有未提交 Phase 1-7 改动上继续推进。本轮补齐安全真实 Qwen HTTP transport、Qwen env 映射、auto 视觉关键词判定、三工具端到端 smoke test、失败路径测试和文档同步。仍不包含自动截图、adb/hdc/Windows/macOS 截图、artifact 上传、多 provider、UI dashboard 或任意 shell 扩展。

## 当前项目已实现能力

- 目标仓库配置解析：固定读取目标仓库根目录 `FORGIS_CONFIG.yml`，未知字段失败，必填 `source_repo`、`target_branch`，`target_repo` 由 workflow/CLI 输入。
- 运行开关：真实模型执行需要 `dry_run=false`、`run_agent=true`、`confirm_real_run=true` 同时成立。
- DeepSeek 调用：`agent/deepseek_agent.py` 使用 OpenAI-compatible `/chat/completions`，模型默认 `deepseek-v4-pro`。
- 受控文件工具：支持 list/tree/read/file_exists/search/git_status/git_diff/mkdir/write/append/delete/edit/apply_patch/run_command/run_build/run_tests。
- 文件沙箱：source 只读，target outside `target_subdir` 只读，写入仅限 `target_subdir`，并拒绝 secret-like 路径、symlink 写入、workflow 文件写入。
- build/test feedback：可选 `build_command`、`test_command` 参数数组，经保守 allowlist 执行，输出会截断和脱敏。
- repair loop：可配置有限修复尝试、diff/build/test gate、事件和报告。
- staged translation：支持 overview、per_file、stabilization 阶段和 per-file 微阶段 gate。
- local skills：支持从仓库本地 `skills/*.md` 自动或显式选择并注入短指导。
- Qwen Visual Evidence Mode 闭环：v6.0 已包含 `docs/QWEN_VISUAL_MODE.md`、`skills/qwen_visual_mode.md`、`visual_validation` 配置解析、脱敏 env/output 字段、`agent/visual_evidence.py` 证据目录/状态 helper、`agent/qwen_vision.py` 可 mock provider adapter 与安全真实 HTTP transport、视觉 tool schema、sandbox dispatch、runtime visual state/gate、`FORGIS_RUN_REPORT.md/json` 视觉字段和 PR body 视觉摘要。
- migration scheduler / plan：支持 source inventory、unit 类型和优先级、计划持久化、resume、人工 active unit switch、人工 unit status update、audit summary。
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
- 跨语言 build adapter、UI 控制台。
- 上传 legacy runtime diagnostics artifacts、业务源码、完整 diff、secret、未脱敏模型输出或 target repository snapshot。
- 自动截图、adb/hdc/Windows/macOS 截图、visual artifact 上传、多 provider、UI dashboard。当前视觉闭环依赖用户提供的有效 reference/actual 图片虚拟路径；真实 Qwen transport 只有显式提供 `QWEN_API_KEY` 时才会调用，单元测试仍使用 mock，不联网。

## 当前已知 bug / 风险

- `agent/build_target.sh` 的 `validation_commands` 通过 `bash -lc` 运行字符串命令，安全边界弱于 `command_runner.py` 的数组 allowlist。当前 workflow 将 cwd 限制到 `target_subdir`，但仍需谨慎维护。
- `tests/test_forgis_config.py` 覆盖面广但文件很大，新增行为时容易漏读相关测试块。
- `agent/forgis_config.py`、`agent/tool_loop.py`、`agent/staged_translation.py` 字段和状态面较宽，新增字段需要同时更新 env/output、report、tests、README 和 fixture。
- `visual_validation` 已驱动受控视觉工具、报告字段和 runtime gate。缺少 API key 或 provider 不可用时必须写 blocker；reference-only 必须写 limitation，不能被当成完整视觉验收。真实 transport 的风险集中在 env 管理与 provider response 脱敏，测试必须保持 mock-first。
- README 和 README.zh-CN 包含多个历史版本章节，容易误读为当前新增能力。当前行为应以源码、workflow 和 `RELEASE_NOTES.md` v5.0 为准。
- `rules/` 目录当前为空，运行时含义未确认。

## 当前优先级建议

- 修改配置字段或运行 gate 时，先从 `agent/forgis_config.py` 和配置测试入手。
- 继续 v6.0 时，下一步才考虑截图 acquisition adapters；不要直接实现 artifact 上传、多 provider、UI dashboard 或任意 shell。
- 修改工具权限或路径行为时，先读 `agent/file_tools.py`、`agent/command_runner.py`、`agent/guardrails.py` 和相关测试。
- 修改报告或 migration plan 时，同步 fixture、schema 文档和 PR body/report 测试。
- 修改 GitHub Actions 时，同步 `.github/workflows/validate-forgis.yml` 中的 workflow 结构测试。

## 文档可信度说明

本轮文档基于实际读取的目录结构、README、RELEASE_NOTES、workflow、核心 `agent/` 源码、skills、prompt、测试清单和 fixture。v6.0 视觉闭环的实际验证命令以本轮最终报告和 `docs/TESTING.md` 为准。

## 源码与旧文档冲突记录

- README 中存在历史版本说明；若与当前源码冲突，以 `agent/` 源码和 `.github/workflows/` 为准。
- 历史 v5.0 文档仍会提到 `forgis.run_report.v5.0`；当前源码的 run report schema 已因视觉字段升级到 `forgis.run_report.v6.0`。
