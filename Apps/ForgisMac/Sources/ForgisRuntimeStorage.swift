#if canImport(SwiftUI)
import Foundation
import IntatisCore
#if canImport(Security)
import Security
#endif

enum ForgisRuntimeStorageError: LocalizedError {
    case emptyCredential
    case keychainUnavailable
    case keychainUnexpectedStatus(OSStatus, String)
    case keychainInvalidData
    case invalidProjection
    case unsafeStorage

    var errorDescription: String? {
        switch self {
        case .emptyCredential:
            return "The Responses credential is empty."
        case .keychainUnavailable:
            return "Keychain is unavailable on this platform."
        case .keychainUnexpectedStatus(let status, let detail):
            return "Keychain operation failed: \(detail) (OSStatus \(status))."
        case .keychainInvalidData:
            return "The Keychain item is not valid UTF-8 text."
        case .invalidProjection:
            return "The saved Forgis runtime projection is invalid."
        case .unsafeStorage:
            return "Forgis runtime storage is not an owner-only, non-symlink directory."
        }
    }
}

struct ForgisRuntimePreferencesStore {
    var defaults: UserDefaults = .standard

    private var workspaceKey: String {
        IntatisHostApplication.identity.userDefaultsKey("runtime.workspace")
    }

    private var providerKey: String {
        IntatisHostApplication.identity.userDefaultsKey("runtime.provider")
    }

    private var executionKey: String {
        IntatisHostApplication.identity.userDefaultsKey("runtime.execution")
    }

    func loadWorkspace() -> ForgisWorkspaceConfiguration {
        decode(ForgisWorkspaceConfiguration.self, key: workspaceKey)
            ?? .empty
    }

    func loadProvider() -> ForgisProviderConfiguration {
        decode(ForgisProviderConfiguration.self, key: providerKey)
            ?? .empty
    }

    func loadExecution() -> (RunMode, Bool) {
        guard let value = decode(ExecutionPreferences.self, key: executionKey)
        else {
            return (.dryRun, true)
        }
        return (value.mode, value.runAgent)
    }

    func save(
        workspace: ForgisWorkspaceConfiguration,
        provider: ForgisProviderConfiguration,
        mode: RunMode,
        runAgent: Bool
    ) throws {
        try encode(workspace, key: workspaceKey)
        try encode(provider, key: providerKey)
        try encode(
            ExecutionPreferences(mode: mode, runAgent: runAgent),
            key: executionKey)
    }

    func reset() {
        defaults.removeObject(forKey: workspaceKey)
        defaults.removeObject(forKey: providerKey)
        defaults.removeObject(forKey: executionKey)
    }

    private func decode<T: Decodable>(
        _ type: T.Type,
        key: String
    ) -> T? {
        guard let data = defaults.data(forKey: key) else { return nil }
        return try? JSONDecoder().decode(type, from: data)
    }

    private func encode<T: Encodable>(_ value: T, key: String) throws {
        defaults.set(try JSONEncoder().encode(value), forKey: key)
    }

    private struct ExecutionPreferences: Codable {
        let mode: RunMode
        let runAgent: Bool
    }
}

struct ForgisRuntimeCredentialStore {
    private let service = IntatisHostApplication.identity
        .keychainService("codex-runtime")
    private let account = "responses-route"

    func read() throws -> String? {
        #if canImport(Security)
        var query = baseQuery
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne

        var item: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &item)
        if status == errSecItemNotFound { return nil }
        guard status == errSecSuccess else {
            throw unexpectedStatus(status)
        }
        guard let data = item as? Data,
              let value = String(data: data, encoding: .utf8) else {
            throw ForgisRuntimeStorageError.keychainInvalidData
        }
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
        #else
        throw ForgisRuntimeStorageError.keychainUnavailable
        #endif
    }

    func hasCredential() throws -> Bool {
        #if canImport(Security)
        var query = baseQuery
        query[kSecReturnAttributes as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        query[kSecUseAuthenticationUI as String] = kSecUseAuthenticationUISkip

        var item: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &item)
        if status == errSecSuccess || status == errSecInteractionNotAllowed {
            return true
        }
        if status == errSecItemNotFound { return false }
        throw unexpectedStatus(status)
        #else
        return false
        #endif
    }

    func save(_ rawValue: String) throws {
        #if canImport(Security)
        let value = rawValue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !value.isEmpty else {
            throw ForgisRuntimeStorageError.emptyCredential
        }
        let data = Data(value.utf8)
        let update: [String: Any] = [kSecValueData as String: data]
        let updateStatus = SecItemUpdate(
            baseQuery as CFDictionary,
            update as CFDictionary)
        if updateStatus == errSecSuccess { return }
        guard updateStatus == errSecItemNotFound else {
            throw unexpectedStatus(updateStatus)
        }

        var add = baseQuery
        add[kSecValueData as String] = data
        add[kSecAttrAccessible as String] =
            kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        let addStatus = SecItemAdd(add as CFDictionary, nil)
        guard addStatus == errSecSuccess else {
            throw unexpectedStatus(addStatus)
        }
        #else
        throw ForgisRuntimeStorageError.keychainUnavailable
        #endif
    }

    func delete() throws {
        #if canImport(Security)
        let status = SecItemDelete(baseQuery as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else {
            throw unexpectedStatus(status)
        }
        #else
        throw ForgisRuntimeStorageError.keychainUnavailable
        #endif
    }

    #if canImport(Security)
    private var baseQuery: [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
    }

    private func unexpectedStatus(
        _ status: OSStatus
    ) -> ForgisRuntimeStorageError {
        let detail = SecCopyErrorMessageString(status, nil) as String?
            ?? "Unknown Keychain error"
        return .keychainUnexpectedStatus(status, detail)
    }
    #endif
}

struct ForgisRuntimeFileStore {
    private let fileManager: FileManager
    let rootURL: URL

    init(fileManager: FileManager = .default) throws {
        self.fileManager = fileManager
        rootURL = try IntatisHostApplication.identity
            .applicationSupportRoot(fileManager: fileManager)
            .appendingPathComponent("Runtime", isDirectory: true)
        try Self.createOwnerOnlyDirectory(rootURL, fileManager: fileManager)
    }

    func runtimeRoot(sessionID: String) throws -> URL {
        let root = rootURL
            .appendingPathComponent("Sessions", isDirectory: true)
            .appendingPathComponent(safeComponent(sessionID), isDirectory: true)
            .appendingPathComponent("codex-runtime", isDirectory: true)
        try Self.createOwnerOnlyDirectory(root, fileManager: fileManager)
        return root
    }

    func loadProjection(sessionID: String) throws -> ForgisSessionProjection? {
        let url = projectionURL(sessionID: sessionID)
        guard fileManager.fileExists(atPath: url.path) else { return nil }
        let data = try readBoundedData(url, maximumBytes: 12_000_000)
        let projection = try JSONDecoder().decode(
            ForgisSessionProjection.self,
            from: data)
        guard projection.schemaVersion == "forgis.ui_projection.v1",
              projection.sessionID == sessionID else {
            throw ForgisRuntimeStorageError.invalidProjection
        }
        return projection
    }

    func saveProjection(_ projection: ForgisSessionProjection) throws {
        let url = projectionURL(sessionID: projection.sessionID)
        try Self.createOwnerOnlyDirectory(
            url.deletingLastPathComponent(),
            fileManager: fileManager)
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
        try encoder.encode(projection).write(to: url, options: .atomic)
    }

    func writeReport(
        _ report: ForgisRunReport,
        activities: [ForgisRuntimeActivity]
    ) throws -> ForgisStoredReport {
        let reportID = safeComponent(
            [report.sessionID, report.turnID, UUID().uuidString]
                .filter { !$0.isEmpty }
                .joined(separator: "-"))
        let directory = rootURL
            .appendingPathComponent("Reports", isDirectory: true)
            .appendingPathComponent(reportID, isDirectory: true)
        try Self.createOwnerOnlyDirectory(directory, fileManager: fileManager)

        let jsonURL = directory.appendingPathComponent("FORGIS_RUN_REPORT.json")
        let markdownURL = directory.appendingPathComponent("FORGIS_RUN_REPORT.md")
        let operationLogURL = directory.appendingPathComponent("FORGIS_OPERATION_LOG.json")
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
        try encoder.encode(report).write(to: jsonURL, options: .atomic)
        try encoder.encode(activities).write(to: operationLogURL, options: .atomic)
        try Data(markdown(report).utf8).write(to: markdownURL, options: .atomic)

        return ForgisStoredReport(
            id: reportID,
            report: report,
            jsonURL: jsonURL,
            markdownURL: markdownURL,
            modifiedAt: Date())
    }

    func loadReports() throws -> [ForgisStoredReport] {
        let reportsRoot = rootURL.appendingPathComponent("Reports", isDirectory: true)
        guard let directories = try? fileManager.contentsOfDirectory(
            at: reportsRoot,
            includingPropertiesForKeys: [.contentModificationDateKey, .isDirectoryKey],
            options: [.skipsHiddenFiles]) else {
            return []
        }
        let decoder = JSONDecoder()
        return directories.compactMap { directory in
            let jsonURL = directory.appendingPathComponent("FORGIS_RUN_REPORT.json")
            let markdownURL = directory.appendingPathComponent("FORGIS_RUN_REPORT.md")
            guard let data = try? readBoundedData(
                    jsonURL,
                    maximumBytes: 1_000_000),
                  let report = try? decoder.decode(ForgisRunReport.self, from: data),
                  report.schemaVersion == "forgis.run_report.v7.0" else {
                return nil
            }
            let modified = (try? jsonURL.resourceValues(
                forKeys: [.contentModificationDateKey]))?
                .contentModificationDate ?? .distantPast
            return ForgisStoredReport(
                id: directory.lastPathComponent,
                report: report,
                jsonURL: jsonURL,
                markdownURL: markdownURL,
                modifiedAt: modified)
        }
        .sorted { $0.modifiedAt > $1.modifiedAt }
    }

    private func projectionURL(sessionID: String) -> URL {
        rootURL
            .appendingPathComponent("Sessions", isDirectory: true)
            .appendingPathComponent(safeComponent(sessionID), isDirectory: true)
            .appendingPathComponent("ui-projection.json")
    }

    private func readBoundedData(
        _ url: URL,
        maximumBytes: Int
    ) throws -> Data {
        let standardized = url.standardizedFileURL
        guard standardized.resolvingSymlinksInPath() == standardized else {
            throw ForgisRuntimeStorageError.unsafeStorage
        }
        let values = try standardized.resourceValues(
            forKeys: [.isRegularFileKey, .isSymbolicLinkKey, .fileSizeKey])
        guard values.isRegularFile == true,
              values.isSymbolicLink != true,
              let size = values.fileSize,
              size > 0,
              size <= maximumBytes else {
            throw ForgisRuntimeStorageError.invalidProjection
        }
        let data = try Data(contentsOf: standardized, options: [.mappedIfSafe])
        guard data.count == size else {
            throw ForgisRuntimeStorageError.invalidProjection
        }
        return data
    }

    private func safeComponent(_ value: String) -> String {
        let allowed = CharacterSet.alphanumerics
            .union(CharacterSet(charactersIn: "-_."))
        let scalars = value.unicodeScalars.map {
            allowed.contains($0) ? Character(String($0)) : "_"
        }
        let result = String(scalars.prefix(180))
        return result.isEmpty ? "unavailable" : result
    }

    private func markdown(_ report: ForgisRunReport) -> String {
        """
        # Forgis Run Report

        - Schema: `\(report.schemaVersion)`
        - Kernel: `\(report.runtimeKernel)`
        - Runtime: `\(report.runtimeVersion)`
        - Status: `\(report.status)`
        - Session: `\(report.sessionID)`
        - Thread: `\(report.threadID)`
        - Turn: `\(report.turnID)`
        - Tool calls: `\(report.toolCallCount)`
        - File-change items: `\(report.writeToolCount)`

        ## Final Summary

        \(report.finalSummary)

        ## Visual Validation

        - Required: `\(report.visualValidation.required)`
        - Called: `\(report.visualValidation.called)`
        - Full rendered validation: `\(report.visualValidation.fullRenderedValidation)`
        - Limitation: \(report.visualValidation.limitations)
        """
    }

    private static func createOwnerOnlyDirectory(
        _ url: URL,
        fileManager: FileManager
    ) throws {
        try fileManager.createDirectory(
            at: url,
            withIntermediateDirectories: true,
            attributes: [.posixPermissions: 0o700])
        let standardized = url.standardizedFileURL
        let values = try standardized.resourceValues(
            forKeys: [.isDirectoryKey, .isSymbolicLinkKey])
        guard values.isDirectory == true,
              values.isSymbolicLink != true,
              standardized.resolvingSymlinksInPath() == standardized else {
            throw ForgisRuntimeStorageError.unsafeStorage
        }
        try fileManager.setAttributes(
            [.posixPermissions: 0o700],
            ofItemAtPath: standardized.path)
    }
}
#endif
