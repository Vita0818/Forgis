# Forgis

Forgis 是一个带受控文件工具运行时的本地代码迁移助手。默认 backend 仍是 DeepSeek，v7.0 第一阶段也支持非 streaming 的 OpenAI-compatible Chat Completions，并继续使用同一套安全边界。

它不是内置迁移智能的迁移器，而是一个很薄的工具壳：从目标仓库读取配置和任务提示词，在显式允许时调用配置的 OpenAI-compatible 文本模型，并把受控文件工具交给模型使用。迁移策略、平台差异和具体项目规则，都应该写在任务提示词或参考文档里。

## Forgis 是什么

Forgis 本体只做三件事：

1. 从目标仓库读取 `FORGIS_CONFIG.yml` 和配置里的任务提示词文件。
2. 在 `dry_run=false`、`run_agent=true`、`confirm_real_run=true` 同时成立时，调用非 streaming OpenAI-compatible Chat Completions。
3. 给模型提供受控文件工具，让它自己读取、分析并写入目标文件。

这种设计让 Forgis 保持通用。它负责边界、工具和日志，不负责把某个平台或某个项目的迁移经验写死到系统逻辑里。

## Forgis 不是什么

Forgis 不是平台迁移器，不是 Android、iOS、Web 或任何单一技术栈专用工具，也不是内置项目理解系统、脚手架生成器或自动保证迁移成功的工具。

它不会预加载 source repo 内容，不会把 `FORGIS_TASK.md` 改写成更大的策略提示词，也不会替人工 review 做最终判断。真实运行的结果应该进入 PR，由人检查、修正和合并。

## 核心工作流

主 workflow 的手动输入只有一个：

```text
target_repo: owner/target-repo
```

其它配置都来自目标仓库根目录的 `FORGIS_CONFIG.yml`。Forgis 会按配置 checkout source repo 和 target repo，解析任务提示词，必要时运行模型 tool loop，然后在符合条件时向 target repo 推送分支并创建 PR。

## 本地 CLI

v7.0 第一阶段新增本地 CLI 入口，它复用 workflow 使用的 config resolver 和 tool loop：

```bash
python3 -m venv /tmp/forgis-v7-local-venv
/tmp/forgis-v7-local-venv/bin/python -m pip install -r requirements.txt

python -m agent.cli help
python -m agent.cli doctor
python -m agent.cli smoke --workdir /tmp/forgis-smoke
```

显式指定本地 config 并 dry-run：

```bash
python -m agent.cli run \
  --source /path/to/source \
  --target /path/to/target \
  --target-repo local/my-migration \
  --config examples/FORGIS_CONFIG.local.smoke.yml \
  --summary-output /tmp/forgis-summary.md \
  --dry-run
```

真实 OpenAI-compatible 本地运行只在你自己导出 secret env 后执行：

```bash
export FORGIS_MODEL_API_KEY="..."
python -m agent.cli run \
  --source /path/to/source \
  --target /path/to/target \
  --target-repo local/my-migration \
  --config examples/FORGIS_CONFIG.local.openai-compatible.yml \
  --summary-output /tmp/forgis-summary.md
```

`doctor` 只检查本地运行环境，并且只显示 API env 名称的 set/unset 状态；不会调用 API。`smoke` 会在指定 workdir 下创建临时 source/target/config 并执行 dry-run，所以不需要 API key。从仓库根目录之外运行时，请先设置 `PYTHONPATH=/path/to/Forgis` 再执行 `python -m agent.cli`。

CLI 不新增写入权限，也不新增 shell 执行能力。source 仍保持只读，target 写入仍只能通过 `target_subdir`，真实模型调用仍必须同时满足 `dry_run=false`、`run_agent=true`、`confirm_real_run=true`。

## 仓库和文件布局

典型目标仓库需要包含：

```text
FORGIS_CONFIG.yml
FORGIS_TASK.md
target-output/
```

其中：

- `FORGIS_CONFIG.yml`：运行配置，固定放在目标仓库根目录。
- `FORGIS_TASK.md`：给模型的任务提示词，路径由 `task_prompt_path` 指定，默认在目标仓库根目录。
- `target-output/`：默认可写输出目录，对应 `target_subdir`。
- `target-output/FORGIS_LOG.md`：默认长期运行日志，对应 `run_log_path`。

Forgis 自身的 `docs/` 和 `guides/` 目录用于发布说明和参考材料，不会自动变成模型的内置规则。

## FORGIS_CONFIG.yml 配置指南

`FORGIS_CONFIG.yml` 默认放在目标仓库根目录；本地 CLI 可以用 `--config` 显式指向另一个配置文件。配置必须是非空 YAML mapping，并且只能使用 Forgis 当前支持的字段。未知字段会在 Resolve Forgis config 阶段直接失败，模型不会开始运行。

请把三类信息分开：

- **GitHub Actions input / CLI 提供，不能写进 config：** `target_repo`。
- **`FORGIS_CONFIG.yml`：** repo ref、输出分支、输出子目录、任务文件路径、OpenAI-compatible 模型连接字段、运行开关、skills、report、repair loop、migration plan，以及不含 secret 的 visual validation 开关。
- **`FORGIS_TASK.md`：** 产品与迁移指令，例如 Android / Kotlin / Jetpack Compose、目标技术栈、UI 风格、信息架构、迁移范围、隐私规则，以及“只写入 `target_subdir`”这类业务限制。

不要把这些字段或写法放进 `FORGIS_CONFIG.yml`：

- `target_repo`：通过 workflow input 或 CLI `--target-repo` 传入。
- `target_stack`：Android / Kotlin / Jetpack Compose 应写进 `FORGIS_TASK.md`。
- `source_branch`：应改为 `source_ref`。
- `target_repo_url`、`source_repo_url`、`target_path`、`source_path`。
- `agent_backend: aider`：Forgis 当前支持 `agent_backend: deepseek` 和 `agent_backend: openai-compatible`。
- `build_command: []` 或 `test_command: []`：不配置 build/test 时直接省略字段。
- `model: deepseek/deepseek-v4-pro`：应使用 DeepSeek API 接受的 `deepseek-v4-pro` 或 `deepseek-v4-flash`。
- `FORGIS_CONFIG.yml` 中不得写 Qwen API key、token、evidence root、截图文件路径或本地敏感路径。v6.0 只接受下文记录的不含 secret 的 `visual_validation` 控制块；reference/actual 截图目录必须是目标仓库相对路径且作为只读输入；Qwen key/base/model 只能通过显式 runtime env 提供，且不会写入报告。

最小可跑通配置：

```yaml
source_repo: Vita0818/Kikaria
source_ref: main
target_branch: forgis/kikaria-android
target_base_branch: main
target_subdir: Kikaria-Android
task_prompt_path: FORGIS_TASK.md

agent_backend: deepseek
model: deepseek-v4-pro
api_base: https://api.deepseek.com
api_format: openai-compatible
request_timeout_seconds: 120
model_env:
  DEEPSEEK_API_KEY: DEEPSEEK_API_KEY

execution_mode: tool_loop
dry_run: false
run_agent: true
confirm_real_run: true

run_report_enabled: true
```

Kikaria Android / Kotlin / Jetpack Compose 第一轮迁移推荐配置：

```yaml
source_repo: Vita0818/Kikaria
source_ref: main

target_branch: forgis/kikaria-android
target_base_branch: main
target_subdir: Kikaria-Android
task_prompt_path: FORGIS_TASK.md

agent_backend: deepseek
model: deepseek-v4-pro
api_base: https://api.deepseek.com
api_format: openai-compatible
request_timeout_seconds: 120
model_env:
  DEEPSEEK_API_KEY: DEEPSEEK_API_KEY

execution_mode: tool_loop
dry_run: false
run_agent: true
confirm_real_run: true

skills_enabled: true
auto_select_skills: false
selected_skills:
  - migration_general
  - swiftui_to_compose
  - ui_style_preservation
  - build_repair

run_report_enabled: true

migration_scheduler_enabled: true
migration_plan_persistence_enabled: true
migration_plan_resume_enabled: false
migration_plan_auto_update_enabled: true
migration_plan_auto_complete_on_success: false
migration_plan_audit_summary_enabled: true

repair_loop_enabled: false
```

v6.0 可选的 Qwen Visual Evidence Mode 控制块：

```yaml
visual_validation:
  enabled: auto
  provider: qwen
  mode: reference_guidance
  reference_screenshot_dirs:
    - forgis-reference-screenshots
  actual_screenshot_dirs: []
  max_visual_iterations: 2
  require_reference_first: true
  require_actual_for_full_validation: false
  upload_visual_artifact: false
```

如果只是先验证配置解析，可以保留同一份配置，但把运行开关改成：

```yaml
dry_run: true
run_agent: false
confirm_real_run: false
```

必填项：

- `source_repo`
- `target_branch`
- workflow 输入 `target_repo`

常用默认值：

- `source_ref: main`
- `target_subdir: target-output`
- `task_prompt_path: FORGIS_TASK.md`
- `agent_backend: deepseek`
- `model: deepseek-v4-pro`
- `api_base: https://api.deepseek.com`
- `api_format: openai-compatible`
- `request_timeout_seconds: 120`
- `target_base_branch: main`
- `run_log_path: {target_subdir}/FORGIS_LOG.md`
- `dry_run: true`
- `run_agent: false`
- `confirm_real_run: false`
- `max_iterations: 80`
- `max_tool_result_chars: 20000`
- `execution_mode: tool_loop`
- 未显式配置时没有 `build_command` 或 `test_command`
- `repair_loop_enabled: false`
- `run_report_enabled: true`
- `skills_enabled: true`
- `auto_select_skills: true`
- `migration_scheduler_enabled: false`
- `migration_plan_persistence_enabled: true`
- `migration_plan_resume_enabled: false`
- `migration_plan_auto_complete_on_success: false`
- `migration_plan_audit_summary_enabled: true`
- `visual_validation.enabled: auto`
- `visual_validation.provider: qwen`
- `visual_validation.mode: reference_guidance`
- `visual_validation.reference_screenshot_dirs: []`
- `visual_validation.actual_screenshot_dirs: []`
- `visual_validation.max_visual_iterations: 2`
- `visual_validation.require_reference_first: true`
- `visual_validation.require_actual_for_full_validation: false`
- `visual_validation.upload_visual_artifact: false`

长时间真实迁移任务可以显式调大运行量字段，但默认值仍保持温和：

| 字段 | 默认值 | 最大允许值 |
| --- | ---: | ---: |
| `max_iterations` | `80` | `5000` |
| `max_tool_result_chars` | `20000` | `5000000` |
| `max_command_output_chars` | `8000` | `2000000` |
| `request_timeout_seconds` | `120` | `600` |
| `run_report_max_events` | `100` | `10000` |
| `run_report_max_chars` | `200000` | `20000000` |

较大的值适合长任务，但会增加日志体积、报告体积、内存使用、模型 token 暴露和总运行时间。它们不会改变工具权限、命令 allowlist、report redaction 或 reports-only artifact 边界。

`target_branch` 是目标仓库里的输出分支 / PR head branch，不是 base branch。真实运行建议使用 `forgis/kikaria-android` 这类功能分支，并用 `target_base_branch: main` 指向 PR base。

### build_command / test_command

`build_command` 和 `test_command` 是可选字段。不需要 Forgis 提供 build/test feedback 时，直接省略这两个字段。

如果要配置，必须是非空参数数组：

```yaml
build_command:
  - python3
  - -m
  - py_compile
  - app.py

test_command:
  - python3
  - -m
  - unittest
  - discover
```

这些数组不支持 shell 字符串、shell 展开、glob、绝对路径、`..`、管道、重定向或命令串联。safe command runner 会拒绝 shell 解释器、`rm`、`sudo`、`chmod`、`chown`、`curl`、`wget`、`ssh`、`scp`、`git` 等危险或不受控命令。

第一轮 Android 迁移建议省略 `build_command` 和 `test_command`。此时 Gradle 工程可能还没成型，并且 v5.0 不建议把 `./gradlew` 直接写入这些字段，除非 command runner 明确允许且已有测试覆盖。

### 模型 API 与 secret

v7.0 第一阶段的模型 transport 是非 streaming OpenAI-compatible Chat Completions。DeepSeek 仍是默认兼容路径：

```yaml
agent_backend: deepseek
model: deepseek-v4-pro
api_base: https://api.deepseek.com
```

或：

```yaml
model: deepseek-v4-flash
```

其它 OpenAI-compatible 文本 provider 可以使用显式 backend alias，并配置 `api_base` 或 `base_url`：

```yaml
agent_backend: openai-compatible
model: deepseek-chat
api_base: https://api.deepseek.com/v1
api_format: openai-compatible
request_timeout_seconds: 120
model_env:
  api_key: FORGIS_MODEL_API_KEY
```

真实运行总是需要声明 secret 环境变量映射：

```yaml
model_env:
  DEEPSEEK_API_KEY: DEEPSEEK_API_KEY
```

这里写的是环境变量名，不要把真实 API key 写进 `FORGIS_CONFIG.yml`。env 缺失错误只会显示环境变量名，不显示值。模型 API key、Authorization header、provider raw response 和完整模型输出不得写入日志、报告、PR body 或测试 fixture。

v7.0 第一阶段不实现 streaming SSE、Responses API、image/multimodal 模型调用、本地 server/gateway、council、多 Agent、自动截图、GUI、Keychain、`~/.config` 默认配置或 provider 私有协议。

### Qwen Visual Evidence Mode（v6.0 reference guidance）

Forgis v6.0 已把 Qwen Visual Evidence Mode 接成 reference-guided migration 闭环，完整契约见 `docs/QWEN_VISUAL_MODE.md`。用户把源 App 参考截图预先放进目标仓库，并通过 `visual_validation.reference_screenshot_dirs` 声明目录。主 Agent 可先调用 `list_visual_references`，再对关键图片调用 `inspect_visual_reference`，让 Qwen 提取页面结构、视觉层级、颜色、字体、间距、圆角、组件关系和产品气质；DeepSeek/Forgis 仍负责读源码、改代码、构建、测试和最终报告。由于 `visual_validation` 已成为稳定顶层 report 块，run report schema 当前为 `forgis.run_report.v6.0`。

实现上，`agent/visual_evidence.py` 负责视觉证据状态和路径安全，`agent/qwen_vision.py` 负责可 mock 的 provider adapter。自动截图 acquisition 仍属于 Phase 8+ 之后的可选能力。

Qwen 的定位是视觉理解 provider，不是代码迁移 Agent。Qwen 只通过 sandbox 虚拟路径读取已批准的截图图片，不得读取源码、修改文件、运行命令，或接收源码、secret、token、`.env`、证书、私钥、provisioning profile、报告中的图片 bytes/base64 或私有本地配置。`actual_screenshot_dirs` 和 `compare_visual_screenshots` 只是用户已提供目标渲染截图时的可选增强。reference-only 是有效视觉迁移指导，但不是完整真实渲染验收。单元测试默认 mock provider 且不联网；只有显式提供 `QWEN_API_KEY` 时才会真实调用 Qwen HTTP transport，可选 `QWEN_API_BASE` 和 `QWEN_VISION_MODEL`。当前仍不实现自动模拟器/真机/窗口截图、visual artifact 上传、多 provider、任意 shell 或 UI dashboard。

`visual_validation.enabled=auto` 使用确定且保守的规则：显式选中 `qwen_visual_mode`、任一视觉工具已被调用，或已配置 `reference_screenshot_dirs` 且任务文本包含强 UI/视觉/截图关键词时才要求视觉证据。纯代码、后端、配置、构建脚本或单元测试修复不会自动进入视觉 gate，除非出现上述信号。

### FORGIS_TASK.md 示例

目标技术栈和产品迁移要求写进 `FORGIS_TASK.md`，不要写进 config：

```markdown
# Kikaria Android Migration

Migrate current Kikaria to Android Kotlin Jetpack Compose.

Write generated code only under `Kikaria-Android`.

Preserve information architecture, core flows, visual hierarchy, and interaction intent.

Do not hard-code user names, local paths, secrets, or private data.

First run scope: create the Android/Compose foundation and core screens; leave TODOs for deferred areas.
```

## FORGIS_TASK.md 任务提示词说明

任务提示词是模型执行工作的核心输入。Forgis 不内置迁移策略，所以任务提示词需要写清楚：

- 要读取哪些 source 和 target 路径；
- 只能写入 `target_subdir`；
- 输出应优先能进入 PR 供人工 review；
- 需要遵守哪些平台、产品或迁移指引；
- 完成后需要返回什么样的 `final_summary`。

不要把 API key、token、证书、签名材料或个人隐私写进任务提示词。

## 真实运行与 dry run

默认配置是安全 dry run：

```yaml
dry_run: true
run_agent: false
confirm_real_run: false
```

此时 Forgis 不调用模型、不写 target、不 push、不创建 PR。

只有下面三个开关同时成立，才会真实调用配置的模型：

```yaml
dry_run: false
run_agent: true
confirm_real_run: true
```

真实运行会消耗模型 API 额度。`dry_run=false` 但缺少 `confirm_real_run=true` 会直接失败；`run_agent=false` 会跳过模型调用。

## PR 分支冲突处理

Forgis 不会使用无条件 force push。如果配置的 `target_branch` 在 `origin` 上不存在，`create_pr.sh` 会保持原有行为：从 `target_base_branch` 创建本地输出分支，提交 agent output，推送该分支，并以它作为 PR head。

如果 `origin/$target_branch` 已存在，Forgis 不会覆盖旧分支，而是把本次运行结果推送到唯一 fallback branch。GitHub Actions 中 fallback 名称为：

```text
${target_branch}-run-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}
```

PR head 始终使用实际推送的分支。日志会打印配置的 target branch、远端分支是否已存在、实际 push branch，以及 PR head branch。

## PR body 长度限制

Forgis 会保持 PR body 短小且有硬上限。`create_pr.sh` 生成的摘要 body 最多 30,000 字符，显著低于 GitHub GraphQL `createPullRequest` 限制。body 会包含配置的 target branch、实际 push branch、target base branch、target subdir、可取得的 commit hash、运行模式、可取得的 Actions run 链接，以及 `forgis-reports` artifact 提示。

完整 `FORGIS_RUN_REPORT.md`、`FORGIS_RUN_REPORT.json`、`FORGIS_MIGRATION_PLAN.json`、完整 diff、tool operation log、大段模型 summary、provider 原始响应、截图 bytes/base64 和大段 build/test output 不会写进 PR body。PR body 只会从 run report 中摘取有界的 Visual Validation 摘要。完整安全报告请下载 `forgis-reports` artifact。

如果 GitHub 仍然因为 body 过长拒绝创建 PR，Forgis 会自动用最多 3,000 字符的极短 body 重试一次。重试时仍然使用实际 push branch 作为 PR head。

## 模型 tool loop 和实时日志

真实运行时，Forgis 会把任务交给配置的模型，并允许它通过工具逐步读取和写入文件。日志会显示：

- iteration 进度；
- tool call 名称和安全处理后的路径；
- read/write 计数；
- tool result 是否被截断；
- changed paths 数量；
- 写工具成功后的 changed path；
- 最终 `final_summary` 是否收到。

日志不能显示 secret 值、`reasoning_content`、大段源码、完整工具结果或写入内容。工具结果会按 `max_tool_result_chars` 限制截断，较大的文件应让模型使用 `start_line` 和 `max_lines` 分页读取。

## staged_translation 分阶段执行模式

`staged_translation` 是可选执行模式，适合跨端迁移、重构迁移、逐文件投喂模型、或任何需要让模型先整体理解再逐单元推进的任务。它不是 Forgis 内置的平台迁移智能，也不会把某个技术栈或业务项目规则写死进 Forgis。具体迁移策略仍然由 `FORGIS_TASK.md`、目标仓库 docs 和用户任务要求定义。

这个模式是 controller-enforced，不只是提示词建议。Forgis 会维护 source unit queue、当前 phase、当前 micro-phase、已处理/延期单元、compare report 状态、目标侧变更路径和 folder review 状态；如果当前门控条件没满足，Forgis 会停留在当前 micro-phase，并在下一轮把缺失条件反馈给模型。

启用方式：

```yaml
execution_mode: staged_translation
max_iterations: 160

staged_translation:
  min_total_iterations: 120
  min_processed_units: 3
  max_units_per_run: 12

  enforce_micro_phases: true
  require_source_read: true
  require_compare_report: true
  require_progress_update: true
  require_target_effect_or_deferred_reason: true

  phases:
    overview:
      min_iterations: 20
      max_iterations: 80
    per_file:
      min_iterations: 80
      max_iterations: 240
    stabilization:
      min_iterations: 20
      max_iterations: 80

  per_file_micro_phases:
    enabled: true
    require_feed: true
    require_write: true
    require_compare_report: true
    require_revision: true

  folder_batch_review:
    enabled: true
    max_bundle_chars: 80000
    require_after_folder_complete: true

  low_impact_warning:
    enabled: true
    min_code_changed_paths: 1
    ignore_report_only_changes: true

  source_inventory:
    include_globs:
      - "**/*"
    exclude_globs:
      - ".git/**"
      - "**/.DS_Store"
      - "**/build/**"
      - "**/.gradle/**"
      - "**/DerivedData/**"
      - "**/node_modules/**"

  progress_files:
    plan: FORGIS_TRANSLATION_PLAN.md
    source_target_map: FORGIS_SOURCE_TARGET_MAP.md
    progress: FORGIS_TRANSLATION_PROGRESS.md
    compare_report_dir: FORGIS_COMPARE_REPORTS
```

不配置 `execution_mode` 时仍走旧的普通 tool loop。`execution_mode` 也可以写成 `run_mode`，但两者同时出现时必须一致。启用 staged 模式后，`max_iterations` 必须大于等于 `staged_translation.min_total_iterations`；如果没有显式配置 `max_iterations`，Forgis 会给 staged 模式使用不低于默认最低总轮次的值。

source unit queue 来自 `source_inventory`。Forgis 会稳定排序，默认排除 `.git`、构建/缓存/生成目录、锁文件、常见二进制和图片文件，并优先处理源代码、项目说明、架构文档、配置和文本规格。queue 会写入 `FORGIS_TRANSLATION_PROGRESS.md` 和 `FORGIS_SOURCE_TARGET_MAP.md`，实时日志会显示 queue length 和当前 unit index。queue 为空时 staged 模式会 fail-fast。

staged 模式分为三段：

1. `overview`：先让 DeepSeek 读取任务、source tree、target_subdir tree，识别源目录、目标结构、处理顺序和风险，并写入计划、source-target map、progress 文件。这个阶段只允许写 staged 进度 artifact，避免一上来大范围重写目标实现。
2. `per_file`：按 source unit queue 顺序逐个处理源文件或源功能单元。每个单元都必须走小四段式，不能跳步。
3. `stabilization`：所有选定单元处理后，只做小修和 build-oriented 一致性检查。若配置了 `validation_commands`，由现有 workflow 运行；否则只做静态复核，不会声称真实 build 成功。

单文件小四段式：

1. `feed`：必须用 `read_file` 读取当前 source unit，读取相关目标文件，判断目标侧是已覆盖、部分覆盖、缺失还是偏离；此阶段禁止写目标实现代码。
2. `write/translate`：必须围绕当前 source unit 创建或修改目标实现。如果判断无需修改，必须在 progress/map 中明确写出 `already_covered`、`deferred` 或缺失支持原因；否则 Forgis 不会认为该单元完成。
3. `readonly_compare`：必须只读当前 source unit 和刚生成/相关目标文件，必须写 compare report 或 progress 中的明确 compare section；此阶段禁止修改普通实现文件，只允许写 report/progress/map artifact。
4. `revise`：根据 compare report 做一轮小修。如果不需要改代码，必须记录 `no_revision_needed`；修完还要更新 progress 或 source-target map，然后 Forgis 才会把当前 source unit 标记为 processed 或 deferred。

`min_processed_units` 防止模型只处理 0-1 个单元就结束；`max_units_per_run` 防止一次运行吞完整仓库。达到本轮最大单元数后，Forgis 会进入 stabilization，而不是继续无限推进。若 reached `max_iterations`，Forgis 会写入 partial progress，不会声称完整完成。

当某个 source folder 下本轮直接文件都处理完或延期后，Forgis 会强制触发一次 `folder_review`。它会把该 folder 作为整体让 DeepSeek 检查跨文件状态、类型、导航、组件依赖和目标侧一致性。`max_bundle_chars` 限制一次 folder review 可提示的源文件规模；超过限制时，控制消息会明确列出本轮包含和省略的文件，要求模型分页读取或说明检查范围，不能静默跳过。folder review 必须更新 progress 或 source-target map 才能结束。

Forgis 还会做 low-impact detection。如果迭代很多但有效处理单元少、只改报告/README、没有代码类目标变更、compare report 缺失、progress/map 未更新，会在日志、progress 和 `final_summary` 中写入 `LOW IMPACT WARNING`。默认 `strict_mode=false` 时 warning 不阻断 PR；`strict_mode=true` 时 low-impact 会让 tool loop 以失败状态结束。

staged 模式会在 `target_subdir` 内维护进度文件：

- `FORGIS_TRANSLATION_PLAN.md`
- `FORGIS_SOURCE_TARGET_MAP.md`
- `FORGIS_TRANSLATION_PROGRESS.md`
- `FORGIS_COMPARE_REPORTS/<safe-source-path>.md`

compare report 文件名会安全化，避免路径注入。所有进度 artifact 路径都解析到 `target_subdir` 内；配置成绝对路径、`..`、`.git` 等不安全路径会失败。

阶段门控包括：

- 全局最低轮次 `min_total_iterations`；
- 每阶段 `min_iterations` / `max_iterations`；
- 有效处理单元数 `min_processed_units`；
- 单次运行最多处理单元数 `max_units_per_run`；
- overview 必须生成计划、source-target map、progress；
- per-file 必须按 source unit queue 顺序推进；
- 每个 source unit 必须满足 feed/write/readonly_compare/revise 的事实门控；
- compare report 或 progress compare section 必须存在；
- 过早 `final_summary` 会被 Forgis 拒绝，并注入控制消息要求继续当前阶段；
- 达到 `max_iterations` 时不会假装完成，而是记录当前 phase、已处理/剩余单元数量，并向 progress 文件追加 partial progress 和 next-step 线索。

staged 实时日志会额外显示 staged mode enabled、source unit queue length、current unit index、current source unit、current micro-phase、source unit 是否已读取、target changed paths before/after、compare report path、processed/deferred unit count、folder review start/end、low-impact warning、`final_summary` 接受或拒绝原因、`max_iterations reached` 和 partial progress saved。日志仍然不会打印 secret、Authorization header、完整请求/响应、`reasoning_content`、大段源码或写入内容。

## Forgis v3.0 第一阶段 Runtime

Forgis v3.0 第一阶段加入的是最小 Claude Code-like agent runtime 内核，不替换现有 v2 tool loop，也不替换 `staged_translation`。这一阶段的目标是让 DeepSeek 能真实观察仓库状态、搜索、做小步修改、查看自己的 diff，并具备后续接入构建/测试反馈循环的基础。

新增能力：

- `search_text`：在 source、target 或 target_subdir 内做有上限的文本/正则搜索；
- `git_status`：查看 target workspace 的 git status 摘要；
- `git_diff`：查看 target workspace 当前 diff，并支持字符数限制；
- `edit_file` / `apply_patch`：对 target_subdir 内已有文件做小步替换或 unified diff 修改；
- `run_command`：在 `target_subdir` 内运行保守 allowlist 命令，禁用 `shell=True`，带 timeout 和输出截断；
- runtime controller skeleton：记录本轮是否读过文件、是否修改 target、是否查看 diff、是否运行命令。

这不是完整 v3，也不是完整 Claude Code 能力。完整构建编排、自动 repair 调度、migration unit scheduler、远程 skill 发现和更完整的 controller 状态机仍然是后续工作。

## Forgis v3.1 构建/测试反馈闭环基础

Forgis v3.1 新增的是最小验证反馈闭环基础。它不会强制每个任务都 build/test，也不会自动进入复杂修复循环；它只是给 DeepSeek 提供两个配置驱动的专用工具：

- `run_build`：当配置了 `build_command` 时运行构建检查；
- `run_tests`：当配置了 `test_command` 时运行测试检查。

两个工具都在 `target_subdir` 内运行，继续使用 safe command runner，不使用 `shell=True`，有 timeout 和输出截断，并返回结构化结果：

- `status`：`success` / `failed` / `skipped` / `rejected` / `timeout`；
- `exit_code`；
- `stdout_tail` / `stderr_tail`；
- `duration_seconds`；
- 失败时的短 `summary`。

错误摘要器会识别 Python `SyntaxError`、`ImportError`、`ModuleNotFoundError`、unittest failure、命令被拒绝、timeout 和通用非零退出。runtime controller 会记录最近一次 build/test 状态、最近失败摘要，以及失败后是否发生过 target 文件修改。

命令必须写成参数数组，不是 shell 字符串：

```yaml
build_command:
  - python3
  - -m
  - py_compile
  - app.py

test_command:
  - python3
  - -m
  - unittest
  - discover
```

v3.1 暂不支持 command array 里的 glob 展开。请写明确相对路径，或使用安全的测试发现命令。

## Forgis v3.2 受限 repair loop 第一阶段

Forgis v3.2 新增的是受限 repair loop controller。它默认关闭，只有显式配置后才会记录并执行 repair 门控：

```yaml
repair_loop_enabled: true
max_repair_attempts: 2
repair_requires_diff_check: true
repair_requires_build_or_test: true
repair_stop_on_success: true
```

当 `run_build` 或 `run_tests` 返回 `failed`、`rejected` 或 `timeout` 时，controller 会记录失败摘要，并允许最多 N 次小步修复尝试。修复只能通过现有 read/search/edit/apply_patch 等工具推进；controller 不会自己调用模型，也不会自己运行命令。

如果 `repair_requires_diff_check=true`，每次 edit/apply_patch 后必须先调用 `git_diff`，才能再次运行 `run_build` 或 `run_tests`。再次检查成功会停止 repair loop，并记录 `stopped_reason: success`；达到尝试上限会停止，并记录 `stopped_reason: max_attempts_reached`；违反顺序的工具调用会返回 `status: blocked`，而不是让 tool loop 崩溃。

`max_repair_attempts` 最大为 5。repair loop 不扩大 `run_command` / `run_build` / `run_tests` 的安全权限，不允许任意 shell，也不是完整 Claude Code 或自动迁移调度器。它只是最小的“检查 → 摘要 → 小步修复 → diff 自查 → 再检查”闭环。

## Forgis v3.3 repair event log 与 runtime report

Forgis v3.3 增强的是 build/test/repair 流程的可观测性，不增加新的自动化智能，不是完整 Claude Code，不做完整 migration scheduler，也不改变 push 或 PR 创建语义。

普通 tool loop 运行时，Forgis 会在 repair loop 启用的情况下维护一个有长度上限的 repair event log。事件包括 build/test 开始和结束、失败摘要记录、允许 repair attempt、失败后的 edit/apply_patch、diff 自查、repair recheck、repair 成功、被门控阻止，以及达到最大尝试次数。每个事件只保存短状态、attempt 编号、check 类型、安全相对路径和短失败摘要。

tool loop 的 JSON summary 现在会包含 compact runtime summary 和 Markdown `repair_report`。报告会展示：

- build/test 运行次数和最近状态；
- repair loop 是否启用、已用 attempts、是否成功、停止原因；
- 最近失败摘要；
- 每次 repair attempt 的触发原因、修改路径、是否看过 diff、复核结果；
- blocked / stopped reason；
- next suggested action。

如果运行环境提供 `GITHUB_STEP_SUMMARY`，Forgis 会把同一份安全 Markdown 报告追加到 GitHub Actions step summary。summary 路径缺失或不可写不会让主流程崩溃。

报告会遮蔽 secret-like 内容，避免输出绝对私人路径，限制事件和报告长度，并且不会输出完整源码或完整 diff。

## Forgis v3.4 持久化运行报告

Forgis v3.4 会把 v3.3 的 runtime report 以受控文件形式持久化，便于本地调试和 GitHub Actions artifact 下载：

- `FORGIS_RUN_REPORT.md`
- `FORGIS_RUN_REPORT.json`

Markdown report 面向人阅读，包含配置概览、tool 统计、build/test 状态、repair loop 状态、changed paths、v3.3 repair report、final summary、停止原因和 next suggested action。JSON report 面向自动化分析，包含同样的信息，并在 `run_report_include_events=true` 时写入有数量上限的 repair event log。

报告只会写入 Forgis runtime output 目录。默认配置路径是 `.forgis/reports`；GitHub workflow 中显式写入 `forgis-runtime/reports`，方便作为 artifact 上传。报告路径必须是相对 runtime path；绝对路径、路径穿越、source/target checkout 目录、`target_subdir`、`.git` 和 secret-like 路径段会被拒绝。写入失败会记录在 tool loop JSON/status output 里，默认不阻断主流程；只有 `run_report_required: true` 时才会让运行失败。

workflow 只会把 `forgis-runtime/reports/**` 作为 Forgis reports artifact 上传。它不会上传 resolved config summary、run summary、tool-loop summary、operation log、status env、long-log preview 等 legacy runtime diagnostics artifacts。这不改变 dry-run、real-run、push 或 PR 创建门控。

持久化报告仍然不会输出完整源码、完整 diff、API key、token、绝对私人路径或无上限 stdout/stderr。v3.4 仍然不是完整 Claude Code，也不是 migration scheduler。

## Forgis v3.5 本地动态 skills 第一阶段

Forgis v3.5 新增第一阶段本地动态 skills。skill 是 Forgis 仓库内 `skills/` 目录下的短 Markdown 文档，用来把迁移规则拆成可控、按需注入的小块，避免继续膨胀 system prompt。

默认本地 skills：

- `migration_general`
- `ui_style_preservation`
- `swiftui_to_compose`
- `swiftui_to_harmonyos`
- `build_repair`

可以用 `selected_skills` 显式指定本轮要加载的 skill：

```yaml
selected_skills:
  - migration_general
  - swiftui_to_compose
```

当 `selected_skills` 非空时，Forgis 只加载这些显式配置的 skill。否则在 `auto_select_skills: true` 时，根据任务文本和未来可选的 target stack hint 做简单关键词选择：

- Android / Compose / Kotlin -> `swiftui_to_compose`
- HarmonyOS / ArkUI / 鸿蒙 -> `swiftui_to_harmonyos`
- UI / interface / 界面 / 组件 / 风格 -> `ui_style_preservation`
- build / test / repair / failure / error -> `build_repair`
- 自动选择时默认加载 `migration_general`

选中的 skill 会作为独立的 `Relevant Forgis Skills` section 进入模型上下文，不会混进用户 task prompt，也不会改变 tool 权限、dry-run 语义、命令 allowlist、build/test 配置、push 门控或 PR 门控。Forgis 只从仓库自身 `skills/` 读取 skill，拒绝路径穿越、绝对路径、secret-like skill 名称、单个 skill 超限和总内容超限；不会联网下载 skill，也不会从 source repo 或 target repo 业务目录读取 skill。

运行报告只记录 skill 名称和统计，包括 `skills_enabled`、`auto_select_skills`、`selected_skill_names`、skipped/failed skill names 和 `total_skill_chars`。报告不会写入完整 skill 内容。

v3.5 仍然不是完整 migration scheduler，不是完整 Claude Code，也不是跨语言构建适配器。具体迁移判断仍然以任务文件和实际仓库代码为准。

## Forgis v3.6 migration unit scheduler 第一阶段

Forgis v3.6 新增第一阶段轻量 migration unit scheduler。它默认关闭，不替代普通 tool loop，也不替代 `staged_translation`。

启用 `migration_scheduler_enabled: true` 后，Forgis 会根据 source inventory 路径和任务文本里显式提到的路径生成有上限的 `MigrationPlan`。每个 `MigrationUnit` 只记录安全元信息：unit id、标题、source/target virtual path、unit 类型、优先级、状态、原因、selected skill 名称、最近失败摘要、changed paths、build/test 状态。它不会保存完整源码、完整 diff 或 secret-like 内容。

scheduler 会选择一个 active unit，并只把这个 active unit 摘要注入模型上下文。模型应优先围绕该 unit 工作；如果发现 unit 阻塞，应说明原因，而不是跳到无关文件。运行时结果可以回写 active unit 的 changed paths 和 build/test 状态。v3.4 持久化报告现在会记录 migration plan summary，包括 active unit、completed/blocked/pending/deferred 计数和当前 unit 状态。

配置项：

```yaml
migration_scheduler_enabled: false
max_migration_units: 50
migration_unit_strategy: inventory
migration_unit_prioritize_ui: true
migration_unit_include_tests: true
migration_unit_include_assets: true
migration_plan_persistence_enabled: true
migration_plan_output_dir: .forgis/reports
migration_plan_filename: FORGIS_MIGRATION_PLAN.json
migration_plan_resume_enabled: false
migration_plan_required: false
migration_plan_auto_update_enabled: true
migration_plan_resume_summary_enabled: true
migration_plan_event_log_max_events: 100
migration_plan_audit_summary_enabled: true
migration_plan_audit_max_events: 10
migration_plan_auto_complete_on_success: false
migration_plan_requested_active_unit_id: ""
migration_plan_allow_switch_from_blocked: true
migration_plan_allow_switch_from_completed: false
migration_plan_allow_switch_from_deferred: true
migration_plan_switch_requires_resume: true
migration_plan_switch_reason: ""
migration_plan_requested_unit_status_unit_id: ""
migration_plan_requested_unit_status: ""
migration_plan_requested_unit_status_reason: ""
migration_plan_allow_manual_complete: true
migration_plan_allow_manual_block: true
migration_plan_allow_manual_defer: true
migration_plan_allow_manual_activate: true
migration_plan_status_update_requires_resume: true
```

`max_migration_units` 硬上限为 200。第一阶段只使用简单路径规则：UI-like 文件优先，model/service/config/asset/test 分开分类；当 inventory 不完整时，任务文本中的显式路径也可以生成 unit。v3.6 仍不是完整自动迁移调度，不做复杂规划或 RAG，也不改变工具权限。

## Forgis v3.7 持久化 MigrationPlan / Resume 基础

Forgis v3.7 会把 v3.6 的安全 `MigrationPlan` 元信息持久化为：

- `FORGIS_MIGRATION_PLAN.json`

当 `migration_scheduler_enabled: true` 时，Forgis 可以把 plan 写入安全 runtime report/artifact 目录。GitHub Actions 运行时会把 report 目录设为 `forgis-runtime/reports`，因此该文件会落在现有 `forgis-runtime/reports/**` artifact 上传范围内。plan 不会写入 source checkout、target checkout、`target_subdir`、`.git`、Desktop、Downloads、Documents 或 secret-like 路径。

配置项：

```yaml
migration_plan_persistence_enabled: true
migration_plan_output_dir: .forgis/reports
migration_plan_filename: FORGIS_MIGRATION_PLAN.json
migration_plan_resume_enabled: false
migration_plan_required: false
```

默认允许写 plan artifact，但不会自动 resume。只有显式设置 `migration_plan_resume_enabled: true`，下一次运行才会尝试读取已有 `FORGIS_MIGRATION_PLAN.json`；否则会生成新 plan。文件不存在、JSON 损坏或版本不匹配时，Forgis 会记录 load status，并安全生成新的有界 plan。写入失败默认不让主流程崩溃，除非设置 `migration_plan_required: true`。

plan JSON 只保存安全摘要：schema version、plan id、active unit id、unit 计数、unit id、标题、清洗后的 source/target virtual path、unit 类型、优先级、状态、原因、selected skill 名称、短失败摘要、changed paths、build/test 状态。它不会保存完整源码、完整 diff、完整 stdout/stderr、模型隐藏推理、secret、API key 或绝对私人路径。

v3.7 仍不是完整多 unit 自动调度器；它不会跨 run 自动执行多个 unit，不做复杂 RAG，也不替代 `staged_translation`。

## Forgis v3.8 migration plan state / resume summary 第一阶段

Forgis v3.8 让 active unit 的状态回写更清晰、更可审计，但仍不会把 scheduler 变成多 unit 自动执行器。

新增行为：

- `migration_plan_auto_update_enabled: true` 允许 Forgis 根据 runtime 证据回写 active unit 的安全摘要：changed paths、build status、test status、短失败摘要。
- `migration_plan_auto_complete_on_success: false` 是安全默认值。即使存在 target 修改且 build/test 验证通过，Forgis 默认仍保持 unit 为 `active`，并记录“验证已通过但等待显式完成”。只有显式设为 `true` 时，才允许满足证据条件后自动标记 `completed`。
- `blocked` 只能来自 runtime 证据，例如 repair 达到最大尝试次数、repair blocked、build/test rejected/timeout 或 fatal runtime failure。`deferred` 也必须有明确 reason。
- plan event log 会记录有界、脱敏事件，例如 `plan_loaded`、`plan_generated`、`active_unit_selected`、`active_unit_updated`、`unit_completed`、`unit_blocked`、`unit_deferred`、`plan_write_succeeded`、`plan_write_failed`、`resume_summary_generated`。
- 当显式启用 resume 且成功加载已有 plan 时，Forgis 会生成面向用户的 resume summary，包含 plan id、active unit id/status、各状态计数、上次 stopped reason、changed paths 摘要和建议下一步。

`tool_loop` final output 与 `FORGIS_RUN_REPORT.md` / `FORGIS_RUN_REPORT.json` 会包含 plan update status、active unit state、plan events 和 resume summary。`staged_translation` 只把 active unit id/status 作为 summary 信息记录，不让 scheduler 接管 staged micro-phase。

v3.8 仍不是完整多 unit 自动调度：不会自动执行下一个 unit，不做多 unit loop，不做复杂 RAG，也不扩大命令权限。

## Forgis v3.9 人工 active unit 切换

Forgis v3.9 新增一个安全的人工接口，用来从已 resume 的现有 plan 中明确选择 active migration unit。它仍然要求显式启用 `migration_scheduler_enabled: true`；默认还要求 `migration_plan_resume_enabled: true` 且成功加载已有 plan。

配置：

```yaml
migration_plan_requested_active_unit_id: ""
migration_plan_allow_switch_from_blocked: true
migration_plan_allow_switch_from_completed: false
migration_plan_allow_switch_from_deferred: true
migration_plan_switch_requires_resume: true
migration_plan_switch_reason: ""
```

当 `migration_plan_requested_active_unit_id` 为空时，Forgis 保持 v3.8 行为。非空时，Forgis 会校验 scheduler/resume 条件、requested id 是否存在于 `plan.units`、目标 unit 状态是否允许切换。`blocked` 和 `deferred` 默认允许切换，`completed` 默认不允许切回，除非显式设置 `migration_plan_allow_switch_from_completed: true`。

切换尝试会写入有界、脱敏的 plan events：`active_unit_switch_requested`、`active_unit_switch_succeeded`、`active_unit_switch_rejected`、`active_unit_switch_skipped`。`tool_loop` 会在切换尝试之后再注入 active unit context；成功切换时模型看到新的 active unit，切换被拒绝时保留原 active unit。`FORGIS_RUN_REPORT.md` / `FORGIS_RUN_REPORT.json` 会显示 Active Unit Switch 结果，包括 requested id、previous active id、最终 active id、status、reason/message。

v3.9 不允许模型重排 plan，不会自动执行下一个 unit，也仍然不是完整多 unit 自动调度器。`staged_translation` 只记录 active unit summary，不让 scheduler 接管 staged phase。

## Forgis v4.8 受控人工 unit 状态操作

Forgis v4.8 新增一个受控人工接口，用配置显式把某个 migration unit 标记为 `completed`、`blocked`、`deferred` 或 `active`。它仍然要求 `migration_scheduler_enabled: true`；默认还要求成功 resume 已持久化的 plan，避免误改本轮新生成的 plan。

配置：

```yaml
migration_plan_requested_unit_status_unit_id: ""
migration_plan_requested_unit_status: ""
migration_plan_requested_unit_status_reason: ""
migration_plan_allow_manual_complete: true
migration_plan_allow_manual_block: true
migration_plan_allow_manual_defer: true
migration_plan_allow_manual_activate: true
migration_plan_status_update_requires_resume: true
```

当 unit id 或 requested status 为空时，v4.8 会跳过人工状态操作。requested status 非 `completed` / `blocked` / `deferred` / `active` 时会拒绝。`completed`、`blocked`、`deferred` 必须填写非空 reason；`active` 可以使用配置 reason，也可以使用安全默认 reason。每种目标状态分别由 `migration_plan_allow_manual_*` 控制。

`tool_loop` 的顺序是：先加载或生成 plan，再处理 active unit switch，再处理 manual unit status update。把某个 unit 设为 `active` 会更新 `plan.active_unit_id`。把当前 active unit 设为 `completed`、`blocked` 或 `deferred` 时不会自动选择或执行下一个 unit；active id 保留指向该 unit，context/report 会显示它的最终状态，等待下一轮明确指示。

状态操作会写入有界、脱敏的 plan events：`unit_status_update_requested`、`unit_status_update_succeeded`、`unit_status_update_rejected`、`unit_status_update_skipped`。`FORGIS_RUN_REPORT.md` / `FORGIS_RUN_REPORT.json` 会显示 **Manual Unit Status Update**，包括 unit id、previous status、requested status、final status、result、reason/message。

v4.8 仍然不是完整多 unit 自动调度器。它不允许模型自由重写全部 unit 状态，不重排 plan，不做多 unit loop，也不会自动执行下一个 unit。`staged_translation` 仍只记录 active unit summary，不让 scheduler 驱动 staged phase。

## Forgis v4.9 人工 migration audit summary

Forgis v4.9 在 `FORGIS_RUN_REPORT.md`、`FORGIS_RUN_REPORT.json` 和 tool loop runtime outputs 中新增更紧凑的 **Migration Plan Audit Summary**。它会汇总最近的人工动作、active unit、unit 计数、最近关键 plan events，以及一条简短 suggested next action。建议只用于人工判断；Forgis 不会自动切换 unit、自动运行验证，或自动执行下一个 migration unit。

audit summary 配置：

```yaml
migration_plan_audit_summary_enabled: true
migration_plan_audit_max_events: 10
```

`migration_plan_audit_max_events` 上限为 50。audit summary 会做有界裁剪和脱敏；不会包含完整源码、完整 diff、完整日志、secret，或私人绝对路径。

可复制示例：

开启 scheduler、plan persistence 和 resume：

```yaml
migration_scheduler_enabled: true
migration_plan_resume_enabled: true
migration_plan_persistence_enabled: true
```

人工切换 active unit：

```yaml
migration_plan_requested_active_unit_id: "ui-homeview-swift"
migration_plan_switch_reason: "Continue the HomeView migration first."
```

人工标记 blocked：

```yaml
migration_plan_requested_unit_status_unit_id: "ui-homeview-swift"
migration_plan_requested_unit_status: "blocked"
migration_plan_requested_unit_status_reason: "Target platform component is missing; needs manual design decision."
```

人工标记 deferred：

```yaml
migration_plan_requested_unit_status_unit_id: "asset-icons"
migration_plan_requested_unit_status: "deferred"
migration_plan_requested_unit_status_reason: "Asset conversion will be handled after UI structure is stable."
```

人工标记 completed：

```yaml
migration_plan_requested_unit_status_unit_id: "model-userprofile"
migration_plan_requested_unit_status: "completed"
migration_plan_requested_unit_status_reason: "Implementation reviewed and build/test passed in the previous run."
```

切回 active：

```yaml
migration_plan_requested_unit_status_unit_id: "ui-homeview-swift"
migration_plan_requested_unit_status: "active"
migration_plan_requested_unit_status_reason: "Required design decision has been resolved."
```

`completed`、`blocked`、`deferred` 的 reason 必填。这些配置只影响 migration plan 状态，不扩大 `run_command`、`run_build` 或 `run_tests` 权限，不允许任意 shell，也不会自动执行下一个 unit。

## Forgis v5.0 final schema freeze 与 release checklist

Forgis v5.0 final 对 v5 report / plan 表面做版本定版，不新增运行能力。run report schema 为 `forgis.run_report.v5.0`；migration plan 写出 schema 为 `forgis.migration_plan.v5.0`。plan 读取仍兼容 `forgis.migration_plan.v4.8`、`v3.9`、`v3.8`、`v3.7`，因此旧的持久化 plan 仍可以安全 resume。

v5.0 包含：

- DeepSeek tool loop 基础
- 受 Forgis virtual path 限制的 safe file tools
- `search_text`、`git_status`、`git_diff`、`edit_file`、`apply_patch`
- `target_subdir` 内的 safe `run_command`
- 配置驱动的 `run_build` / `run_tests`
- build/test feedback summary
- limited repair loop
- repair event log
- runtime Markdown report 与 GitHub Step Summary
- 持久化 `FORGIS_RUN_REPORT.md` / `FORGIS_RUN_REPORT.json`
- 通过 `forgis-runtime/reports/**` 上传 reports-only Actions artifact
- dynamic local skills
- migration units
- migration plan persistence 与显式 resume
- manual active unit switch
- manual unit status update
- Migration Plan Audit Summary
- report fixtures / golden samples

v5.0 不包含：

- 完整 Claude Code parity
- 自动多 unit 连续执行
- 模型自由重排 plan
- 复杂 RAG
- 外部 skill 下载
- 从 source/target 业务仓库读取 skills
- 任意 shell
- 跨语言 build adapter
- UI 控制台
- Aider

report fixtures 和 golden samples 位于 `tests/fixtures/reports/`，覆盖：

- `active`
- `blocked`
- `deferred`
- `completed`

测试采用关键 JSON 字段和必要 Markdown section 标题断言，不做脆弱的 Markdown/JSON 全文逐字匹配。它们会验证 Migration Plan Audit Summary 稳定存在、recommended next action 稳定存在、active unit id 和状态计数正确、event log 受上限约束、redaction 生效，以及 report write safety 仍会拒绝 source/target checkout、`.git`、用户 Desktop/Downloads/Documents、runtime root 外路径等不安全写入位置。

Release checklist：

- 安全默认值：scheduler 默认关闭，resume 默认关闭，repair loop 默认关闭，不自动执行下一个 unit，不允许任意 shell，不扩大 command 权限，不把 report/plan 写入 source checkout、target checkout、`target_subdir` 或业务目录。
- 必须通过的测试：`python3 -m py_compile agent/*.py`、`python3 -m unittest`、`bash -n agent/create_pr.sh`、`bash -n agent/build_target.sh`、`git diff --check`。
- Report regression：active fixture、blocked fixture、deferred fixture、completed fixture、redaction、path safety、event limit、write safety。
- Actions artifact：只上传 `forgis-runtime/reports/**`。启用时该目录用于包含 `FORGIS_RUN_REPORT.md`、`FORGIS_RUN_REPORT.json`、`FORGIS_MIGRATION_PLAN.json`。v5.0 final 不上传 legacy runtime diagnostics artifacts、业务源码、完整 diff、secret、未脱敏模型输出或 target repository snapshot。
- 不属于 v5.0：完整 Claude Code parity、多 unit 自动执行、复杂 RAG、跨语言 build adapter、UI 控制台、Aider。

legacy runtime diagnostics 文件仍可在 workflow 内部本地生成，用于流程控制和日志上下文，但 v5.0 final 不把它们作为 artifact 发布。未来版本如需重新考虑上传这些文件，应先加入明确的 redaction、bounding 和回归测试。

## 文件工具列表

读工具：

- `list_dir(path)`
- `tree(path, max_depth?)`
- `read_file(path, start_line?, max_lines?)`
- `file_exists(path)`
- `search_text(query, root?, regex?, case_sensitive?, max_results?)`
- `git_status(max_entries?)`
- `git_diff(max_chars?)`

写工具：

- `mkdir(path)`
- `write_file(path, content)`
- `append_file(path, content)`
- `delete_file(path)`
- `edit_file(path, old_text, new_text, expected_replacements?)`
- `apply_patch(path, patch)`

安全命令工具：

- `run_command(command, cwd?, timeout_seconds?, max_output_chars?)`
- `run_build()`
- `run_tests()`

DeepSeek 使用 Forgis 虚拟路径：

- `task`：配置的任务提示词文件；
- `config`：`FORGIS_CONFIG.yml`；
- `source/...`：checkout 后的 source repo；
- `target/...`：checkout 后的 target repo；
- `target_subdir/...`：可写输出目录。

写工具只能修改 `target_subdir` 内部文件，不能写 source repo、target repo 根目录、workflow 文件、config 文件或 task 文件。

## 安全边界

Forgis 的边界是通用的，不依赖具体平台：

- source repo 必须保持只读；source repo 被修改是 hard fail。
- secret 泄漏到 target output 是 hard fail。
- 绝对路径、路径穿越、`.git`、symlink escape、前缀伪装会被拒绝。
- secret-like 路径会被拒绝。
- `run_log_path` 必须位于 `target_subdir` 内。
- dry run 不应改动 target。
- confirmed run 应至少产生一个非日志目标输出变更。
- `git_status` / `git_diff` 只作用于 target workspace，不能 commit。
- `run_command` 只能在 `target_subdir` 内运行，不能访问 source cwd，不能使用 shell 拼接命令，默认拒绝 rm、sudo、chmod/chown、curl/wget、ssh/scp、git commit/push 等危险命令。
- `run_build` / `run_tests` 不接受模型传入的任意命令，只读取配置里的 command array；仍然只能在 `target_subdir` 内运行，禁用 `shell=True`，并拒绝 rm、sudo、chmod/chown、curl/wget、ssh/scp、git、shell 解释器等危险命令。

这些检查是为了让模型能工作，但不能越界。

## strict_mode 说明

默认 `strict_mode=false`。此时目标侧检查更偏向 warning，便于先生成 PR，再由人工 review 判断结果是否值得继续。

在默认模式下，目标输出校验、target config/task 变更、target writable scope、dry-run target changes、`validation_commands` 失败等目标侧问题会尽量以 warning 报出。

但 source repo 被修改和 secret 泄漏仍然是 hard fail。

如果你希望自动化流程更严格，可以设置：

```yaml
strict_mode: true
```

这会恢复更严格的目标侧阻断。

## 典型使用流程

1. 在目标仓库添加 `FORGIS_CONFIG.yml` 和 `FORGIS_TASK.md`。
2. 先保持 `dry_run=true`，确认配置可解析、source/target 分支和路径正确。
3. 准备模型 API secret 和 source/target 访问 token。
4. 把任务拆小，明确只写 `target_subdir`。
5. 确认要消耗模型 API 后，设置 `dry_run=false`、`run_agent=true`、`confirm_real_run=true`。
6. 运行 workflow，只输入 `target_repo`。
7. 查看 workflow 日志、Forgis run log 和生成的 PR。
8. 由人工 review PR，继续迭代或关闭。

## 示例配置

```yaml
source_repo: owner/source-repo
source_ref: main

target_subdir: generated-output
task_prompt_path: FORGIS_TASK.md

target_branch: forgis/generated-output
target_base_branch: main
run_log_path: generated-output/FORGIS_LOG.md

agent_backend: deepseek
model: deepseek-v4-pro
api_base: https://api.deepseek.com
api_format: openai-compatible

dry_run: true
run_agent: false
confirm_real_run: false
strict_mode: false

model_env:
  DEEPSEEK_API_KEY: DEEPSEEK_API_KEY

max_iterations: 80
max_tool_result_chars: 20000
execution_mode: tool_loop
```

不需要 build/test feedback 时，不要写 `build_command` 或 `test_command`。如果确实配置 `validation_commands` 或 `success_checks`，它们会在 `target_subdir` 内执行或评估；不要在这里写入会访问外部项目、打印 secret 或破坏工作区的命令。

## 示例任务提示词

```markdown
# Task

Read `source/...` and `target/...` with Forgis file tools.

Only write files under `target_subdir/`.
Do not modify `source/...`, `config`, `task`, or workflow files.

Create a minimal, reviewable output in `target_subdir/`.
Prefer a runnable skeleton over an unfinished broad rewrite.

If the target repository includes `docs/DS_GUIDE_Swift_Kotlin.md`,
read it first and follow it as migration guidance.

When finished, return a concise final_summary with:
- changed files
- remaining gaps
- recommended next review steps
```

## 迁移类任务的推荐分阶段流程

不要期待一次真实运行完成完整迁移。更稳妥的流程是：

1. 第一轮：生成可运行骨架，确保目录、构建文件和入口结构成立。
2. 第二轮：修 build、sync、compile 和基础依赖问题。
3. 第三轮：对齐视觉和交互，处理布局、导航、弹层、手势和动画。
4. 第四轮：修状态语义、异步生命周期和运行时 bug。
5. 后续：基于真机截图、测试结果和人工 review 继续迭代。

默认 `strict_mode=false` 的目的就是让早期结果尽量进入 PR，先获得可审查的差异，再逐步收敛。

## SwiftUI 到 Compose 的迁移思想

本仓库提供了 [SwiftUI → Kotlin / Jetpack Compose 迁移指引](docs/DS_GUIDE_Swift_Kotlin.md) 作为参考入口。README 只概括核心思想：

- 逻辑层做语义翻译；
- 状态层做结构映射；
- UI 层做语义重建；
- 不要把 SwiftUI 逐行翻译成 Compose；
- 目标是保留用户感知，而不是保留源码形状。

这些思想属于任务参考材料，不是 Forgis 内置规则。Forgis 本体仍保持通用，不把 Swift/Kotlin、某个产品或某个业务项目写死进系统逻辑。

## 如何 review PR

review Forgis 生成的 PR 时，建议先看边界，再看质量：

1. 确认改动只在目标仓库允许的输出目录内。
2. 确认 source repo、config、task、workflow 和 secret 没有被修改或泄漏。
3. 查看 `FORGIS_LOG.md` 和 workflow 日志，确认运行开关、tool call 数量、changed paths 和 `final_summary`。
4. 运行目标项目自己的 build/test/sync 检查。
5. 对迁移类结果，结合截图、真机行为和人工设计判断继续迭代。

不要把模型输出直接视为可合并结果。PR 是 review 入口，不是质量保证。

## 常见失败原因

- 目标仓库缺少 `FORGIS_CONFIG.yml` 或任务提示词文件。
- `dry_run=false` 但没有 `confirm_real_run=true`。
- `run_agent=false`，所以 DeepSeek 被跳过。
- `model_env` 只配置了名字，但运行环境没有提供对应 secret。
- 任务提示词太宽，模型在 `max_iterations` 内没有收敛。
- DeepSeek 尝试写 source repo、target root、workflow、config 或 task。
- `run_log_path` 不在 `target_subdir` 内。
- `validation_commands` 在 `target_subdir` 内不可执行或依赖缺失。
- 指引文档只存在于 Forgis 发布文档中，但没有被写进目标仓库任务上下文。

## 与迁移指引文档的关系

`docs/DS_GUIDE_Swift_Kotlin.md` 是给使用者和任务提示词编写者看的迁移参考。它可以帮助你组织 `FORGIS_TASK.md`，也可以被复制或同步到目标仓库后让 DeepSeek 通过文件工具读取。

Forgis 不会自动把这份指引注入系统提示词，也不会因为仓库中存在这份文档就改变运行逻辑。这样可以避免 Forgis 被某个迁移方向绑死。

## 免责声明 / 使用建议

Forgis 是受控文件工具接口，不是魔法迁移系统。真实运行会消耗模型 API，模型可能理解错误、漏改、过度改写或生成无法运行的代码。

建议始终：

- 先 dry run；
- 使用最小可审查任务；
- 保持 source repo 只读；
- 不在 config/task/log 中写 secret；
- 让结果进入 PR；
- 由人工 review、测试和真机验证后再合并。
