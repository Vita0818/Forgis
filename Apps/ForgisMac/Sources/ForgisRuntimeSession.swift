#if canImport(SwiftUI)
import AppKit
import Foundation
import IntatisCodexRuntime
import IntatisCore
import IntatisProtocol
import IntatisProviders

private let forgisUIProjectionSchema = "forgis.ui_projection.v1"
private let forgisRunReportSchema = "forgis.run_report.v7.0"
private let maximumTaskBytes = 1_000_000
private let maximumMessages = 400
private let maximumActivities = 200
private let maximumMessageCharacters = 64_000
private let maximumUserTurnCharacters = 200_000

private enum ForgisRuntimeUIError: Error, LocalizedError {
    case invalid(String)
    case missing(String)
    case unavailable(String)

    var errorDescription: String? {
        switch self {
        case .invalid(let message), .missing(let message),
             .unavailable(let message):
            return message
        }
    }
}

private struct ForgisPreparedRuntimeContext {
    let sourceURL: URL
    let targetURL: URL
    let workspaceURL: URL
    let taskURL: URL
    let targetRepo: String
    let unitID: String
    let endpointID: String
    let model: String
    let baseURL: URL?
    let queryParameters: [String: String]
    let requestAdapter: ForgisRequestAdapter
    let reasoningEffort: String?
    let credential: String
    let sessionID: SessionID
    let runtimeRootURL: URL?
    let taskText: String
}

@MainActor
final class ForgisRuntimeViewModel: ObservableObject {
    @Published var workspace: ForgisWorkspaceConfiguration
    @Published var provider: ForgisProviderConfiguration
    @Published var runMode: RunMode
    @Published var runAgent: Bool
    @Published var confirmRealRun = false
    @Published var input = ""
    @Published var selectedReportID: String?

    @Published private(set) var messages: [ForgisRuntimeMessage] = []
    @Published private(set) var activities: [ForgisRuntimeActivity] = []
    @Published private(set) var pendingApprovals: [CodexRuntimeApprovalRequest] = []
    @Published private(set) var usage: ForgisRuntimeUsageSummary?
    @Published private(set) var reports: [ForgisStoredReport] = []
    @Published private(set) var status: ForgisRuntimeStatus = .unconfigured
    @Published private(set) var credentialStatus: ForgisCredentialStatus = .unset
    @Published private(set) var runtimeVersion = ""
    @Published private(set) var threadID = ""
    @Published private(set) var currentTurnID = ""
    @Published private(set) var isWorking = false
    @Published private(set) var errorText: String?
    @Published private(set) var settingsStatusText: String?

    private let preferencesStore: ForgisRuntimePreferencesStore
    private let credentialStore: ForgisRuntimeCredentialStore
    private let fileStore: ForgisRuntimeFileStore?
    private let fileStoreError: String?
    private var runtime: CodexAppServerSession?
    private var eventTask: Task<Void, Never>?
    private var turnTask: Task<Void, Never>?
    private var activeCredential = ""
    private var reportedTurnIDs: Set<String> = []
    private var turnMessageStartIndex = 0

    init(
        preferencesStore: ForgisRuntimePreferencesStore =
            ForgisRuntimePreferencesStore(),
        credentialStore: ForgisRuntimeCredentialStore =
            ForgisRuntimeCredentialStore()
    ) {
        self.preferencesStore = preferencesStore
        self.credentialStore = credentialStore
        workspace = preferencesStore.loadWorkspace()
        provider = preferencesStore.loadProvider()
        let execution = preferencesStore.loadExecution()
        runMode = execution.0
        runAgent = execution.1

        do {
            fileStore = try ForgisRuntimeFileStore()
            fileStoreError = nil
        } catch {
            fileStore = nil
            fileStoreError = error.localizedDescription
        }

        refreshCredentialStatus()
        reloadReports()
        loadCurrentProjection()
        if status == .unconfigured && configurationLooksComplete {
            status = .ready
        }
    }

    var selectedReport: ForgisStoredReport? {
        guard let selectedReportID else { return reports.first }
        return reports.first { $0.id == selectedReportID } ?? reports.first
    }

    var canEditConfiguration: Bool {
        runtime == nil && !isWorking
    }

    var canStartMigration: Bool {
        !isWorking && threadID.isEmpty
    }

    var canSendFollowUp: Bool {
        !isWorking
            && !threadID.isEmpty
            && !input.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    var canStop: Bool { isWorking && runtime != nil }

    var runtimeSubtitle: String {
        let model = provider.model.trimmingCharacters(in: .whitespacesAndNewlines)
        if model.isEmpty { return status.title }
        return "\(model) · \(status.title)"
    }

    var safetyItems: [SafetyItem] {
        let sourceReady = directoryExists(workspace.sourcePath)
        let targetReady = directoryExists(workspace.targetPath)
            && safeRelativePath(workspace.targetSubdir) != nil
        let credentialReady: Bool
        switch credentialStatus {
        case .keychain, .environment, .notRequired:
            credentialReady = true
        case .unset, .error:
            credentialReady = false
        }
        return [
            SafetyItem(
                title: "Source readonly",
                tone: sourceReady ? .success : .warning),
            SafetyItem(
                title: "Target subdir bound",
                tone: targetReady ? .success : .warning),
            SafetyItem(
                title: "Credential isolated",
                tone: credentialReady ? .success : .warning),
            SafetyItem(
                title: "Intatis v1 only",
                tone: .success),
        ]
    }

    func chooseSourceDirectory() {
        guard canEditConfiguration,
              let url = chooseURL(directories: true) else { return }
        workspace.sourcePath = url.path
    }

    func chooseTargetDirectory() {
        guard canEditConfiguration,
              let url = chooseURL(directories: true) else { return }
        workspace.targetPath = url.path
        if workspace.targetRepo.trimmingCharacters(
            in: .whitespacesAndNewlines).isEmpty {
            workspace.targetRepo = url.lastPathComponent
        }
        let defaultTask = url.appendingPathComponent("FORGIS_TASK.md")
        if FileManager.default.fileExists(atPath: defaultTask.path) {
            workspace.taskPath = defaultTask.path
        }
    }

    func chooseTaskFile() {
        guard canEditConfiguration,
              let url = chooseURL(directories: false) else { return }
        workspace.taskPath = url.path
    }

    func saveSettings() {
        guard canEditConfiguration else {
            settingsStatusText =
                "Start a new session before changing runtime configuration."
            return
        }
        do {
            try preferencesStore.save(
                workspace: workspace,
                provider: provider,
                mode: runMode,
                runAgent: runAgent)
            confirmRealRun = false
            messages = []
            activities = []
            pendingApprovals = []
            usage = nil
            runtimeVersion = ""
            threadID = ""
            currentTurnID = ""
            reportedTurnIDs = []
            refreshCredentialStatus()
            loadCurrentProjection()
            if status == .unconfigured && configurationLooksComplete {
                status = .ready
            }
            settingsStatusText = "Settings saved. No network request was made."
            errorText = nil
        } catch {
            settingsStatusText = bounded(error.localizedDescription, limit: 500)
        }
    }

    func resetSettings() {
        guard canEditConfiguration else {
            settingsStatusText =
                "Start a new session before resetting runtime configuration."
            return
        }
        preferencesStore.reset()
        workspace = .empty
        provider = .empty
        runMode = .dryRun
        runAgent = true
        confirmRealRun = false
        messages = []
        activities = []
        usage = nil
        runtimeVersion = ""
        threadID = ""
        currentTurnID = ""
        status = .unconfigured
        settingsStatusText = "Settings reset. Stored reports and Keychain credentials were preserved."
        refreshCredentialStatus()
    }

    func saveCredential(_ rawValue: String) -> Bool {
        do {
            try credentialStore.save(rawValue)
            refreshCredentialStatus()
            settingsStatusText = "Responses credential saved to Keychain."
            return true
        } catch {
            settingsStatusText = bounded(error.localizedDescription, limit: 500)
            refreshCredentialStatus()
            return false
        }
    }

    func deleteCredential() {
        do {
            try credentialStore.delete()
            settingsStatusText = "Keychain credential deleted."
        } catch {
            settingsStatusText = bounded(error.localizedDescription, limit: 500)
        }
        refreshCredentialStatus()
    }

    func refreshCredentialStatus() {
        guard provider.requiresAuthentication else {
            credentialStatus = .notRequired
            return
        }
        do {
            if try credentialStore.hasCredential() {
                credentialStatus = .keychain
                return
            }
        } catch {
            credentialStatus = .error(bounded(error.localizedDescription, limit: 500))
            return
        }
        let environmentName = provider.credentialEnvironmentName
            .trimmingCharacters(in: .whitespacesAndNewlines)
        if isEnvironmentName(environmentName),
           ProcessInfo.processInfo.environment[environmentName]?.isEmpty == false {
            credentialStatus = .environment(environmentName)
        } else {
            credentialStatus = .unset
        }
    }

    func startMigration() {
        guard canStartMigration else { return }
        isWorking = true
        errorText = nil
        turnTask = Task { @MainActor [weak self] in
            await self?.runInitialMigration()
        }
    }

    func sendFollowUp() {
        guard canSendFollowUp else { return }
        let text = input.trimmingCharacters(in: .whitespacesAndNewlines)
        guard text.count <= maximumUserTurnCharacters else {
            errorText = "Follow-up text exceeds the bounded Intatis turn input limit."
            return
        }
        input = ""
        isWorking = true
        errorText = nil
        turnMessageStartIndex = messages.count
        messages.append(ForgisRuntimeMessage(role: .user, text: text))
        trimProjectionCollections()
        turnTask = Task { @MainActor [weak self] in
            guard let self else { return }
            do {
                let context = try self.preparedContext(
                    requiresProvider: true,
                    resolvesCredential: true,
                    createsWorkspace: true)
                try await self.persistProjectionOrStop(
                    sessionID: context.sessionID.rawValue)
                await self.performTurn(text: text, context: context)
            } catch {
                await self.fail(error, context: nil)
            }
        }
    }

    func stopCurrentTurn() {
        guard canStop, let runtime else { return }
        status = .stopping
        Task { @MainActor [weak self] in
            do {
                try await runtime.interruptCurrentTurn()
            } catch {
                self?.errorText = self?.sanitized(error.localizedDescription)
                self?.status = .failed
            }
        }
    }

    func resolveApproval(
        _ request: CodexRuntimeApprovalRequest,
        decision: CodexRuntimeApprovalDecision
    ) {
        guard let runtime else {
            errorText = "The Intatis runtime is not available for this approval."
            return
        }
        Task { @MainActor [weak self] in
            do {
                try await runtime.resolveApproval(
                    requestID: request.requestID,
                    decision: decision)
            } catch {
                self?.errorText = self?.sanitized(error.localizedDescription)
            }
        }
    }

    func approvalTitle(_ request: CodexRuntimeApprovalRequest) -> String {
        sanitized(request.title, limit: 500)
    }

    func approvalSummary(_ request: CodexRuntimeApprovalRequest) -> String {
        sanitized(request.summary, limit: 2_000)
    }

    func startNewSession() {
        guard !isWorking else { return }
        Task { @MainActor [weak self] in
            guard let self else { return }
            await self.shutdownRuntime()
            self.workspace.sessionToken = UUID().uuidString.lowercased()
            self.messages = []
            self.activities = []
            self.pendingApprovals = []
            self.usage = nil
            self.runtimeVersion = ""
            self.threadID = ""
            self.currentTurnID = ""
            self.reportedTurnIDs = []
            self.turnMessageStartIndex = 0
            self.status = self.configurationLooksComplete ? .ready : .unconfigured
            self.confirmRealRun = false
            do {
                try self.preferencesStore.save(
                    workspace: self.workspace,
                    provider: self.provider,
                    mode: self.runMode,
                    runAgent: self.runAgent)
                self.settingsStatusText = "A new Intatis session is ready. Previous session data was preserved."
            } catch {
                self.settingsStatusText = self.bounded(
                    error.localizedDescription,
                    limit: 500)
            }
        }
    }

    func shutdown() async {
        turnTask?.cancel()
        turnTask = nil
        await shutdownRuntime()
        if status == .running || status == .starting || status == .stopping {
            status = configurationLooksComplete ? .ready : .unconfigured
        }
    }

    private func runInitialMigration() async {
        var context: ForgisPreparedRuntimeContext?
        do {
            if runMode == .dryRun || !runAgent {
                context = try preparedContext(
                    requiresProvider: false,
                    resolvesCredential: false,
                    createsWorkspace: false)
                let reason = runMode == .dryRun
                    ? "dry_run"
                    : "run_agent_disabled"
                status = .skipped
                messages.append(ForgisRuntimeMessage(
                    role: .system,
                    text: "The Intatis runtime was not started because \(reason). Source and target were not modified."))
                try persistReport(
                    status: "skipped-\(reason)",
                    executed: false,
                    turnID: "",
                    context: context!,
                    runtimeError: "")
                isWorking = false
                turnTask = nil
                return
            }
            guard confirmRealRun else {
                throw ForgisRuntimeUIError.invalid(
                    "Real migration requires explicit confirmation that target_subdir may be modified.")
            }
            context = try preparedContext(
                requiresProvider: true,
                resolvesCredential: true,
                createsWorkspace: true)
            let unit = context!.unitID.isEmpty
                ? "No explicit unit"
                : context!.unitID
            turnMessageStartIndex = messages.count
            messages.append(ForgisRuntimeMessage(
                role: .user,
                text: "Start migration · \(unit) · \(context!.taskURL.lastPathComponent)"))
            trimProjectionCollections()
            try await persistProjectionOrStop(
                sessionID: context!.sessionID.rawValue)
            await performTurn(
                text: migrationPrompt(context!),
                context: context!)
        } catch {
            await fail(error, context: context)
        }
    }

    private func performTurn(
        text: String,
        context: ForgisPreparedRuntimeContext
    ) async {
        do {
            let runtime = try await runtimeSession(context: context)
            let result = try await runtime.runTurn(text: text)
            await Task.yield()
            if !reportedTurnIDs.contains(result.turnID) {
                try await completeTurn(result, context: context)
            }
            if !result.succeeded, errorText == nil {
                errorText = sanitized(
                    result.errorMessage ?? "The Intatis turn ended with status \(result.status).")
            }
        } catch {
            await fail(error, context: context)
        }
        turnTask = nil
    }

    private func runtimeSession(
        context: ForgisPreparedRuntimeContext
    ) async throws -> CodexAppServerSession {
        if let runtime { return runtime }
        guard let baseURL = context.baseURL,
              let runtimeRootURL = context.runtimeRootURL else {
            throw ForgisRuntimeUIError.unavailable(
                "The real-run Intatis runtime context is incomplete.")
        }
        let upstreamAdapter: ProviderRequestAdapter
        switch context.requestAdapter {
        case .responsesCompatible:
            upstreamAdapter = .openAICompatible
        case .openRouter:
            upstreamAdapter = .openRouter
        }
        let route = ResponsesRuntimeRoute(
            endpointID: context.endpointID,
            model: ModelID(rawValue: context.model),
            baseURL: baseURL,
            queryParameters: context.queryParameters,
            bearerToken: context.credential,
            reasoningEffort: context.reasoningEffort,
            requestAdapter: upstreamAdapter)
        let configuration = CodexRuntimeConfiguration(
            sessionID: context.sessionID,
            mode: .code,
            workspaceURL: context.workspaceURL,
            runtimeRootURL: runtimeRootURL,
            route: route,
            approvalReviewer: .user,
            reasoningEffort: context.reasoningEffort)
        let newRuntime = CodexAppServerSession(configuration: configuration)
        activeCredential = context.credential
        status = .starting
        let stream = await newRuntime.events()
        eventTask = Task { @MainActor [weak self] in
            for await event in stream {
                guard !Task.isCancelled else { return }
                await self?.handle(event, context: context)
            }
        }
        do {
            let identity = try await newRuntime.start()
            runtime = newRuntime
            runtimeVersion = identity.runtimeVersion
            threadID = identity.threadID
            status = .ready
            try await persistProjectionOrStop(
                sessionID: context.sessionID.rawValue)
            return newRuntime
        } catch {
            eventTask?.cancel()
            eventTask = nil
            await newRuntime.shutdown()
            activeCredential = ""
            throw error
        }
    }

    private func handle(
        _ event: CodexRuntimeEvent,
        context: ForgisPreparedRuntimeContext
    ) async {
        switch event {
        case .ready(let identity):
            runtimeVersion = identity.runtimeVersion
            threadID = identity.threadID
            status = .ready
        case .turnStarted(let turnID):
            currentTurnID = turnID
            status = .running
            isWorking = true
        case .assistantDelta(let itemID, let text, let phase):
            upsertAssistant(
                itemID: itemID,
                text: sanitized(text),
                phase: phase?.rawValue,
                complete: false,
                isDelta: true)
        case .assistantCompleted(let itemID, let text, let phase):
            upsertAssistant(
                itemID: itemID,
                text: sanitized(text),
                phase: phase?.rawValue,
                complete: true,
                isDelta: false)
            try? await persistProjectionOrStop(
                sessionID: context.sessionID.rawValue)
        case .reasoningDelta:
            break
        case .appServerEvent:
            break
        case .itemStarted(let item):
            upsertActivity(item)
        case .itemCompleted(let item):
            upsertActivity(item)
            try? await persistProjectionOrStop(
                sessionID: context.sessionID.rawValue)
        case .approvalRequested(let request):
            if !pendingApprovals.contains(where: {
                $0.requestID == request.requestID
            }) {
                pendingApprovals.append(request)
            }
        case .approvalResolved(let requestID):
            pendingApprovals.removeAll { $0.requestID == requestID }
        case .responsesUsage(let value):
            usage = ForgisRuntimeUsageSummary(
                inputTokens: value.inputTokens,
                cachedInputTokens: value.cachedInputTokens,
                cacheWriteInputTokens: value.cacheWriteInputTokens,
                outputTokens: value.outputTokens,
                reasoningOutputTokens: value.reasoningOutputTokens,
                totalTokens: value.totalTokens,
                durationMs: value.durationMs)
        case .goalUpdated:
            break
        case .turnCompleted(let result):
            do {
                try await completeTurn(result, context: context)
            } catch {
                errorText = sanitized(error.localizedDescription)
                status = .failed
            }
        case .runtimeError(_, let message, let fatal):
            let safe = sanitized(message)
            errorText = safe
            if fatal {
                status = .failed
                isWorking = false
            }
        case .child:
            break
        @unknown default:
            break
        }
    }

    private func completeTurn(
        _ result: CodexRuntimeTurnResult,
        context: ForgisPreparedRuntimeContext
    ) async throws {
        guard reportedTurnIDs.insert(result.turnID).inserted else { return }
        currentTurnID = result.turnID
        status = result.succeeded ? .completed : .failed
        isWorking = false
        pendingApprovals = []
        try persistReport(
            status: result.status,
            executed: true,
            turnID: result.turnID,
            context: context,
            runtimeError: result.errorMessage.map {
                sanitized($0)
            } ?? "")
        try await persistProjectionOrStop(
            sessionID: context.sessionID.rawValue)
    }

    private func fail(
        _ error: Error,
        context: ForgisPreparedRuntimeContext?
    ) async {
        let safe = sanitized(error.localizedDescription)
        errorText = safe
        status = .failed
        isWorking = false
        pendingApprovals = []
        messages.append(ForgisRuntimeMessage(
            role: .system,
            text: safe))
        trimProjectionCollections()
        if let context {
            do {
                try persistReport(
                    status: "failed",
                    executed: runtimeVersion.isEmpty == false,
                    turnID: currentTurnID,
                    context: context,
                    runtimeError: safe)
                try await persistProjectionOrStop(
                    sessionID: context.sessionID.rawValue)
            } catch {
                errorText = "\(safe) Report persistence also failed: \(bounded(error.localizedDescription, limit: 500))"
            }
        }
        turnTask = nil
    }

    private func persistReport(
        status: String,
        executed: Bool,
        turnID: String,
        context: ForgisPreparedRuntimeContext,
        runtimeError: String
    ) throws {
        guard let fileStore else {
            throw ForgisRuntimeUIError.unavailable(
                "Forgis runtime storage is unavailable: \(fileStoreError ?? "unknown error")")
        }
        let currentTurnMessages = messages.dropFirst(
            min(turnMessageStartIndex, messages.count))
        let finalSummary = currentTurnMessages.reversed().first(where: {
            $0.role == .assistant && !$0.isCommentary && $0.isComplete
                && !$0.text.isEmpty
        })?.text
            ?? (runtimeError.isEmpty
                ? "The Intatis runtime finished without a final assistant message."
                : runtimeError)
        let report = ForgisRunReport(
            schemaVersion: forgisRunReportSchema,
            runtimeKernel: "intatis-codex-app-server",
            runtimeVersion: runtimeVersion.isEmpty ? "not-started" : runtimeVersion,
            status: status,
            executed: executed,
            targetRepo: context.targetRepo,
            unitID: context.unitID,
            sessionID: context.sessionID.rawValue,
            threadID: threadID,
            turnID: turnID,
            finalSummary: bounded(finalSummary, limit: 16_000),
            runtimeError: bounded(runtimeError, limit: 4_000),
            toolCallCount: activities.filter {
                Self.runtimeToolKinds.contains($0.kind)
            }.count,
            writeToolCount: activities.filter { $0.kind == "fileChange" }.count,
            usage: usage,
            visualValidation: .unavailable)
        let stored = try fileStore.writeReport(
            report,
            activities: activities)
        reports.removeAll { $0.id == stored.id }
        reports.insert(stored, at: 0)
        selectedReportID = stored.id
    }

    private func persistProjectionOrStop(
        sessionID: String
    ) async throws {
        guard let fileStore else {
            throw ForgisRuntimeUIError.unavailable(
                "Forgis runtime storage is unavailable: \(fileStoreError ?? "unknown error")")
        }
        let projection = ForgisSessionProjection(
            schemaVersion: forgisUIProjectionSchema,
            sessionID: sessionID,
            threadID: threadID,
            runtimeVersion: runtimeVersion,
            status: status,
            messages: messages,
            activities: activities,
            usage: usage)
        do {
            try fileStore.saveProjection(projection)
        } catch {
            if let runtime, isWorking {
                try? await runtime.interruptCurrentTurn()
            }
            throw ForgisRuntimeUIError.unavailable(
                "Forgis stopped because its UI projection could not be persisted: \(bounded(error.localizedDescription, limit: 500))")
        }
    }

    private func loadCurrentProjection() {
        let needsProvider = runMode == .realRun && runAgent
        guard let fileStore,
              let sessionID = try? preparedContext(
                requiresProvider: needsProvider,
                resolvesCredential: false,
                createsWorkspace: false).sessionID.rawValue,
              let projection = try? fileStore.loadProjection(
                sessionID: sessionID) else {
            if threadID.isEmpty {
                status = configurationLooksComplete ? .ready : .unconfigured
            }
            return
        }
        messages = projection.messages
        activities = projection.activities
        usage = projection.usage
        runtimeVersion = projection.runtimeVersion
        threadID = projection.threadID
        switch projection.status {
        case .starting, .running, .stopping:
            status = .failed
            messages.append(ForgisRuntimeMessage(
                role: .system,
                text: "The previous UI process ended during an active turn. Resume only through an explicit follow-up; Forgis did not select a fallback runtime."))
        default:
            status = projection.status
        }
        trimProjectionCollections()
    }

    private func reloadReports() {
        guard let fileStore else { return }
        do {
            reports = try fileStore.loadReports()
            selectedReportID = reports.first?.id
        } catch {
            errorText = bounded(error.localizedDescription, limit: 500)
        }
    }

    private func preparedContext(
        requiresProvider: Bool,
        resolvesCredential: Bool,
        createsWorkspace: Bool
    ) throws -> ForgisPreparedRuntimeContext {
        let source = try existingDirectory(
            workspace.sourcePath,
            label: "Source repository")
        let target = try existingDirectory(
            workspace.targetPath,
            label: "Target repository")
        guard !isInside(source, root: target),
              !isInside(target, root: source) else {
            throw ForgisRuntimeUIError.invalid(
                "Source and target repositories must not overlap.")
        }
        guard let targetSubdir = safeRelativePath(workspace.targetSubdir) else {
            throw ForgisRuntimeUIError.invalid(
                "Target subdir must be a safe relative path.")
        }
        let requestedWorkspace = target
            .appendingPathComponent(targetSubdir, isDirectory: true)
            .standardizedFileURL
        let writableWorkspace = canonicalizedFutureURL(requestedWorkspace)
        guard requestedWorkspace == writableWorkspace,
              writableWorkspace != target,
              isInside(writableWorkspace, root: target) else {
            throw ForgisRuntimeUIError.invalid(
                "The writable workspace must be a strict, non-symlink target subdirectory.")
        }

        let taskURL = try existingFile(
            workspace.taskPath,
            label: "Task file")
        guard isInside(taskURL, root: target),
              !isInside(taskURL, root: writableWorkspace) else {
            throw ForgisRuntimeUIError.invalid(
                "The task file must be a read-only target input outside target_subdir.")
        }
        let taskText = try readBoundedTask(taskURL)
        let targetRepo = try safeLabel(
            workspace.targetRepo,
            label: "Target repository label",
            maximum: 512)
        let unitID = try safeOptionalLabel(
            workspace.unitID,
            label: "Unit ID",
            maximum: 120)

        var endpointID = "forgis-runtime"
        var model = "dry-run"
        var baseURL: URL?
        var queryParameters: [String: String] = [:]
        var reasoningEffort: String?
        var credential = ""
        if requiresProvider {
            endpointID = try safeLabel(
                provider.endpointID,
                label: "Endpoint ID",
                maximum: 128)
            model = try safeLabel(
                provider.model,
                label: "Model",
                maximum: 256)
            let route = try normalizedResponsesRoute(provider.responsesBaseURL)
            baseURL = route.url
            queryParameters = route.queryParameters
            reasoningEffort = try normalizedReasoningEffort(
                provider.reasoningEffort)
            if resolvesCredential {
                credential = try resolveCredential()
                guard credential.isEmpty || !taskText.contains(credential) else {
                    throw ForgisRuntimeUIError.invalid(
                        "The task file contains the configured model credential and cannot be sent.")
                }
            }
        }

        let digest = stableFNV64([
            targetRepo,
            writableWorkspace.path,
            unitID,
            model,
            baseURL?.absoluteString ?? "dry-run",
            provider.requestAdapter.rawValue,
            workspace.sessionToken,
        ])
        let sessionID = SessionID(rawValue: "forgis_\(digest)")
        let runtimeRoot: URL?
        if createsWorkspace {
            try FileManager.default.createDirectory(
                at: writableWorkspace,
                withIntermediateDirectories: true)
            guard let fileStore else {
                throw ForgisRuntimeUIError.unavailable(
                    "Forgis runtime storage is unavailable: \(fileStoreError ?? "unknown error")")
            }
            runtimeRoot = try fileStore.runtimeRoot(sessionID: sessionID.rawValue)
            guard let runtimeRoot,
                  !isInside(runtimeRoot, root: source),
                  !isInside(runtimeRoot, root: target),
                  !isInside(source, root: runtimeRoot),
                  !isInside(target, root: runtimeRoot) else {
                throw ForgisRuntimeUIError.invalid(
                    "Runtime storage must stay outside source and target repositories.")
            }
        } else {
            runtimeRoot = nil
        }

        return ForgisPreparedRuntimeContext(
            sourceURL: source,
            targetURL: target,
            workspaceURL: writableWorkspace,
            taskURL: taskURL,
            targetRepo: targetRepo,
            unitID: unitID,
            endpointID: endpointID,
            model: model,
            baseURL: baseURL,
            queryParameters: queryParameters,
            requestAdapter: provider.requestAdapter,
            reasoningEffort: reasoningEffort,
            credential: credential,
            sessionID: sessionID,
            runtimeRootURL: runtimeRoot,
            taskText: taskText)
    }

    private func resolveCredential() throws -> String {
        guard provider.requiresAuthentication else { return "" }
        if let value = try credentialStore.read(), !value.isEmpty {
            return value
        }
        let name = provider.credentialEnvironmentName
            .trimmingCharacters(in: .whitespacesAndNewlines)
        guard isEnvironmentName(name) else {
            throw ForgisRuntimeUIError.invalid(
                "Credential environment name is invalid.")
        }
        guard let value = ProcessInfo.processInfo.environment[name],
              !value.isEmpty else {
            throw ForgisRuntimeUIError.missing(
                "No Responses credential is available in Keychain or \(name).")
        }
        return value
    }

    private func migrationPrompt(
        _ context: ForgisPreparedRuntimeContext
    ) -> String {
        let unit = context.unitID.isEmpty
            ? "[no explicit unit]"
            : context.unitID
        return """
        Execute this Forgis migration task using the native Intatis Codex runtime and its native tools.

        Security and ownership contract:
        - The current working directory is the only writable root: \(context.workspaceURL.path)
        - The source repository is read-only: \(context.sourceURL.path)
        - The target repository outside the working directory is read-only: \(context.targetURL.path)
        - Never modify the task file: \(context.taskURL.path)
        - Use native Codex file, patch, command, sandbox, approval, context, and agent-loop capabilities.
        - Do not invoke or emulate the retired Forgis Python AgentLoop, Chat Completions client, or file-tool backend.
        - If a required capability is unavailable through the official Intatis runtime, report the exact blocker instead of inventing a fallback.

        Selected migration unit: \(unit)

        Task instructions:
        \(context.taskText)
        """
    }

    private func upsertAssistant(
        itemID: String,
        text: String,
        phase: String?,
        complete: Bool,
        isDelta: Bool
    ) {
        let id = "codex:\(itemID)"
        if let index = messages.firstIndex(where: { $0.id == id }) {
            let next = isDelta
                ? messages[index].text + text
                : text
            messages[index].text = bounded(
                next,
                limit: maximumMessageCharacters)
            messages[index].phase = phase
            messages[index].isComplete = complete
        } else {
            messages.append(ForgisRuntimeMessage(
                id: id,
                role: .assistant,
                text: bounded(text, limit: maximumMessageCharacters),
                phase: phase,
                isComplete: complete))
        }
        trimProjectionCollections()
    }

    private func upsertActivity(_ item: CodexRuntimeItem) {
        let activity = ForgisRuntimeActivity(
            id: item.id,
            kind: item.kind.rawValue,
            title: sanitized(item.title, limit: 1_000),
            detail: sanitized(item.detail, limit: 4_000),
            status: sanitized(item.status ?? "running", limit: 200),
            failed: item.isFailure)
        if let index = activities.firstIndex(where: { $0.id == item.id }) {
            activities[index] = activity
        } else if activities.count < maximumActivities {
            activities.append(activity)
        }
    }

    private static let runtimeToolKinds: Set<String> = [
        "command", "fileChange", "mcpTool", "dynamicTool",
        "collaboration", "subagent", "webSearch", "image",
    ]

    private func trimProjectionCollections() {
        if messages.count > maximumMessages {
            messages.removeFirst(messages.count - maximumMessages)
        }
        if activities.count > maximumActivities {
            activities.removeFirst(activities.count - maximumActivities)
        }
    }

    private func shutdownRuntime() async {
        eventTask?.cancel()
        eventTask = nil
        let runtimeToStop = runtime
        runtime = nil
        await runtimeToStop?.shutdown()
        activeCredential = ""
        pendingApprovals = []
    }

    private var configurationLooksComplete: Bool {
        !workspace.sourcePath.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && !workspace.targetPath.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && !workspace.taskPath.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && !workspace.targetRepo.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && !workspace.targetSubdir.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && (!runAgent || runMode == .dryRun
                || (!provider.model.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                    && !provider.responsesBaseURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty))
    }

    private func chooseURL(directories: Bool) -> URL? {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = directories
        panel.canChooseFiles = !directories
        panel.allowsMultipleSelection = false
        panel.canCreateDirectories = directories
        panel.resolvesAliases = true
        if directories {
            panel.prompt = "Choose"
        } else {
            panel.allowedContentTypes = []
            panel.prompt = "Use Task"
        }
        return panel.runModal() == .OK
            ? panel.url?.standardizedFileURL.resolvingSymlinksInPath()
            : nil
    }

    private func existingDirectory(_ raw: String, label: String) throws -> URL {
        let value = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard value.hasPrefix("/") else {
            throw ForgisRuntimeUIError.invalid("\(label) must be an absolute path.")
        }
        let url = URL(fileURLWithPath: value, isDirectory: true)
            .standardizedFileURL
            .resolvingSymlinksInPath()
        var isDirectory: ObjCBool = false
        guard FileManager.default.fileExists(
            atPath: url.path,
            isDirectory: &isDirectory),
              isDirectory.boolValue else {
            throw ForgisRuntimeUIError.missing("\(label) is unavailable.")
        }
        return url
    }

    private func existingFile(_ raw: String, label: String) throws -> URL {
        let value = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard value.hasPrefix("/") else {
            throw ForgisRuntimeUIError.invalid("\(label) must be an absolute path.")
        }
        let requested = URL(fileURLWithPath: value).standardizedFileURL
        let values = try requested.resourceValues(
            forKeys: [.isRegularFileKey, .isSymbolicLinkKey])
        guard values.isRegularFile == true,
              values.isSymbolicLink != true,
              requested.resolvingSymlinksInPath() == requested else {
            throw ForgisRuntimeUIError.missing(
                "\(label) must be a regular non-symlink file.")
        }
        return requested
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

    private func readBoundedTask(_ url: URL) throws -> String {
        let values = try url.resourceValues(forKeys: [.fileSizeKey])
        guard let size = values.fileSize,
              size > 0,
              size <= maximumTaskBytes else {
            throw ForgisRuntimeUIError.invalid(
                "Task file must contain at most \(maximumTaskBytes) bytes.")
        }
        let data = try Data(contentsOf: url, options: [.mappedIfSafe])
        guard data.count == size,
              let text = String(data: data, encoding: .utf8),
              !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw ForgisRuntimeUIError.invalid(
                "Task file must contain nonempty UTF-8 text.")
        }
        return text
    }

    private func normalizedResponsesRoute(
        _ raw: String
    ) throws -> (url: URL, queryParameters: [String: String]) {
        let value = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard var components = URLComponents(string: value),
              ["http", "https"].contains(
                components.scheme?.lowercased() ?? ""),
              components.host?.isEmpty == false,
              components.user == nil,
              components.password == nil,
              components.fragment == nil else {
            throw ForgisRuntimeUIError.invalid(
                "Responses base must be a safe HTTP(S) URL.")
        }
        var query: [String: String] = [:]
        for item in components.queryItems ?? [] {
            guard item.name.lowercased() == "api-version",
                  let value = item.value,
                  !value.isEmpty,
                  query[item.name] == nil else {
                throw ForgisRuntimeUIError.invalid(
                    "Responses base supports only one non-secret api-version query parameter.")
            }
            query[item.name] = value
        }
        components.query = nil
        let path = components.path.lowercased()
        guard !path.hasSuffix("/chat/completions") else {
            throw ForgisRuntimeUIError.invalid(
                "Chat Completions endpoints are not supported. Configure a native Responses API base.")
        }
        if path.hasSuffix("/responses") {
            components.path = String(
                components.path.dropLast("/responses".count))
        }
        guard let url = components.url else {
            throw ForgisRuntimeUIError.invalid("Responses base is invalid.")
        }
        return (url, query)
    }

    private func normalizedReasoningEffort(_ raw: String) throws -> String? {
        let value = raw.trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
        if value.isEmpty { return nil }
        guard [
            "minimal", "low", "medium", "high", "xhigh", "max", "ultra",
        ].contains(value) else {
            throw ForgisRuntimeUIError.invalid(
                "Reasoning effort is not supported by the Intatis runtime contract.")
        }
        return value
    }

    private func safeRelativePath(_ raw: String) -> String? {
        let normalized = raw.replacingOccurrences(of: "\\", with: "/")
            .trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        let parts = normalized.split(separator: "/").map(String.init)
        let secretWords = ["secret", "token", "credential", "password", ".env"]
        guard !normalized.isEmpty,
              !raw.hasPrefix("/"),
              !parts.contains("."),
              !parts.contains(".."),
              !parts.contains(".git"),
              !parts.contains(where: { part in
                  secretWords.contains { part.lowercased().contains($0) }
              }) else {
            return nil
        }
        return parts.joined(separator: "/")
    }

    private func safeLabel(
        _ raw: String,
        label: String,
        maximum: Int
    ) throws -> String {
        let value = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !value.isEmpty,
              value.count <= maximum,
              !value.unicodeScalars.contains(where: {
                  CharacterSet.controlCharacters.contains($0)
              }) else {
            throw ForgisRuntimeUIError.invalid("\(label) is invalid.")
        }
        return value
    }

    private func safeOptionalLabel(
        _ raw: String,
        label: String,
        maximum: Int
    ) throws -> String {
        if raw.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return ""
        }
        return try safeLabel(raw, label: label, maximum: maximum)
    }

    private func isEnvironmentName(_ value: String) -> Bool {
        guard let first = value.unicodeScalars.first,
              CharacterSet.letters
                .union(CharacterSet(charactersIn: "_"))
                .contains(first) else {
            return false
        }
        return value.unicodeScalars.allSatisfy {
            CharacterSet.alphanumerics
                .union(CharacterSet(charactersIn: "_"))
                .contains($0)
        }
    }

    private func isInside(_ url: URL, root: URL) -> Bool {
        let path = url.standardizedFileURL.path
        let rootPath = root.standardizedFileURL.path
        return path == rootPath || path.hasPrefix(rootPath + "/")
    }

    private func directoryExists(_ path: String) -> Bool {
        var isDirectory: ObjCBool = false
        return FileManager.default.fileExists(
            atPath: path,
            isDirectory: &isDirectory) && isDirectory.boolValue
    }

    private func stableFNV64(_ values: [String]) -> String {
        var hash: UInt64 = 14_695_981_039_346_656_037
        for byte in values.joined(separator: "\u{001F}").utf8 {
            hash ^= UInt64(byte)
            hash = hash &* 1_099_511_628_211
        }
        return String(hash, radix: 16)
    }

    private func sanitized(_ value: String, limit: Int = 16_000) -> String {
        var safe = value
        if !activeCredential.isEmpty {
            safe = safe.replacingOccurrences(
                of: activeCredential,
                with: "[REDACTED]")
        }
        return bounded(safe, limit: limit)
    }

    private func bounded(_ value: String, limit: Int) -> String {
        let clean = String(value.unicodeScalars.filter {
            !CharacterSet.controlCharacters.contains($0)
                || $0 == "\n"
        })
        guard clean.count > limit else { return clean }
        return String(clean.prefix(max(0, limit - 16))) + "… [truncated]"
    }
}
#endif
