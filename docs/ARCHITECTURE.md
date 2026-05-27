# 架构说明

最近自查日期：2026-05-26

## 总体架构

Forgis 是一个 Python CLI/Agent 工具。它本身不内置具体平台迁移智能，而是读取目标仓库的 `FORGIS_CONFIG.yml` 与任务文件，在满足真实运行开关时调用 DeepSeek OpenAI-compatible Chat Completions，并把受控文件工具交给模型使用。

核心运行方式：

1. GitHub Actions 接收 `target_repo`。
2. checkout Forgis 仓库、目标仓库和只读 source 仓库。
3. `agent/resolve_config.py` 解析目标仓库 `FORGIS_CONFIG.yml`，输出环境变量和 workflow outputs。
4. `agent/forge.py` 做 source/target 目录与配置校验，生成运行摘要。
5. `agent/tool_loop.py` 根据 `dry_run`、`run_agent`、`confirm_real_run`、`execution_mode` 决定跳过、默认 tool loop 或 staged translation。
6. `agent/file_tools.py` 提供虚拟路径文件工具，写入限制在目标仓库 `target_subdir`。
7. guardrails、target validation、report、log、PR 创建按 workflow 顺序执行。

## 模块边界

- 配置层：`agent/forgis_config.py` 是所有运行配置的单一解析源。它定义支持字段、默认值、路径约束、`ResolvedConfig` 和 GitHub Actions env/output。
- 工作流入口层：`.github/workflows/migrate.yml` 编排 checkout、config resolve、guardrails、tool loop、validation、log、PR、artifact。`.github/workflows/validate-forgis.yml` 只验证本仓库脚本。
- Agent 调用层：`agent/deepseek_agent.py` 提供系统提示词、tool schema 和 DeepSeek client。
- 工具沙箱层：`agent/file_tools.py` 实现所有模型可调用工具，并强制虚拟路径、symlink、防 secret-like 路径、写入范围和 workflow 文件保护。
- 命令执行层：`agent/command_runner.py`、`agent/build_runner.py`、`agent/build_feedback.py` 限制命令 allowlist、执行 build/test、生成脱敏摘要。
- 控制器层：`agent/tool_loop.py` 处理默认循环、运行时状态、repair loop、migration plan、report 写入。`agent/staged_translation.py` 处理分阶段控制模式。
- 安全校验层：`agent/guardrails.py`、`agent/validate_target_output.py`、`agent/model_env.py` 负责 read-only、scope、dry-run、secret leak、meaningful output、环境变量映射。
- 报告层：`agent/run_report.py`、`agent/repair_report.py`、`agent/write_run_log.py`、`agent/pr_body.py` 输出有界、脱敏报告和 PR body。
- 迁移计划层：`agent/migration_units.py`、`agent/migration_scheduler.py`、`agent/migration_state.py`、`agent/migration_plan_store.py`、`agent/plan_audit.py` 管理 migration unit、状态转换、持久化、resume 和 audit summary。
- 本地知识层：`skills/` 和 `agent/skill_loader.py` 只注入仓库本地短文档，不扩大工具权限。

## 主要数据模型

- `ResolvedConfig`：位于 `agent/forgis_config.py`，承载 source/target repo、路径、运行开关、模型、命令、report、skills、migration scheduler、staged translation 等配置。
- `StagedTranslationConfig` 及其子配置：位于 `agent/forgis_config.py`，控制 overview、per_file、stabilization 和微阶段 gate。
- `FileToolSandbox`：位于 `agent/file_tools.py`，维护 source root、target root、target_subdir、config/task 路径、工具调用计数和操作日志。
- `ToolLoopResult`：位于 `agent/tool_loop.py`，记录是否执行、状态、summary、迭代数、工具调用数、operation log、runtime state、report 路径和 migration plan 字段。
- `RuntimeController`：位于 `agent/runtime_controller.py`，记录读写、diff、命令、build/test、repair、skills、migration plan 等观测状态。
- `MigrationUnit` / `MigrationPlan`：位于 `agent/migration_units.py`，支持 unit 类型、状态、优先级、路径、失败摘要、changed paths 和合法状态转换。
- `SourceUnit`：位于 `agent/source_inventory.py`，表示 staged translation 或 scheduler 中的源文件单元。
- `RunReportWriteResult` / report JSON：`agent/run_report.py` 输出 `forgis.run_report.v5.0`。
- Migration plan JSON：`agent/migration_plan_store.py` 输出 `forgis.migration_plan.v5.0`，并兼容读取 v4.8、v3.9、v3.8、v3.7。

## 关键业务链路

### 默认 tool loop

1. `resolve_config()` 固定读取目标仓库根目录 `FORGIS_CONFIG.yml`。
2. `run_tool_loop()` 先加载 skills 和 migration plan。
3. 若 `dry_run=true` 或有效 `run_agent=false`，返回 skipped result，不调用 DeepSeek。
4. 若执行，创建 `FileToolSandbox`、`RuntimeController`、`RepairLoopController`。
5. DeepSeek 每轮返回 tool calls 或 final summary。
6. 工具调用经 `sandbox.invoke()` 执行，结果写回 message history，并同步 runtime/repair/migration plan 状态。
7. final summary 前可能被 repair loop gate 阻止，要求先 diff 或 build/test。
8. 完成或达到 max iterations 后，生成 repair report、run report、migration plan、status env、operation log。

### staged translation

`execution_mode=staged_translation` 时，`tool_loop.py` 转入 `agent/staged_translation.py`。该模式先扫描 source inventory，然后按 `overview`、`per_file`、`stabilization` 推进。per-file 阶段可强制 `feed`、`write`、`readonly_compare`、`revise` 微阶段。控制器会阻止过早 final summary，并限制 overview、feed、compare 等阶段只能写 staged progress artifacts 或 compare reports。

### GitHub Actions 真实运行

`.github/workflows/migrate.yml` 中真实 push/PR 只在 `dry_run=false`、`run_agent=true`、`confirm_real_run=true` 且 guardrails、validation、secret leak 检查成功时发生。`agent/create_pr.sh` 不 force push。如果 `origin/$TARGET_BRANCH` 已存在，会使用 `${TARGET_BRANCH}-run-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}` 作为实际 push/PR head。

## 数据流、请求流和状态流

- 配置流：目标仓库 `FORGIS_CONFIG.yml` -> `resolve_config.py` -> `ResolvedConfig.env()` -> GitHub Actions env -> 后续脚本。
- 任务流：目标仓库 task file -> `deepseek_agent.initial_messages()` 中提示模型先读取 `task`。
- 模型请求流：`tool_loop.py` / `staged_translation.py` -> `DeepSeekClient.chat()` -> `{api_base}/chat/completions`。
- 文件访问流：模型 tool call -> `FileToolSandbox` -> source/target/target_subdir 虚拟路径解析 -> 文件读写或 git/command 工具。
- 状态流：工具结果 -> `RuntimeController.observe_tool_result()`、`RepairLoopController.observe_tool_result()`、migration plan runtime fields -> report/status outputs。
- 报告流：runtime state + operation log -> `repair_report`、`run_report`、`FORGIS_MIGRATION_PLAN.json`、GitHub Step Summary、target `FORGIS_LOG.md`。

## 网络、本地存储、后台任务

- 网络：运行时只在 `DeepSeekClient.chat()` 中调用 OpenAI-compatible Chat Completions API。仓库 checkout、push、PR 由 GitHub Actions 和 `gh`/`git` 完成。
- 本地存储：目标仓库输出只允许写入 `target_subdir`。运行报告和 migration plan 写入 Forgis runtime workspace 下的安全输出目录，不能写到 source/target checkout、Desktop、Downloads、Documents 或 secret-like 路径。
- 后台任务：没有常驻 daemon。所有任务由 CLI 或 GitHub Actions step 驱动。

## UI 与业务逻辑分层

本项目没有前端 UI。唯一用户可见界面是 CLI 输出、GitHub Actions logs、GitHub Step Summary、PR body、Markdown/JSON 报告和目标仓库 run log。

## 平台相关与共享代码边界

Forgis 核心保持平台无关。SwiftUI、Compose、HarmonyOS 相关内容位于 `skills/` 和 `docs/DS_GUIDE_Swift_Kotlin.md`，用于任务上下文和人工参考，不应硬编码到 `agent/` 的核心逻辑中。

## 安全、鉴权、权限和文件访问

- `model_env` 只映射环境变量名，`model_env.py` 校验缺失但不打印真实 secret。
- `guardrails.py check-secret-leaks` 会扫描 `target_subdir` 是否写入配置映射中的 secret 值。
- 文件工具拒绝绝对路径、`..`、`.git`、secret-like 路径、symlink 写入、source 写入、target root 写入、workflow 文件写入。
- `run_command` 只允许保守基础命令，且 cwd 必须在 `target_subdir` 内。
- `run_build` / `run_tests` 只运行配置数组命令，profile 目前只允许安全 Python `py_compile` / `unittest` 类命令。
- `validation_commands` 在 `agent/build_target.sh` 中以 shell 字符串执行，作用域在 `target_subdir`，但其安全性依赖目标仓库配置和 workflow gate，应谨慎对待。

## 当前架构风险或不确定点

- `validation_commands` 使用 `bash -lc`，虽然 cwd 限定在 `target_subdir`，但比 `command_runner.py` 的数组 allowlist 更宽松。修改相关逻辑时必须同步测试。
- 测试集中在单个 6000 行左右的 `tests/test_forgis_config.py`，定位方便但维护成本高。
- `rules/` 目录为空且未确认使用。
- staging、migration plan、report、repair loop 的状态字段很多，新增字段时容易漏掉 env、report、fixture 和测试。
- README 存在历史版本说明，当前行为应以 `agent/` 源码、workflow 和 `RELEASE_NOTES.md` v5.0 为准。
