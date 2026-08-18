#if canImport(SwiftUI)
import SwiftUI

struct SidebarView: View {
    @Binding var selection: ForgisSection?
    let mode: RunMode
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
                ForEach(primarySections) { item in
                    navigationRow(item)
                }
            }

            Text(mode.title)
                .font(ForgisType.caption(11, weight: .medium))
                .foregroundStyle(ForgisTheme.textTertiary(scheme))
                .padding(.horizontal, 10)
                .padding(.top, 18)

            Spacer(minLength: 16)

            Divider()
                .padding(.bottom, 10)
            navigationRow(.settings)
        }
        .padding(12)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    }

    private var primarySections: [ForgisSection] {
        [.aiChat, .migration, .reports]
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
                .font(ForgisType.body(13, weight: selection == item ? .semibold : .medium))
                .foregroundStyle(
                    selection == item
                        ? ForgisTheme.textPrimary(scheme)
                        : ForgisTheme.textSecondary(scheme)
                )
                .frame(maxWidth: .infinity, minHeight: 36, alignment: .leading)
                .padding(.horizontal, 10)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }
}

struct MigrationWorkspaceView: View {
    let units: [MigrationUnit]
    @Binding var selectedUnitID: MigrationUnit.ID?
    let selectedUnit: MigrationUnit?

    var body: some View {
        VStack(spacing: 0) {
            ForgisPageHeader(title: "Migration Units")
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 18)
            .padding(.top, 18)
            .padding(.bottom, 10)

            Divider()

            workspaceLayout
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .background {
            ForgisSystemCanvas()
        }
    }

    @ViewBuilder private var workspaceLayout: some View {
        ViewThatFits(in: .horizontal) {
            HSplitView {
                MigrationUnitListView(units: units, selectedUnitID: $selectedUnitID)
                    .frame(minWidth: 240, idealWidth: 300)
                MigrationUnitDetailView(unit: selectedUnit)
                    .frame(minWidth: 260, idealWidth: 360)
            }

            VStack(spacing: 0) {
                MigrationUnitListView(units: units, selectedUnitID: $selectedUnitID)
                    .frame(minHeight: 220)
                Divider()
                MigrationUnitDetailView(unit: selectedUnit)
                    .frame(minHeight: 260)
            }
        }
    }
}

struct MigrationUnitListView: View {
    let units: [MigrationUnit]
    @Binding var selectedUnitID: MigrationUnit.ID?
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        List(selection: $selectedUnitID) {
            if units.isEmpty {
                Text("No units")
                    .foregroundStyle(ForgisTheme.textSecondary(scheme))
            } else {
                ForEach(units) { unit in
                    VStack(alignment: .leading, spacing: 8) {
                        ViewThatFits(in: .horizontal) {
                            HStack(spacing: 8) {
                                unitID(unit.id)
                                Spacer(minLength: 8)
                                StatusPill(text: unit.status.rawValue, tone: statusTone(unit.status))
                            }

                            VStack(alignment: .leading, spacing: 6) {
                                unitID(unit.id)
                                StatusPill(text: unit.status.rawValue, tone: statusTone(unit.status))
                            }
                        }

                        Text(unit.title)
                            .font(ForgisType.body(13, weight: .semibold))
                            .foregroundStyle(ForgisTheme.textPrimary(scheme))
                            .lineLimit(1)
                            .truncationMode(.tail)

                        PathLabel(path: unit.sourcePath)
                        PathLabel(path: unit.targetPath)

                    }
                    .padding(.vertical, 8)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .tag(unit.id)
                }
            }
        }
        .listStyle(.inset)
        .scrollContentBackground(.hidden)
        .background {
            ForgisSystemCanvas()
        }
    }

    private func unitID(_ id: String) -> some View {
        Text(id)
            .font(ForgisType.mono(11, weight: .semibold))
            .foregroundStyle(ForgisTheme.textTertiary(scheme))
            .lineLimit(1)
            .truncationMode(.middle)
    }
}

struct MigrationUnitDetailView: View {
    let unit: MigrationUnit?
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                if let unit {
                    SectionCard(title: "Summary") {
                        InfoRow(title: "Unit", value: unit.id, monospaced: true)
                        InfoRow(title: "Title", value: unit.title)
                        InfoRow(title: "Status", value: unit.status.rawValue)
                        InfoRow(title: "Risk", value: unit.risk.rawValue)
                        InfoRow(title: "Validation", value: unit.validation.rawValue)
                    }

                    SectionCard(title: "Paths") {
                        InfoRow(title: "Source", value: unit.sourcePath, monospaced: true)
                        InfoRow(title: "Target", value: unit.targetPath, monospaced: true)
                    }

                    SectionCard(title: "Report") {
                        InfoRow(title: "Last report", value: unit.lastReport, monospaced: true)
                    }
                } else {
                    Text("No run selected")
                        .font(ForgisType.body(13))
                        .foregroundStyle(ForgisTheme.textSecondary(scheme))
                        .frame(maxWidth: .infinity, alignment: .center)
                        .padding(24)
                }
            }
            .padding(16)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .background {
            ForgisSystemCanvas()
        }
    }
}

struct InspectorView: View {
    let activeSection: ForgisSection
    let unit: MigrationUnit?
    let report: ReportSummary
    let safety: [SafetyItem]
    @ObservedObject var chatModel: ForgisChatViewModel
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                Text("Inspector")
                    .font(ForgisType.sectionTitle())
                    .foregroundStyle(ForgisTheme.textPrimary(scheme))

                switch activeSection {
                case .aiChat:
                    ChatInspectorView(model: chatModel, safety: safety)

                case .migration:
                    if let unit {
                        SectionCard(title: "Unit") {
                            InfoRow(title: "Unit", value: unit.id, monospaced: true)
                            InfoRow(title: "Status", value: unit.status.rawValue)
                            InfoRow(title: "Risk", value: unit.risk.rawValue)
                            InfoRow(title: "Source", value: unit.sourcePath, monospaced: true)
                            InfoRow(title: "Target", value: unit.targetPath, monospaced: true)
                        }

                        SectionCard(title: "Run") {
                            InfoRow(title: "Validation", value: unit.validation.rawValue)
                            InfoRow(title: "Report", value: unit.lastReport, monospaced: true)
                            SafetyStrip(items: safety)
                        }
                    } else {
                        Text("No run selected")
                            .font(ForgisType.body(13))
                            .foregroundStyle(ForgisTheme.textSecondary(scheme))
                    }

                case .reports:
                    SectionCard(title: "Report") {
                        InfoRow(title: "Name", value: report.title)
                        InfoRow(title: "Status", value: report.status)
                        InfoRow(title: "Schema", value: report.schema, monospaced: true)
                        InfoRow(title: "Validation", value: report.validation.rawValue)
                        SafetyStrip(items: safety)
                    }

                case .settings:
                    SectionCard(title: "Connection") {
                        InfoRow(title: "Model", value: chatModel.configuration.model, monospaced: true)
                        InfoRow(title: "API base", value: chatModel.configuration.apiBase, monospaced: true)
                        InfoRow(title: "Auth", value: chatModel.apiKeyStatus)
                        SafetyStrip(items: safety)
                    }
                }
            }
            .padding(16)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .background {
            ForgisSystemCanvas()
        }
    }
}

struct ReportPanelView: View {
    let report: ReportSummary

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                ForgisPageHeader(
                    title: "Report"
                )

                SectionCard(title: "Current") {
                    InfoRow(title: "Name", value: report.title)
                    InfoRow(title: "Status", value: report.status)
                    InfoRow(title: "Path", value: report.path, monospaced: true)
                    InfoRow(title: "Schema", value: report.schema, monospaced: true)
                    InfoRow(title: "Validation", value: report.validation.rawValue)
                }
            }
            .padding(18)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .background {
            ForgisSystemCanvas()
        }
    }
}

struct SettingsView: View {
    let run: MigrationRun
    let mode: RunMode
    @ObservedObject var chatModel: ForgisChatViewModel
    @Environment(\.colorScheme) private var scheme
    @State private var providerDraft: String
    @State private var modelDraft: String
    @State private var apiBaseDraft: String
    @State private var apiKeyEnvNameDraft: String
    @State private var timeoutDraft: Double
    @State private var requiresAuthenticationDraft: Bool
    @State private var apiKeyDraft = ""

    init(run: MigrationRun, mode: RunMode, chatModel: ForgisChatViewModel) {
        self.run = run
        self.mode = mode
        self.chatModel = chatModel
        _providerDraft = State(initialValue: chatModel.configuration.provider)
        _modelDraft = State(initialValue: chatModel.configuration.model)
        _apiBaseDraft = State(initialValue: chatModel.configuration.apiBase)
        _apiKeyEnvNameDraft = State(initialValue: chatModel.configuration.apiKeyEnvName)
        _timeoutDraft = State(initialValue: chatModel.configuration.timeoutSeconds)
        _requiresAuthenticationDraft = State(initialValue: chatModel.configuration.requiresAuthentication)
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                ForgisPageHeader(
                    title: "Settings"
                )

                SectionCard(title: "Provider") {
                    SettingsFieldRow(title: "Provider", text: $providerDraft)
                    SettingsFieldRow(title: "Model", text: $modelDraft, monospaced: true)
                    SettingsFieldRow(title: "API base", text: $apiBaseDraft, monospaced: true)
                    SettingsFieldRow(title: "API key env", text: $apiKeyEnvNameDraft, monospaced: true)
                    Toggle("Require API key", isOn: $requiresAuthenticationDraft)
                        .font(ForgisType.body(12))
                    HStack(alignment: .firstTextBaseline, spacing: 10) {
                        Text("Timeout")
                            .font(ForgisType.caption(11, weight: .semibold))
                            .foregroundStyle(ForgisTheme.textTertiary(scheme))
                        Stepper("\(Int(timeoutDraft))s", value: $timeoutDraft, in: 5...600, step: 5)
                            .font(ForgisType.body(12))
                    }
                    ViewThatFits(in: .horizontal) {
                        HStack(spacing: 8) {
                            providerActions
                        }
                        VStack(alignment: .leading, spacing: 8) {
                            providerActions
                        }
                    }
                    .padding(.top, 2)
                }

                SectionCard(title: "API key") {
                    InfoRow(title: "Status", value: chatModel.apiKeyStatus)
                    InfoRow(title: "Source", value: chatModel.secretStatus.detail)
                    SecureField("New API key", text: $apiKeyDraft)
                        .textFieldStyle(.roundedBorder)
                        .font(ForgisType.body(12))
                        .disabled(!requiresAuthenticationDraft)
                    ViewThatFits(in: .horizontal) {
                        HStack(spacing: 8) {
                            keyActions
                        }
                        VStack(alignment: .leading, spacing: 8) {
                            keyActions
                        }
                    }
                    .padding(.top, 2)
                }

                if let settingsStatusText = chatModel.settingsStatusText {
                    Text(settingsStatusText)
                        .font(ForgisType.caption(12))
                        .foregroundStyle(chatModel.secretStatus.isError ? ForgisTheme.danger : ForgisTheme.textSecondary(scheme))
                        .fixedSize(horizontal: false, vertical: true)
                }

                SectionCard(title: "Paths") {
                    InfoRow(title: "Config", value: run.configPath, monospaced: true)
                    InfoRow(title: "Source", value: run.sourcePath, monospaced: true)
                    InfoRow(title: "Target", value: run.targetPath, monospaced: true)
                    InfoRow(title: "Target subdir", value: run.targetSubdir, monospaced: true)
                    InfoRow(title: "Mode", value: mode.title)
                }
            }
            .padding(18)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .background {
            ForgisSystemCanvas()
        }
        .onAppear {
            syncDrafts()
            chatModel.refreshSecretStatus()
        }
        .onChange(of: chatModel.configuration) { _ in
            syncDrafts()
        }
    }

    private var providerActions: some View {
        Group {
            Button {
                if saveProviderSettings() {
                    syncDrafts()
                }
            } label: {
                Label("Save", systemImage: "checkmark")
            }
            .forgisGlassButton(prominent: true)

            Button {
                chatModel.resetConfiguration()
                syncDrafts()
            } label: {
                Label("Reset", systemImage: "arrow.counterclockwise")
            }
            .forgisGlassButton()

            Button {
                if saveProviderSettings() {
                    syncDrafts()
                    chatModel.testConnection()
                }
            } label: {
                if chatModel.isTestingConnection {
                    Label("Testing", systemImage: "network")
                } else {
                    Label("Test", systemImage: "network")
                }
            }
            .disabled(chatModel.isSending || chatModel.isTestingConnection)
            .forgisGlassButton()
        }
        .controlSize(.small)
    }

    private var keyActions: some View {
        Group {
            Button {
                if chatModel.saveAPIKey(apiKeyDraft) {
                    apiKeyDraft = ""
                }
            } label: {
                Label("Save key", systemImage: "key.fill")
            }
            .disabled(!requiresAuthenticationDraft || apiKeyDraft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            .forgisGlassButton()

            Button(role: .destructive) {
                chatModel.deleteStoredAPIKey()
            } label: {
                Label("Delete key", systemImage: "trash")
            }
            .disabled(!chatModel.hasStoredAPIKey)
            .forgisGlassButton()
        }
        .controlSize(.small)
    }

    @discardableResult
    private func saveProviderSettings() -> Bool {
        chatModel.updateConfiguration(
            provider: providerDraft,
            model: modelDraft,
            apiBase: apiBaseDraft,
            apiKeyEnvName: apiKeyEnvNameDraft,
            timeoutSeconds: timeoutDraft,
            requiresAuthentication: requiresAuthenticationDraft
        )
    }

    private func syncDrafts() {
        providerDraft = chatModel.configuration.provider
        modelDraft = chatModel.configuration.model
        apiBaseDraft = chatModel.configuration.apiBase
        apiKeyEnvNameDraft = chatModel.configuration.apiKeyEnvName
        timeoutDraft = chatModel.configuration.timeoutSeconds
        requiresAuthenticationDraft = chatModel.configuration.requiresAuthentication
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
                .font(monospaced ? ForgisType.mono(12) : ForgisType.body(12))
                .lineLimit(1)
        }
    }
}
#endif
