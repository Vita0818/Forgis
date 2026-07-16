#if canImport(SwiftUI)
import Foundation
import SwiftUI

enum ForgisChatRole: String, Codable {
    case system
    case user
    case assistant
}

struct ForgisChatMessage: Identifiable, Codable, Equatable {
    let id: UUID
    var role: ForgisChatRole
    var text: String
    var isComplete: Bool
    let createdAt: Date

    init(
        id: UUID = UUID(),
        role: ForgisChatRole,
        text: String,
        isComplete: Bool = true,
        createdAt: Date = Date()
    ) {
        self.id = id
        self.role = role
        self.text = text
        self.isComplete = isComplete
        self.createdAt = createdAt
    }
}

struct ForgisChatConfiguration: Equatable {
    var provider: String
    var model: String
    var apiBase: String
    var apiKeyEnvName: String
    var timeoutSeconds: TimeInterval
    var requiresAuthentication: Bool
    var keychainService: String
    var keychainAccount: String

    static func from(run: MigrationRun) -> ForgisChatConfiguration {
        ForgisChatConfiguration(
            provider: run.provider,
            model: run.model,
            apiBase: run.apiBase,
            apiKeyEnvName: run.apiKeyEnvName,
            timeoutSeconds: 120,
            requiresAuthentication: true,
            keychainService: "com.vita.forgis.mac.chat",
            keychainAccount: "default-openai-compatible"
        )
    }

    var hostLabel: String {
        guard let url = URL(string: apiBase), let host = url.host else {
            return apiBase
        }
        return host
    }

    func envAPIKey(in environment: [String: String]) -> String? {
        let value = environment[apiKeyEnvName]?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return value.isEmpty ? nil : value
    }
}

enum ForgisChatSecretStatus: Equatable {
    case notRequired
    case keychainSet
    case environmentSet(String)
    case unset
    case error(String)

    var label: String {
        switch self {
        case .notRequired: return "no auth"
        case .keychainSet: return "keychain"
        case .environmentSet: return "env"
        case .unset: return "unset"
        case .error: return "error"
        }
    }

    var detail: String {
        switch self {
        case .notRequired:
            return "Authentication disabled"
        case .keychainSet:
            return "Keychain item set"
        case .environmentSet(let name):
            return "\(name) set"
        case .unset:
            return "No API key set"
        case .error(let message):
            return message
        }
    }

    var isUsable: Bool {
        switch self {
        case .notRequired, .keychainSet, .environmentSet:
            return true
        case .unset, .error:
            return false
        }
    }

    var isError: Bool {
        if case .error = self {
            return true
        }
        return false
    }
}

@MainActor
final class ForgisChatViewModel: ObservableObject {
    @Published private(set) var messages: [ForgisChatMessage] = []
    @Published var input: String = ""
    @Published private(set) var isSending = false
    @Published private(set) var isTestingConnection = false
    @Published private(set) var errorText: String?
    @Published var configuration: ForgisChatConfiguration
    @Published private(set) var secretStatus: ForgisChatSecretStatus = .unset
    @Published private(set) var settingsStatusText: String?

    private let client: ForgisOpenAICompatibleChatClient
    private let preferencesStore: ForgisChatPreferencesStore
    private let defaultConfiguration: ForgisChatConfiguration
    private var keychainStore: ForgisKeychainSecretStore

    init(
        configuration: ForgisChatConfiguration,
        client: ForgisOpenAICompatibleChatClient = ForgisOpenAICompatibleChatClient(),
        preferencesStore: ForgisChatPreferencesStore = ForgisChatPreferencesStore()
    ) {
        let storedConfiguration = preferencesStore.load(fallback: configuration)
        self.configuration = storedConfiguration
        self.client = client
        self.preferencesStore = preferencesStore
        self.defaultConfiguration = configuration
        self.keychainStore = ForgisKeychainSecretStore(service: storedConfiguration.keychainService)
        refreshSecretStatus()
    }

    var canSend: Bool {
        !isSending && !isTestingConnection && !input.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    var statusText: String {
        if isSending { return "Waiting" }
        if isTestingConnection { return "Testing" }
        return "Idle"
    }

    var apiKeyStatus: String {
        secretStatus.label
    }

    var hasStoredAPIKey: Bool {
        secretStatus == .keychainSet
    }

    func send() {
        guard canSend else { return }
        let prompt = input.trimmingCharacters(in: .whitespacesAndNewlines)

        let apiKey: String?
        switch requestAPIKey() {
        case .success(let value):
            apiKey = value
        case .failure(let message):
            errorText = message
            return
        }

        let requestMessages = providerMessages(adding: prompt)
        input = ""
        errorText = nil
        isSending = true
        messages.append(ForgisChatMessage(role: .user, text: prompt))
        let assistantID = UUID()
        messages.append(ForgisChatMessage(id: assistantID, role: .assistant, text: "", isComplete: false))

        let config = configuration
        Task { @MainActor [weak self] in
            guard let self else { return }
            do {
                let response = try await client.complete(
                    messages: requestMessages,
                    configuration: config,
                    apiKey: apiKey
                )
                updateAssistantMessage(id: assistantID, text: response, isComplete: true)
            } catch {
                updateAssistantMessage(id: assistantID, text: "Request failed.", isComplete: true)
                errorText = error.localizedDescription
            }
            isSending = false
        }
    }

    func clear() {
        guard !isSending && !isTestingConnection else { return }
        messages = []
        errorText = nil
    }

    func testConnection() {
        guard !isSending && !isTestingConnection else { return }

        let apiKey: String?
        switch requestAPIKey() {
        case .success(let value):
            apiKey = value
        case .failure(let message):
            settingsStatusText = message
            return
        }

        let config = configuration
        isTestingConnection = true
        settingsStatusText = "Testing provider..."
        errorText = nil

        Task { @MainActor [weak self] in
            guard let self else { return }
            do {
                _ = try await client.complete(
                    messages: [
                        ForgisProviderChatMessage(
                            role: .system,
                            content: "You are a connection test for the Forgis Mac app. Reply with one short sentence."
                        ),
                        ForgisProviderChatMessage(role: .user, content: "Confirm the chat endpoint is reachable."),
                    ],
                    configuration: config,
                    apiKey: apiKey
                )
                settingsStatusText = "Provider test passed."
            } catch {
                settingsStatusText = error.localizedDescription
            }
            isTestingConnection = false
            refreshSecretStatus()
        }
    }

    func refreshSecretStatus() {
        guard configuration.requiresAuthentication else {
            secretStatus = .notRequired
            return
        }

        do {
            keychainStore = ForgisKeychainSecretStore(service: configuration.keychainService)
            if try keychainStore.hasSecret(account: configuration.keychainAccount) {
                secretStatus = .keychainSet
                return
            }
        } catch {
            secretStatus = .error(error.localizedDescription)
            return
        }

        if configuration.envAPIKey(in: ProcessInfo.processInfo.environment) != nil {
            secretStatus = .environmentSet(configuration.apiKeyEnvName)
        } else {
            secretStatus = .unset
        }
    }

    @discardableResult
    func updateConfiguration(
        provider: String,
        model: String,
        apiBase: String,
        apiKeyEnvName: String,
        timeoutSeconds: TimeInterval,
        requiresAuthentication: Bool
    ) -> Bool {
        do {
            let next = try ForgisChatConfiguration.validated(
                provider: provider,
                model: model,
                apiBase: apiBase,
                apiKeyEnvName: apiKeyEnvName,
                timeoutSeconds: timeoutSeconds,
                requiresAuthentication: requiresAuthentication,
                keychainService: configuration.keychainService,
                keychainAccount: configuration.keychainAccount
            )
            configuration = next
            preferencesStore.save(next)
            settingsStatusText = "Settings saved."
            errorText = nil
            refreshSecretStatus()
            return true
        } catch {
            settingsStatusText = error.localizedDescription
            return false
        }
    }

    @discardableResult
    func saveAPIKey(_ rawValue: String) -> Bool {
        let value = rawValue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !value.isEmpty else {
            settingsStatusText = ForgisChatSettingsError.emptyAPIKey.localizedDescription
            return false
        }

        do {
            try keychainStore.saveSecret(value, account: configuration.keychainAccount)
            settingsStatusText = "API key saved to Keychain."
            errorText = nil
            refreshSecretStatus()
            return true
        } catch {
            settingsStatusText = error.localizedDescription
            refreshSecretStatus()
            return false
        }
    }

    func deleteStoredAPIKey() {
        do {
            try keychainStore.deleteSecret(account: configuration.keychainAccount)
            settingsStatusText = "Keychain item deleted."
            refreshSecretStatus()
        } catch {
            settingsStatusText = error.localizedDescription
            refreshSecretStatus()
        }
    }

    func resetConfiguration() {
        preferencesStore.reset()
        configuration = defaultConfiguration
        settingsStatusText = "Settings reset."
        errorText = nil
        refreshSecretStatus()
    }

    private enum APIKeyResolution {
        case success(String?)
        case failure(String)
    }

    private func requestAPIKey() -> APIKeyResolution {
        guard configuration.requiresAuthentication else {
            refreshSecretStatus()
            return .success(nil)
        }

        do {
            keychainStore = ForgisKeychainSecretStore(service: configuration.keychainService)
            if let stored = try keychainStore.readSecret(account: configuration.keychainAccount) {
                refreshSecretStatus()
                return .success(stored)
            }
        } catch {
            refreshSecretStatus()
            return .failure(error.localizedDescription)
        }

        if let envValue = configuration.envAPIKey(in: ProcessInfo.processInfo.environment) {
            refreshSecretStatus()
            return .success(envValue)
        }

        refreshSecretStatus()
        return .failure("API key is unset.")
    }

    private func providerMessages(adding prompt: String) -> [ForgisProviderChatMessage] {
        var result = [
            ForgisProviderChatMessage(
                role: .system,
                content: """
                You are the Forgis AI chat assistant inside the local Forgis Mac app. Help with code migration planning, migration units, run reports, validation results, dry-run and real-run gates, and provider configuration. You do not have filesystem or shell access from this chat. Do not ask for or reveal secrets.
                """
            )
        ]

        for message in messages where message.isComplete {
            switch message.role {
            case .user:
                result.append(ForgisProviderChatMessage(role: .user, content: message.text))
            case .assistant:
                if !message.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                    result.append(ForgisProviderChatMessage(role: .assistant, content: message.text))
                }
            case .system:
                break
            }
        }
        result.append(ForgisProviderChatMessage(role: .user, content: prompt))
        return result
    }

    private func updateAssistantMessage(id: UUID, text: String, isComplete: Bool) {
        guard let index = messages.firstIndex(where: { $0.id == id }) else { return }
        messages[index].text = text
        messages[index].isComplete = isComplete
    }
}
#endif
