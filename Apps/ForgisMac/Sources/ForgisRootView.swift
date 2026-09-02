#if canImport(SwiftUI)
import SwiftUI

struct ForgisRootView: View {
    @State private var section: ForgisSection? = .migration
    @StateObject private var runtimeModel = ForgisRuntimeViewModel()

    private var activeSection: ForgisSection {
        section ?? .migration
    }

    var body: some View {
        NavigationSplitView {
            SidebarView(
                selection: $section,
                mode: runtimeModel.runMode,
                status: runtimeModel.status)
                .navigationSplitViewColumnWidth(min: 200, ideal: 236, max: 270)
        } content: {
            ZStack {
                ForgisSystemCanvas().ignoresSafeArea()
                content
            }
            .navigationSplitViewColumnWidth(min: 420, ideal: 650)
        } detail: {
            ZStack {
                ForgisSystemCanvas().ignoresSafeArea()
                InspectorView(
                    activeSection: activeSection,
                    model: runtimeModel)
            }
            .navigationSplitViewColumnWidth(min: 260, ideal: 320, max: 390)
        }
        .tint(.accentColor)
        .frame(minWidth: 940, minHeight: 640)
        .onDisappear {
            Task { await runtimeModel.shutdown() }
        }
    }

    @ViewBuilder private var content: some View {
        switch activeSection {
        case .migration:
            MigrationWorkspaceView(model: runtimeModel)
        case .reports:
            ReportPanelView(model: runtimeModel)
        case .settings:
            SettingsView(model: runtimeModel)
        }
    }
}
#endif
