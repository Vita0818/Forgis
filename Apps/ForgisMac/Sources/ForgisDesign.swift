#if canImport(SwiftUI)
import SwiftUI

enum ForgisTheme {
    static let accent = Color(red: 0.918, green: 0.568, blue: 0.314)
    static let accentDeep = Color(red: 0.624, green: 0.314, blue: 0.157)
    static let accentStroke = Color(red: 0.843, green: 0.467, blue: 0.231)
    static let success = Color(red: 0.243, green: 0.584, blue: 0.341)
    static let warning = Color(red: 0.741, green: 0.498, blue: 0.137)
    static let danger = Color(red: 0.706, green: 0.216, blue: 0.196)
    static let info = Color(red: 0.278, green: 0.459, blue: 0.702)

    static func background(_ scheme: ColorScheme) -> Color {
        scheme == .dark
            ? Color(red: 0.090, green: 0.087, blue: 0.082)
            : Color(red: 0.979, green: 0.975, blue: 0.968)
    }

    static func surface(_ scheme: ColorScheme) -> Color {
        scheme == .dark
            ? Color(red: 0.135, green: 0.130, blue: 0.121)
            : Color(red: 1.000, green: 0.996, blue: 0.988)
    }

    static func surfaceElevated(_ scheme: ColorScheme) -> Color {
        scheme == .dark
            ? Color(red: 0.172, green: 0.162, blue: 0.148)
            : Color(red: 1.000, green: 1.000, blue: 0.998)
    }

    static func surfaceMuted(_ scheme: ColorScheme) -> Color {
        scheme == .dark
            ? Color(red: 0.118, green: 0.112, blue: 0.103)
            : Color(red: 0.955, green: 0.948, blue: 0.936)
    }

    static func accentSoft(_ scheme: ColorScheme) -> Color {
        scheme == .dark
            ? Color(red: 0.278, green: 0.169, blue: 0.105)
            : Color(red: 0.996, green: 0.925, blue: 0.866)
    }

    static func separator(_ scheme: ColorScheme) -> Color {
        scheme == .dark
            ? Color.white.opacity(0.10)
            : Color.black.opacity(0.10)
    }

    static func textPrimary(_ scheme: ColorScheme) -> Color {
        scheme == .dark
            ? Color(red: 0.918, green: 0.902, blue: 0.871)
            : Color(red: 0.137, green: 0.125, blue: 0.110)
    }

    static func textSecondary(_ scheme: ColorScheme) -> Color {
        scheme == .dark
            ? Color(red: 0.690, green: 0.663, blue: 0.612)
            : Color(red: 0.420, green: 0.392, blue: 0.349)
    }

    static func textTertiary(_ scheme: ColorScheme) -> Color {
        scheme == .dark
            ? Color(red: 0.502, green: 0.478, blue: 0.435)
            : Color(red: 0.612, green: 0.573, blue: 0.510)
    }
}

enum ForgisType {
    static func appTitle(_ size: CGFloat = 25, weight: Font.Weight = .semibold) -> Font {
        .system(size: size, weight: weight, design: .serif)
    }

    static func sectionTitle(_ size: CGFloat = 18, weight: Font.Weight = .semibold) -> Font {
        .system(size: size, weight: weight, design: .serif)
    }

    static func body(_ size: CGFloat = 13, weight: Font.Weight = .regular) -> Font {
        .system(size: size, weight: weight)
    }

    static func caption(_ size: CGFloat = 11, weight: Font.Weight = .medium) -> Font {
        .system(size: size, weight: weight)
    }

    static func mono(_ size: CGFloat = 12, weight: Font.Weight = .regular) -> Font {
        .system(size: size, weight: weight, design: .monospaced)
    }
}

struct ForgisCardModifier: ViewModifier {
    @Environment(\.colorScheme) private var scheme

    func body(content: Content) -> some View {
        content
            .background(ForgisTheme.surfaceElevated(scheme), in: RoundedRectangle(cornerRadius: 10, style: .continuous))
            .overlay {
                RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .stroke(ForgisTheme.separator(scheme), lineWidth: 1)
            }
    }
}

extension View {
    func forgisCard() -> some View {
        modifier(ForgisCardModifier())
    }
}
#endif
