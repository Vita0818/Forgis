#if canImport(SwiftUI)
import SwiftUI
import IntatisCodexRuntime

struct MigrationWorkspaceView: View {
    @ObservedObject var model: ForgisRuntimeViewModel

    var body: some View {
        GeometryReader { proxy in
            let layout = ForgisRuntimeLayout(width: proxy.size.width)
            VStack(spacing: 0) {
                header(layout: layout)
                Divider()
                transcript(layout: layout)
                if let approval = model.pendingApprovals.first {
                    ForgisRuntimeApprovalCard(
                        request: approval,
                        model: model)
                        .frame(maxWidth: layout.contentMaxWidth)
                        .padding(.horizontal, layout.horizontalPadding)
                        .padding(.top, 10)
                }
                errorStrip(layout: layout)
                actionArea(layout: layout)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background { ForgisSystemCanvas() }
        }
    }

    private func header(layout: ForgisRuntimeLayout) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 12) {
            ForgisPageHeader(
                title: "Migration",
                subtitle: model.runtimeSubtitle)
            StatusPill(
                text: model.status.title,
                tone: runtimeStatusTone(model.status))
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, layout.horizontalPadding)
        .padding(.top, 18)
        .padding(.bottom, 12)
    }

    @ViewBuilder private func transcript(
        layout: ForgisRuntimeLayout
    ) -> some View {
        if model.messages.isEmpty {
            emptyState(layout: layout)
        } else {
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(spacing: 16) {
                        ForEach(model.messages) { message in
                            ForgisRuntimeMessageRow(
                                message: message,
                                maxWidth: layout.messageMaxWidth,
                                gutter: layout.messageGutter)
                                .id(message.id)
                        }
                    }
                    .frame(maxWidth: layout.contentMaxWidth)
                    .frame(maxWidth: .infinity)
                    .padding(.horizontal, layout.horizontalPadding)
                    .padding(.vertical, 16)
                }
                .scrollContentBackground(.hidden)
                .onChange(of: model.messages.count) { _, _ in
                    guard let last = model.messages.last else { return }
                    withAnimation {
                        proxy.scrollTo(last.id, anchor: .bottom)
                    }
                }
            }
        }
    }

    private func emptyState(layout: ForgisRuntimeLayout) -> some View {
        VStack(spacing: 16) {
            Spacer()
            Image(systemName: "arrow.triangle.2.circlepath.circle")
                .font(.system(size: 34, weight: .semibold))
                .foregroundStyle(ForgisTheme.accentDeep)
                .accessibilityHidden(true)
            Text("Configure source, target, task, and a native Responses route in Settings.")
                .font(ForgisType.body(14))
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 440)
            Text("Forgis starts Intatis only after you press the run control. It never falls back to the retired Chat client.")
                .font(ForgisType.caption(12))
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 520)
            Spacer()
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(.horizontal, layout.horizontalPadding)
    }

    @ViewBuilder private func actionArea(
        layout: ForgisRuntimeLayout
    ) -> some View {
        if model.threadID.isEmpty {
            HStack(spacing: 10) {
                Button {
                    model.startMigration()
                } label: {
                    if model.isWorking {
                        Label("Validating", systemImage: "hourglass")
                    } else if model.runMode == .dryRun || !model.runAgent {
                        Label("Validate dry run", systemImage: "checkmark.shield")
                    } else {
                        Label("Start migration", systemImage: "play.fill")
                    }
                }
                .disabled(!model.canStartMigration)
                .forgisGlassButton(prominent: true)

                Text(model.runMode == .realRun && model.runAgent
                     ? "Writes remain confined to target_subdir."
                     : "No runtime, credential, or target write is used.")
                    .font(ForgisType.caption(11))
                    .foregroundStyle(.secondary)
            }
            .frame(maxWidth: layout.contentMaxWidth, alignment: .leading)
            .padding(.horizontal, layout.horizontalPadding)
            .padding(.top, 12)
            .padding(.bottom, 20)
        } else {
            ForgisRuntimeComposer(model: model)
                .frame(maxWidth: layout.contentMaxWidth)
                .padding(.horizontal, layout.horizontalPadding)
                .padding(.top, 10)
                .padding(.bottom, 18)
        }
    }

    @ViewBuilder private func errorStrip(
        layout: ForgisRuntimeLayout
    ) -> some View {
        if let errorText = model.errorText, !errorText.isEmpty {
            HStack(alignment: .top, spacing: 8) {
                Image(systemName: "exclamationmark.triangle.fill")
                    .foregroundStyle(ForgisTheme.danger)
                Text(errorText)
                    .font(ForgisType.caption(12))
                    .foregroundStyle(ForgisTheme.danger)
                    .lineLimit(3)
                    .textSelection(.enabled)
            }
            .padding(10)
            .frame(maxWidth: layout.contentMaxWidth, alignment: .leading)
            .forgisCard(cornerRadius: 10)
            .overlay {
                RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .stroke(ForgisTheme.danger.opacity(0.36), lineWidth: 1)
            }
            .padding(.horizontal, layout.horizontalPadding)
            .padding(.top, 10)
        }
    }
}

struct ForgisRuntimeMessageRow: View {
    let message: ForgisRuntimeMessage
    let maxWidth: CGFloat
    let gutter: CGFloat
    @Environment(\.colorScheme) private var scheme

    private var isUser: Bool { message.role == .user }
    private var hasSurface: Bool {
        message.role == .user || message.role == .system
    }

    private var displayedText: String {
        if message.text.isEmpty && !message.isComplete { return "Waiting…" }
        return message.text
    }

    var body: some View {
        HStack(spacing: 0) {
            if isUser { Spacer(minLength: gutter) }
            VStack(alignment: .leading, spacing: 6) {
                if message.role == .system {
                    Text("Runtime")
                        .font(ForgisType.caption(10, weight: .semibold))
                        .foregroundStyle(ForgisTheme.textTertiary(scheme))
                }
                Text(displayedText)
                    .font(message.isCommentary
                          ? ForgisType.caption(13)
                          : ForgisType.chat())
                    .foregroundStyle(message.isCommentary
                                     ? ForgisTheme.textSecondary(scheme)
                                     : ForgisTheme.textPrimary(scheme))
                    .textSelection(.enabled)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .padding(.horizontal, hasSurface ? 14 : 0)
            .padding(.vertical, hasSurface ? 10 : 8)
            .background {
                if hasSurface {
                    let shape = RoundedRectangle(
                        cornerRadius: 12,
                        style: .continuous)
                    shape
                        .fill(.regularMaterial)
                        .overlay {
                            shape.stroke(
                                isUser
                                    ? ForgisTheme.accentStroke.opacity(0.72)
                                    : ForgisTheme.separator(scheme),
                                lineWidth: 1)
                        }
                }
            }
            .frame(maxWidth: maxWidth, alignment: .leading)
            if !isUser { Spacer(minLength: gutter) }
        }
    }
}

struct ForgisRuntimeComposer: View {
    @ObservedObject var model: ForgisRuntimeViewModel
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        HStack(alignment: .bottom, spacing: ForgisComposerMetrics.rowSpacing) {
            if model.canStop {
                Button {
                    model.stopCurrentTurn()
                } label: {
                    Label("Stop", systemImage: "stop.fill")
                        .forgisComposerIconLabel()
                }
                .forgisCompactIconButton()
                .help("Interrupt the current Intatis turn")
            }

            TextField(
                "Follow up with the migration agent…",
                text: $model.input,
                axis: .vertical)
                .textFieldStyle(.plain)
                .font(ForgisType.chat())
                .foregroundStyle(ForgisTheme.textPrimary(scheme))
                .lineLimit(1...6)
                .disabled(model.isWorking)
                .padding(.horizontal, ForgisComposerMetrics.inputHorizontalPadding)
                .padding(.vertical, ForgisComposerMetrics.inputVerticalPadding)
                .frame(minHeight: ForgisComposerMetrics.controlHeight)
                .forgisLiquidGlass(
                    cornerRadius: ForgisComposerMetrics.inputCornerRadius,
                    interactive: true)
                .onSubmit {
                    guard model.canSendFollowUp else { return }
                    model.sendFollowUp()
                }

            Button {
                model.sendFollowUp()
            } label: {
                Label("Send", systemImage: "arrow.up")
                    .forgisComposerIconLabel()
                    .opacity(model.isWorking ? 0 : 1)
                    .overlay {
                        if model.isWorking {
                            ProgressView().controlSize(.small)
                        }
                    }
            }
            .forgisCompactIconButton(prominent: true)
            .disabled(!model.canSendFollowUp)
            .help("Send through the current Intatis session")
        }
    }
}

struct ForgisRuntimeApprovalCard: View {
    let request: CodexRuntimeApprovalRequest
    @ObservedObject var model: ForgisRuntimeViewModel

    var body: some View {
        SectionCard(title: "Approval required") {
            Text(model.approvalTitle(request))
                .font(ForgisType.body(13, weight: .semibold))
            Text(model.approvalSummary(request))
                .font(ForgisType.caption(12))
                .foregroundStyle(.secondary)
                .textSelection(.enabled)
                .fixedSize(horizontal: false, vertical: true)
            ViewThatFits(in: .horizontal) {
                HStack(spacing: 8) { actions }
                VStack(alignment: .leading, spacing: 8) { actions }
            }
        }
    }

    private var actions: some View {
        Group {
            Button("Allow") {
                model.resolveApproval(request, decision: .accept)
            }
            .forgisGlassButton(prominent: true)
            Button("Allow for session") {
                model.resolveApproval(request, decision: .acceptForSession)
            }
            .forgisGlassButton()
            Button("Decline") {
                model.resolveApproval(request, decision: .decline)
            }
            .forgisGlassButton()
            Button("Cancel turn", role: .destructive) {
                model.resolveApproval(request, decision: .cancel)
            }
            .forgisGlassButton()
        }
        .controlSize(.small)
    }
}

private struct ForgisRuntimeLayout {
    let width: CGFloat

    var horizontalPadding: CGFloat {
        if width < 460 { return 10 }
        if width < 620 { return 14 }
        if width < 820 { return 20 }
        return 30
    }

    var contentMaxWidth: CGFloat { 940 }

    var messageGutter: CGFloat {
        if width < 460 { return 0 }
        if width < 620 { return 8 }
        if width < 820 { return 24 }
        return 48
    }

    var messageMaxWidth: CGFloat {
        let available = width
            - (horizontalPadding * 2)
            - (messageGutter * 2)
        return min(680, max(240, available))
    }
}
#endif
