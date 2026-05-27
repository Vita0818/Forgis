# 工程禁区

最近自查日期：2026-05-26

## 不得破坏的用户数据格式

- 目标仓库 `FORGIS_CONFIG.yml` 字段集合和默认值由 `agent/forgis_config.py` 管理。新增、改名或删除字段必须同步 README、测试和 workflow。
- `ResolvedConfig.env()` 输出的环境变量名被 `.github/workflows/migrate.yml`、shell 脚本和报告链路使用，不得随意改名。
- `FORGIS_RUN_REPORT.json` schema 当前为 `forgis.run_report.v5.0`。
- `FORGIS_MIGRATION_PLAN.json` schema 当前写出为 `forgis.migration_plan.v5.0`，读取兼容 `v4.8`、`v3.9`、`v3.8`、`v3.7`。
- `ToolLoopResult.as_dict()`、`write_status()` 输出字段、report fixture 字段被测试覆盖，新增字段要保证脱敏和有界。
- PR body 必须保持有界，标准 body 当前限制 30000 字符，short body 当前限制 3000 字符。

## 不得破坏的文件路径约定

- 目标配置固定为目标仓库根目录 `FORGIS_CONFIG.yml`。
- 目标任务文件默认 `FORGIS_TASK.md`，可配置但必须在目标仓库根内。
- `target_subdir` 默认 `target-output`，必须是目标仓库内非根相对路径。
- `run_log_path` 默认 `{target_subdir}/FORGIS_LOG.md`，必须位于 `target_subdir` 内。
- 模型工具虚拟路径约定：`task`、`config`、`source/`、`target/`、`target_subdir/`。
- 写工具只能修改 `target_subdir` 内文件，且不能修改 source、target root、config/task、`.github/workflows`。
- report 和 migration plan 输出目录必须在 Forgis runtime root 下，不能位于 source/target checkout、Desktop、Downloads、Documents 或 secret-like 路径。

## 不得破坏的 API / 路由 / 协议 / 存储结构

- DeepSeek client 使用 OpenAI-compatible chat completions：`{api_base}/chat/completions`，payload 包含 `model`、`messages`、`tools`、`tool_choice: auto`。
- Tool schema 名称和参数由 `agent/deepseek_agent.py` 定义，`agent/file_tools.py` 按同名 `invoke()`。改动任一边必须同步另一边和测试。
- `model_env` 是 runtime env name 到 secret env name 的映射，只允许环境变量名，不允许真实 secret 值。
- `success_checks` 支持 `path_exists` 或 `command`，每个 mapping 只能包含其中一个。
- `build_command` 和 `test_command` 是非空 YAML 参数数组，不是 shell 字符串。
- `validation_commands` 是字符串列表，由 `agent/build_target.sh` 在 `target_subdir` 下执行。不要和 build/test command array 混淆。

## 不得绕过的安全机制

- 真实运行必须同时满足 `dry_run=false`、`run_agent=true`、`confirm_real_run=true`。
- source 仓库必须保持只读。
- target repo outside `target_subdir` 必须保持只读，除非由 workflow 明确处理 PR/log 等允许范围。
- config 和 task 文件必须通过 snapshot/hash 验证保持只读。
- dry run 不得写 target。
- secret leak check 必须扫描 `model_env` 对应 secret 值是否写入 `target_subdir`。
- 命令执行不得开启任意 shell 权限。`run_command` 和 build/test feedback 必须经过 `command_runner.py`。
- 报告、日志、PR body、migration plan 必须脱敏、截断、禁止完整 diff/source/model output 泄露。

## 不得随意重构的核心模块

- `agent/forgis_config.py`：配置字段、默认值、路径安全、运行 gate。
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
- README、README.zh-CN、RELEASE_NOTES：用户和 release 说明来源。

## 不得引入的架构倒退

- 不要把 target-stack、业务项目规则或特定平台迁移策略硬编码进 Forgis 核心。
- 不要让模型读写任意本地路径。
- 不要让模型修改 source repo、target root、workflow、config 或 task。
- 不要把 secret 值写入 env output、logs、reports、PR body 或 fixture。
- 不要上传 legacy runtime diagnostics artifact、完整 diff、业务源码或未脱敏模型输出。
- 不要 force push 到目标分支。
- 不要把本地 skills 扩展成外部下载或业务仓库读取，除非先设计安全边界和测试。

## 修改前必须阅读的关键源码位置

- 配置或 README 示例：`agent/forgis_config.py`、`README.md`、`README.zh-CN.md`、`tests/test_forgis_config.py`。
- Tool schema 或文件权限：`agent/deepseek_agent.py`、`agent/file_tools.py`、`tests/test_forgis_config.py`。
- 命令执行：`agent/command_runner.py`、`agent/build_runner.py`、`agent/build_target.sh`。
- Guardrails：`agent/guardrails.py`、`agent/validate_target_output.py`、`.github/workflows/migrate.yml`。
- DeepSeek 调用：`agent/deepseek_agent.py`、`agent/model_env.py`、`agent/tool_loop.py`.
- Staged translation：`agent/staged_translation.py`、`agent/source_inventory.py`。
- Migration plan：`agent/migration_units.py`、`agent/migration_scheduler.py`、`agent/migration_state.py`、`agent/migration_plan_store.py`、`agent/plan_audit.py`。
- Reports：`agent/run_report.py`、`agent/repair_report.py`、`tests/fixtures/reports/*.json`。
- PR flow：`agent/create_pr.sh`、`agent/pr_body.py`。

## 回归验证要求

- 文档-only 修改：至少运行 `git diff --check`，并检查 `git status --short`。
- Python 逻辑修改：运行相关窄测试，通常至少 `python3 -m unittest tests/test_forgis_config.py`；发布前运行 `python3 -m py_compile agent/*.py`。
- Shell 脚本修改：运行 `bash -n agent/build_target.sh` 和/或 `bash -n agent/create_pr.sh`。
- Workflow 修改：阅读并更新 `tests/test_forgis_config.py` 中 workflow 断言，必要时运行完整 unittest。
- Report/schema 修改：更新 fixture 和 schema 相关断言，确认脱敏、截断和 artifact 范围。
- 安全边界修改：增加负向测试，覆盖路径逃逸、secret-like 路径、symlink、dry-run、target scope 和 source clean。
