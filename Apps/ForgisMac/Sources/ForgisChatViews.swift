#if canImport(SwiftUI)
import SwiftUI

struct AIChatWorkspaceView: View {
    @ObservedObject var model: ForgisChatViewModel

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
            .background {
                ForgisSystemCanvas()
            }
        }
    }

    private func header(layout: ForgisChatLayout) -> some View {
        ForgisPageHeader(
            title: "AI Chat",
            subtitle: model.configuration.model
        )
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, layout.horizontalPadding)
        .padding(.top, 18)
        .padding(.bottom, 12)
    }

    @ViewBuilder private func messages(layout: ForgisChatLayout) -> some View {
        if model.messages.isEmpty {
            emptyState
        } else {
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(spacing: 16) {
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
        VStack {
            Spacer()
            Image(systemName: "sparkles")
                .font(.system(size: 28, weight: .semibold))
                .foregroundStyle(ForgisTheme.accentDeep)
                .frame(width: 64, height: 64)
                .accessibilityLabel("Start a conversation")
            Spacer()
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    @ViewBuilder private func errorStrip(layout: ForgisChatLayout) -> some View {
        if let errorText = model.errorText {
            HStack(alignment: .top, spacing: 8) {
                Image(systemName: "exclamationmark.triangle.fill")
                    .foregroundStyle(ForgisTheme.danger)
                Text(errorText)
                    .font(ForgisType.caption(12))
                    .foregroundStyle(ForgisTheme.danger)
                    .lineLimit(2)
            }
                .padding(10)
                .frame(maxWidth: layout.contentMaxWidth, alignment: .leading)
                .forgisCard(cornerRadius: 10)
                .overlay {
                    RoundedRectangle(cornerRadius: 10, style: .continuous)
                        .stroke(ForgisTheme.danger.opacity(0.36), lineWidth: 1)
                }
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

    private var hasSurface: Bool {
        message.role != .assistant
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
                if message.role == .system {
                    Text("System")
                        .font(ForgisType.caption(10, weight: .semibold))
                        .foregroundStyle(ForgisTheme.textTertiary(scheme))
                        .tracking(0.4)
                        .lineLimit(1)
                }
                Text(displayText)
                    .font(ForgisType.chat())
                    .foregroundStyle(ForgisTheme.textPrimary(scheme))
                    .textSelection(.enabled)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .padding(.horizontal, hasSurface ? 14 : 0)
            .padding(.vertical, hasSurface ? 10 : 8)
            .background {
                if hasSurface {
                    bubbleBackground
                }
            }
            .frame(maxWidth: maxWidth, alignment: .leading)
            if !isUser { Spacer(minLength: gutter) }
        }
    }

    private var bubbleBackground: some View {
        let shape = RoundedRectangle(cornerRadius: 12, style: .continuous)
        return shape
            .fill(.regularMaterial)
            .overlay {
                shape.stroke(
                    isUser
                        ? ForgisTheme.accentStroke.opacity(0.72)
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
        HStack(alignment: .bottom, spacing: ForgisComposerMetrics.rowSpacing) {
            Button {
                model.clear()
            } label: {
                Label("Clear chat", systemImage: "trash")
                    .forgisComposerIconLabel()
            }
            .forgisCompactIconButton()
            .disabled(model.messages.isEmpty || model.isSending)
            .help("Clear chat")

            inputControl

            Button {
                model.send()
            } label: {
                Label("Send", systemImage: "arrow.up")
                    .forgisComposerIconLabel()
                    .opacity(model.isSending ? 0 : 1)
                    .overlay {
                        if model.isSending {
                            ProgressView()
                                .controlSize(.small)
                        }
                    }
            }
            .forgisCompactIconButton(prominent: true)
            .disabled(!model.canSend)
            .help("Send")
        }
    }

    private var inputControl: some View {
        TextField("Message Forgis...", text: $model.input, axis: .vertical)
            .textFieldStyle(.plain)
            .font(ForgisType.chat())
            .foregroundStyle(ForgisTheme.textPrimary(scheme))
            .lineLimit(1...6)
            .focused($focused)
            .disabled(model.isSending)
            .padding(.horizontal, ForgisComposerMetrics.inputHorizontalPadding)
            .padding(.vertical, ForgisComposerMetrics.inputVerticalPadding)
            .frame(
                minHeight: ForgisComposerMetrics.controlHeight,
                alignment: .center
            )
            .forgisLiquidGlass(
                cornerRadius: ForgisComposerMetrics.inputCornerRadius,
                interactive: true
            )
            .onSubmit {
                guard model.canSend else { return }
                model.send()
            }
    }
}

struct ChatInspectorView: View {
    @ObservedObject var model: ForgisChatViewModel
    let safety: [SafetyItem]

    var body: some View {
        SectionCard(title: "Connection") {
                InfoRow(title: "Model", value: model.configuration.model, monospaced: true)
                InfoRow(title: "Endpoint", value: model.configuration.apiBase, monospaced: true)
                InfoRow(title: "Auth", value: model.apiKeyStatus)
                SafetyStrip(items: safety)
        }
    }
}

private struct ForgisChatLayout {
    let width: CGFloat

    var horizontalPadding: CGFloat {
        if width < 460 { return 10 }
        if width < 620 { return 14 }
        if width < 820 { return 20 }
        return 30
    }

    var contentMaxWidth: CGFloat {
        940
    }

    var messageGutter: CGFloat {
        if width < 460 { return 0 }
        if width < 620 { return 8 }
        if width < 820 { return 24 }
        return 48
    }

    var messageMaxWidth: CGFloat {
        let available = width - (horizontalPadding * 2) - (messageGutter * 2)
        return min(640, max(240, available))
    }
}
#endif
