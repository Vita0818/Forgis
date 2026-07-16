#if canImport(SwiftUI)
import Foundation
#if canImport(Security)
import Security
#endif

enum ForgisChatSettingsError: LocalizedError {
    case emptyProvider
    case emptyModel
    case emptyAPIBase
    case invalidAPIBase
    case emptyAPIKeyEnvName
    case invalidTimeout
    case emptyAPIKey
    case keychainUnavailable
    case keychainUnexpectedStatus(OSStatus, String)
    case keychainInvalidData

    var errorDescription: String? {
        switch self {
        case .emptyProvider:
            return "Provider is empty."
        case .emptyModel:
            return "Model is empty."
        case .emptyAPIBase:
            return "API base is empty."
        case .invalidAPIBase:
            return "API base must be an HTTP or HTTPS URL."
        case .emptyAPIKeyEnvName:
            return "API key env is empty."
        case .invalidTimeout:
            return "Timeout must be between 5 and 600 seconds."
        case .emptyAPIKey:
            return "API key is empty."
        case .keychainUnavailable:
            return "Keychain is unavailable on this platform."
        case .keychainUnexpectedStatus(let status, let detail):
            return "Keychain operation failed: \(detail) (OSStatus \(status))."
        case .keychainInvalidData:
            return "Keychain item is not valid UTF-8 text."
        }
    }
}

struct ForgisChatPreferencesStore {
    var defaults: UserDefaults = .standard

    private enum Key {
        static let provider = "forgis.chat.provider"
        static let model = "forgis.chat.model"
        static let apiBase = "forgis.chat.apiBase"
        static let apiKeyEnvName = "forgis.chat.apiKeyEnvName"
        static let timeoutSeconds = "forgis.chat.timeoutSeconds"
        static let requiresAuthentication = "forgis.chat.requiresAuthentication"
    }

    func load(fallback: ForgisChatConfiguration) -> ForgisChatConfiguration {
        ForgisChatConfiguration(
            provider: storedString(Key.provider, fallback: fallback.provider),
            model: storedString(Key.model, fallback: fallback.model),
            apiBase: storedString(Key.apiBase, fallback: fallback.apiBase),
            apiKeyEnvName: storedString(Key.apiKeyEnvName, fallback: fallback.apiKeyEnvName),
            timeoutSeconds: storedTimeout(fallback: fallback.timeoutSeconds),
            requiresAuthentication: storedAuthenticationRequirement(fallback: fallback.requiresAuthentication),
            keychainService: fallback.keychainService,
            keychainAccount: fallback.keychainAccount
        )
    }

    func save(_ configuration: ForgisChatConfiguration) {
        defaults.set(configuration.provider, forKey: Key.provider)
        defaults.set(configuration.model, forKey: Key.model)
        defaults.set(configuration.apiBase, forKey: Key.apiBase)
        defaults.set(configuration.apiKeyEnvName, forKey: Key.apiKeyEnvName)
        defaults.set(configuration.timeoutSeconds, forKey: Key.timeoutSeconds)
        defaults.set(configuration.requiresAuthentication, forKey: Key.requiresAuthentication)
    }

    func reset() {
        defaults.removeObject(forKey: Key.provider)
        defaults.removeObject(forKey: Key.model)
        defaults.removeObject(forKey: Key.apiBase)
        defaults.removeObject(forKey: Key.apiKeyEnvName)
        defaults.removeObject(forKey: Key.timeoutSeconds)
        defaults.removeObject(forKey: Key.requiresAuthentication)
    }

    private func storedString(_ key: String, fallback: String) -> String {
        guard let stored = defaults.string(forKey: key)?.trimmingCharacters(in: .whitespacesAndNewlines),
              !stored.isEmpty else {
            return fallback
        }
        return stored
    }

    private func storedTimeout(fallback: TimeInterval) -> TimeInterval {
        guard defaults.object(forKey: Key.timeoutSeconds) != nil else { return fallback }
        let value = defaults.double(forKey: Key.timeoutSeconds)
        return (5...600).contains(value) ? value : fallback
    }

    private func storedAuthenticationRequirement(fallback: Bool) -> Bool {
        guard defaults.object(forKey: Key.requiresAuthentication) != nil else { return fallback }
        return defaults.bool(forKey: Key.requiresAuthentication)
    }
}

struct ForgisKeychainSecretStore {
    var service: String

    init(service: String) {
        self.service = service
    }

    func readSecret(account: String) throws -> String? {
        #if canImport(Security)
        var query = baseQuery(account: account)
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne

        var item: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &item)
        if status == errSecItemNotFound {
            return nil
        }
        guard status == errSecSuccess else {
            throw unexpectedStatus(status)
        }
        guard let data = item as? Data,
              let value = String(data: data, encoding: .utf8) else {
            throw ForgisChatSettingsError.keychainInvalidData
        }
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
        #else
        throw ForgisChatSettingsError.keychainUnavailable
        #endif
    }

    func hasSecret(account: String) throws -> Bool {
        #if canImport(Security)
        var query = baseQuery(account: account)
        query[kSecReturnAttributes as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        query[kSecUseAuthenticationUI as String] = kSecUseAuthenticationUISkip

        var item: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &item)
        if status == errSecSuccess || status == errSecInteractionNotAllowed {
            return true
        }
        if status == errSecItemNotFound {
            return false
        }
        throw unexpectedStatus(status)
        #else
        return false
        #endif
    }

    func saveSecret(_ value: String, account: String) throws {
        #if canImport(Security)
        let data = Data(value.utf8)
        let query = baseQuery(account: account)
        let update: [String: Any] = [kSecValueData as String: data]
        let updateStatus = SecItemUpdate(query as CFDictionary, update as CFDictionary)

        if updateStatus == errSecSuccess {
            return
        }
        if updateStatus != errSecItemNotFound {
            throw unexpectedStatus(updateStatus)
        }

        var add = query
        add[kSecValueData as String] = data
        add[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        let addStatus = SecItemAdd(add as CFDictionary, nil)
        guard addStatus == errSecSuccess else {
            throw unexpectedStatus(addStatus)
        }
        #else
        throw ForgisChatSettingsError.keychainUnavailable
        #endif
    }

    func deleteSecret(account: String) throws {
        #if canImport(Security)
        let status = SecItemDelete(baseQuery(account: account) as CFDictionary)
        if status == errSecSuccess || status == errSecItemNotFound {
            return
        }
        throw unexpectedStatus(status)
        #else
        throw ForgisChatSettingsError.keychainUnavailable
        #endif
    }

    #if canImport(Security)
    private func baseQuery(account: String) -> [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
    }

    private func unexpectedStatus(_ status: OSStatus) -> ForgisChatSettingsError {
        let detail = SecCopyErrorMessageString(status, nil) as String? ?? "Unknown Keychain error"
        return .keychainUnexpectedStatus(status, detail)
    }
    #endif
}

extension ForgisChatConfiguration {
    static func validated(
        provider: String,
        model: String,
        apiBase: String,
        apiKeyEnvName: String,
        timeoutSeconds: TimeInterval,
        requiresAuthentication: Bool,
        keychainService: String,
        keychainAccount: String
    ) throws -> ForgisChatConfiguration {
        let provider = provider.trimmingCharacters(in: .whitespacesAndNewlines)
        let model = model.trimmingCharacters(in: .whitespacesAndNewlines)
        let apiBase = try normalizedAPIBase(apiBase)
        let apiKeyEnvName = apiKeyEnvName.trimmingCharacters(in: .whitespacesAndNewlines)

        guard !provider.isEmpty else { throw ForgisChatSettingsError.emptyProvider }
        guard !model.isEmpty else { throw ForgisChatSettingsError.emptyModel }
        guard !apiKeyEnvName.isEmpty else { throw ForgisChatSettingsError.emptyAPIKeyEnvName }
        guard (5...600).contains(timeoutSeconds) else { throw ForgisChatSettingsError.invalidTimeout }

        return ForgisChatConfiguration(
            provider: provider,
            model: model,
            apiBase: apiBase,
            apiKeyEnvName: apiKeyEnvName,
            timeoutSeconds: timeoutSeconds,
            requiresAuthentication: requiresAuthentication,
            keychainService: keychainService,
            keychainAccount: keychainAccount
        )
    }

    static func normalizedAPIBase(_ raw: String) throws -> String {
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { throw ForgisChatSettingsError.emptyAPIBase }
        let base = baseURL(fromChatEndpoint: trimmed).trimmingTrailingSlashesForChat()
        guard
            let url = URL(string: base),
            let scheme = url.scheme?.lowercased(),
            (scheme == "http" || scheme == "https"),
            url.host != nil
        else {
            throw ForgisChatSettingsError.invalidAPIBase
        }
        return base
    }

    private static func baseURL(fromChatEndpoint endpoint: String) -> String {
        let trimmed = endpoint.trimmingTrailingSlashesForChat()
        let suffix = "/chat/completions"
        if trimmed.lowercased().hasSuffix(suffix) {
            return String(trimmed.dropLast(suffix.count))
        }
        return trimmed
    }
}

private extension String {
    func trimmingTrailingSlashesForChat() -> String {
        var value = self
        while value.hasSuffix("/") && !value.hasSuffix("://") {
            value.removeLast()
        }
        return value
    }
}
#endif
