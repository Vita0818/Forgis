# ForgisMac 设计语言

当前修订日期：2026-09-02

本文记录 ForgisMac 当前的视觉与交互约束。它将 Intatis 的现行 Apple-native 工作台原则适配到 Forgis，但不复制 Intatis 的品牌文案、产品身份或业务结构。

## 核心原则

1. **系统语义优先**：正文、次级文本、强调色、状态色和分隔线使用 SwiftUI / AppKit 语义资源，不维护固定 Light/Dark RGB 色板。
2. **内容层与功能层分离**：系统 window canvas 承载页面和长文本；结构化信息使用 Material；导航、composer 和操作按钮才使用 Liquid Glass。
3. **编辑感与技术感并存**：英文品牌和页面标题使用 serif；正文使用系统 sans-serif；路径、模型、endpoint、schema 等技术字段使用 monospaced。
4. **信息密集但低装饰**：不用渐变、自定义阴影、装饰性图片或自绘玻璃；图标统一使用 SF Symbols。
5. **状态不能只靠颜色**：状态同时保留文字，危险操作继续使用 destructive role。

## 表面层级

- **Window canvas**：`ForgisSystemCanvas`。当前macOS 26 target使用动态`.windowBackground`；旧availability fallback源码仍保留，但不代表shipping平台支持。
- **Sidebar**：保留 `NavigationSplitView` 的系统 sidebar 表面。选中的主导航行使用 interactive Glass；run mode与runtime status显示为两行安静文字，不单独成卡。
- **Conversation canvas**：普通 assistant 回复直接落在系统 canvas，不增加卡片。
- **Structured content**：migration detail、report、inspector、settings、system/error message 使用 `.regularMaterial + 1pt system separator + continuous rounded rectangle`。
- **Functional Glass**：composer 输入、主次操作和选中导航在当前macOS 26 target使用原生Liquid Glass；旧Material或bordered button fallback仅是保留源码。

## 字体

- Brand / large page title：30pt semibold serif。
- Section title：20pt semibold serif。
- Headline：16pt semibold system。
- Body：14pt system。
- Chat：15pt system。
- Caption：12pt system。
- Technical values：13pt monospaced。

## 主要组件

### Sidebar

- 顶部只保留 `Forgis` 品牌名。
- Migration、Reports纵向排列；Settings固定在底部。旧AI Chat入口已删除。
- 只给当前选中模式 interactive Glass，不给所有导航行套卡片。
- 只保留run mode与runtime status两行；路径集中在Settings和Inspector，不在侧栏重复。

### Migration thread

- Header使用30pt serif标题，副标题显示当前model与Intatis runtime状态；provider、host和鉴权状态不重复成卡。
- 用户消息 trailing，使用 Material 与 accent 描边。
- Intatis assistant final消息leading、无背景、无描边；commentary使用次级小号文字。
- 用户与普通 assistant 消息不再重复角色标注；system 状态仍保留明确文字。
- system/error 是结构化状态，保留 Material 与语义状态色。
- 空状态只保留一个可访问的SF Symbol和明确配置/运行说明，不伪造聊天示例。

### Composer

- session尚未创建时只显示`Validate dry run`或`Start migration`；session创建后使用单排Stop、follow-up输入和Send。模型集中在Header/Settings，消息数、安全数和鉴权标记不在composer重复。
- 控件高 40pt，图标 label 32pt，同行间距 8pt，输入圆角 20pt。
- Send与Start使用prominent Glass；Stop使用普通Glass并直接调用Intatis官方interrupt API。
- 模型由 Settings 驱动，因此不伪造 model picker。

### Migration、Report、Inspector、Settings

- 页面标题使用 `ForgisPageHeader`。
- 结构化数据使用 Material 卡片；同一主题尽量合并，路径和 schema 保持 monospaced。
- Migration主栏呈现真实Intatis thread；tool item、usage、workspace与runtime identity集中在Inspector，避免重复卡片。
- Inspector 每个 section 保持 1–2 张卡，避免重复主栏已有的 provider、report 与 safety 信息。
- 四项健康安全状态折叠为一行文字状态；异常时仍保留明确的图标、文字与语义色。
- 不允许mock运行数据或未接线按钮；空状态必须明确说明尚未配置。
- Settings的Save是prominent action；New session、Reset和credential actions使用普通Glass，Delete继续是destructive。没有provider Test按钮或HTTP旁路。

## 兼容与安全边界

- Deployment target 为macOS 26.0，以直接链接Intatis公开SwiftPM product；SwiftPM、Xcode target和生成Info.plist必须一致。
- Mac build product必须包含validated `Contents/Resources/CodexRuntime/{architecture}` root；该bundle wiring不得改变视觉层，也不得在普通App启动时自动发送turn。
- 原生 `glassEffect`、`.glass`、`.glassProminent` 必须同时受 `#if compiler(>=6.2)` 与 macOS 26 availability gate 保护。
- 视觉层不得绕过Intatis v1 session、Keychain/env credential隔离、dry-run/real-run gate、`target_subdir`或source/target只读边界，也不得添加Chat Completions/另一runtime路径。
- UI 验证不得设置真实 provider key、发送真实网络请求或执行真实 migration。

## 验证

至少运行：

```bash
swift build --scratch-path /tmp/forgis-design-language-swift-build
xcodebuild -project Forgis.xcodeproj -scheme ForgisMac -configuration Debug \
  -derivedDataPath /tmp/forgis-design-language-derived-data build CODE_SIGNING_ALLOWED=NO
git diff --check
```

运行态应人工检查Migration、Reports、Settings、sidebar selection、空状态、Start/Stop/follow-up composer、approval card、真实report详情、合并后的Inspector、单行安全状态与长技术字段截断；同时确认没有AI Chat入口、重复provider卡、消息/安全counters或mock按钮。视觉检查不得发送turn或provider请求。截图只能证明被检查的窗口尺寸和状态；不能替代Dark Mode、Increase Contrast或Reduce Transparency专项验收。
