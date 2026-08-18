#if canImport(SwiftUI)
import SwiftUI

enum PillTone {
    case neutral
    case accent
    case success
    case warning
    case danger
    case info

    func foreground(_ scheme: ColorScheme) -> Color {
        switch self {
        case .neutral: return ForgisTheme.textSecondary(scheme)
        case .accent: return ForgisTheme.accentDeep
        case .success: return ForgisTheme.success
        case .warning: return ForgisTheme.warning
        case .danger: return ForgisTheme.danger
        case .info: return ForgisTheme.info
        }
    }

    func background(_ scheme: ColorScheme) -> Color {
        switch self {
        case .neutral: return ForgisTheme.surfaceMuted(scheme)
        case .accent: return ForgisTheme.accentSoft(scheme)
        case .success: return ForgisTheme.success.opacity(scheme == .dark ? 0.20 : 0.12)
        case .warning: return ForgisTheme.warning.opacity(scheme == .dark ? 0.20 : 0.12)
        case .danger: return ForgisTheme.danger.opacity(scheme == .dark ? 0.20 : 0.12)
        case .info: return ForgisTheme.info.opacity(scheme == .dark ? 0.20 : 0.12)
        }
    }

    func border(_ scheme: ColorScheme) -> Color {
        switch self {
        case .neutral: return ForgisTheme.separator(scheme)
        case .accent: return ForgisTheme.accentStroke.opacity(scheme == .dark ? 0.55 : 0.45)
        case .success: return ForgisTheme.success.opacity(0.35)
        case .warning: return ForgisTheme.warning.opacity(0.40)
        case .danger: return ForgisTheme.danger.opacity(0.35)
        case .info: return ForgisTheme.info.opacity(0.35)
        }
    }
}

struct StatusPill: View {
    let text: String
    let tone: PillTone
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        Text(text)
            .font(ForgisType.caption(10, weight: .semibold))
            .foregroundStyle(tone.foreground(scheme))
            .lineLimit(1)
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .background(tone.background(scheme), in: Capsule(style: .continuous))
            .overlay {
                Capsule(style: .continuous)
                    .stroke(tone.border(scheme), lineWidth: 1)
            }
            .fixedSize(horizontal: true, vertical: false)
    }
}

struct PathLabel: View {
    let path: String
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        Text(path)
            .font(ForgisType.mono(12))
            .foregroundStyle(ForgisTheme.textSecondary(scheme))
            .lineLimit(1)
            .truncationMode(.middle)
            .textSelection(.enabled)
    }
}

struct SafetyStrip: View {
    let items: [SafetyItem]

    var body: some View {
        Label(
            isProtected ? "Protected" : "Review safeguards",
            systemImage: isProtected ? "checkmark.shield" : "exclamationmark.shield"
        )
        .font(ForgisType.caption(11, weight: .semibold))
        .foregroundStyle(
            isProtected
                ? ForgisTheme.success
                : ForgisTheme.warning
        )
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityLabel(
            isProtected
                ? "All \(items.count) safeguards active"
                : "Safeguards need review"
        )
    }

    private var isProtected: Bool {
        !items.isEmpty && items.allSatisfy { item in
            if case .success = item.tone {
                return true
            }
            return false
        }
    }
}

struct InfoRow: View {
    let title: String
    let value: String
    var monospaced = false
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            Text(title)
                .font(ForgisType.caption(11, weight: .semibold))
                .foregroundStyle(ForgisTheme.textTertiary(scheme))
                .lineLimit(1)
                .fixedSize(horizontal: true, vertical: false)
            Text(value)
                .font(monospaced ? ForgisType.mono(12) : ForgisType.body(12))
                .foregroundStyle(ForgisTheme.textPrimary(scheme))
                .lineLimit(1)
                .truncationMode(.middle)
                .textSelection(.enabled)
                .layoutPriority(1)
            Spacer(minLength: 0)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

struct SectionCard<Content: View>: View {
    let title: String
    @ViewBuilder let content: Content
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(title)
                .font(ForgisType.caption(12, weight: .semibold))
                .foregroundStyle(ForgisTheme.textSecondary(scheme))
            content
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .forgisCard(cornerRadius: 14)
    }
}

func statusTone(_ status: UnitStatus) -> PillTone {
    switch status {
    case .pending: return .neutral
    case .running: return .info
    case .completed: return .success
    case .failed: return .danger
    }
}

#endif
