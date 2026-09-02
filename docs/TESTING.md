# 构建与测试说明

## 外部依赖与禁止兜底验证（Vitemis 强制规则）

本项目继承 `/Users/vita/Vitemis/docs/DEPENDENCY_POLICY.md`。涉及外部能力的变更必须验证：

- exact 外部依赖可用时只调用其官方 API/扩展点，不调用第一方重复实现。
- 依赖缺失、版本不兼容或构建/签名/许可证/平台/安全条件不成立时，产生明确、可诊断失败并停止该能力。
- 失败路径不会切换到 legacy、另一 provider/backend、adapter/shim、cache、mock、简化实现或不完整路径。
- 测试 double 只存在于测试 target，不进入 production selection 或 runtime fallback。
- Review 检查新增 wrapper/adapter/facade 是否仅为官方 API 必需的最薄接线；发现核心能力复制、第二实现或静默降级即判定失败。

最近自查日期：2026-09-02

## 环境要求

- Python 3.11：GitHub Actions workflow 使用 `actions/setup-python@v5` 且 `python-version: "3.11"`。
- 全量内核切换：Xcode 27 / Swift 6.4、macOS 26、只读同级checkout `../Intatis`，以及exact runtime kit `../Intatis/.intatis/runtime-kit/0.66/CodexRuntime/{architecture}`。workflow使用官方`xcode-27` runner并固定Intatis commit。
- Python 依赖：`requirements.txt` 当前只有 `PyYAML>=6.0.2`。
- Shell：`agent/build_target.sh` 和 `agent/create_pr.sh` 使用 bash。
- Git/GitHub CLI：真实 PR 创建路径依赖 `git` 和 `gh`，在 `agent/create_pr.sh` 中使用。
- GitHub Actions secrets：真实运行依赖 `FORGIS_TARGET_TOKEN`、`FORGIS_SOURCE_TOKEN` 和模型 secret 环境变量。不要在文档或配置中写入真实值。
- 所有runtime/UI测试默认离线，不真实调用任何provider。Python legacy client测试只使用mock HTTP。CLI credential只能通过`model_env`指向环境变量名；Mac UI Responses credential只能通过Forgis identity派生的Keychain或显式env fallback解析，UserDefaults只保存非secret workspace/route/gate偏好。异常、projection、operation log、报告和fixture不得包含secret、Authorization header、raw provider response或完整模型输出。
- v6.0 视觉闭环测试不需要真实 Qwen API key。`visual_validation` 配置不得包含真实 token、API key、截图文件路径、evidence root 或本地敏感路径；`reference_screenshot_dirs` / `actual_screenshot_dirs` 只能是目标仓库相对目录。`agent/qwen_vision.py` 的 provider transport 在测试中必须 mock。真实 Qwen 调用只允许在运行时显式提供 `QWEN_API_KEY`，可选 `QWEN_API_BASE` 和 `QWEN_VISION_MODEL`，这些值不得写入报告。

## 依赖安装方式

Forgis不复制或修改Intatis源码。SwiftPM与Xcode都通过本地path `../Intatis`解析公开
Core/Protocol/Providers/CodexRuntime products；根`Package.resolved`与
`Forgis.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved`分别固定两个构建入口解析到的
远程传递依赖。本地Intatis path本身不会进入锁文件，构建与验证不得写入Intatis checkout。

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

Swift production kernel构建使用仓库外scratch目录：

```bash
swift build --product forgis-runtime --scratch-path /tmp/forgis-intatis-swift-build
```

随后只允许以下零网络验证：

```bash
export FORGIS_RUNTIME_EXECUTABLE=/tmp/forgis-intatis-swift-build/debug/forgis-runtime
export FORGIS_CODEX_RUNTIME=/Users/vita/Vitemis/Intatis/.intatis/runtime-kit/0.66/CodexRuntime/arm64/codex

"$FORGIS_RUNTIME_EXECUTABLE" doctor --codex-runtime "$FORGIS_CODEX_RUNTIME"
"$FORGIS_RUNTIME_EXECUTABLE" smoke --codex-runtime "$FORGIS_CODEX_RUNTIME"
```

smoke只执行App Server initialize/thread-start/shutdown，不发送turn，输出必须含`network_requests: 0`。

## 单元测试命令

当前Python控制面/legacy fixture suite在先构建Swift host并设置上述两个非secret executable path后运行：

```bash
python -m unittest
```

当前基线为172 tests；其中`test_codex_runtime_cutover.py`真实运行exact doctor与offline session smoke，但不发送turn或provider请求。

`RELEASE_NOTES.md` 的 release checklist 写的是：

```bash
python3 -m unittest
```

两者都来自项目文件。若需要最接近当前 v7.1 验证，请优先运行 `python -m unittest tests/test_openai_compatible_client.py tests/test_v7_cli_config.py tests/test_v7_local_cli.py tests/test_v7_local_smoke.py tests/test_v7_local_init_status.py tests/test_v7_local_migration_flow.py tests/test_v7_validation_commands.py tests/test_forgis_config.py`，发布前再运行完整 `python -m unittest`。

v7.0 第一阶段的新增测试点：

- `tests/test_openai_compatible_client.py` 覆盖 Chat Completions request schema、base URL 拼接、model/tools/tool_choice、timeout、HTTP error 脱敏、invalid JSON、missing choices、malformed message/tool_calls、API key 不出现在异常或 repr、DeepSeek shim 兼容。
- `tests/test_v7_cli_config.py` 覆盖 `agent_backend: deepseek` 兼容、`agent_backend: openai-compatible` alias、`base_url` alias、`request_timeout_seconds`、env var 缺失错误只显示 env 名、CLI help/dry-run、command allowlist 未放宽、`validation_commands` 没被改成 shell bypass。
- `tests/test_v7_local_cli.py` 覆盖 `python -m agent.cli help`、`doctor`、`run --config`、summary output、外部 config 解析、缺少 API key 错误脱敏、examples config 解析、DeepSeek shim 兼容。
- `tests/test_v7_local_smoke.py` 覆盖 `python -m agent.cli smoke --workdir ...` 的本地 dry-run 闭环，不需要 API key、不调用 API、不写 target。
- `tests/test_v7_local_init_status.py` 覆盖 `init` 生成最小 local config、`init` 不写 source/target、`status` 读取 local config、API key env 只显示 set/unset 且不泄露 secret。
- `tests/test_v7_local_migration_flow.py` 覆盖 `run --unit` 只选择指定 unit、dry-run 不调用 API/不写 target、summary output 有界脱敏、local run 不依赖 `$GITHUB_ENV` / `$GITHUB_OUTPUT`、`resume` active/failed/pending/no-task 处理、examples fixture smoke。
- `tests/test_v7_validation_commands.py` 覆盖 `validation_commands` argv 配置解析、allowlist 执行、`bash -lc` argv bypass 拒绝、旧 shell 字符串 warning、DeepSeek/openai-compatible/Qwen 配置兼容。
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

python -m agent.cli init \
  --source /path/to/source \
  --target /path/to/target \
  --target-repo local/my-migration \
  --output /tmp/FORGIS_CONFIG.local.yml

python -m agent.cli status --config /tmp/FORGIS_CONFIG.local.yml

python -m agent.cli run \
  --config /tmp/FORGIS_CONFIG.local.yml \
  --unit "<unit-id>" \
  --summary-output /tmp/forgis-summary.md

python -m agent.cli resume --config /tmp/FORGIS_CONFIG.local.yml
```

该命令仍受 `FORGIS_CONFIG.yml` 的 dry-run/real-run gate 约束，不应写 source，不应绕过 `target_subdir`。

真实 OpenAI-compatible 本地运行只应由用户手动设置 env 后执行，测试不得运行：

```bash
export FORGIS_MODEL_API_KEY="..."
python -m agent.cli run \
  --config /path/to/FORGIS_CONFIG.local.yml \
  --unit "<unit-id>" \
  --summary-output /tmp/forgis-summary.md
```

本轮未运行该 smoke test。

## UI 测试命令

Mac Intatis Migration UI可用Xcode project或SwiftPM构建：

```bash
xcodebuild -list -project Forgis.xcodeproj
xcodebuild -project Forgis.xcodeproj -scheme ForgisMac -configuration Debug build
swift build --product ForgisMac \
  --scratch-path /tmp/forgis-ui-swift-build \
  --disable-automatic-resolution
```

用独立DerivedData验证主工程、runtime root静态校验和bundle接线：

```bash
xcodebuild -project Forgis.xcodeproj -scheme ForgisMac \
  -configuration Debug \
  -derivedDataPath /tmp/forgis-intatis-derived-data \
  CODE_SIGNING_ALLOWED=NO build
```

成功图应显示ForgisMac直接依赖`IntatisCore` / `IntatisProtocol` / `IntatisProviders` /
`IntatisCodexRuntime` products；不应出现Forgis自建App Server wrapper或HTTP Chat target。构建不得启动
turn、读取credential或修改Intatis源码。

构建后运行Mac bundle离线smoke：

```bash
/tmp/forgis-intatis-derived-data/Build/Products/Debug/ForgisMac.app/Contents/MacOS/ForgisMac \
  --forgis-codex-runtime-smoke
```

预期：`FORGIS_CODEX_RUNTIME_SMOKE_OK ... network_requests=0`。

建议本地构建把 DerivedData 放在 `/tmp`，避免污染默认 DerivedData：

```bash
xcodebuild -project Forgis.xcodeproj -scheme ForgisMac -configuration Debug -derivedDataPath /tmp/forgis-v7-3-derived-data build
```

不存在`--forgis-chat-smoke`或任何HTTP provider smoke。UI/runtime验证必须确认：

- 普通App启动停在Migration未配置态，不自动启动session或发送turn；
- Settings真实展示source/target/task/write root、native Responses route、Keychain/env状态与三重gate；
- Reports只展示实际持久化的`forgis.run_report.v7.0`，没有mock report；
- dry run不启动Intatis、不解析credential、不创建`target_subdir`，只写Application Support下的skipped report；
- real run只有`dry_run=false`、`run_agent=true`、`confirm_real_run=true`同时成立后才能Start；
- event stream能投影assistant/tool/approval/usage，Stop调用official interrupt，follow-up复用同一session；
- Chat Completions URL明确失败，且失败不会选择旧client、Python loop、mock或另一backend。

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
- Codex model config：固定`agent_backend=codex-app-server`/`api_format=responses`、request adapter、`api_base` / `base_url`、model、单一`model_env`引用；历史backend值只验证归一化，不得触发旧runtime。
- Mac Intatis UI：缺少Keychain/env credential且auth required时不启动turn并显示blocker；auth disabled时允许用户显式配置的无鉴权Responses endpoint；credential、provider/runtime错误、projection和report都必须有界脱敏；不得写source、target root、task、UserDefaults secret或fixture。
- ForgisMac视觉：Migration/Reports/Settings主导航可切换；system canvas与Material层级连续；sidebar只有品牌、导航、run mode/runtime status与Settings；assistant final无卡片、commentary为次级文字、user/system/error有边界；session前显示Start/Validate，session后为Stop/input/Send单排composer；approval card、runtime/tool/usage inspector和真实report详情不溢出；不存在AI Chat入口、重复provider卡、counters、mock unit/report或未接线按钮。视觉检查不得设置真实credential、发送turn或执行migration。
- Codex kernel cutover：Swift CLI与Mac bundle都直接构造`CodexAppServerSession`；doctor验证exact version/derivation，offline smoke验证真实process/session且零network；workflow无Python tool-loop调用；Python real loop无test client时明确拒绝；dry-run不读credential、不启动runtime、不写target。
- Local v7.1 flow：`init` 只写显式 output，`status` 不泄露 secret，`run --unit` 不自动 all-units，dry-run 不调用 API/不写 target，`resume` 默认不跳过 blocked/failed unit。
- Validation commands：新配置使用 argv mapping 并复用 allowlist；旧 shell string 只兼容 warning；新增测试覆盖 shell bypass 不被 argv 接受。
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

2026-09-01全量内核切换实际运行：

- `swift build --product forgis-runtime --scratch-path /tmp/forgis-runtime-cutover-build`：通过。
- `forgis-runtime doctor --codex-runtime <exact .4 binary>`：通过，version/derivation匹配。
- `forgis-runtime smoke --codex-runtime <exact .4 binary>`：通过，`network_requests=0`。
- ForgisMac Debug Xcode build（仓库外DerivedData）：通过；官方validator确认embedded arm64 root。
- ForgisMac `--forgis-codex-runtime-smoke`：通过，`network_requests=0`。
- embedded/source Codex binary SHA-256一致：`9d5d81ef622f5bf7bc288837f2cd825fdd686dfe770109a0e9218cd087c90c74`。
- `python3 -m py_compile agent/*.py`：通过。
- `python3 -m unittest`：172 tests通过；测试环境只传executable路径，不传真实credential。
- `bash -n agent/build_target.sh` / `bash -n agent/create_pr.sh`：通过。
- 两个workflow YAML解析、Xcode project plist语法与`git diff --check`：通过。
- 未发送真实turn，未调用OpenAI/Qwen/第三方provider API。

2026-09-02 Mac UI全量切换实际运行：

- `swift build --product ForgisMac --scratch-path /tmp/forgis-ui-cutover-swift-build --disable-automatic-resolution`：通过。
- Xcode Debug bundle build（`/tmp/forgis-ui-cutover-derived-data`、`CODE_SIGNING_ALLOWED=NO`）：通过；官方validator确认embedded arm64 runtime root。
- bundle `--forgis-codex-runtime-smoke`：通过，`version=0.145.0-intatis.4 network_requests=0`。
- `forgis-runtime doctor`与offline smoke：通过；host API v1、version/derivation匹配，`network_requests=0`。
- `python3 -m unittest`：172 tests通过；只使用test client/mock HTTP和offline runtime smoke。
- `python3 -m py_compile agent/*.py`、两份shell语法、workflow YAML：通过。
- 运行态只读视觉核对Migration、Settings、Reports与Inspector：通过；没有AI Chat、mock数据或provider Test入口。
- `plutil -lint Forgis.xcodeproj/project.pbxproj`与范围内`git diff --check`：通过。
- 未设置credential、未发送turn、未调用任何provider API、未修改Intatis源仓库。
