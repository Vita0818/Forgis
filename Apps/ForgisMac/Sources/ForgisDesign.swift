#if canImport(SwiftUI)
import SwiftUI
#if canImport(AppKit)
import AppKit
#endif

// MARK: - Semantic color tokens

enum ForgisTheme {
    static let accentDeep = Color.accentColor
    static let accentStroke = Color.accentColor
    static let success = Color.green
    static let warning = Color.orange
    static let danger = Color.red
    static let info = Color.blue

    static func surfaceMuted(_: ColorScheme) -> Color {
        .secondary.opacity(0.12)
    }

    static func accentSoft(_: ColorScheme) -> Color {
        .accentColor.opacity(0.12)
    }

    static func separator(_: ColorScheme) -> Color {
        #if canImport(AppKit)
        return Color(nsColor: .separatorColor)
        #else
        return .secondary.opacity(0.28)
        #endif
    }

    static func textPrimary(_: ColorScheme) -> Color {
        .primary
    }

    static func textSecondary(_: ColorScheme) -> Color {
        .secondary
    }

    static func textTertiary(_: ColorScheme) -> Color {
        .secondary.opacity(0.72)
    }
}

/// The native macOS window surface. It follows the active appearance,
/// wallpaper tint, contrast, transparency, and window state.
struct ForgisSystemCanvas: View {
    @ViewBuilder var body: some View {
        if #available(macOS 14.0, *) {
            Rectangle().fill(.windowBackground)
        } else {
            legacyWindowBackground
        }
    }

    @ViewBuilder private var legacyWindowBackground: some View {
        #if canImport(AppKit)
        ForgisLegacyWindowBackground()
        #else
        Rectangle().fill(.background)
        #endif
    }
}

#if canImport(AppKit)
private struct ForgisLegacyWindowBackground: NSViewRepresentable {
    func makeNSView(context: Context) -> NSVisualEffectView {
        let view = NSVisualEffectView()
        view.material = .windowBackground
        view.blendingMode = .behindWindow
        view.state = .followsWindowActiveState
        return view
    }

    func updateNSView(_ nsView: NSVisualEffectView, context: Context) {}
}
#endif

// MARK: - Typography

enum ForgisType {
    static func appTitle(_ size: CGFloat = 30, weight: Font.Weight = .semibold) -> Font {
        .system(size: size, weight: weight, design: .serif)
    }

    static func largeTitle(_ size: CGFloat = 30, weight: Font.Weight = .semibold) -> Font {
        .system(size: size, weight: weight, design: .serif)
    }

    static func sectionTitle(_ size: CGFloat = 20, weight: Font.Weight = .semibold) -> Font {
        .system(size: size, weight: weight, design: .serif)
    }

    static func headline(_ size: CGFloat = 16, weight: Font.Weight = .semibold) -> Font {
        .system(size: size, weight: weight)
    }

    static func body(_ size: CGFloat = 14, weight: Font.Weight = .regular) -> Font {
        .system(size: size, weight: weight)
    }

    static func caption(_ size: CGFloat = 12, weight: Font.Weight = .medium) -> Font {
        .system(size: size, weight: weight)
    }

    static func mono(_ size: CGFloat = 13, weight: Font.Weight = .regular) -> Font {
        .system(size: size, weight: weight, design: .monospaced)
    }

    static func chat(_ size: CGFloat = 15, weight: Font.Weight = .regular) -> Font {
        .system(size: size, weight: weight)
    }
}

// MARK: - Native surfaces and controls

private struct ForgisContentSurfaceModifier: ViewModifier {
    @Environment(\.colorScheme) private var scheme
    let cornerRadius: CGFloat

    func body(content: Content) -> some View {
        let shape = RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
        content
            .background(.regularMaterial, in: shape)
            .overlay {
                shape.stroke(ForgisTheme.separator(scheme), lineWidth: 1)
            }
    }
}

private struct ForgisLiquidGlassModifier: ViewModifier {
    @Environment(\.colorScheme) private var scheme
    let cornerRadius: CGFloat
    let isInteractive: Bool

    @ViewBuilder func body(content: Content) -> some View {
        #if compiler(>=6.2)
        if #available(macOS 26.0, *) {
            content.glassEffect(
                isInteractive ? .regular.interactive() : .regular,
                in: .rect(cornerRadius: cornerRadius)
            )
        } else {
            fallback(content)
        }
        #else
        fallback(content)
        #endif
    }

    private func fallback(_ content: Content) -> some View {
        let shape = RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
        return content
            .background(.regularMaterial, in: shape)
            .overlay {
                shape.stroke(ForgisTheme.separator(scheme), lineWidth: 1)
            }
    }
}

private struct ForgisGlassButtonModifier: ViewModifier {
    let isProminent: Bool

    @ViewBuilder func body(content: Content) -> some View {
        #if compiler(>=6.2)
        if #available(macOS 26.0, *) {
            if isProminent {
                content.buttonStyle(.glassProminent)
            } else {
                content.buttonStyle(.glass)
            }
        } else {
            fallback(content)
        }
        #else
        fallback(content)
        #endif
    }

    @ViewBuilder private func fallback(_ content: Content) -> some View {
        if isProminent {
            content.buttonStyle(.borderedProminent)
        } else {
            content.buttonStyle(.bordered)
        }
    }
}

extension View {
    func forgisCard(cornerRadius: CGFloat = 16) -> some View {
        modifier(ForgisContentSurfaceModifier(cornerRadius: cornerRadius))
    }

    func forgisLiquidGlass(
        cornerRadius: CGFloat = 16,
        interactive: Bool = false
    ) -> some View {
        modifier(
            ForgisLiquidGlassModifier(
                cornerRadius: cornerRadius,
                isInteractive: interactive
            )
        )
    }

    func forgisGlassButton(prominent: Bool = false) -> some View {
        modifier(ForgisGlassButtonModifier(isProminent: prominent))
    }

    @ViewBuilder func forgisCompactIconButton(prominent: Bool = false) -> some View {
        if #available(macOS 14.0, *) {
            labelStyle(.iconOnly)
                .controlSize(.regular)
                .buttonBorderShape(.circle)
                .forgisGlassButton(prominent: prominent)
        } else {
            labelStyle(.iconOnly)
                .controlSize(.regular)
                .forgisGlassButton(prominent: prominent)
        }
    }

    func forgisComposerIconLabel() -> some View {
        font(.system(size: 15, weight: .semibold))
            .frame(
                width: ForgisComposerMetrics.iconLabelExtent,
                height: ForgisComposerMetrics.iconLabelExtent
            )
    }
}

enum ForgisComposerMetrics {
    static let controlHeight: CGFloat = 40
    static let iconLabelExtent: CGFloat = 32
    static let rowSpacing: CGFloat = 8
    static let inputHorizontalPadding: CGFloat = 14
    static let inputVerticalPadding: CGFloat = 9
    static let inputCornerRadius: CGFloat = controlHeight / 2
}

struct ForgisPageHeader: View {
    let title: String
    var subtitle: String?
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title)
                .font(ForgisType.largeTitle())
                .foregroundStyle(ForgisTheme.textPrimary(scheme))
            if let subtitle {
                Text(subtitle)
                    .font(ForgisType.caption(13))
                    .foregroundStyle(ForgisTheme.textSecondary(scheme))
                    .lineLimit(1)
                    .truncationMode(.middle)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}
#endif
