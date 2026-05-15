# Forgis

Forgis 是一个由 DeepSeek 驱动的受控文件交互接口。

它不是内置迁移智能的迁移器，而是一个很薄的工具壳：从目标仓库读取配置和任务提示词，在显式允许时调用 DeepSeek，并把受控文件工具交给 DeepSeek 使用。迁移策略、平台差异和具体项目规则，都应该写在任务提示词或参考文档里。

## Forgis 是什么

Forgis 本体只做三件事：

1. 从目标仓库读取 `FORGIS_CONFIG.yml` 和配置里的任务提示词文件。
2. 在 `dry_run=false`、`run_agent=true`、`confirm_real_run=true` 同时成立时，调用 DeepSeek OpenAI-compatible Chat Completions。
3. 给 DeepSeek 提供受控文件工具，让它自己读取、分析并写入目标文件。

这种设计让 Forgis 保持通用。它负责边界、工具和日志，不负责把某个平台或某个项目的迁移经验写死到系统逻辑里。

## Forgis 不是什么

Forgis 不是平台迁移器，不是 Android、iOS、Web 或任何单一技术栈专用工具，也不是内置项目理解系统、脚手架生成器或自动保证迁移成功的工具。

它不会预加载 source repo 内容，不会把 `FORGIS_TASK.md` 改写成更大的策略提示词，也不会替人工 review 做最终判断。真实运行的结果应该进入 PR，由人检查、修正和合并。

## 核心工作流

主 workflow 的手动输入只有一个：

```text
target_repo: owner/target-repo
```

其它配置都来自目标仓库根目录的 `FORGIS_CONFIG.yml`。Forgis 会按配置 checkout source repo 和 target repo，解析任务提示词，必要时运行 DeepSeek tool loop，然后在符合条件时向 target repo 推送分支并创建 PR。

## 仓库和文件布局

典型目标仓库需要包含：

```text
FORGIS_CONFIG.yml
FORGIS_TASK.md
target-output/
```

其中：

- `FORGIS_CONFIG.yml`：运行配置，固定放在目标仓库根目录。
- `FORGIS_TASK.md`：给 DeepSeek 的任务提示词，路径由 `task_prompt_path` 指定，默认在目标仓库根目录。
- `target-output/`：默认可写输出目录，对应 `target_subdir`。
- `target-output/FORGIS_LOG.md`：默认长期运行日志，对应 `run_log_path`。

Forgis 自身的 `docs/` 和 `guides/` 目录用于发布说明和参考材料，不会自动变成 DeepSeek 的内置规则。

## FORGIS_CONFIG.yml 配置说明

`FORGIS_CONFIG.yml` 必须是非空 YAML mapping。当前支持的配置都是通用的 DeepSeek/file-tool 设置；未知字段会失败。

必填项：

- `source_repo`
- `target_branch`
- workflow 输入 `target_repo`

常用字段：

```yaml
source_repo: owner/source-repo
source_ref: main

target_subdir: target-output
task_prompt_path: FORGIS_TASK.md

agent_backend: deepseek
model: deepseek/deepseek-v4-pro
api_base: https://api.deepseek.com
api_format: openai-compatible

target_branch: forgis/output
target_base_branch: main
run_log_path: target-output/FORGIS_LOG.md

dry_run: true
run_agent: false
confirm_real_run: false
strict_mode: false

model_env:
  DEEPSEEK_API_KEY: DEEPSEEK_API_KEY

max_iterations: 80
max_tool_result_chars: 20000

validation_commands: []
success_checks: []
```

`agent_backend` 当前只支持 `deepseek`，`api_format` 当前只支持 `openai-compatible`。`model_env` 只声明环境变量名映射，不应该包含任何 secret 值。

## FORGIS_TASK.md 任务提示词说明

任务提示词是 DeepSeek 执行工作的核心输入。Forgis 不内置迁移策略，所以任务提示词需要写清楚：

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

只有下面三个开关同时成立，才会真实调用 DeepSeek：

```yaml
dry_run: false
run_agent: true
confirm_real_run: true
```

真实运行会消耗模型 API 额度。`dry_run=false` 但缺少 `confirm_real_run=true` 会直接失败；`run_agent=false` 会跳过 DeepSeek。

## DeepSeek tool loop 和实时日志

真实运行时，Forgis 会把任务交给 DeepSeek，并允许它通过工具逐步读取和写入文件。日志会显示：

- iteration 进度；
- tool call 名称和安全处理后的路径；
- read/write 计数；
- tool result 是否被截断；
- changed paths 数量；
- 写工具成功后的 changed path；
- 最终 `final_summary` 是否收到。

日志不能显示 secret 值、`reasoning_content`、大段源码、完整工具结果或写入内容。工具结果会按 `max_tool_result_chars` 限制截断，较大的文件应让 DeepSeek 使用 `start_line` 和 `max_lines` 分页读取。

## 文件工具列表

读工具：

- `list_dir(path)`
- `tree(path, max_depth?)`
- `read_file(path, start_line?, max_lines?)`
- `file_exists(path)`

写工具：

- `mkdir(path)`
- `write_file(path, content)`
- `append_file(path, content)`
- `delete_file(path)`

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
model: deepseek/deepseek-v4-pro
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

validation_commands:
  - "./gradlew test"

success_checks:
  - path_exists: "build.gradle.kts"
```

`validation_commands` 和 `success_checks` 在 `target_subdir` 内执行或评估。不要在这里写入会访问外部项目、打印 secret 或破坏工作区的命令。

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
