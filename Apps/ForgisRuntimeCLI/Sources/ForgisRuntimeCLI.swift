import Foundation
import IntatisCodexRuntime
import IntatisCore
import IntatisProtocol
import IntatisProviders

private let forgisRuntimeResultSchema = "forgis.codex_runtime_result.v1"
private let forgisRunReportSchema = "forgis.run_report.v7.0"
private let maximumTaskBytes = 1_000_000
private let maximumFinalSummaryCharacters = 16_000
private let maximumRecordedItems = 200

private enum ForgisRuntimeCLIError: Error, LocalizedError {
    case usage(String)
    case invalid(String)
    case missing(String)
    case runtime(String)

    var errorDescription: String? {
        switch self {
        case .usage(let message), .invalid(let message),
             .missing(let message), .runtime(let message):
            return message
        }
    }
}

private struct ParsedArguments {
    let command: String
    let values: [String: String]
    let flags: Set<String>

    init(_ arguments: [String]) throws {
        guard let command = arguments.first else {
            throw ForgisRuntimeCLIError.usage(Self.help)
        }
        self.command = command

        var values: [String: String] = [:]
        var flags: Set<String> = []
        let flagNames: Set<String> = ["--non-interactive", "--no-auth"]
        var index = 1
        while index < arguments.count {
            let key = arguments[index]
            guard key.hasPrefix("--") else {
                throw ForgisRuntimeCLIError.usage(
                    "Unexpected positional argument: \(key)\n\n\(Self.help)")
            }
            guard values[key] == nil, !flags.contains(key) else {
                throw ForgisRuntimeCLIError.usage(
                    "Duplicate argument: \(key)")
            }
            if flagNames.contains(key) {
                flags.insert(key)
                index += 1
                continue
            }
            guard arguments.indices.contains(index + 1) else {
                throw ForgisRuntimeCLIError.usage(
                    "Missing value for \(key)")
            }
            values[key] = arguments[index + 1]
            index += 2
        }
        self.values = values
        self.flags = flags
    }

    func required(_ name: String) throws -> String {
        guard let value = values[name],
              !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw ForgisRuntimeCLIError.missing(
                "Missing required argument \(name)")
        }
        return value
    }

    func optional(_ name: String, default fallback: String = "") -> String {
        values[name] ?? fallback
    }

    func boolean(_ name: String, default fallback: Bool = false) throws -> Bool {
        guard let rawValue = values[name] else { return fallback }
        switch rawValue.trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased() {
        case "true", "1", "yes": return true
        case "false", "0", "no": return false
        default:
            throw ForgisRuntimeCLIError.invalid(
                "\(name) must be true or false")
        }
    }

    static let help = """
    Forgis Codex Runtime

      forgis-runtime doctor --codex-runtime <absolute-path>
      forgis-runtime smoke --codex-runtime <absolute-path> [--workdir <absolute-path>]
      forgis-runtime run \\
        --source <absolute-directory> \\
        --target <absolute-directory> \\
        --target-subdir <relative-path> \\
        --task-prompt <target-relative-path> \\
        --target-repo <label> \\
        --api-base <responses-api-base> \\
        --model <model-id> \\
        --model-env-json <json-object-of-env-names> \\
        --runtime-root <absolute-directory> \\
        [--output-root <absolute-directory>] \\
        --codex-runtime <absolute-path> \\
        --dry-run <true|false> \\
        --run-agent <true|false> \\
        --confirm-real-run <true|false> \\
        [--unit <unit-id>] \\
        [--request-adapter <openai-compatible|openrouter|openai>] \\
        [--reasoning-effort <effort>] \\
        [--status-output <absolute-path>] \\
        [--summary-output <absolute-path>] \\
        [--operation-log-output <absolute-path>] \\
        [--report-output-dir <absolute-directory>] \\
        [--visual-validation-enabled <auto|true|false>] \\
        [--non-interactive] [--no-auth]

    This executable is the only production Agent kernel entry. It uses
    IntatisCodexRuntime directly and never falls back to the retired Python loop.
    """
}

private struct RuntimeItemSummary: Codable, Sendable {
    let id: String
    let kind: String
    let title: String
    let status: String
    let failed: Bool
}

private struct RuntimeUsageSummary: Codable, Sendable {
    let inputTokens: Int
    let cachedInputTokens: Int
    let cacheWriteInputTokens: Int
    let outputTokens: Int
    let reasoningOutputTokens: Int
    let totalTokens: Int
    let durationMs: Int?

    init(_ usage: CodexRuntimeResponsesUsage) {
        inputTokens = usage.inputTokens
        cachedInputTokens = usage.cachedInputTokens
        cacheWriteInputTokens = usage.cacheWriteInputTokens
        outputTokens = usage.outputTokens
        reasoningOutputTokens = usage.reasoningOutputTokens
        totalTokens = usage.totalTokens
        durationMs = usage.durationMs
    }
}

private struct RuntimeEventSnapshot: Sendable {
    let finalSummary: String
    let items: [RuntimeItemSummary]
    let usage: RuntimeUsageSummary?
    let runtimeError: String

    var toolCallCount: Int { items.count }
    var writeToolCount: Int {
        items.filter { $0.kind == CodexRuntimeItem.Kind.fileChange.rawValue }
            .count
    }
}

private actor RuntimeEventCollector {
    private var finalMessages: [String] = []
    private var itemsByID: [String: RuntimeItemSummary] = [:]
    private var orderedItemIDs: [String] = []
    private var usage: RuntimeUsageSummary?
    private var runtimeError = ""
    private let credential: String

    init(credential: String) {
        self.credential = credential
    }

    func consume(_ event: CodexRuntimeEvent) {
        switch event {
        case .assistantCompleted(_, let text, let phase):
            if phase != .commentary {
                let cleaned = boundedSafeText(text, credential: credential)
                if !cleaned.isEmpty { finalMessages.append(cleaned) }
            }
        case .itemStarted(let item), .itemCompleted(let item):
            let toolKinds: Set<CodexRuntimeItem.Kind> = [
                .command, .fileChange, .mcpTool, .dynamicTool,
                .collaboration, .subagent, .webSearch, .image,
            ]
            guard toolKinds.contains(item.kind) else { return }
            if itemsByID[item.id] == nil,
               orderedItemIDs.count < maximumRecordedItems {
                orderedItemIDs.append(item.id)
            }
            guard orderedItemIDs.contains(item.id) else { return }
            itemsByID[item.id] = RuntimeItemSummary(
                id: boundedSafeText(item.id, credential: credential, limit: 256),
                kind: item.kind.rawValue,
                title: boundedSafeText(item.title, credential: credential, limit: 1_000),
                status: boundedSafeText(item.status ?? "", credential: credential, limit: 200),
                failed: item.isFailure)
        case .responsesUsage(let value):
            usage = RuntimeUsageSummary(value)
        case .runtimeError(_, let message, _):
            runtimeError = boundedSafeText(
                message,
                credential: credential,
                limit: 4_000)
        default:
            break
        }
    }

    func snapshot() -> RuntimeEventSnapshot {
        RuntimeEventSnapshot(
            finalSummary: boundedSafeText(
                finalMessages.joined(separator: "\n\n"),
                credential: credential),
            items: orderedItemIDs.compactMap { itemsByID[$0] },
            usage: usage,
            runtimeError: runtimeError)
    }
}

private struct RuntimeResultDocument: Codable {
    let schemaVersion: String
    let kernel: String
    let hostAPIMajorVersion: Int
    let pinnedRuntimeVersion: String
    let actualRuntimeVersion: String
    let executed: Bool
    let status: String
    let targetRepo: String
    let unitID: String
    let sessionID: String
    let threadID: String
    let turnID: String
    let finalSummary: String
    let runtimeError: String
    let toolCallCount: Int
    let readToolCount: Int
    let writeToolCount: Int
    let items: [RuntimeItemSummary]
    let usage: RuntimeUsageSummary?

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case kernel
        case hostAPIMajorVersion = "host_api_major_version"
        case pinnedRuntimeVersion = "pinned_runtime_version"
        case actualRuntimeVersion = "actual_runtime_version"
        case executed, status
        case targetRepo = "target_repo"
        case unitID = "unit_id"
        case sessionID = "session_id"
        case threadID = "thread_id"
        case turnID = "turn_id"
        case finalSummary = "final_summary"
        case runtimeError = "runtime_error"
        case toolCallCount = "tool_call_count"
        case readToolCount = "read_tool_count"
        case writeToolCount = "write_tool_count"
        case items, usage
    }
}

private struct RunContext {
    let sourceURL: URL
    let targetURL: URL
    let workspaceURL: URL
    let taskURL: URL
    let runtimeRootURL: URL
    let executableURL: URL
    let targetRepo: String
    let unitID: String
    let apiBase: URL
    let queryParameters: [String: String]
    let model: String
    let credential: String
    let requestAdapter: ProviderRequestAdapter
    let reasoningEffort: String?
    let sessionID: SessionID
    let taskText: String
    let nonInteractive: Bool
    let visualValidationEnabled: String
    let statusOutputURL: URL?
    let summaryOutputURL: URL?
    let operationLogOutputURL: URL?
    let reportOutputURL: URL?
}

@main
private enum ForgisRuntimeCLI {
    static func main() async {
        do {
            try installHostIdentity()
            let arguments = try ParsedArguments(
                Array(CommandLine.arguments.dropFirst()))
            switch arguments.command {
            case "help", "--help", "-h":
                print(ParsedArguments.help)
            case "doctor":
                try runDoctor(arguments)
            case "smoke":
                try await runOfflineSmoke(arguments)
            case "run":
                try await runMigration(arguments)
            default:
                throw ForgisRuntimeCLIError.usage(
                    "Unknown command: \(arguments.command)\n\n\(ParsedArguments.help)")
            }
        } catch {
            writeStderr("ERROR: \(error.localizedDescription)\n")
            Foundation.exit(1)
        }
    }
}

private func installHostIdentity() throws {
    guard CodexRuntimeHostContract.publicAPIMajorVersion == 1 else {
        throw ForgisRuntimeCLIError.runtime(
            "Forgis requires IntatisCodexRuntime host API v1.")
    }
    _ = try IntatisHostApplication.configure(name: "Forgis")
}

private func runDoctor(_ arguments: ParsedArguments) throws {
    let executable = try absoluteFileURL(
        arguments.required("--codex-runtime"),
        label: "--codex-runtime")
    let version = try CodexRuntimeExecutable.verifiedVersion(at: executable)
    let payload: [String: Any] = [
        "status": "ok",
        "kernel": "intatis-codex-app-server",
        "host_api_major_version": CodexRuntimeHostContract.publicAPIMajorVersion,
        "runtime_version": version,
        "runtime_derivation": CodexRuntimeHostContract.pinnedRuntimeDerivationID,
    ]
    try printJSON(payload)
}

private func runOfflineSmoke(_ arguments: ParsedArguments) async throws {
    let executable = try absoluteFileURL(
        arguments.required("--codex-runtime"),
        label: "--codex-runtime")
    let explicitWorkdir = arguments.optional("--workdir")
    let ownsWorkdir = explicitWorkdir.isEmpty
    let workdir: URL
    if ownsWorkdir {
        workdir = FileManager.default.temporaryDirectory
            .appendingPathComponent(
                "forgis-codex-smoke-\(UUID().uuidString.lowercased())",
                isDirectory: true)
    } else {
        workdir = try absoluteDirectoryURL(
            explicitWorkdir,
            label: "--workdir",
            createIfMissing: true)
    }
    if ownsWorkdir {
        try FileManager.default.createDirectory(
            at: workdir,
            withIntermediateDirectories: true)
    }
    defer {
        if ownsWorkdir { try? FileManager.default.removeItem(at: workdir) }
    }

    let workspace = workdir.appendingPathComponent("workspace", isDirectory: true)
    let runtimeRoot = workdir.appendingPathComponent("runtime", isDirectory: true)
    try FileManager.default.createDirectory(
        at: workspace,
        withIntermediateDirectories: true)
    let route = ResponsesRuntimeRoute(
        endpointID: "forgis-offline-smoke",
        model: ModelID(rawValue: "forgis-offline-smoke-model"),
        baseURL: URL(string: "http://127.0.0.1:9/v1")!,
        bearerToken: "forgis-offline-smoke-token")
    let session = CodexAppServerSession(configuration:
        CodexRuntimeConfiguration(
            sessionID: SessionID(rawValue: "forgis_smoke_\(UUID().uuidString.lowercased())"),
            mode: .code,
            workspaceURL: workspace,
            runtimeRootURL: runtimeRoot,
            route: route,
            executableOverride: executable))
    let identity: CodexRuntimeIdentity
    do {
        identity = try await session.start()
    } catch {
        await session.shutdown()
        throw error
    }
    await session.shutdown()
    try printJSON([
        "status": "ok",
        "network_requests": 0,
        "runtime_version": identity.runtimeVersion,
        "mode": identity.mode.rawValue,
    ])
}

private func runMigration(_ arguments: ParsedArguments) async throws {
    let dryRun = try arguments.boolean("--dry-run")
    let runAgent = try arguments.boolean("--run-agent")
    let confirmRealRun = try arguments.boolean("--confirm-real-run")
    let targetRepo = try safeLabel(
        arguments.required("--target-repo"),
        label: "--target-repo")
    let sourceBoundary = try absoluteDirectoryURL(
        arguments.required("--source"),
        label: "--source")
    let targetBoundary = try absoluteDirectoryURL(
        arguments.required("--target"),
        label: "--target")
    let runtimeRoot = try absoluteDirectoryPathURL(
        arguments.required("--runtime-root"),
        label: "--runtime-root")
    guard !isInside(runtimeRoot, root: sourceBoundary),
          !isInside(runtimeRoot, root: targetBoundary),
          !isInside(sourceBoundary, root: runtimeRoot),
          !isInside(targetBoundary, root: runtimeRoot) else {
        throw ForgisRuntimeCLIError.invalid(
            "Runtime root must be outside source and target repositories.")
    }
    try FileManager.default.createDirectory(
        at: runtimeRoot,
        withIntermediateDirectories: true)
    let outputRoot: URL
    if arguments.optional("--output-root").isEmpty {
        outputRoot = runtimeRoot
    } else {
        outputRoot = try absoluteDirectoryPathURL(
            arguments.required("--output-root"),
            label: "--output-root")
        guard !isInside(outputRoot, root: sourceBoundary),
              !isInside(outputRoot, root: targetBoundary) else {
            throw ForgisRuntimeCLIError.invalid(
                "Output root must not be inside source or target repositories.")
        }
        try FileManager.default.createDirectory(
            at: outputRoot,
            withIntermediateDirectories: true)
    }
    let statusOutput = try optionalOutputURL(
        arguments.optional("--status-output"),
        allowedRoot: outputRoot)
    let summaryOutput = try optionalOutputURL(
        arguments.optional("--summary-output"),
        allowedRoot: outputRoot)
    let operationLogOutput = try optionalOutputURL(
        arguments.optional("--operation-log-output"),
        allowedRoot: outputRoot)
    let reportOutput = try optionalOutputURL(
        arguments.optional("--report-output-dir"),
        allowedRoot: outputRoot,
        isDirectory: true)
    for output in [
        statusOutput,
        summaryOutput,
        operationLogOutput,
        reportOutput,
    ].compactMap({ $0 }) {
        guard !isInside(output, root: sourceBoundary),
              !isInside(output, root: targetBoundary) else {
            throw ForgisRuntimeCLIError.invalid(
                "Runtime output files must not be written inside source or target repositories.")
        }
    }

    if dryRun || !runAgent {
        let reason = dryRun ? "dry_run" : "run_agent_disabled"
        let document = RuntimeResultDocument(
            schemaVersion: forgisRuntimeResultSchema,
            kernel: "intatis-codex-app-server",
            hostAPIMajorVersion: 1,
            pinnedRuntimeVersion: CodexRuntimeHostContract.pinnedRuntimeVersion,
            actualRuntimeVersion: "not-started",
            executed: false,
            status: "skipped-\(reason)",
            targetRepo: targetRepo,
            unitID: arguments.optional("--unit"),
            sessionID: "",
            threadID: "",
            turnID: "",
            finalSummary: "Codex runtime was not started because \(reason).",
            runtimeError: "",
            toolCallCount: 0,
            readToolCount: 0,
            writeToolCount: 0,
            items: [],
            usage: nil)
        try writeRuntimeOutputs(
            document,
            statusOutput: statusOutput,
            summaryOutput: summaryOutput,
            operationLogOutput: operationLogOutput,
            reportOutput: reportOutput,
            visualValidationEnabled: arguments.optional(
                "--visual-validation-enabled",
                default: "false"))
        try printDocument(document)
        return
    }
    guard confirmRealRun else {
        throw ForgisRuntimeCLIError.invalid(
            "Real Forgis runs require --confirm-real-run true.")
    }
    if arguments.optional(
        "--visual-validation-enabled",
        default: "false").lowercased() == "true" {
        throw ForgisRuntimeCLIError.runtime(
            "visual_validation.enabled=true is not available on the shared Codex v1 host; the capability fails closed before workspace or credential access instead of invoking the retired Python/Qwen tool path.")
    }

    let context = try buildRunContext(
        arguments,
        targetRepo: targetRepo,
        runtimeRoot: runtimeRoot,
        statusOutput: statusOutput,
        summaryOutput: summaryOutput,
        operationLogOutput: operationLogOutput,
        reportOutput: reportOutput)
    try await execute(context)
}

private func buildRunContext(
    _ arguments: ParsedArguments,
    targetRepo: String,
    runtimeRoot: URL,
    statusOutput: URL?,
    summaryOutput: URL?,
    operationLogOutput: URL?,
    reportOutput: URL?
) throws -> RunContext {
    let source = try absoluteDirectoryURL(
        arguments.required("--source"),
        label: "--source")
    let target = try absoluteDirectoryURL(
        arguments.required("--target"),
        label: "--target")
    guard !isInside(source, root: target),
          !isInside(target, root: source) else {
        throw ForgisRuntimeCLIError.invalid(
            "Source and target repositories must not overlap.")
    }
    guard !isInside(runtimeRoot, root: source),
          !isInside(runtimeRoot, root: target),
          !isInside(source, root: runtimeRoot),
          !isInside(target, root: runtimeRoot) else {
        throw ForgisRuntimeCLIError.invalid(
            "Runtime root must be outside source and target repositories.")
    }

    let targetSubdir = try safeRelativePath(
        arguments.required("--target-subdir"),
        label: "--target-subdir")
    let workspace = target.appendingPathComponent(
        targetSubdir,
        isDirectory: true).standardizedFileURL
    guard isInside(workspace, root: target), workspace != target else {
        throw ForgisRuntimeCLIError.invalid(
            "Writable workspace must be a strict target subdirectory.")
    }
    try FileManager.default.createDirectory(
        at: workspace,
        withIntermediateDirectories: true)

    let taskRelative = try safeRelativePath(
        arguments.required("--task-prompt"),
        label: "--task-prompt")
    let taskURL = target.appendingPathComponent(taskRelative)
        .standardizedFileURL
    guard isInside(taskURL, root: target),
          !isInside(taskURL, root: workspace) else {
        throw ForgisRuntimeCLIError.invalid(
            "Task prompt must be a read-only target input outside target_subdir.")
    }
    let taskText = try readBoundedUTF8(taskURL, maximumBytes: maximumTaskBytes)

    let executable = try absoluteFileURL(
        arguments.required("--codex-runtime"),
        label: "--codex-runtime")
    let responseRoute = try normalizedResponsesRoute(
        arguments.required("--api-base"))
    let model = try safeLabel(
        arguments.required("--model"),
        label: "--model",
        maximum: 256)
    let credential = try resolveCredential(
        modelEnvJSON: arguments.required("--model-env-json"),
        noAuthentication: arguments.flags.contains("--no-auth"))
    guard credential.isEmpty || !taskText.contains(credential) else {
        throw ForgisRuntimeCLIError.invalid(
            "Task prompt contains the configured model credential and cannot be sent.")
    }
    let adapter = try requestAdapter(
        arguments.optional(
            "--request-adapter",
            default: "openai-compatible"))
    let unitID = try safeOptionalLabel(
        arguments.optional("--unit"),
        label: "--unit",
        maximum: 120)
    let sessionDigest = stableFNV64([
        targetRepo,
        workspace.path,
        unitID,
        model,
        responseRoute.baseURL.absoluteString,
        adapter.rawValue,
    ])
    let sessionID = SessionID(rawValue: "forgis_\(sessionDigest)")
    let sessionRoot = runtimeRoot
        .appendingPathComponent("codex-sessions", isDirectory: true)
        .appendingPathComponent(sessionID.rawValue, isDirectory: true)

    return RunContext(
        sourceURL: source,
        targetURL: target,
        workspaceURL: workspace,
        taskURL: taskURL,
        runtimeRootURL: sessionRoot,
        executableURL: executable,
        targetRepo: targetRepo,
        unitID: unitID,
        apiBase: responseRoute.baseURL,
        queryParameters: responseRoute.queryParameters,
        model: model,
        credential: credential,
        requestAdapter: adapter,
        reasoningEffort: try safeOptionalLabel(
            arguments.optional("--reasoning-effort"),
            label: "--reasoning-effort",
            maximum: 32),
        sessionID: sessionID,
        taskText: taskText,
        nonInteractive: arguments.flags.contains("--non-interactive"),
        visualValidationEnabled: arguments.optional(
            "--visual-validation-enabled",
            default: "false"),
        statusOutputURL: statusOutput,
        summaryOutputURL: summaryOutput,
        operationLogOutputURL: operationLogOutput,
        reportOutputURL: reportOutput)
}

private func execute(_ context: RunContext) async throws {
    let route = ResponsesRuntimeRoute(
        endpointID: "forgis-runtime",
        model: ModelID(rawValue: context.model),
        baseURL: context.apiBase,
        queryParameters: context.queryParameters,
        bearerToken: context.credential,
        reasoningEffort: context.reasoningEffort,
        requestAdapter: context.requestAdapter)
    let session = CodexAppServerSession(configuration:
        CodexRuntimeConfiguration(
            sessionID: context.sessionID,
            mode: .code,
            workspaceURL: context.workspaceURL,
            runtimeRootURL: context.runtimeRootURL,
            route: route,
            approvalReviewer: .automatic,
            reasoningEffort: context.reasoningEffort,
            executableOverride: context.executableURL))
    let collector = RuntimeEventCollector(credential: context.credential)
    let events = await session.events()
    let eventTask = Task {
        for await event in events {
            await collector.consume(event)
            switch event {
            case .assistantDelta(_, let text, _):
                let safe = boundedSafeText(
                    text,
                    credential: context.credential,
                    limit: 4_000)
                if !safe.isEmpty { writeStderr(safe) }
            case .approvalRequested(let request):
                let decision = approvalDecision(
                    request,
                    nonInteractive: context.nonInteractive,
                    credential: context.credential)
                try? await session.resolveApproval(
                    requestID: request.requestID,
                    decision: decision)
            default:
                break
            }
        }
    }

    var identity: CodexRuntimeIdentity?
    var result: CodexRuntimeTurnResult?
    var executionError: Error?
    do {
        identity = try await session.start()
        result = try await session.runTurn(text: migrationPrompt(context))
    } catch {
        executionError = error
    }
    await session.shutdown()
    eventTask.cancel()
    _ = await eventTask.result
    let snapshot = await collector.snapshot()

    let finalSummary: String
    if !snapshot.finalSummary.isEmpty {
        finalSummary = snapshot.finalSummary
    } else if let result, let message = result.errorMessage, !message.isEmpty {
        finalSummary = boundedSafeText(
            message,
            credential: context.credential)
    } else if let executionError {
        finalSummary = boundedSafeText(
            executionError.localizedDescription,
            credential: context.credential)
    } else {
        finalSummary = "Codex runtime finished without a final assistant message."
    }

    let document = RuntimeResultDocument(
        schemaVersion: forgisRuntimeResultSchema,
        kernel: "intatis-codex-app-server",
        hostAPIMajorVersion: 1,
        pinnedRuntimeVersion: CodexRuntimeHostContract.pinnedRuntimeVersion,
        actualRuntimeVersion: identity?.runtimeVersion ?? "not-started",
        executed: identity != nil,
        status: result?.status ?? "failed",
        targetRepo: context.targetRepo,
        unitID: context.unitID,
        sessionID: context.sessionID.rawValue,
        threadID: identity?.threadID ?? "",
        turnID: result?.turnID ?? "",
        finalSummary: finalSummary,
        runtimeError: snapshot.runtimeError,
        toolCallCount: snapshot.toolCallCount,
        readToolCount: 0,
        writeToolCount: snapshot.writeToolCount,
        items: snapshot.items,
        usage: snapshot.usage)
    try writeRuntimeOutputs(
        document,
        statusOutput: context.statusOutputURL,
        summaryOutput: context.summaryOutputURL,
        operationLogOutput: context.operationLogOutputURL,
        reportOutput: context.reportOutputURL,
        visualValidationEnabled: context.visualValidationEnabled)
    try printDocument(document)

    if let executionError { throw executionError }
    guard result?.succeeded == true else {
        throw ForgisRuntimeCLIError.runtime(
            "Codex runtime turn did not complete successfully: \(document.status)")
    }
}

private func migrationPrompt(_ context: RunContext) -> String {
    let unit = context.unitID.isEmpty ? "[no explicit unit]" : context.unitID
    return """
    Execute this Forgis migration task using the native Codex runtime and its native tools.

    Security and ownership contract:
    - The current working directory is the only writable root: \(context.workspaceURL.path)
    - The source repository is read-only: \(context.sourceURL.path)
    - The target repository outside the working directory is read-only: \(context.targetURL.path)
    - Never modify the task file: \(context.taskURL.path)
    - Use native Codex file, patch, command, sandbox, approval, context, and agent-loop capabilities.
    - Do not invoke or emulate the retired Forgis Python AgentLoop or its file-tool backend.
    - If the task requires a capability unavailable through the current official runtime, report the exact blocker instead of inventing a fallback.

    Selected migration unit: \(unit)

    Task instructions:
    \(context.taskText)
    """
}

private func approvalDecision(
    _ request: CodexRuntimeApprovalRequest,
    nonInteractive: Bool,
    credential: String
) -> CodexRuntimeApprovalDecision {
    if nonInteractive { return .decline }
    let title = boundedSafeText(request.title, credential: credential, limit: 500)
    let summary = boundedSafeText(request.summary, credential: credential, limit: 2_000)
    writeStderr("\nApproval required: \(title)\n\(summary)\nAccept? [y]es / [a]lways session / [n]o / [c]ancel turn: ")
    let answer = readLine()?
        .trimmingCharacters(in: .whitespacesAndNewlines)
        .lowercased() ?? "n"
    switch answer {
    case "y", "yes": return .accept
    case "a", "always": return .acceptForSession
    case "c", "cancel": return .cancel
    default: return .decline
    }
}

private func writeRuntimeOutputs(
    _ document: RuntimeResultDocument,
    statusOutput: URL?,
    summaryOutput: URL?,
    operationLogOutput: URL?,
    reportOutput: URL?,
    visualValidationEnabled: String
) throws {
    let encoder = JSONEncoder()
    encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
    let documentData = try encoder.encode(document)
    if let summaryOutput {
        try writeAtomically(documentData, to: summaryOutput)
    }
    if let operationLogOutput {
        try writeAtomically(try encoder.encode(document.items), to: operationLogOutput)
    }
    if let statusOutput {
        let lines = [
            "runtime_executed=\(shellQuote(document.executed ? "true" : "false"))",
            "runtime_status=\(shellQuote(document.status))",
            "tool_call_count=\(shellQuote(String(document.toolCallCount)))",
            "read_tool_count=\(shellQuote(String(document.readToolCount)))",
            "write_tool_count=\(shellQuote(String(document.writeToolCount)))",
            "final_summary=\(shellQuote(document.finalSummary.replacingOccurrences(of: "\n", with: " ")))",
        ]
        try writeAtomically(
            Data((lines.joined(separator: "\n") + "\n").utf8),
            to: statusOutput)
    }
    if let reportOutput {
        try FileManager.default.createDirectory(
            at: reportOutput,
            withIntermediateDirectories: true)
        let visualRequired = visualValidationEnabled.lowercased() == "true"
        let usageObject: [String: Any]
        if let usage = document.usage {
            usageObject = [
                "input_tokens": usage.inputTokens,
                "cached_input_tokens": usage.cachedInputTokens,
                "cache_write_input_tokens": usage.cacheWriteInputTokens,
                "output_tokens": usage.outputTokens,
                "reasoning_output_tokens": usage.reasoningOutputTokens,
                "total_tokens": usage.totalTokens,
                "duration_ms": usage.durationMs.map { $0 as Any } ?? NSNull(),
            ]
        } else {
            usageObject = [:]
        }
        let report: [String: Any] = [
            "schema_version": forgisRunReportSchema,
            "runtime_kernel": document.kernel,
            "runtime_version": document.actualRuntimeVersion,
            "status": document.status,
            "executed": document.executed,
            "target_repo": document.targetRepo,
            "unit_id": document.unitID,
            "session_id": document.sessionID,
            "thread_id": document.threadID,
            "turn_id": document.turnID,
            "final_summary": document.finalSummary,
            "tool_call_count": document.toolCallCount,
            "write_tool_count": document.writeToolCount,
            "usage": usageObject,
            "visual_validation": [
                "required": visualRequired,
                "provider": "qwen",
                "mode": "reference_guidance",
                "called": false,
                "guidance_completed": false,
                "valid_visual_evidence": "NO",
                "compare_screenshots_completed": false,
                "full_rendered_validation": false,
                "actual_screenshot_blocker": visualRequired
                    ? "QWEN_VISUAL_DYNAMIC_TOOL_NOT_AVAILABLE_ON_CODEX_RUNTIME"
                    : "none",
                "visual_validation_limitations": "The shared Codex v1 cutover does not invoke the retired Python Qwen tool path.",
            ],
        ]
        let reportData = try JSONSerialization.data(
            withJSONObject: report,
            options: [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes])
        try writeAtomically(
            reportData,
            to: reportOutput.appendingPathComponent("FORGIS_RUN_REPORT.json"))
        let markdown = """
        # Forgis Run Report

        - Schema: `\(forgisRunReportSchema)`
        - Kernel: `\(document.kernel)`
        - Runtime: `\(document.actualRuntimeVersion)`
        - Status: `\(document.status)`
        - Tool calls: `\(document.toolCallCount)`
        - File-change items: `\(document.writeToolCount)`

        ## Final Summary

        \(document.finalSummary)

        ## Visual Validation

        - Required: `\(visualRequired)`
        - Called: `false`
        - Full rendered validation: `false`
        - Limitation: shared Codex v1 does not invoke the retired Python Qwen tool path.
        """
        try writeAtomically(
            Data(markdown.utf8),
            to: reportOutput.appendingPathComponent("FORGIS_RUN_REPORT.md"))
    }
}

private func printDocument(_ document: RuntimeResultDocument) throws {
    let encoder = JSONEncoder()
    encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
    guard let text = String(data: try encoder.encode(document), encoding: .utf8) else {
        throw ForgisRuntimeCLIError.runtime("Could not encode runtime result.")
    }
    print(text)
}

private func printJSON(_ object: [String: Any]) throws {
    let data = try JSONSerialization.data(
        withJSONObject: object,
        options: [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes])
    guard let text = String(data: data, encoding: .utf8) else {
        throw ForgisRuntimeCLIError.runtime("Could not encode JSON output.")
    }
    print(text)
}

private func normalizedResponsesRoute(
    _ rawValue: String
) throws -> (baseURL: URL, queryParameters: [String: String]) {
    let trimmed = rawValue.trimmingCharacters(in: .whitespacesAndNewlines)
    guard var components = URLComponents(string: trimmed),
          ["http", "https"].contains(components.scheme?.lowercased() ?? ""),
          components.host?.isEmpty == false,
          components.user == nil,
          components.password == nil,
          components.fragment == nil else {
        throw ForgisRuntimeCLIError.invalid(
            "--api-base must be a safe HTTP(S) Responses API base URL.")
    }
    var queryParameters: [String: String] = [:]
    for item in components.queryItems ?? [] {
        guard item.name.lowercased() == "api-version",
              let value = item.value,
              !value.isEmpty,
              queryParameters[item.name] == nil else {
            throw ForgisRuntimeCLIError.invalid(
                "--api-base supports only one non-secret api-version query parameter.")
        }
        queryParameters[item.name] = value
    }
    components.query = nil
    let lowerPath = components.path.lowercased()
    if lowerPath.hasSuffix("/chat/completions") {
        throw ForgisRuntimeCLIError.invalid(
            "Chat Completions endpoints are not supported by the Codex runtime.")
    }
    if components.path.hasSuffix("/responses") {
        components.path = String(components.path.dropLast("/responses".count))
    }
    guard let url = components.url else {
        throw ForgisRuntimeCLIError.invalid("Invalid --api-base URL.")
    }
    return (url, queryParameters)
}

private func requestAdapter(_ rawValue: String) throws -> ProviderRequestAdapter {
    switch rawValue.trimmingCharacters(in: .whitespacesAndNewlines)
        .lowercased() {
    case "openai-compatible": return .openAICompatible
    case "openrouter": return .openRouter
    case "openai": return .openAI
    default:
        throw ForgisRuntimeCLIError.invalid(
            "--request-adapter must be openai-compatible, openrouter, or openai.")
    }
}

private func resolveCredential(
    modelEnvJSON: String,
    noAuthentication: Bool
) throws -> String {
    if noAuthentication { return "" }
    guard let data = modelEnvJSON.data(using: .utf8),
          let object = try JSONSerialization.jsonObject(with: data) as? [String: String],
          object.count == 1,
          let sourceEnvironmentName = object.values.first,
          isEnvironmentName(sourceEnvironmentName) else {
        throw ForgisRuntimeCLIError.invalid(
            "Codex runtime requires exactly one safe model_env credential mapping.")
    }
    guard let value = ProcessInfo.processInfo.environment[sourceEnvironmentName],
          !value.isEmpty else {
        throw ForgisRuntimeCLIError.missing(
            "Missing required model credential environment variable: \(sourceEnvironmentName)")
    }
    return value
}

private func isEnvironmentName(_ value: String) -> Bool {
    guard let first = value.unicodeScalars.first,
          CharacterSet.letters.union(CharacterSet(charactersIn: "_"))
            .contains(first) else { return false }
    return value.unicodeScalars.allSatisfy {
        CharacterSet.alphanumerics
            .union(CharacterSet(charactersIn: "_"))
            .contains($0)
    }
}

private func absoluteDirectoryURL(
    _ rawValue: String,
    label: String,
    createIfMissing: Bool = false
) throws -> URL {
    guard rawValue.hasPrefix("/") else {
        throw ForgisRuntimeCLIError.invalid("\(label) must be absolute.")
    }
    let url = URL(fileURLWithPath: rawValue, isDirectory: true)
        .standardizedFileURL
    if createIfMissing {
        try FileManager.default.createDirectory(
            at: url,
            withIntermediateDirectories: true)
    }
    var isDirectory: ObjCBool = false
    guard FileManager.default.fileExists(atPath: url.path, isDirectory: &isDirectory),
          isDirectory.boolValue else {
        throw ForgisRuntimeCLIError.missing(
            "\(label) directory is unavailable: \(url.path)")
    }
    return url.resolvingSymlinksInPath()
}

private func absoluteDirectoryPathURL(
    _ rawValue: String,
    label: String
) throws -> URL {
    guard rawValue.hasPrefix("/") else {
        throw ForgisRuntimeCLIError.invalid("\(label) must be absolute.")
    }
    return URL(fileURLWithPath: rawValue, isDirectory: true)
        .standardizedFileURL
        .resolvingSymlinksInPath()
}

private func absoluteFileURL(_ rawValue: String, label: String) throws -> URL {
    guard rawValue.hasPrefix("/") else {
        throw ForgisRuntimeCLIError.invalid("\(label) must be absolute.")
    }
    let url = URL(fileURLWithPath: rawValue)
        .standardizedFileURL
        .resolvingSymlinksInPath()
    var isDirectory: ObjCBool = false
    guard FileManager.default.fileExists(atPath: url.path, isDirectory: &isDirectory),
          !isDirectory.boolValue else {
        throw ForgisRuntimeCLIError.missing(
            "\(label) file is unavailable: \(url.path)")
    }
    return url
}

private func optionalOutputURL(
    _ rawValue: String,
    allowedRoot: URL,
    isDirectory: Bool = false
) throws -> URL? {
    guard !rawValue.isEmpty else { return nil }
    guard rawValue.hasPrefix("/") else {
        throw ForgisRuntimeCLIError.invalid(
            "Runtime output paths must be absolute.")
    }
    let url = canonicalizedFutureURL(
        URL(fileURLWithPath: rawValue, isDirectory: isDirectory))
    guard isInside(url, root: allowedRoot) else {
        throw ForgisRuntimeCLIError.invalid(
            "Runtime outputs must stay inside --runtime-root.")
    }
    return url
}

private func canonicalizedFutureURL(_ input: URL) -> URL {
    var ancestor = input.standardizedFileURL
    var suffix: [String] = []
    while !FileManager.default.fileExists(atPath: ancestor.path),
          ancestor.path != "/" {
        suffix.append(ancestor.lastPathComponent)
        ancestor.deleteLastPathComponent()
    }
    var result = ancestor.resolvingSymlinksInPath()
    for component in suffix.reversed() {
        result.appendPathComponent(component)
    }
    return result.standardizedFileURL
}

private func safeRelativePath(_ rawValue: String, label: String) throws -> String {
    let normalized = rawValue.replacingOccurrences(of: "\\", with: "/")
        .trimmingCharacters(in: CharacterSet(charactersIn: "/"))
    let parts = normalized.split(separator: "/").map(String.init)
    let secretWords = ["secret", "token", "credential", "password", ".env"]
    guard !normalized.isEmpty,
          !rawValue.hasPrefix("/"),
          !parts.contains("."),
          !parts.contains(".."),
          !parts.contains(".git"),
          !parts.contains(where: { part in
              secretWords.contains { part.lowercased().contains($0) }
          }) else {
        throw ForgisRuntimeCLIError.invalid(
            "\(label) contains an unsafe relative path.")
    }
    return parts.joined(separator: "/")
}

private func safeLabel(
    _ rawValue: String,
    label: String,
    maximum: Int = 512
) throws -> String {
    let value = rawValue.trimmingCharacters(in: .whitespacesAndNewlines)
    guard !value.isEmpty,
          value.count <= maximum,
          !value.unicodeScalars.contains(where: {
              CharacterSet.controlCharacters.contains($0)
          }) else {
        throw ForgisRuntimeCLIError.invalid("\(label) is invalid.")
    }
    return value
}

private func safeOptionalLabel(
    _ rawValue: String,
    label: String,
    maximum: Int
) throws -> String {
    if rawValue.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
        return ""
    }
    return try safeLabel(rawValue, label: label, maximum: maximum)
}

private func readBoundedUTF8(_ url: URL, maximumBytes: Int) throws -> String {
    let values = try url.resourceValues(
        forKeys: [.isRegularFileKey, .isSymbolicLinkKey, .fileSizeKey])
    guard values.isRegularFile == true,
          values.isSymbolicLink != true,
          let size = values.fileSize,
          size > 0,
          size <= maximumBytes else {
        throw ForgisRuntimeCLIError.invalid(
            "Task prompt must be a bounded regular file.")
    }
    let data = try Data(contentsOf: url, options: [.mappedIfSafe])
    guard data.count == size,
          let text = String(data: data, encoding: .utf8),
          !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
        throw ForgisRuntimeCLIError.invalid(
            "Task prompt must contain nonempty UTF-8 text.")
    }
    return text
}

private func isInside(_ url: URL, root: URL) -> Bool {
    let path = url.standardizedFileURL.path
    let rootPath = root.standardizedFileURL.path
    return path == rootPath || path.hasPrefix(rootPath + "/")
}

private func stableFNV64(_ values: [String]) -> String {
    var hash: UInt64 = 14_695_981_039_346_656_037
    for byte in values.joined(separator: "\u{001F}").utf8 {
        hash ^= UInt64(byte)
        hash = hash &* 1_099_511_628_211
    }
    return String(hash, radix: 16)
}

private func boundedSafeText(
    _ rawValue: String,
    credential: String,
    limit: Int = maximumFinalSummaryCharacters
) -> String {
    var value = rawValue
        .replacingOccurrences(of: "\r", with: " ")
        .trimmingCharacters(in: .whitespacesAndNewlines)
    if !credential.isEmpty {
        value = value.replacingOccurrences(of: credential, with: "[REDACTED]")
    }
    value = String(value.unicodeScalars.filter {
        !CharacterSet.controlCharacters.contains($0) || $0 == "\n"
    })
    if value.count > limit {
        value = String(value.prefix(max(0, limit - 20))) + "… [truncated]"
    }
    return value
}

private func writeAtomically(_ data: Data, to url: URL) throws {
    try FileManager.default.createDirectory(
        at: url.deletingLastPathComponent(),
        withIntermediateDirectories: true)
    try data.write(to: url, options: .atomic)
}

private func shellQuote(_ value: String) -> String {
    "'" + value.replacingOccurrences(of: "'", with: "'\"'\"'") + "'"
}

private func writeStderr(_ text: String) {
    FileHandle.standardError.write(Data(text.utf8))
}
