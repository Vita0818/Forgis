#if canImport(SwiftUI)
import SwiftUI

struct ForgisRootView: View {
    @State private var section: ForgisSection? = .migration
    @State private var selectedUnitID: MigrationUnit.ID? = MockForgisData.units.first?.id
    @State private var runMode: RunMode = MockForgisData.run.mode

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
                .navigationSplitViewColumnWidth(min: 190, ideal: 220, max: 260)
        } content: {
            content
                .navigationSplitViewColumnWidth(min: 440, ideal: 620)
        } detail: {
            InspectorView(unit: selectedUnit, report: report, safety: MockForgisData.safety)
                .navigationSplitViewColumnWidth(min: 280, ideal: 320, max: 380)
        }
        .frame(minWidth: 1120, minHeight: 700)
    }

    @ViewBuilder private var content: some View {
        switch activeSection {
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
            SettingsView(run: run, mode: runMode)
        }
    }
}
#endif
