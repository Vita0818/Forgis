# ForgisMac 设计语言

当前修订日期：2026-07-28

本文记录 ForgisMac 当前的视觉与交互约束。它将 Intatis 的现行 Apple-native 工作台原则适配到 Forgis，但不复制 Intatis 的品牌文案、产品身份或业务结构。

## 核心原则

1. **系统语义优先**：正文、次级文本、强调色、状态色和分隔线使用 SwiftUI / AppKit 语义资源，不维护固定 Light/Dark RGB 色板。
2. **内容层与功能层分离**：系统 window canvas 承载页面和长文本；结构化信息使用 Material；导航、composer 和操作按钮才使用 Liquid Glass。
3. **编辑感与技术感并存**：英文品牌和页面标题使用 serif；正文使用系统 sans-serif；路径、模型、endpoint、schema 等技术字段使用 monospaced。
4. **信息密集但低装饰**：不用渐变、自定义阴影、装饰性图片或自绘玻璃；图标统一使用 SF Symbols。
5. **状态不能只靠颜色**：状态同时保留文字，危险操作继续使用 destructive role。

## 表面层级

- **Window canvas**：`ForgisSystemCanvas`。macOS 14+ 使用动态 `.windowBackground`；macOS 13 使用 `NSVisualEffectView.Material.windowBackground`。
- **Sidebar**：保留 `NavigationSplitView` 的系统 sidebar 表面。选中的主导航行使用 interactive Glass；run mode 只显示为一行安静文字，不单独成卡。
- **Conversation canvas**：普通 assistant 回复直接落在系统 canvas，不增加卡片。
- **Structured content**：migration detail、report、inspector、settings、system/error message 使用 `.regularMaterial + 1pt system separator + continuous rounded rectangle`。
- **Functional Glass**：composer 输入、主次操作和选中导航在 macOS 26+ 使用原生 Liquid Glass；旧系统使用 Material 或 bordered button fallback。

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
- AI Chat、Migration、Reports 纵向排列；Settings 固定在底部。
- 只给当前选中模式 interactive Glass，不给所有导航行套卡片。
- 只保留一行 run mode；路径集中在 Settings 和选中 unit 详情，不在侧栏重复。

### Chat

- Header 使用 30pt serif 标题，副标题只显示当前 model；provider、host 和鉴权状态不重复成卡。
- 用户消息 trailing，使用 Material 与 accent 描边。
- 普通 assistant 消息 leading、无背景、无描边。
- 用户与普通 assistant 消息不再重复角色标注；system 状态仍保留明确文字。
- system/error 是结构化状态，保留 Material 与语义状态色。
- 空状态只保留一个可访问的 SF Symbol，不重复品牌名和起始说明。

### Composer

- 单排结构，只保留 Clear、输入和 Send；模型集中在 Header / Settings，消息数、安全数和鉴权标记不在 composer 重复。
- 控件高 40pt，图标 label 32pt，同行间距 8pt，输入圆角 20pt。
- Send 使用 prominent Glass；Clear 使用普通 Glass。
- Forgis 当前没有 cancel API，因此不伪造 Stop 控件。
- 模型由 Settings 驱动，因此不伪造 model picker。

### Migration、Report、Inspector、Settings

- 页面标题使用 `ForgisPageHeader`。
- 结构化数据使用 Material 卡片；同一主题尽量合并，路径和 schema 保持 monospaced。
- Migration 列表最多保留一个主状态；risk、validation 等次级状态在详情中使用普通信息行。
- Inspector 每个 section 保持 1–2 张卡，避免重复主栏已有的 provider、report 与 safety 信息。
- 四项健康安全状态折叠为一行文字状态；异常时仍保留明确的图标、文字与语义色。
- 未接线 mock 操作不作为常驻按钮，也不因视觉简化接入真实迁移。
- Settings 的 Save 是 prominent action；Reset、Test、key actions 使用普通 Glass，Delete 继续是 destructive。

## 兼容与安全边界

- Deployment target 保持 macOS 13.0。
- 原生 `glassEffect`、`.glass`、`.glassProminent` 必须同时受 `#if compiler(>=6.2)` 与 macOS 26 availability gate 保护。
- 视觉层不得改变非 streaming Chat Completions、Keychain/env secret 解析、dry-run/real-run gate、`target_subdir`、command allowlist 或 source/target 只读边界。
- UI 验证不得设置真实 provider key、发送真实网络请求或执行真实 migration。

## 验证

至少运行：

```bash
swift build --scratch-path /tmp/forgis-design-language-swift-build
xcodebuild -project Forgis.xcodeproj -scheme ForgisMac -configuration Debug \
  -derivedDataPath /tmp/forgis-design-language-derived-data build CODE_SIGNING_ALLOWED=NO
git diff --check
```

运行态应人工检查 AI Chat、Migration、Reports、Settings、sidebar selection、单排 composer、Migration 单主状态、合并后的 Inspector、单行安全状态与长技术字段截断；同时确认没有重复 provider 卡、消息/安全 counters 或未接线 mock 按钮。截图只能证明被检查的窗口尺寸和状态；不能替代 macOS 13 fallback、Dark Mode、Increase Contrast 或 Reduce Transparency 的专项验收。
