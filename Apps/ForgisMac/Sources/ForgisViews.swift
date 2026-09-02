#if canImport(SwiftUI)
import AppKit
import SwiftUI

struct SidebarView: View {
    @Binding var selection: ForgisSection?
    let mode: RunMode
    let status: ForgisRuntimeStatus
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text("Forgis")
                .font(ForgisType.appTitle())
                .foregroundStyle(ForgisTheme.textPrimary(scheme))
                .padding(.horizontal, 8)
                .padding(.top, 8)
                .padding(.bottom, 18)

            VStack(spacing: 6) {
                navigationRow(.migration)
                navigationRow(.reports)
            }

            VStack(alignment: .leading, spacing: 4) {
                Text(mode.title)
                Text(status.title)
            }
            .font(ForgisType.caption(11, weight: .medium))
            .foregroundStyle(ForgisTheme.textTertiary(scheme))
            .padding(.horizontal, 10)
            .padding(.top, 18)

            Spacer(minLength: 16)
            Divider().padding(.bottom, 10)
            navigationRow(.settings)
        }
        .padding(12)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    }

    @ViewBuilder private func navigationRow(_ item: ForgisSection) -> some View {
        if selection == item {
            navigationButton(item)
                .forgisLiquidGlass(cornerRadius: 10, interactive: true)
        } else {
            navigationButton(item)
        }
    }

    private func navigationButton(_ item: ForgisSection) -> some View {
        Button {
            selection = item
        } label: {
            Label(item.title, systemImage: item.icon)
                .font(ForgisType.body(
                    13,
                    weight: selection == item ? .semibold : .medium))
                .foregroundStyle(
                    selection == item
                        ? ForgisTheme.textPrimary(scheme)
                        : ForgisTheme.textSecondary(scheme))
                .frame(maxWidth: .infinity, minHeight: 36, alignment: .leading)
                .padding(.horizontal, 10)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }
}

struct InspectorView: View {
    let activeSection: ForgisSection
    @ObservedObject var model: ForgisRuntimeViewModel
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                Text("Inspector")
                    .font(ForgisType.sectionTitle())
                    .foregroundStyle(ForgisTheme.textPrimary(scheme))

                switch activeSection {
                case .migration:
                    migrationInspector
                case .reports:
                    reportInspector
                case .settings:
                    settingsInspector
                }
            }
            .padding(16)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .background { ForgisSystemCanvas() }
    }

    private var migrationInspector: some View {
        Group {
            SectionCard(title: "Runtime") {
                InfoRow(title: "Kernel", value: "Intatis Codex v1")
                InfoRow(title: "Status", value: model.status.title)
                InfoRow(
                    title: "Version",
                    value: display(model.runtimeVersion),
                    monospaced: true)
                InfoRow(
                    title: "Thread",
                    value: display(model.threadID),
                    monospaced: true)
                SafetyStrip(items: model.safetyItems)
            }

            SectionCard(title: "Workspace") {
                InfoRow(
                    title: "Source",
                    value: display(model.workspace.sourcePath),
                    monospaced: true)
                InfoRow(
                    title: "Target",
                    value: display(model.workspace.targetPath),
                    monospaced: true)
                InfoRow(
                    title: "Write root",
                    value: display(model.workspace.targetSubdir),
                    monospaced: true)
                InfoRow(
                    title: "Unit",
                    value: display(model.workspace.unitID),
                    monospaced: true)
            }

            if let usage = model.usage {
                SectionCard(title: "Usage") {
                    InfoRow(
                        title: "Input",
                        value: String(usage.inputTokens))
                    InfoRow(
                        title: "Output",
                        value: String(usage.outputTokens))
                    InfoRow(
                        title: "Reasoning",
                        value: String(usage.reasoningOutputTokens))
                    InfoRow(
                        title: "Total",
                        value: String(usage.totalTokens))
                }
            }

            if !model.activities.isEmpty {
                SectionCard(title: "Recent activity") {
                    ForEach(model.activities.suffix(8)) { activity in
                        HStack(alignment: .firstTextBaseline, spacing: 8) {
                            Image(systemName: activity.failed
                                  ? "xmark.circle.fill"
                                  : "checkmark.circle")
                                .foregroundStyle(activity.failed
                                                 ? ForgisTheme.danger
                                                 : ForgisTheme.textTertiary(scheme))
                            VStack(alignment: .leading, spacing: 2) {
                                Text(activity.title)
                                    .font(ForgisType.body(12, weight: .semibold))
                                    .lineLimit(1)
                                Text(activity.status)
                                    .font(ForgisType.caption(10))
                                    .foregroundStyle(.secondary)
                                    .lineLimit(1)
                            }
                        }
                    }
                }
            }
        }
    }

    @ViewBuilder private var reportInspector: some View {
        if let stored = model.selectedReport {
            SectionCard(title: "Selected report") {
                InfoRow(title: "Status", value: stored.report.status)
                InfoRow(
                    title: "Schema",
                    value: stored.report.schemaVersion,
                    monospaced: true)
                InfoRow(
                    title: "Session",
                    value: stored.report.sessionID,
                    monospaced: true)
                InfoRow(
                    title: "Turn",
                    value: display(stored.report.turnID),
                    monospaced: true)
                InfoRow(
                    title: "JSON",
                    value: stored.jsonURL.path,
                    monospaced: true)
            }
        } else {
            Text("No run report has been written.")
                .font(ForgisType.body(13))
                .foregroundStyle(.secondary)
        }
    }

    private var settingsInspector: some View {
        SectionCard(title: "Native Responses route") {
            InfoRow(
                title: "Model",
                value: display(model.provider.model),
                monospaced: true)
            InfoRow(
                title: "Base",
                value: display(model.provider.responsesBaseURL),
                monospaced: true)
            InfoRow(title: "Auth", value: model.credentialStatus.title)
            InfoRow(title: "Kernel", value: "Intatis only")
            SafetyStrip(items: model.safetyItems)
        }
    }

    private func display(_ value: String) -> String {
        value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            ? "Not set"
            : value
    }
}

struct ReportPanelView: View {
    @ObservedObject var model: ForgisRuntimeViewModel

    var body: some View {
        VStack(spacing: 0) {
            ForgisPageHeader(
                title: "Reports",
                subtitle: model.reports.isEmpty
                    ? "No persisted runs"
                    : "\(model.reports.count) persisted run\(model.reports.count == 1 ? "" : "s")")
                .padding(.horizontal, 18)
                .padding(.top, 18)
                .padding(.bottom, 12)
            Divider()

            if model.reports.isEmpty {
                VStack(spacing: 12) {
                    Spacer()
                    Image(systemName: "doc.text.magnifyingglass")
                        .font(.system(size: 30, weight: .semibold))
                        .foregroundStyle(.secondary)
                    Text("Reports appear here after a dry-run validation or an Intatis turn.")
                        .font(ForgisType.body(13))
                        .foregroundStyle(.secondary)
                    Spacer()
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                ViewThatFits(in: .horizontal) {
                    HSplitView {
                        reportList.frame(minWidth: 250, idealWidth: 300)
                        reportDetail.frame(minWidth: 330, idealWidth: 520)
                    }
                    VStack(spacing: 0) {
                        reportList.frame(minHeight: 220)
                        Divider()
                        reportDetail.frame(minHeight: 300)
                    }
                }
            }
        }
        .background { ForgisSystemCanvas() }
    }

    private var reportList: some View {
        List(selection: $model.selectedReportID) {
            ForEach(model.reports) { stored in
                VStack(alignment: .leading, spacing: 7) {
                    HStack {
                        Text(stored.report.targetRepo)
                            .font(ForgisType.body(13, weight: .semibold))
                            .lineLimit(1)
                        Spacer()
                        StatusPill(
                            text: stored.report.status,
                            tone: stored.report.status == "completed"
                                ? .success
                                : (stored.report.status.hasPrefix("skipped")
                                    ? .neutral
                                    : .danger))
                    }
                    Text(stored.report.unitID.isEmpty
                         ? "No explicit unit"
                         : stored.report.unitID)
                        .font(ForgisType.mono(11))
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                    Text(stored.modifiedAt.formatted(date: .abbreviated, time: .shortened))
                        .font(ForgisType.caption(10))
                        .foregroundStyle(.tertiary)
                }
                .padding(.vertical, 7)
                .tag(stored.id)
            }
        }
        .listStyle(.inset)
        .scrollContentBackground(.hidden)
        .background { ForgisSystemCanvas() }
    }

    @ViewBuilder private var reportDetail: some View {
        if let stored = model.selectedReport {
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    SectionCard(title: "Run") {
                        InfoRow(title: "Status", value: stored.report.status)
                        InfoRow(
                            title: "Kernel",
                            value: stored.report.runtimeKernel,
                            monospaced: true)
                        InfoRow(
                            title: "Runtime",
                            value: stored.report.runtimeVersion,
                            monospaced: true)
                        InfoRow(
                            title: "Thread",
                            value: stored.report.threadID.isEmpty
                                ? "Not started"
                                : stored.report.threadID,
                            monospaced: true)
                        InfoRow(
                            title: "Tools",
                            value: String(stored.report.toolCallCount))
                        InfoRow(
                            title: "Writes",
                            value: String(stored.report.writeToolCount))
                    }

                    SectionCard(title: "Final summary") {
                        Text(stored.report.finalSummary)
                            .font(ForgisType.body(13))
                            .textSelection(.enabled)
                            .fixedSize(horizontal: false, vertical: true)
                    }

                    SectionCard(title: "Files") {
                        InfoRow(
                            title: "JSON",
                            value: stored.jsonURL.path,
                            monospaced: true)
                        InfoRow(
                            title: "Markdown",
                            value: stored.markdownURL.path,
                            monospaced: true)
                        Button {
                            NSWorkspace.shared.activateFileViewerSelecting([
                                stored.jsonURL,
                            ])
                        } label: {
                            Label("Reveal report", systemImage: "folder")
                        }
                        .forgisGlassButton()
                        .controlSize(.small)
                    }
                }
                .padding(16)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
    }
}

struct SettingsView: View {
    @ObservedObject var model: ForgisRuntimeViewModel
    @State private var credentialDraft = ""
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                ForgisPageHeader(
                    title: "Settings",
                    subtitle: "Workspace and Intatis native Responses route")

                SectionCard(title: "Workspace") {
                    SettingsPathRow(
                        title: "Source repository",
                        text: $model.workspace.sourcePath,
                        action: model.chooseSourceDirectory)
                    SettingsPathRow(
                        title: "Target repository",
                        text: $model.workspace.targetPath,
                        action: model.chooseTargetDirectory)
                    SettingsPathRow(
                        title: "Task file",
                        text: $model.workspace.taskPath,
                        action: model.chooseTaskFile)
                    SettingsFieldRow(
                        title: "Target subdir (only write root)",
                        text: $model.workspace.targetSubdir,
                        monospaced: true)
                    SettingsFieldRow(
                        title: "Target repository label",
                        text: $model.workspace.targetRepo,
                        monospaced: true)
                    SettingsFieldRow(
                        title: "Migration unit (optional)",
                        text: $model.workspace.unitID,
                        monospaced: true)
                }
                .disabled(!model.canEditConfiguration)

                SectionCard(title: "Intatis Responses route") {
                    SettingsFieldRow(
                        title: "Endpoint ID",
                        text: $model.provider.endpointID,
                        monospaced: true)
                    SettingsFieldRow(
                        title: "Model",
                        text: $model.provider.model,
                        monospaced: true)
                    SettingsFieldRow(
                        title: "Responses API base",
                        text: $model.provider.responsesBaseURL,
                        monospaced: true)
                    Picker("Request adapter", selection: $model.provider.requestAdapter) {
                        ForEach(ForgisRequestAdapter.allCases) { adapter in
                            Text(adapter.title).tag(adapter)
                        }
                    }
                    .font(ForgisType.body(12))
                    SettingsFieldRow(
                        title: "Reasoning effort (optional)",
                        text: $model.provider.reasoningEffort,
                        monospaced: true)
                    Toggle(
                        "Require bearer credential",
                        isOn: $model.provider.requiresAuthentication)
                        .font(ForgisType.body(12))
                    SettingsFieldRow(
                        title: "Credential environment fallback",
                        text: $model.provider.credentialEnvironmentName,
                        monospaced: true)
                        .disabled(!model.provider.requiresAuthentication)
                }
                .disabled(!model.canEditConfiguration)

                SectionCard(title: "Execution gate") {
                    Picker("Mode", selection: $model.runMode) {
                        ForEach(RunMode.allCases) { mode in
                            Text(mode.title).tag(mode)
                        }
                    }
                    .pickerStyle(.segmented)
                    Toggle("Enable migration agent", isOn: $model.runAgent)
                        .font(ForgisType.body(12))
                    Toggle(
                        "I confirm this real run may modify target_subdir",
                        isOn: $model.confirmRealRun)
                        .font(ForgisType.body(12))
                        .disabled(model.runMode != .realRun || !model.runAgent)
                    Text("Dry run never starts Intatis, resolves credentials, or creates target_subdir. Confirmation is intentionally not persisted.")
                        .font(ForgisType.caption(11))
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .disabled(!model.canEditConfiguration)

                SectionCard(title: "Credential") {
                    InfoRow(title: "Status", value: model.credentialStatus.title)
                    Text(model.credentialStatus.detail)
                        .font(ForgisType.caption(11))
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                    SecureField("New Responses credential", text: $credentialDraft)
                        .textFieldStyle(.roundedBorder)
                        .disabled(!model.provider.requiresAuthentication)
                    HStack(spacing: 8) {
                        Button {
                            if model.saveCredential(credentialDraft) {
                                credentialDraft = ""
                            }
                        } label: {
                            Label("Save credential", systemImage: "key.fill")
                        }
                        .disabled(
                            !model.provider.requiresAuthentication
                                || credentialDraft.trimmingCharacters(
                                    in: .whitespacesAndNewlines).isEmpty)
                        .forgisGlassButton()

                        Button(role: .destructive) {
                            model.deleteCredential()
                        } label: {
                            Label("Delete", systemImage: "trash")
                        }
                        .forgisGlassButton()
                    }
                    .controlSize(.small)
                }

                if let statusText = model.settingsStatusText {
                    Text(statusText)
                        .font(ForgisType.caption(12))
                        .foregroundStyle(ForgisTheme.textSecondary(scheme))
                        .fixedSize(horizontal: false, vertical: true)
                }

                ViewThatFits(in: .horizontal) {
                    HStack(spacing: 8) { settingsActions }
                    VStack(alignment: .leading, spacing: 8) { settingsActions }
                }
            }
            .padding(18)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .background { ForgisSystemCanvas() }
        .onAppear { model.refreshCredentialStatus() }
    }

    private var settingsActions: some View {
        Group {
            Button {
                model.saveSettings()
            } label: {
                Label("Save", systemImage: "checkmark")
            }
            .disabled(!model.canEditConfiguration)
            .forgisGlassButton(prominent: true)

            Button {
                model.startNewSession()
            } label: {
                Label("New session", systemImage: "plus.bubble")
            }
            .disabled(model.isWorking)
            .forgisGlassButton()

            Button {
                model.resetSettings()
            } label: {
                Label("Reset settings", systemImage: "arrow.counterclockwise")
            }
            .disabled(!model.canEditConfiguration)
            .forgisGlassButton()
        }
        .controlSize(.small)
    }
}

private struct SettingsPathRow: View {
    let title: String
    @Binding var text: String
    let action: () -> Void
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(title)
                .font(ForgisType.caption(11, weight: .semibold))
                .foregroundStyle(ForgisTheme.textTertiary(scheme))
            HStack(spacing: 8) {
                TextField(title, text: $text)
                    .textFieldStyle(.roundedBorder)
                    .font(ForgisType.mono(12))
                    .lineLimit(1)
                Button("Choose", action: action)
                    .forgisGlassButton()
                    .controlSize(.small)
            }
        }
    }
}

private struct SettingsFieldRow: View {
    let title: String
    @Binding var text: String
    var monospaced = false
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(title)
                .font(ForgisType.caption(11, weight: .semibold))
                .foregroundStyle(ForgisTheme.textTertiary(scheme))
            TextField(title, text: $text)
                .textFieldStyle(.roundedBorder)
                .font(monospaced
                      ? ForgisType.mono(12)
                      : ForgisType.body(12))
                .lineLimit(1)
        }
    }
}
#endif
