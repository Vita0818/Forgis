#if canImport(SwiftUI)
import Foundation
import IntatisCodexRuntime
import IntatisCore
import IntatisProtocol
import IntatisProviders
#if canImport(Darwin)
import Darwin
#endif

enum ForgisCodexRuntimeSmokeRunner {
    private static let trigger = "--forgis-codex-runtime-smoke"

    static func runIfRequested(arguments: [String] = CommandLine.arguments) {
        guard arguments.contains(trigger) else { return }

        let semaphore = DispatchSemaphore(value: 0)
        var exitCode: Int32 = 1
        Task {
            exitCode = await run()
            semaphore.signal()
        }
        semaphore.wait()
        exit(exitCode)
    }

    private static func run() async -> Int32 {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent(
                "forgis-mac-codex-smoke-\(UUID().uuidString.lowercased())",
                isDirectory: true)
        defer { try? FileManager.default.removeItem(at: root) }

        do {
            let workspace = root.appendingPathComponent("workspace", isDirectory: true)
            let runtimeRoot = root.appendingPathComponent("runtime", isDirectory: true)
            try FileManager.default.createDirectory(
                at: workspace,
                withIntermediateDirectories: true)
            let route = ResponsesRuntimeRoute(
                endpointID: "forgis-mac-offline-smoke",
                model: ModelID(rawValue: "forgis-mac-offline-smoke-model"),
                baseURL: URL(string: "http://127.0.0.1:9/v1")!,
                bearerToken: "forgis-mac-offline-smoke-token")
            let session = CodexAppServerSession(configuration:
                CodexRuntimeConfiguration(
                    sessionID: SessionID(
                        rawValue: "forgis_mac_smoke_\(UUID().uuidString.lowercased())"),
                    mode: .code,
                    workspaceURL: workspace,
                    runtimeRootURL: runtimeRoot,
                    route: route))
            let identity: CodexRuntimeIdentity
            do {
                identity = try await session.start()
            } catch {
                await session.shutdown()
                throw error
            }
            await session.shutdown()
            print(
                "FORGIS_CODEX_RUNTIME_SMOKE_OK version=\(identity.runtimeVersion) network_requests=0")
            return 0
        } catch {
            print(
                "FORGIS_CODEX_RUNTIME_SMOKE_FAILED: \(bounded(error.localizedDescription))")
            return 1
        }
    }

    private static func bounded(_ value: String, limit: Int = 300) -> String {
        let clean = value
            .replacingOccurrences(of: "\r", with: " ")
            .replacingOccurrences(of: "\n", with: " ")
        if clean.count <= limit { return clean }
        return String(clean.prefix(limit)) + "...[truncated]"
    }
}
#endif
