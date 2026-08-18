#if canImport(SwiftUI)
import SwiftUI

@main
struct ForgisMacApp: App {
    init() {
        ForgisChatSmokeRunner.runIfRequested()
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
        print("ForgisMac requires SwiftUI on macOS.")
    }
}
#endif
