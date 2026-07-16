#if canImport(SwiftUI)
import Foundation
#if canImport(Darwin)
import Darwin
#endif

enum ForgisChatSmokeRunner {
    private static let trigger = "--forgis-chat-smoke"

    static func runIfRequested(
        arguments: [String] = CommandLine.arguments,
        environment: [String: String] = ProcessInfo.processInfo.environment
    ) {
        guard arguments.contains(trigger) else { return }

        let semaphore = DispatchSemaphore(value: 0)
        var exitCode: Int32 = 1

        Task {
            exitCode = await run(arguments: arguments, environment: environment)
            semaphore.signal()
        }

        semaphore.wait()
        exit(exitCode)
    }

    private static func run(arguments: [String], environment: [String: String]) async -> Int32 {
        do {
            let options = SmokeOptions(arguments: arguments)
            let configuration = try ForgisChatConfiguration.validated(
                provider: "smoke",
                model: options.model,
                apiBase: options.apiBase,
                apiKeyEnvName: options.apiKeyEnvName,
                timeoutSeconds: options.timeoutSeconds,
                requiresAuthentication: options.requiresAuthentication,
                keychainService: "com.vita.forgis.mac.chat.smoke",
                keychainAccount: "smoke"
            )

            let apiKey: String?
            if options.requiresAuthentication {
                guard let value = configuration.envAPIKey(in: environment) else {
                    print("FORGIS_CHAT_SMOKE_FAILED: \(configuration.apiKeyEnvName) is unset.")
                    return 2
                }
                apiKey = value
            } else {
                apiKey = nil
            }

            let response = try await ForgisOpenAICompatibleChatClient().complete(
                messages: [
                    ForgisProviderChatMessage(
                        role: .system,
                        content: "Reply exactly with FORGIS_SMOKE_OK."
                    ),
                    ForgisProviderChatMessage(role: .user, content: "smoke"),
                ],
                configuration: configuration,
                apiKey: apiKey
            )

            guard response.trimmingCharacters(in: .whitespacesAndNewlines) == "FORGIS_SMOKE_OK" else {
                print("FORGIS_CHAT_SMOKE_FAILED: unexpected response.")
                return 3
            }

            print("FORGIS_CHAT_SMOKE_OK")
            return 0
        } catch {
            print("FORGIS_CHAT_SMOKE_FAILED: \(bounded(error.localizedDescription))")
            return 1
        }
    }

    private static func bounded(_ value: String, limit: Int = 240) -> String {
        if value.count <= limit { return value }
        return String(value.prefix(limit)) + "...[truncated]"
    }

    private struct SmokeOptions {
        let apiBase: String
        let model: String
        let apiKeyEnvName: String
        let timeoutSeconds: TimeInterval
        let requiresAuthentication: Bool

        init(arguments: [String]) {
            apiBase = Self.value(after: "--api-base", in: arguments) ?? "http://127.0.0.1:8765/v1"
            model = Self.value(after: "--model", in: arguments) ?? "forgis-smoke-model"
            apiKeyEnvName = Self.value(after: "--api-key-env", in: arguments) ?? "FORGIS_CHAT_SMOKE_API_KEY"
            if let timeout = Self.value(after: "--timeout", in: arguments).flatMap(Double.init) {
                timeoutSeconds = timeout
            } else {
                timeoutSeconds = 10
            }
            requiresAuthentication = arguments.contains("--auth")
        }

        private static func value(after flag: String, in arguments: [String]) -> String? {
            guard let index = arguments.firstIndex(of: flag) else { return nil }
            let nextIndex = arguments.index(after: index)
            guard nextIndex < arguments.endIndex else { return nil }
            return arguments[nextIndex]
        }
    }
}
#endif
