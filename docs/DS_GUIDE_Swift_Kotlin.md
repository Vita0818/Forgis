# SwiftUI → Kotlin / Jetpack Compose 迁移风险与策略文档

## 1. 核心结论

SwiftUI 到 Kotlin / Jetpack Compose 的迁移，不应该被理解为“代码语法翻译”。

更准确的原则是：

> **逻辑层做语义翻译，状态层做结构映射，UI 层做语义重建。**

也就是说：

- Model / 数据结构：尽量保留 Swift 原本的运行时语义。
- ViewModel / 状态层：迁移为 Android / Compose 可观察、可重组、可持久化的状态体系。
- UI / 页面层：不能逐行翻译 SwiftUI，而应从 SwiftUI 中提取视觉结构、交互关系和产品气质，再用 Compose 原生方式重建。

对于 Forgis 这类自动迁移工具，最危险的不是“编译不过”，而是：

> **编译通过，但运行时语义、状态更新、界面体验悄悄变了。**

---

## 2. 为什么迁移后界面差距会很大？

SwiftUI 和 Jetpack Compose 都是声明式 UI，但它们并不是一一对应的系统。

界面差异通常来自以下几个原因。

### 2.1 声明式框架也无法直接互译

一些简单结构可以相对直观地对应：

```swift
VStack(spacing: 8) {
    Text("Hello")
}
```

大致可以迁移为：

```kotlin
Column(
    verticalArrangement = Arrangement.spacedBy(8.dp)
) {
    Text("Hello")
}
```

但复杂 UI 并不适合这样逐行对应，例如：

- `GeometryReader`
- `LazyVGrid`
- `matchedGeometryEffect`
- 自定义 `ViewModifier`
- 自定义动画
- 手势组合
- `overlay` / `background` / `alignmentGuide`
- 安全区与窗口尺寸适配

这些在 Compose 中通常需要重新组织布局和状态，而不是机械替换 API 名称。

---

### 2.2 平台组件和导航系统不同

SwiftUI 中常见的：

- `NavigationStack`
- `NavigationLink`
- `.sheet`
- `.alert`
- `TabView`
- `List`

在 Android / Compose 中通常会对应到：

- `NavHost`
- `NavController.navigate(...)`
- `ModalBottomSheet`
- `AlertDialog`
- `NavigationBar`
- `LazyColumn`

它们的返回栈、转场、生命周期、系统手势、默认样式都不同。

如果 AI 只做 API 名称替换，最后很容易出现：

- 页面能打开，但返回逻辑错乱。
- 弹窗行为不对。
- 列表滚动区域不对。
- 状态在页面切换后丢失。
- 按钮样式和平台默认风格冲突。
- 整体视觉变成普通 Material App，而不是原产品。

---

### 2.3 模型无法真正“看见”原始界面

只给模型 SwiftUI 源码时，它看到的是代码文本，而不是渲染后的界面。

如果原 App 的视觉效果依赖：

- 自定义颜色系统
- 字体体系
- 图片资源尺寸
- 透明度
- 阴影
- 圆角
- 复杂布局计算
- 动画节奏
- 卡片层级
- 资产文件

那么模型很可能只能猜出大概结构，无法自然复刻最终视觉。

因此 UI 迁移需要额外要求模型先提取：

- 页面目的
- 视觉层级
- 设计 token
- 交互行为
- 状态来源
- 导航关系
- 可复用组件

再重建 Compose 页面。

---

### 2.4 状态系统差异会直接导致 UI 行为错误

SwiftUI 使用：

- `@State`
- `@Binding`
- `@ObservedObject`
- `@StateObject`
- `@EnvironmentObject`
- `@Published`
- `ObservableObject`

Compose / Android 侧通常需要：

- `remember`
- `mutableStateOf`
- `ViewModel`
- `StateFlow`
- `LiveData`
- `collectAsState`
- `rememberSaveable`

如果把 SwiftUI 状态机械翻译成普通 Kotlin 变量：

```kotlin
var selectedIndex = 0
```

Compose 不一定会自动重组，UI 可能不会更新。

更合理的 Compose 写法可能是：

```kotlin
var selectedIndex by remember { mutableStateOf(0) }
```

或者在 ViewModel 中：

```kotlin
private val _uiState = MutableStateFlow(KikariaUiState())
val uiState: StateFlow<KikariaUiState> = _uiState
```

Compose 侧收集：

```kotlin
val state by viewModel.uiState.collectAsState()
```

---

## 3. Swift → Kotlin 高危语义陷阱

以下问题按迁移危险性整理。重点关注那些“能编译但语义变了”的问题。

---

### 3.1 SwiftUI 状态系统被翻译成普通 Kotlin 变量

**严重度：致命**  
**频率：极高**

SwiftUI 的 UI 状态不能直接变成普通 `var`。

错误方向：

```kotlin
var currentPreset = defaultPreset
var isShowingAnswer = false
var selectedItems = listOf<Item>()
```

这种代码可能可以编译，但 Compose 不一定会在状态变化时重组 UI。

正确方向应根据状态作用域选择：

```kotlin
var isShowingAnswer by remember { mutableStateOf(false) }
```

或：

```kotlin
data class ReviewUiState(
    val currentPreset: Preset,
    val isShowingAnswer: Boolean,
    val selectedItems: List<Item>
)
```

ViewModel 暴露：

```kotlin
val uiState: StateFlow<ReviewUiState>
```

Compose 页面收集：

```kotlin
val state by viewModel.uiState.collectAsState()
```

#### 迁移规则

```text
SwiftUI state must be mapped to Compose-observable state.
Do not translate @State, @Binding, @ObservedObject, @StateObject, @EnvironmentObject, @Published, or ObservableObject into ordinary Kotlin vars.
```

---

### 3.2 Swift struct 值语义与 Kotlin data class 引用语义混淆

**严重度：致命**  
**频率：极高**

Swift 的 `struct` 是值类型，赋值即拷贝。

Swift 示例：

```swift
struct Point {
    var x: Int
}

var a = Point(x: 1)
var b = a
b.x = 2
// a.x 仍然是 1
```

错误 Kotlin 迁移：

```kotlin
data class Point(var x: Int)

val a = Point(1)
val b = a
b.x = 2
// a.x 也变成 2
```

这会造成共享可变对象，改变原本的运行时语义。

更安全的 Kotlin 方向：

```kotlin
data class Point(
    val x: Int
)

val a = Point(1)
val b = a.copy(x = 2)
```

#### 迁移规则

```text
Swift struct should generally become immutable Kotlin data class with val fields.
Mutation should use copy(...), unless shared mutable reference semantics are explicitly intended.
Avoid data class(var ...) for Swift value types.
```

---

### 3.3 Optional / guard let 控制流丢失

**严重度：致命**  
**频率：极高**

Swift 中：

```swift
guard let user = currentUser else {
    return
}

// use user
```

正确 Kotlin 方向：

```kotlin
val user = currentUser ?: return
```

危险迁移：

```kotlin
if (currentUser != null) {
    // use currentUser
}
// 后续代码仍然继续执行
```

或者：

```kotlin
val user = currentUser!!
```

这可能导致：

- 空指针崩溃
- 错误状态下继续执行
- 原本的快速失败语义丢失

#### 迁移规则

```text
guard let / if let / optional chaining must preserve control flow.
Use Elvis return/throw or explicit early exit.
Do not use !! to hide nullability problems.
```

---

### 3.4 闭包、async/await 与协程生命周期差异

**严重度：严重**  
**频率：中高**

Swift 中常见：

```swift
Task {
    await loadData()
}
```

或：

```swift
someAsyncCall { [weak self] result in
    self?.handle(result)
}
```

Kotlin / Android 侧不能随意使用：

```kotlin
GlobalScope.launch {
    loadData()
}
```

危险点包括：

- 协程生命周期不受控。
- 页面销毁后任务继续运行。
- UI 更新发生在错误线程或错误状态域。
- 原本通过 `[weak self]` 避免的生命周期问题被忽略。
- 异步回调与 Compose 重组机制冲突。

更合理方向通常是：

```kotlin
viewModelScope.launch {
    loadData()
}
```

或者在 Compose 中使用：

```kotlin
LaunchedEffect(key1) {
    loadData()
}
```

#### 迁移规则

```text
Swift async/await, closures, and @MainActor behavior must be mapped to lifecycle-aware Kotlin coroutines.
Avoid GlobalScope.
Use ViewModel scope, lifecycle-aware collection, or Compose side-effect APIs.
```

---

### 3.5 Protocol / Extension 默认实现被弱化

**严重度：严重**  
**频率：中**

Swift 的 protocol extension 可以提供默认实现，并参与面向协议编程。

Swift 示例：

```swift
protocol Trackable {
    var id: String { get }
    func track()
}

extension Trackable {
    func track() {
        print(id)
    }
}
```

Kotlin 中要注意：

- `interface` 可以有默认方法。
- 但 Kotlin extension function 是静态派发，不能替代需要动态分派的协议默认行为。
- Swift protocol 的组合约束也不能随意简化。

危险迁移：

```kotlin
fun Trackable.track() {
    println(id)
}
```

这可能不是等价多态行为。

更安全方向：

```kotlin
interface Trackable {
    val id: String

    fun track() {
        println(id)
    }
}
```

#### 迁移规则

```text
Do not replace Swift protocol default implementations with Kotlin extension functions if dynamic dispatch is required.
Prefer Kotlin interface default methods or abstract base classes when preserving polymorphic behavior.
```

---

### 3.6 Enum associated values 与状态机丢失

**严重度：中高**  
**频率：中**

Swift 枚举可以携带关联值：

```swift
enum LoadState {
    case idle
    case loading
    case success([Item])
    case failed(Error)
}
```

不能简单翻译成：

```kotlin
enum class LoadState {
    Idle,
    Loading,
    Success,
    Failed
}
```

这样会丢失 `success` 携带的数据和 `failed` 的错误信息。

正确方向通常是 sealed class / sealed interface：

```kotlin
sealed interface LoadState {
    data object Idle : LoadState
    data object Loading : LoadState
    data class Success(val items: List<Item>) : LoadState
    data class Failed(val error: Throwable) : LoadState
}
```

#### 迁移规则

```text
Swift enums with associated values should become Kotlin sealed class or sealed interface.
Do not simplify them into enum class if associated data exists.
Preserve exhaustive state handling.
```

---

### 3.7 错误处理机制不当转换

**严重度：严重**  
**频率：中高**

Swift 中：

- `throws`
- `try`
- `try?`
- `try!`
- `catch`

语义不同。

例如：

```swift
let value = try? parse(input)
```

这表示失败时返回 `nil`。

不能简单迁移成：

```kotlin
val value = parse(input)
```

也不能粗暴吞掉异常而不记录：

```kotlin
val value = try {
    parse(input)
} catch (e: Exception) {
    null
}
```

除非这确实对应原 Swift 的 `try?` 语义。

业务错误更适合用：

```kotlin
sealed interface ParseResult {
    data class Success(val value: Value) : ParseResult
    data class Failed(val reason: String) : ParseResult
}
```

或 Kotlin `Result<T>`。

#### 迁移规则

```text
Preserve the difference between throws, try, try?, and try!.
Use Result or sealed classes for recoverable business errors when appropriate.
Do not silently swallow errors unless Swift source explicitly does so.
```

---

### 3.8 Property observer / lazy 初始化语义差异

**严重度：中**  
**频率：中低**

Swift：

```swift
var value: Int = 0 {
    didSet {
        update()
    }
}
```

Kotlin 可以用：

```kotlin
var value: Int by Delegates.observable(0) { _, old, new ->
    update()
}
```

但两者触发时机不完全一样。

此外：

- Swift `lazy` 与 Kotlin `by lazy` 的线程安全默认行为不同。
- `didSet` 在 Swift 初始化阶段不触发。
- Kotlin 委托属性可能在不同阶段触发副作用。

#### 迁移规则

```text
Property observers and lazy initialization must be reviewed manually.
Do not blindly replace didSet/willSet with Delegates.observable without checking initialization and side-effect timing.
```

---

## 4. UI 迁移原则：不是翻译，而是重建

UI 层最重要的原则：

> **Do not mechanically translate SwiftUI code line by line into Jetpack Compose.**

也就是：

```text
SwiftUI → Compose is not syntax translation.
It is UI semantic reconstruction.
```

---

### 4.1 UI 迁移前必须先提取意图

每个 SwiftUI 页面迁移前，AI 应先提取：

1. 页面用途
2. 视觉层级
3. 主要组件
4. 状态输入
5. 状态输出
6. 导航行为
7. 手势和交互
8. 字体
9. 颜色
10. 间距
11. 圆角
12. 阴影
13. 透明度
14. 加载状态
15. 空状态
16. 错误状态

然后再写 Compose。

---

### 4.2 UI 迁移不应该保留源码形状，而应该保留用户感知

错误目标：

```text
让 Compose 代码结构尽量像 SwiftUI 源码。
```

正确目标：

```text
让 Android 用户看到和使用时，感受到同一个产品。
```

这意味着：

- 可以改变代码结构。
- 可以重组组件层级。
- 可以使用 Compose 原生写法。
- 可以拆分组件。
- 可以引入 ViewModel。
- 可以调整导航实现。
- 但不能丢失原产品的视觉身份和交互逻辑。

---

## 5. 适用于 Kikaria / Forgis 的 UI 迁移要求

对于 Kikaria 这类产品，UI 不能退化成普通 Material 风格。

迁移时应保留：

- 柔和浅蓝色调
- 玻璃感
- 轻盈、通透、高级的视觉气质
- 精装书式中文排版气质
- 中文字体与英文 / 数字字体分离
- 数字尽量保持 serif 风格
- 首页气泡结构
- 卡片层级
- 柔和阴影
- 克制的动效
- 极简界面
- 避免非必要元素
- 避免默认 Material 味过重

---

## 6. 推荐的 Forgis 迁移分层策略

### 6.1 第一层：Model / 数据结构

目标：

```text
严格保留运行时语义。
```

重点：

- Swift `struct` → Kotlin immutable `data class`
- Swift associated-value enum → Kotlin sealed class / sealed interface
- Swift optional → Kotlin nullable type
- Swift value mutation → Kotlin `copy(...)`
- 避免共享可变状态

示例：

```swift
struct KnowledgeItem {
    var name: String
    var hint: String
    var content: String
}
```

更合理的 Kotlin：

```kotlin
data class KnowledgeItem(
    val name: String,
    val hint: String,
    val content: String
)
```

修改时：

```kotlin
val updated = item.copy(name = newName)
```

---

### 6.2 第二层：ViewModel / 状态层

目标：

```text
把 SwiftUI 状态迁移为 Compose 可观察状态。
```

SwiftUI 中：

```swift
@Published var currentPreset: Preset
@Published var masteredItems: [KnowledgeItem]
@Published var favoriteItems: [KnowledgeItem]
```

Android 侧可以整理为：

```kotlin
data class KikariaUiState(
    val currentPreset: Preset,
    val masteredItems: List<KnowledgeItem>,
    val favoriteItems: List<KnowledgeItem>
)
```

ViewModel：

```kotlin
class KikariaViewModel : ViewModel() {
    private val _uiState = MutableStateFlow(KikariaUiState(...))
    val uiState: StateFlow<KikariaUiState> = _uiState
}
```

Compose：

```kotlin
val state by viewModel.uiState.collectAsState()
```

---

### 6.3 第三层：UI / Compose 页面

目标：

```text
用 Compose 原生方式重建原产品体验。
```

迁移时应先写出页面意图摘要，例如：

```text
Home screen requirements:
- top-left title "Kikaria"
- top-right avatar/profile entry
- center floating bubble layout
- bubbles represent daily goal, countdown, preset, mastered/favorites etc.
- primary start action is visually emphasized
- visual style: light blue, glass-like, soft shadows, book-like typography
- Chinese text uses Song-style serif feeling
- numbers use serif
- avoid heavy Material default appearance
```

再据此实现 Compose 页面。

---

## 7. 推荐写入 Forgis / DS Prompt 的规则

以下文本可以直接加入 Swift → Kotlin / Compose 迁移任务。

```text
UI migration rule:

Do not mechanically translate SwiftUI code line by line into Jetpack Compose.

For each SwiftUI screen, first infer and document the user-visible intent:
1. screen purpose
2. visual hierarchy
3. reusable components
4. state inputs and outputs
5. navigation behavior
6. gestures and interactions
7. typography, colors, spacing, shadows, rounded corners, translucency
8. loading/empty/error states

Then rebuild the screen using idiomatic Jetpack Compose.

The Compose UI should preserve the original product identity and user experience, not the exact SwiftUI syntax structure.

For Kikaria-like screens, avoid default Material-looking UI unless the source design clearly uses it. Preserve the soft blue, glass-like, bookish, minimal, serif-leaning visual identity where applicable.

State that drives UI must use Compose-observable state such as remember, mutableStateOf, StateFlow, collectAsState, or equivalent ViewModel-backed state. Do not translate SwiftUI state into ordinary Kotlin vars.

After implementing each screen, perform a self-review comparing:
- visible layout
- navigation behavior
- state updates
- button behavior
- list behavior
- persistence behavior
- typography and visual identity
against the source SwiftUI intent.
```

---

## 8. 推荐迁移流程

### 阶段一：可运行骨架迁移

目标：

```text
能编译
能启动
页面路由完整
核心数据结构完整
基础 ViewModel 可用
主要页面都有对应 Compose 文件
```

这个阶段允许 UI 粗糙，但不能牺牲核心状态语义。

重点检查：

- Gradle 能否构建
- App 能否启动
- 页面能否进入
- 数据模型是否完整
- 状态是否接入 ViewModel
- 不要出现大量普通 `var` 驱动 UI
- 不要用 `!!` 掩盖空值问题

---

### 阶段二：视觉与交互对齐

目标：

```text
让 Android 版本更像原始 SwiftUI 产品。
```

任务要求：

```text
Read the existing Android implementation and the source SwiftUI implementation.
Do not rewrite everything.
Identify UI gaps page by page.
Improve Compose screens to better match the original visual hierarchy, typography, spacing, color system, navigation behavior, gestures, and state-driven interactions.
```

重点检查：

- 首页是否保留原产品识别度
- 字体是否接近
- 数字是否使用合适 serif 风格
- 卡片大小、间距、圆角是否接近
- 列表和详情页层级是否正确
- 按钮状态是否对应
- 导航和返回是否符合预期
- 空状态、加载状态、错误状态是否完整

---

### 阶段三：语义与状态 Bug 修复

目标：

```text
修复编译通过但运行时行为不一致的问题。
```

重点检查：

- Swift struct 是否被错误迁移成共享可变对象
- Optional 控制流是否丢失
- ViewModel 状态是否正确更新
- Compose 是否正确重组
- 页面切换后状态是否丢失
- 列表增删改是否影响正确对象
- 预设切换后数据是否串联
- 收藏 / 已掌握 / 学习进度是否独立保存

---

## 9. 迁移后自检清单

### 9.1 编译层

- [ ] Kotlin / Gradle 能编译
- [ ] App 能启动
- [ ] 没有明显运行时崩溃
- [ ] 没有大量 `TODO()` 留在核心路径
- [ ] 没有用 `!!` 大量强制解包
- [ ] 没有未接入的页面入口

---

### 9.2 语义层

- [ ] Swift struct 值语义被保留
- [ ] Kotlin data class 默认使用 `val`
- [ ] 修改数据时使用 `copy(...)`
- [ ] Optional / nullability 控制流正确
- [ ] `guard let` 的 early return / throw 没有丢失
- [ ] Swift enum associated values 没有被简化丢失
- [ ] Protocol 默认实现没有被错误替换成静态 extension
- [ ] 错误处理语义没有被粗暴吞掉

---

### 9.3 状态层

- [ ] UI 状态没有被普通 `var` 驱动
- [ ] Compose 使用 `remember` / `mutableStateOf` / `StateFlow` / `collectAsState`
- [ ] ViewModel 生命周期合理
- [ ] 没有随意使用 `GlobalScope`
- [ ] 页面返回后状态符合预期
- [ ] 列表变化能触发 UI 更新
- [ ] 持久化状态能恢复

---

### 9.4 UI 层

- [ ] 页面视觉层级接近原版
- [ ] 主要交互路径完整
- [ ] 导航和返回逻辑正常
- [ ] 字体体系接近原版
- [ ] 颜色系统接近原版
- [ ] 圆角、阴影、间距接近原版
- [ ] 没有明显默认 Material 味污染原产品气质
- [ ] 空状态 / 加载状态 / 错误状态完整
- [ ] 手势行为没有缺失

---

## 10. 最终原则

可以把整个策略浓缩成三句话：

```text
Business logic should be translated.
State logic should be mapped.
UI should be rebuilt natively from extracted intent and visual rules.
```

或者更直接地说：

```text
SwiftUI → Compose is not syntax translation.
It is UI semantic reconstruction.
```

对于 Forgis 来说，后续迁移不应追求“一次完成全部”。更现实的工作流是：

1. 第一轮：迁移出可运行骨架。
2. 第二轮：对齐 UI 和交互。
3. 第三轮：修复状态与语义 Bug。
4. 后续：基于截图和真机体验继续迭代。

这样才能避免自动翻译最常见的问题：

> 代码看起来迁移了，但产品已经不是原来的产品。
