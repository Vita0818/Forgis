# SwiftUI To Jetpack Compose

- Treat SwiftUI `View` bodies as a composable tree and map them to focused `@Composable` functions.
- Map `@State` to remembered mutable state or hoisted state, and map `@Binding` to value plus callback pairs.
- Preserve navigation intent when translating `NavigationStack`, links, sheets, and detail routes.
- Map `List`, `ForEach`, and lazy containers to Compose list/grid primitives while keeping item identity stable.
- Translate modifiers by intent: layout, spacing, drawing, clipping, input, and accessibility.
- Keep business names and project-specific rules out of this skill; read the actual code before applying mappings.
