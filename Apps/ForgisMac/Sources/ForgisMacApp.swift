#if canImport(SwiftUI)
import SwiftUI

@main
struct ForgisMacApp: App {
    init() {
        ForgisCodexRuntimeBootstrap.configureProcess()
        ForgisCodexRuntimeSmokeRunner.runIfRequested()
    }

    var body: some Scene {
        WindowGroup {
            ForgisRootView()
        }
        .defaultSize(width: 1100, height: 760)
        .windowResizability(.contentMinSize)
    }
}
#else
@main
struct ForgisMacApp {
    static func main() {
        ForgisCodexRuntimeBootstrap.configureProcess()
        print("ForgisMac requires SwiftUI on macOS.")
    }
}
#endif
