#if canImport(SwiftUI)
import SwiftUI

struct AIChatWorkspaceView: View {
    @ObservedObject var model: ForgisChatViewModel
    let safety: [SafetyItem]
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        GeometryReader { proxy in
            let layout = ForgisChatLayout(width: proxy.size.width)
            VStack(spacing: 0) {
                header(layout: layout)
                Divider()
                messages(layout: layout)
                errorStrip(layout: layout)
                ChatComposerView(model: model)
                    .frame(maxWidth: layout.contentMaxWidth)
                    .padding(.horizontal, layout.horizontalPadding)
                    .padding(.top, 10)
                    .padding(.bottom, 18)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(ForgisTheme.background(scheme))
        }
    }

    private func header(layout: ForgisChatLayout) -> some View {
        ViewThatFits(in: .horizontal) {
            HStack(alignment: .top, spacing: 16) {
                titleBlock
                Spacer(minLength: 12)
                providerCard(layout: layout)
            }

            VStack(alignment: .leading, spacing: 12) {
                titleBlock
                providerCard(layout: layout)
            }
        }
        .padding(.horizontal, layout.horizontalPadding)
        .padding(.top, 18)
        .padding(.bottom, 12)
    }

    private var titleBlock: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("AI Chat")
                .font(ForgisType.sectionTitle(20))
                .foregroundStyle(ForgisTheme.textPrimary(scheme))
            Text("\(model.configuration.model) · \(model.configuration.hostLabel)")
                .font(ForgisType.caption(12, weight: .medium))
                .foregroundStyle(ForgisTheme.textSecondary(scheme))
                .lineLimit(1)
                .truncationMode(.middle)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func providerCard(layout: ForgisChatLayout) -> some View {
        HStack(spacing: 8) {
            Image(systemName: "cpu")
                .font(.system(size: 13, weight: .semibold))
                .foregroundStyle(ForgisTheme.accentDeep)
                .frame(width: 18)
            VStack(alignment: .leading, spacing: 2) {
                Text(model.configuration.provider)
                    .font(ForgisType.body(12, weight: .semibold))
                    .foregroundStyle(ForgisTheme.textPrimary(scheme))
                    .lineLimit(1)
                if !layout.isCompact {
                    Text(model.configuration.apiKeyEnvName)
                        .font(ForgisType.mono(11))
                        .foregroundStyle(ForgisTheme.textSecondary(scheme))
                        .lineLimit(1)
                        .truncationMode(.middle)
                }
            }
            StatusPill(
                text: model.apiKeyStatus,
                tone: chatSecretTone(model.secretStatus)
            )
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 9)
        .frame(minWidth: layout.isCompact ? 0 : 230, alignment: .leading)
        .forgisCard()
    }

    @ViewBuilder private func messages(layout: ForgisChatLayout) -> some View {
        if model.messages.isEmpty {
            emptyState
        } else {
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(spacing: 12) {
                        ForEach(model.messages) { message in
                            ChatMessageBubble(
                                message: message,
                                maxWidth: layout.messageMaxWidth,
                                gutter: layout.messageGutter
                            )
                            .id(message.id)
                        }
                    }
                    .frame(maxWidth: layout.contentMaxWidth)
                    .frame(maxWidth: .infinity)
                    .padding(.horizontal, layout.horizontalPadding)
                    .padding(.vertical, 16)
                }
                .scrollContentBackground(.hidden)
                .onChange(of: model.messages.count) { _ in
                    guard let last = model.messages.last else { return }
                    withAnimation {
                        proxy.scrollTo(last.id, anchor: .bottom)
                    }
                }
            }
        }
    }

    private var emptyState: some View {
        VStack(spacing: 12) {
            Spacer()
            Image(systemName: "sparkles")
                .font(.system(size: 30, weight: .semibold))
                .foregroundStyle(ForgisTheme.accentDeep)
                .frame(width: 74, height: 74)
                .background(ForgisTheme.accentSoft(scheme), in: RoundedRectangle(cornerRadius: 18, style: .continuous))
                .overlay {
                    RoundedRectangle(cornerRadius: 18, style: .continuous)
                        .stroke(ForgisTheme.accentStroke.opacity(0.45), lineWidth: 1)
                }
            Text("Forgis")
                .font(ForgisType.appTitle(24))
                .foregroundStyle(ForgisTheme.textPrimary(scheme))
            Text("No messages yet.")
                .font(ForgisType.body(13))
                .foregroundStyle(ForgisTheme.textSecondary(scheme))
                .multilineTextAlignment(.center)
                .padding(.horizontal, 20)
            Spacer()
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    @ViewBuilder private func errorStrip(layout: ForgisChatLayout) -> some View {
        if let errorText = model.errorText {
            Text(errorText)
                .font(ForgisType.caption(12))
                .foregroundStyle(ForgisTheme.danger)
                .lineLimit(2)
                .frame(maxWidth: layout.contentMaxWidth, alignment: .leading)
                .padding(.horizontal, layout.horizontalPadding)
        }
    }
}

struct ChatMessageBubble: View {
    let message: ForgisChatMessage
    let maxWidth: CGFloat
    let gutter: CGFloat
    @Environment(\.colorScheme) private var scheme

    private var isUser: Bool {
        message.role == .user
    }

    private var roleLabel: String {
        switch message.role {
        case .system: return "System"
        case .user: return "You"
        case .assistant: return "Forgis"
        }
    }

    private var displayText: String {
        if message.text.isEmpty && !message.isComplete {
            return "Waiting..."
        }
        return message.text
    }

    var body: some View {
        HStack(spacing: 0) {
            if isUser { Spacer(minLength: gutter) }
            VStack(alignment: .leading, spacing: 6) {
                Text(roleLabel.uppercased())
                    .font(ForgisType.caption(10, weight: .semibold))
                    .foregroundStyle(isUser ? ForgisTheme.accentDeep : ForgisTheme.textTertiary(scheme))
                    .lineLimit(1)
                Text(displayText)
                    .font(ForgisType.body(13))
                    .foregroundStyle(ForgisTheme.textPrimary(scheme))
                    .textSelection(.enabled)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 10)
            .background(bubbleBackground)
            .frame(maxWidth: maxWidth, alignment: .leading)
            if !isUser { Spacer(minLength: gutter) }
        }
    }

    private var bubbleBackground: some View {
        let shape = RoundedRectangle(cornerRadius: 12, style: .continuous)
        return shape
            .fill(isUser ? ForgisTheme.accentSoft(scheme) : ForgisTheme.surfaceElevated(scheme))
            .overlay {
                shape.stroke(
                    isUser
                        ? ForgisTheme.accentStroke.opacity(scheme == .dark ? 0.50 : 0.38)
                        : ForgisTheme.separator(scheme),
                    lineWidth: 1
                )
            }
    }
}

struct ChatComposerView: View {
    @ObservedObject var model: ForgisChatViewModel
    @Environment(\.colorScheme) private var scheme
    @FocusState private var focused: Bool

    var body: some View {
        HStack(alignment: .bottom, spacing: 10) {
            TextField("Message Forgis...", text: $model.input, axis: .vertical)
                .textFieldStyle(.plain)
                .font(ForgisType.body(14))
                .foregroundStyle(ForgisTheme.textPrimary(scheme))
                .lineLimit(1...6)
                .focused($focused)
                .disabled(model.isSending)
                .padding(.horizontal, 14)
                .padding(.vertical, 10)
                .background {
                    Capsule(style: .continuous)
                        .fill(ForgisTheme.surfaceElevated(scheme))
                }
                .overlay {
                    Capsule(style: .continuous)
                        .stroke(ForgisTheme.separator(scheme), lineWidth: 1)
                }
                .onSubmit {
                    model.send()
                }

            Button {
                model.clear()
            } label: {
                Image(systemName: "xmark.circle")
                    .font(.system(size: 17, weight: .semibold))
                    .foregroundStyle(model.messages.isEmpty || model.isSending ? ForgisTheme.textTertiary(scheme) : ForgisTheme.textSecondary(scheme))
                    .frame(width: 36, height: 36)
            }
            .buttonStyle(.plain)
            .disabled(model.messages.isEmpty || model.isSending)
            .help("Clear chat")

            Button {
                model.send()
            } label: {
                ZStack {
                    Circle()
                        .fill(model.canSend ? ForgisTheme.accent : ForgisTheme.surfaceMuted(scheme))
                    if model.isSending {
                        ProgressView()
                            .controlSize(.small)
                    } else {
                        Image(systemName: "arrow.up")
                            .font(.system(size: 15, weight: .bold))
                            .foregroundStyle(model.canSend ? .white : ForgisTheme.textTertiary(scheme))
                    }
                }
                .frame(width: 40, height: 40)
            }
            .buttonStyle(.plain)
            .disabled(!model.canSend)
            .help("Send")
        }
    }
}

struct ChatInspectorView: View {
    @ObservedObject var model: ForgisChatViewModel
    let safety: [SafetyItem]

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            SectionCard(title: "Chat") {
                InfoRow(title: "Status", value: model.statusText)
                InfoRow(title: "Messages", value: "\(model.messages.count)")
            }

            SectionCard(title: "Provider") {
                InfoRow(title: "Provider", value: model.configuration.provider)
                InfoRow(title: "Model", value: model.configuration.model, monospaced: true)
                InfoRow(title: "Endpoint", value: model.configuration.apiBase, monospaced: true)
                InfoRow(title: "Auth", value: model.configuration.requiresAuthentication ? "required" : "disabled")
                InfoRow(title: "API key env", value: model.configuration.apiKeyEnvName, monospaced: true)
                HStack(spacing: 10) {
                    Text("API key")
                        .font(ForgisType.caption(11, weight: .semibold))
                        .foregroundStyle(.secondary)
                    StatusPill(
                        text: model.apiKeyStatus,
                        tone: chatSecretTone(model.secretStatus)
                    )
                    Spacer(minLength: 0)
                }
                InfoRow(title: "Secret source", value: model.secretStatus.detail, monospaced: model.secretStatus == .keychainSet)
            }

            SectionCard(title: "Safety") {
                SafetyStrip(items: safety)
            }
        }
    }
}

private struct ForgisChatLayout {
    let width: CGFloat

    var isCompact: Bool {
        width < 700
    }

    var horizontalPadding: CGFloat {
        if width < 500 { return 14 }
        if width < 760 { return 20 }
        return 24
    }

    var contentMaxWidth: CGFloat {
        900
    }

    var messageGutter: CGFloat {
        width < 560 ? 14 : 42
    }

    var messageMaxWidth: CGFloat {
        let available = width - (horizontalPadding * 2) - (messageGutter * 2)
        return min(620, max(250, available))
    }
}
#endif
