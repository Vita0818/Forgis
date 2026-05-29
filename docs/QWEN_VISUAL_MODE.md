# Qwen Visual Evidence Mode

最近自查日期：2026-05-29

## 模式定位

Qwen Visual Evidence Mode 是 Forgis v6.0 的可选视觉证据能力。用户确认的首选实战形态是 reference-guided migration：源 App 的参考截图由用户预先放到目标仓库，并通过 `visual_validation.reference_screenshot_dirs` 声明目录；Forgis 让 Qwen 读取这些 reference screenshots，提取视觉结构、页面层级、颜色、字体、间距、圆角、组件关系和产品气质，再把视觉反馈提供给 DeepSeek / 主 Agent 用于迁移或修正目标端代码。

当前已完成文档、短 skill、`visual_validation` 配置解析、视觉证据目录/状态 helper、可 mock 且可真实调用的 Qwen provider adapter、视觉 tool schema、`FileToolSandbox` 分发、runtime visual state/gate，以及 run report / PR body 视觉字段。当前仍不自动截图，不上传 artifacts，不支持多 provider，也不让 Qwen 成为代码 Agent。

- Qwen 是视觉理解 provider，不是代码迁移 Agent。
- 主 Agent 仍负责读源码、改代码、构建、测试和最终报告。
- Forgis 负责启用判断、reference screenshot 发现、视觉证据目录、报告字段，以及防止把 reference-only 指导伪造成 full rendered validation。

## Qwen 只负责什么

Qwen 后续只能用于截图层面的视觉理解：

- inspect configured reference screenshots。
- inspect screenshot。
- extract UI structure。
- compare reference vs actual screenshots。
- 输出视觉差异、相似度风险、布局/样式建议和需要主 Agent 修复的观察结果。

## Qwen 不得做什么

Qwen Visual Evidence Mode 不得扩大代码或环境权限：

- 不得修改文件。
- 不得读取源码。
- 不得运行命令。
- 不得替代构建、测试或人工 review。
- 不得接收 secret、token、`.env`、证书、私钥、provisioning profile、完整源码或隐私数据。
- 不得在没有有效截图时声称已完成视觉验收。
- 不得把 reference-only 视觉指导写成 full rendered visual validation。

## Reference Guidance Mode

Reference Guidance Mode 是 v6.0 的默认模式：

1. 用户把源 App 参考截图放到目标仓库，例如 `forgis-reference-screenshots/`。
2. `FORGIS_CONFIG.yml` 通过 `visual_validation.reference_screenshot_dirs` 声明这些只读目录。
3. 主 Agent 阅读任务和源/目标代码。
4. 主 Agent 调用 `list_visual_references` 发现合法 reference 图片。
5. 主 Agent 对关键 reference screenshots 调用 `inspect_visual_reference`。
6. Qwen 输出视觉结构、页面层级、颜色、字体、间距、圆角、组件关系和产品气质。
7. DeepSeek / 主 Agent 根据源码与 Qwen 视觉指导修改目标端代码。
8. build/test 仍由 DeepSeek / Forgis 执行，Qwen 不替代构建测试。
9. 如果用户也提供 actual screenshots，再调用 `inspect_visual_actual` 和 `compare_visual_screenshots`。
10. 如果没有 actual screenshots，报告必须写明这是 reference-guided migration，不是 full rendered visual parity validation。

`reference_guidance` 模式下只要求 reference screenshots；actual screenshots、模拟器、真机、窗口截图和 compare 都是可选增强。

## 配置块

建议配置形态：

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

字段规则：

- `mode` 默认 `reference_guidance`，也支持 `compare`。
- `reference_screenshot_dirs` 是目标仓库根内的只读相对目录列表；允许在 target root 下，不要求位于 `target_subdir`。
- `actual_screenshot_dirs` 默认空，仅在用户已提供目标渲染截图时使用；Forgis 不自动截图。
- `require_actual_for_full_validation=false` 表示 reference-only 可以完成 migration guidance，但报告必须写明不是 full rendered validation。
- 配置中不得放 Qwen API key、真实 token、secret、证书、截图文件路径、evidence root 或本地敏感路径。

## Provider adapter

`agent/qwen_vision.py` 是 Qwen provider adapter，不是 Agent。它只接收经过 `agent/visual_evidence.py` 校验的图片路径和简短 goal，并返回有界、脱敏、可序列化的 `QwenVisionResult`。

当前边界：

- 缺少 API key 时返回 `QWEN_PERMISSION_GATED`，不崩溃。
- 单元测试默认通过 monkeypatch/mock 替换底层 `_post_qwen_vision_payload` 或 HTTP 调用，不真实联网。
- 真实 HTTP transport 只在显式提供 `QWEN_API_KEY` 时发生；`QWEN_API_BASE` 和 `QWEN_VISION_MODEL` 可通过 runtime env 覆盖，不得写入 `FORGIS_CONFIG.yml`。
- 不把 API key、headers、base64 原图、完整 response dump 或图片 bytes 写入异常、报告或 result。
- 不支持多 provider。
- HTTP 层使用标准库实现并保持可 mock。图片 base64 只在私有 transport payload 中短暂存在，不能外泄到日志、异常、报告、PR body 或 fixture。

## Runtime 工具

模型可见视觉工具名称不包含 `run_qwen`，也不授予代码或命令权限：

- `list_visual_references`：列出 `visual_validation.reference_screenshot_dirs` 中的合法图片，返回 Forgis 虚拟路径，不返回绝对路径、图片 bytes 或 base64。
- `inspect_visual_reference`：检查 reference screenshot 并总结视觉结构。
- `inspect_visual_actual`：检查 actual rendered target screenshot 并总结可见 UI。
- `compare_visual_screenshots`：对比 reference screenshot 与 actual screenshot。

工具输入只能是 Forgis 虚拟路径，不能是绝对路径或任意本地路径。reference 优先来自目标仓库中配置的 `reference_screenshot_dirs`；actual 只能来自 `target/` 或 `target_subdir/` 中用户已提供的图片。所有路径必须指向 `.png`、`.jpg`、`.jpeg` 或 `.webp` 图片，并继续拒绝 secret-like、证书、源码、文本和配置文件。

`visual_validation.enabled=false` 时视觉工具返回 disabled blocker，不调用 provider。缺少 API key 或 provider 不可用时返回 `QWEN_PERMISSION_GATED` / `QWEN_UNAVAILABLE_IN_SESSION` blocker，不崩溃，也不得写成视觉验收成功。

## 启用场景

`visual_validation.enabled=auto` 使用确定且保守的 required 判定：显式选中 `qwen_visual_mode` skill、任一视觉工具已被调用，或已经配置 `reference_screenshot_dirs` 且任务文本包含强视觉关键词时，`required=true`。纯代码、后端、配置、构建脚本或单元测试修复默认不视觉阻塞。

强视觉关键词包括：

- 中文：UI、界面、视觉、截图、复刻、验收、布局、颜色、字体、间距、圆角、阴影、组件、质感、像不像、真机、模拟器、预览。
- 英文：UI、visual、screenshot、reference、actual、parity、layout、color、typography、spacing、radius、shadow、component、mockup、rendered、simulator、preview。

典型启用场景：

- UI 复刻。
- Apple UI parity。
- 视觉验收。
- 截图对比。
- reference screenshot。
- actual screenshot。
- 页面布局、颜色、字体、间距、圆角、阴影、组件位置、视觉层级问题。

## 默认不启用场景

下列任务默认不应启用视觉模式：

- 纯代码重构。
- 编译错误修复。
- 单元测试修复。
- 后端逻辑。
- 数据模型。
- 算法。
- 文档。
- 构建脚本。
- 权限配置。
- Git 操作。

例外：编译修复后如果需要确认 UI 是否恢复，可以进入视觉模式，但仍必须提供有效截图证据。

## Reference-first 原则

视觉模式必须先处理 reference，再处理 actual：

1. 先理解 reference screenshot。
2. 再尝试获取或检查 actual screenshot。
3. reference + actual 都存在时才允许 compare。
4. actual 不可得时仍可做 reference-only。
5. reference-only 是有效视觉迁移指导，但不能声称完成真实渲染对比。

如果只有 actual，没有 reference，只能记录 actual-only 观察结果，不得推断是否接近目标设计。

## 视觉证据目录规范

`agent/visual_evidence.py` 负责把视觉证据目录统一规划到 Forgis runtime workspace 下。该模块只处理路径、状态和摘要数据，不做视觉理解，不调用 Qwen，不读源码内容，不修改业务文件。

目录结构：

```text
<runtime_root>/visual-evidence/<run_id>/<target_repo_slug>/
├── reference/
├── actual/
└── qwen/
```

目录规则：

- 不得把截图散落在业务源码目录。
- 不得写入 source repo。
- 不得覆盖旧截图。
- 不得把无效桌面截图当作 actual app screenshot。
- 证据文件名应稳定、有界、避免 secret-like 路径或用户私有路径。
- `owner/repo` 形式的 `target_repo` 会转换为 `owner__repo`。
- runtime root 若位于 source repo、target repo、Desktop、Downloads、Documents 或 secret-like path 下，会被拒绝。
- 当前工具采用安全登记模式：报告记录 Forgis 虚拟 reference/actual 路径，并创建 evidence 目录结构；不会把截图复制进 source repo、target repo、`reference_screenshot_dirs` 或业务源码目录。

## 报告字段

v6.0 已在 `FORGIS_RUN_REPORT.md/json` 和 PR body 中写出有界、脱敏的视觉摘要。JSON 中常驻 `visual_validation` 块，核心字段对应：

- `QWEN_REQUIRED`
- `QWEN_CALLED`
- `QWEN_MODE`
- `REFERENCE_SCREENSHOT_DIRS`
- `REFERENCE_SCREENSHOTS_FOUND`
- `QWEN_VALID_VISUAL_EVIDENCE`
- `QWEN_GUIDANCE_COMPLETED`
- `QWEN_COMPARE_SCREENSHOTS_COMPLETED`
- `QWEN_FULL_RENDERED_VALIDATION`
- `REFERENCE_SCREENSHOTS_USED`
- `ACTUAL_SCREENSHOTS`
- `VISION_TOOLS_CALLED`
- `VISION_RESULT_SUMMARY`
- `ACTUAL_SCREENSHOT_BLOCKER`
- `VISUAL_VALIDATION_LIMITATIONS`
- `FIXES_FROM_QWEN_RESULT`
- `REMAINING_UI_DIFFERENCES`
- `VISUAL_GATE_STATUS`

## 视觉证据状态规划

后续视觉证据状态应使用有界枚举：

- `REFERENCE_AND_ACTUAL`
- `REFERENCE_ONLY`
- `ACTUAL_ONLY`
- `NO`

`REFERENCE_AND_ACTUAL` 才能表示已具备截图对比基础。`REFERENCE_ONLY` 在 `reference_guidance` 模式下可以表示 visual guidance completed，但仍必须在报告里说明不是 full rendered visual validation。`ACTUAL_ONLY`、`NO` 都必须在报告里说明限制。

报告规则：

- `REFERENCE_ONLY` 必须明确 `reference-guided migration` / `reference-only; not full rendered visual validation`。
- provider unavailable 必须显示 blocker。
- 没有视觉证据时不得写成 visually validated。
- reference + actual + compare 完成时可以写 compare completed，但仍应记录 remaining differences。

## 阻塞原因规划

后续阻塞原因应使用有界枚举：

- `QWEN_PERMISSION_GATED`
- `QWEN_UNAVAILABLE_IN_SESSION`
- `BLOCKED_BY_NO_EMULATOR`
- `BLOCKED_BY_DEVECO_OR_DEVICE`
- `SCREENSHOT_BLOCKED_BY_SCREEN_RECORDING`
- `HOST_ENV_BLOCKED`
- `WINDOWS_HOST_VALIDATION_PENDING`
- `NO_REFERENCE_SCREENSHOTS_FOUND`

阻塞原因不得包含 secret、绝对个人路径或大段未脱敏日志。

## 用户人工反馈优先

如果用户说 UI 仍然不像、颜色不对、布局不对、像普通 demo、组件质感差，则用户反馈优先于 Qwen 的相似判断。主 Agent 应把用户反馈视为高优先级视觉缺陷输入，并在后续修改、验证和最终报告中明确处理。

## v6.0 当前闭环

已允许的能力：

- `docs/QWEN_VISUAL_MODE.md`
- `skills/qwen_visual_mode.md`
- `FORGIS_CONFIG.yml` 中的可选 `visual_validation` 控制块解析
- 脱敏且稳定的 visual env/output 字段
- `agent/visual_evidence.py`：证据目录、状态枚举、路径校验、阻塞原因和摘要数据结构
- `agent/qwen_vision.py`：可 mock 的 Qwen provider adapter、有界 result 结构和显式 env 下的安全真实 HTTP transport
- `list_visual_references` tool schema，用于发现配置目录中的 reference screenshots
- `inspect_visual_reference`、`inspect_visual_actual`、`compare_visual_screenshots` tool schema
- `FileToolSandbox.invoke()` 的视觉工具分发
- `RuntimeController` 的视觉状态、auto required 判定和 runtime gate，区分 `guidance_completed` 与 `full_rendered_validation`
- `agent/run_report.py` / `agent/pr_body.py` 的 reference guidance / full validation 摘要字段

明确仍不实现：

- 图片上传或 visual artifact upload。
- 自动截图采集，包括模拟器、真机、adb、hdc、Windows 或 macOS window screenshot。
- 多 provider。

下一轮 Phase 8+ 才能考虑 screenshot acquisition adapters；Phase 9+ 才能考虑显式 opt-in visual artifact upload；Phase 10+ 才能考虑多 provider 抽象。仍不得引入任意 shell、业务仓库 skill loading 或模型控制 migration plan 重排。
