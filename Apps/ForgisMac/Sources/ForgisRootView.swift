#if canImport(SwiftUI)
import SwiftUI

struct ForgisRootView: View {
    @State private var section: ForgisSection? = .aiChat
    @State private var selectedUnitID: MigrationUnit.ID? = MockForgisData.units.first?.id
    @State private var runMode: RunMode = MockForgisData.run.mode
    @StateObject private var chatModel = ForgisChatViewModel(
        configuration: ForgisChatConfiguration.from(run: MockForgisData.run)
    )

    private let run = MockForgisData.run
    private let units = MockForgisData.units
    private let report = MockForgisData.report

    private var selectedUnit: MigrationUnit? {
        guard let selectedUnitID else { return nil }
        return units.first { $0.id == selectedUnitID }
    }

    private var activeSection: ForgisSection {
        section ?? .migration
    }

    var body: some View {
        NavigationSplitView {
            SidebarView(selection: $section, run: run, mode: runMode)
                .navigationSplitViewColumnWidth(min: 180, ideal: 210, max: 250)
        } content: {
            content
                .navigationSplitViewColumnWidth(min: 360, ideal: 560)
        } detail: {
            InspectorView(
                activeSection: activeSection,
                unit: selectedUnit,
                report: report,
                safety: MockForgisData.safety,
                chatModel: chatModel
            )
                .navigationSplitViewColumnWidth(min: 240, ideal: 300, max: 360)
        }
        .frame(minWidth: 900, minHeight: 600)
    }

    @ViewBuilder private var content: some View {
        switch activeSection {
        case .aiChat:
            AIChatWorkspaceView(model: chatModel, safety: MockForgisData.safety)
        case .migration:
            MigrationWorkspaceView(
                units: units,
                selectedUnitID: $selectedUnitID,
                selectedUnit: selectedUnit,
                safety: MockForgisData.safety
            )
        case .reports:
            ReportPanelView(report: report)
        case .settings:
            SettingsView(run: run, mode: runMode, chatModel: chatModel)
        }
    }
}
#endif
