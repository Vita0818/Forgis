#if canImport(SwiftUI)
import Foundation

enum ForgisSection: String, CaseIterable, Identifiable, Hashable {
    case migration
    case reports
    case settings

    var id: String { rawValue }

    var title: String {
        switch self {
        case .migration: return "Migration"
        case .reports: return "Reports"
        case .settings: return "Settings"
        }
    }

    var icon: String {
        switch self {
        case .migration: return "arrow.triangle.2.circlepath"
        case .reports: return "doc.text.magnifyingglass"
        case .settings: return "gearshape"
        }
    }
}

enum RunMode: String, Codable, CaseIterable, Identifiable {
    case dryRun
    case realRun

    var id: String { rawValue }

    var title: String {
        switch self {
        case .dryRun: return "Dry run"
        case .realRun: return "Real run"
        }
    }
}

enum ForgisRuntimeStatus: String, Codable {
    case unconfigured
    case ready
    case starting
    case running
    case stopping
    case completed
    case failed
    case skipped

    var title: String {
        switch self {
        case .unconfigured: return "Not configured"
        case .ready: return "Ready"
        case .starting: return "Starting"
        case .running: return "Running"
        case .stopping: return "Stopping"
        case .completed: return "Completed"
        case .failed: return "Failed"
        case .skipped: return "Skipped"
        }
    }
}

enum ForgisRequestAdapter: String, Codable, CaseIterable, Identifiable {
    case responsesCompatible = "openai-compatible"
    case openRouter = "openrouter"

    var id: String { rawValue }

    var title: String {
        switch self {
        case .responsesCompatible: return "Responses compatible"
        case .openRouter: return "OpenRouter Responses"
        }
    }
}

struct ForgisWorkspaceConfiguration: Codable, Equatable {
    var sourcePath = ""
    var targetPath = ""
    var targetSubdir = "target-output"
    var taskPath = ""
    var targetRepo = ""
    var unitID = ""
    var sessionToken = UUID().uuidString.lowercased()

    static let empty = ForgisWorkspaceConfiguration()
}

struct ForgisProviderConfiguration: Codable, Equatable {
    var endpointID = "forgis-runtime"
    var model = ""
    var responsesBaseURL = ""
    var credentialEnvironmentName = "FORGIS_MODEL_API_KEY"
    var requiresAuthentication = true
    var requestAdapter: ForgisRequestAdapter = .responsesCompatible
    var reasoningEffort = ""

    static let empty = ForgisProviderConfiguration()
}

enum ForgisCredentialStatus: Equatable {
    case keychain
    case environment(String)
    case notRequired
    case unset
    case error(String)

    var title: String {
        switch self {
        case .keychain: return "Keychain"
        case .environment(let name): return "Environment: \(name)"
        case .notRequired: return "Not required"
        case .unset: return "Unset"
        case .error: return "Unavailable"
        }
    }

    var detail: String {
        switch self {
        case .keychain:
            return "Stored in the Forgis Keychain namespace."
        case .environment(let name):
            return "Resolved from \(name); the value is not displayed or persisted."
        case .notRequired:
            return "The selected Responses endpoint does not require a bearer credential."
        case .unset:
            return "Save a credential to Keychain or configure the named environment variable."
        case .error(let message):
            return message
        }
    }
}

enum ForgisRuntimeMessageRole: String, Codable {
    case user
    case assistant
    case system
}

struct ForgisRuntimeMessage: Identifiable, Codable, Equatable {
    let id: String
    var role: ForgisRuntimeMessageRole
    var text: String
    var phase: String?
    var isComplete: Bool

    init(
        id: String = UUID().uuidString.lowercased(),
        role: ForgisRuntimeMessageRole,
        text: String,
        phase: String? = nil,
        isComplete: Bool = true
    ) {
        self.id = id
        self.role = role
        self.text = text
        self.phase = phase
        self.isComplete = isComplete
    }

    var isCommentary: Bool { phase == "commentary" }
}

struct ForgisRuntimeActivity: Identifiable, Codable, Equatable {
    let id: String
    var kind: String
    var title: String
    var detail: String
    var status: String
    var failed: Bool
}

struct ForgisRuntimeUsageSummary: Codable, Equatable {
    let inputTokens: Int
    let cachedInputTokens: Int
    let cacheWriteInputTokens: Int
    let outputTokens: Int
    let reasoningOutputTokens: Int
    let totalTokens: Int
    let durationMs: Int?

    enum CodingKeys: String, CodingKey {
        case inputTokens = "input_tokens"
        case cachedInputTokens = "cached_input_tokens"
        case cacheWriteInputTokens = "cache_write_input_tokens"
        case outputTokens = "output_tokens"
        case reasoningOutputTokens = "reasoning_output_tokens"
        case totalTokens = "total_tokens"
        case durationMs = "duration_ms"
    }
}

struct ForgisVisualValidationSummary: Codable, Equatable {
    let required: Bool
    let provider: String
    let mode: String
    let called: Bool
    let guidanceCompleted: Bool
    let validVisualEvidence: String
    let compareScreenshotsCompleted: Bool
    let fullRenderedValidation: Bool
    let actualScreenshotBlocker: String
    let limitations: String

    enum CodingKeys: String, CodingKey {
        case required, provider, mode, called
        case guidanceCompleted = "guidance_completed"
        case validVisualEvidence = "valid_visual_evidence"
        case compareScreenshotsCompleted = "compare_screenshots_completed"
        case fullRenderedValidation = "full_rendered_validation"
        case actualScreenshotBlocker = "actual_screenshot_blocker"
        case limitations = "visual_validation_limitations"
    }

    static let unavailable = ForgisVisualValidationSummary(
        required: false,
        provider: "qwen",
        mode: "reference_guidance",
        called: false,
        guidanceCompleted: false,
        validVisualEvidence: "NO",
        compareScreenshotsCompleted: false,
        fullRenderedValidation: false,
        actualScreenshotBlocker: "none",
        limitations: "The shared Codex v1 host has no official Qwen dynamic-tool connection; Forgis does not invoke the retired Python visual path."
    )
}

struct ForgisRunReport: Codable, Equatable {
    let schemaVersion: String
    let runtimeKernel: String
    let runtimeVersion: String
    let status: String
    let executed: Bool
    let targetRepo: String
    let unitID: String
    let sessionID: String
    let threadID: String
    let turnID: String
    let finalSummary: String
    let runtimeError: String
    let toolCallCount: Int
    let writeToolCount: Int
    let usage: ForgisRuntimeUsageSummary?
    let visualValidation: ForgisVisualValidationSummary

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case runtimeKernel = "runtime_kernel"
        case runtimeVersion = "runtime_version"
        case status, executed
        case targetRepo = "target_repo"
        case unitID = "unit_id"
        case sessionID = "session_id"
        case threadID = "thread_id"
        case turnID = "turn_id"
        case finalSummary = "final_summary"
        case runtimeError = "runtime_error"
        case toolCallCount = "tool_call_count"
        case writeToolCount = "write_tool_count"
        case usage
        case visualValidation = "visual_validation"
    }
}

struct ForgisStoredReport: Identifiable, Equatable {
    let id: String
    let report: ForgisRunReport
    let jsonURL: URL
    let markdownURL: URL
    let modifiedAt: Date
}

struct ForgisSessionProjection: Codable, Equatable {
    let schemaVersion: String
    var sessionID: String
    var threadID: String
    var runtimeVersion: String
    var status: ForgisRuntimeStatus
    var messages: [ForgisRuntimeMessage]
    var activities: [ForgisRuntimeActivity]
    var usage: ForgisRuntimeUsageSummary?

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case sessionID = "session_id"
        case threadID = "thread_id"
        case runtimeVersion = "runtime_version"
        case status, messages, activities, usage
    }
}

struct SafetyItem: Identifiable {
    let id = UUID()
    let title: String
    let tone: PillTone
}
#endif
