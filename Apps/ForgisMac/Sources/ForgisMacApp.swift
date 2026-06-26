#if canImport(SwiftUI)
import SwiftUI

@main
struct ForgisMacApp: App {
    var body: some Scene {
        WindowGroup {
            ForgisRootView()
        }
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
