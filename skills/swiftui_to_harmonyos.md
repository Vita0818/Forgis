# SwiftUI To HarmonyOS ArkUI

- Treat SwiftUI view trees as ArkUI component hierarchies with equivalent state, layout, and interaction intent.
- Map local state, bindings, and observed data to the target ArkUI state model chosen by the target project.
- Preserve navigation structure, modal presentation intent, and back behavior when translating routes.
- Map lists, grids, conditional views, resources, and lifecycle hooks by behavior rather than by name alone.
- Keep visual hierarchy and user-facing state stable when exact component matches do not exist.
- Keep business names and project-specific rules out of this skill; read the actual code before applying mappings.
