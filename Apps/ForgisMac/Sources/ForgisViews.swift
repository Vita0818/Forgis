#if canImport(SwiftUI)
import SwiftUI

struct SidebarView: View {
    @Binding var selection: ForgisSection?
    let run: MigrationRun
    let mode: RunMode
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        List(selection: $selection) {
            Section {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Forgis")
                        .font(ForgisType.appTitle())
                        .foregroundStyle(ForgisTheme.textPrimary(scheme))
                    Text("Mac")
                        .font(ForgisType.caption(11, weight: .semibold))
                        .foregroundStyle(ForgisTheme.textSecondary(scheme))
                }
                .padding(.vertical, 8)
            }

            Section {
                ForEach(ForgisSection.allCases) { item in
                    Label(item.title, systemImage: item.icon)
                        .tag(item)
                }
            }

            Section("Run") {
                VStack(alignment: .leading, spacing: 7) {
                    PathLabel(path: run.sourcePath)
                    PathLabel(path: run.targetPath)
                    StatusPill(text: mode.title, tone: .accent)
                }
                .padding(.vertical, 4)
            }
        }
        .listStyle(.sidebar)
    }
}

struct MigrationWorkspaceView: View {
    let units: [MigrationUnit]
    @Binding var selectedUnitID: MigrationUnit.ID?
    let selectedUnit: MigrationUnit?
    let safety: [SafetyItem]
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Text("Migration Units")
                    .font(ForgisType.sectionTitle(20))
                    .foregroundStyle(ForgisTheme.textPrimary(scheme))
                Spacer()
                Button("Run doctor") {}
                    .disabled(true)
                Button("Run smoke") {}
                    .disabled(true)
            }
            .padding(.horizontal, 18)
            .padding(.top, 18)
            .padding(.bottom, 10)

            Divider()

            HSplitView {
                MigrationUnitListView(units: units, selectedUnitID: $selectedUnitID)
                    .frame(minWidth: 280, idealWidth: 330)
                MigrationUnitDetailView(unit: selectedUnit, safety: safety)
                    .frame(minWidth: 300, idealWidth: 420)
            }
        }
        .background(ForgisTheme.background(scheme))
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
                        HStack(spacing: 8) {
                            Text(unit.id)
                                .font(ForgisType.mono(11, weight: .semibold))
                                .foregroundStyle(ForgisTheme.textTertiary(scheme))
                            Spacer(minLength: 8)
                            StatusPill(text: unit.status.rawValue, tone: statusTone(unit.status))
                        }

                        Text(unit.title)
                            .font(ForgisType.body(13, weight: .semibold))
                            .foregroundStyle(ForgisTheme.textPrimary(scheme))
                            .lineLimit(1)

                        PathLabel(path: unit.sourcePath)
                        PathLabel(path: unit.targetPath)

                        HStack(spacing: 6) {
                            StatusPill(text: unit.risk.rawValue, tone: riskTone(unit.risk))
                            ValidationBadge(state: unit.validation)
                        }
                    }
                    .padding(.vertical, 8)
                    .tag(unit.id)
                }
            }
        }
        .listStyle(.inset)
        .scrollContentBackground(.hidden)
        .background(ForgisTheme.background(scheme))
    }
}

struct MigrationUnitDetailView: View {
    let unit: MigrationUnit?
    let safety: [SafetyItem]
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                if let unit {
                    SectionCard(title: "Summary") {
                        InfoRow(title: "Unit", value: unit.id, monospaced: true)
                        InfoRow(title: "Title", value: unit.title)
                        HStack(spacing: 8) {
                            StatusPill(text: unit.status.rawValue, tone: statusTone(unit.status))
                            StatusPill(text: unit.risk.rawValue, tone: riskTone(unit.risk))
                            ValidationBadge(state: unit.validation)
                        }
                    }

                    SectionCard(title: "Paths") {
                        InfoRow(title: "Source", value: unit.sourcePath, monospaced: true)
                        InfoRow(title: "Target", value: unit.targetPath, monospaced: true)
                    }

                    SectionCard(title: "Report") {
                        InfoRow(title: "Last report", value: unit.lastReport, monospaced: true)
                        Button("Open report") {}
                            .disabled(true)
                    }

                    SectionCard(title: "Safety") {
                        SafetyStrip(items: safety)
                    }
                } else {
                    Text("No run selected")
                        .font(ForgisType.body(13))
                        .foregroundStyle(ForgisTheme.textSecondary(scheme))
                        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center)
                        .padding(24)
                }
            }
            .padding(16)
        }
        .background(ForgisTheme.background(scheme))
    }
}

struct InspectorView: View {
    let unit: MigrationUnit?
    let report: ReportSummary
    let safety: [SafetyItem]
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                Text("Inspector")
                    .font(ForgisType.sectionTitle())
                    .foregroundStyle(ForgisTheme.textPrimary(scheme))

                if let unit {
                    SectionCard(title: "Summary") {
                        InfoRow(title: "Unit", value: unit.id, monospaced: true)
                        InfoRow(title: "Status", value: unit.status.rawValue)
                        InfoRow(title: "Risk", value: unit.risk.rawValue)
                    }

                    SectionCard(title: "Source / Target") {
                        InfoRow(title: "Source", value: unit.sourcePath, monospaced: true)
                        InfoRow(title: "Target", value: unit.targetPath, monospaced: true)
                    }

                    SectionCard(title: "Last report") {
                        InfoRow(title: "Report", value: unit.lastReport, monospaced: true)
                    }

                    SectionCard(title: "Validation") {
                        ValidationBadge(state: unit.validation)
                    }
                } else {
                    Text("No run selected")
                        .font(ForgisType.body(13))
                        .foregroundStyle(ForgisTheme.textSecondary(scheme))
                }

                SectionCard(title: "Safety") {
                    SafetyStrip(items: safety)
                }

                SectionCard(title: "Report") {
                    InfoRow(title: "Schema", value: report.schema, monospaced: true)
                    ValidationBadge(state: report.validation)
                }
            }
            .padding(16)
        }
        .background(ForgisTheme.surface(scheme))
    }
}

struct ReportPanelView: View {
    let report: ReportSummary
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                Text("Report")
                    .font(ForgisType.sectionTitle(20))
                    .foregroundStyle(ForgisTheme.textPrimary(scheme))

                SectionCard(title: "Current") {
                    InfoRow(title: "Name", value: report.title)
                    InfoRow(title: "Status", value: report.status)
                    InfoRow(title: "Path", value: report.path, monospaced: true)
                    InfoRow(title: "Schema", value: report.schema, monospaced: true)
                    ValidationBadge(state: report.validation)
                }

                Button("Open report") {}
                    .disabled(true)
            }
            .padding(18)
        }
        .background(ForgisTheme.background(scheme))
    }
}

struct SettingsView: View {
    let run: MigrationRun
    let mode: RunMode
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                Text("Settings")
                    .font(ForgisType.sectionTitle(20))
                    .foregroundStyle(ForgisTheme.textPrimary(scheme))

                SectionCard(title: "Provider") {
                    InfoRow(title: "Provider", value: run.provider)
                    InfoRow(title: "Model", value: run.model, monospaced: true)
                    InfoRow(title: "API base", value: run.apiBase, monospaced: true)
                    InfoRow(title: "API key env", value: run.apiKeyEnvName, monospaced: true)
                    HStack {
                        Text("API key")
                            .font(ForgisType.caption(11, weight: .semibold))
                            .foregroundStyle(ForgisTheme.textTertiary(scheme))
                            .frame(width: 96, alignment: .leading)
                        StatusPill(text: run.apiKeyStatus, tone: run.apiKeyStatus == "set" ? .success : .warning)
                        Spacer()
                    }
                }

                SectionCard(title: "Paths") {
                    InfoRow(title: "Config", value: run.configPath, monospaced: true)
                    InfoRow(title: "Source", value: run.sourcePath, monospaced: true)
                    InfoRow(title: "Target", value: run.targetPath, monospaced: true)
                    InfoRow(title: "Target subdir", value: run.targetSubdir, monospaced: true)
                }

                SectionCard(title: "Run mode") {
                    StatusPill(text: mode.title, tone: .accent)
                }

                HStack {
                    Button("Open config") {}
                        .disabled(true)
                    Button("Dry run") {}
                        .disabled(true)
                }
            }
            .padding(18)
        }
        .background(ForgisTheme.background(scheme))
    }
}
#endif
