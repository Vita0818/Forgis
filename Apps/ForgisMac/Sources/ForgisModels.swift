#if canImport(SwiftUI)
import Foundation
import SwiftUI

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

enum RunMode: String, Identifiable {
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

enum UnitStatus: String {
    case pending = "Pending"
    case running = "Running"
    case completed = "Completed"
    case failed = "Failed"
}

enum UnitRisk: String {
    case low = "Low"
    case medium = "Medium"
    case high = "High"
}

enum ValidationState: String {
    case notRun = "Not run"
    case passed = "Passed"
    case failed = "Failed"
}

struct MigrationRun: Identifiable {
    let id: String
    let sourceRepo: String
    let sourcePath: String
    let targetRepo: String
    let targetPath: String
    let targetSubdir: String
    let mode: RunMode
    let provider: String
    let model: String
    let apiBase: String
    let apiKeyEnvName: String
    let apiKeyStatus: String
    let configPath: String
}

struct MigrationUnit: Identifiable, Hashable {
    let id: String
    let title: String
    let sourcePath: String
    let targetPath: String
    let status: UnitStatus
    let risk: UnitRisk
    let validation: ValidationState
    let lastReport: String
}

struct ReportSummary: Identifiable {
    let id: String
    let title: String
    let status: String
    let path: String
    let schema: String
    let validation: ValidationState
}

struct SafetyItem: Identifiable {
    let id = UUID()
    let title: String
    let tone: PillTone
}

enum MockForgisData {
    static let run = MigrationRun(
        id: "run-001",
        sourceRepo: "local/smoke-source",
        sourcePath: "examples/local_migration_fixture/source",
        targetRepo: "local/smoke-target",
        targetPath: "examples/local_migration_fixture/target",
        targetSubdir: "target-output",
        mode: .dryRun,
        provider: "openai-compatible",
        model: "local-smoke-model",
        apiBase: "https://example.invalid/v1",
        apiKeyEnvName: "FORGIS_MODEL_API_KEY",
        apiKeyStatus: "unset",
        configPath: "examples/FORGIS_CONFIG.local.smoke.yml"
    )

    static let units = [
        MigrationUnit(
            id: "unit-001",
            title: "Port primary view",
            sourcePath: "Source/App/MainView.swift",
            targetPath: "Target/App/MainView.kt",
            status: .pending,
            risk: .medium,
            validation: .notRun,
            lastReport: "No report"
        ),
        MigrationUnit(
            id: "unit-002",
            title: "Port greeting label",
            sourcePath: "source/GreetingView.swift",
            targetPath: "target-output/Greeting.kt",
            status: .completed,
            risk: .low,
            validation: .passed,
            lastReport: "FORGIS_RUN_REPORT.json"
        ),
        MigrationUnit(
            id: "unit-003",
            title: "Review validation commands",
            sourcePath: "FORGIS_CONFIG.yml",
            targetPath: "target-output",
            status: .pending,
            risk: .high,
            validation: .notRun,
            lastReport: "No report"
        ),
    ]

    static let report = ReportSummary(
        id: "report-001",
        title: "FORGIS_RUN_REPORT",
        status: "Mock",
        path: "reports/FORGIS_RUN_REPORT.json",
        schema: "forgis.run_report.v6.0",
        validation: .notRun
    )

    static let safety = [
        SafetyItem(title: "Source readonly", tone: .success),
        SafetyItem(title: "Target bound", tone: .success),
        SafetyItem(title: "Secret hidden", tone: .success),
        SafetyItem(title: "Allowlist", tone: .success),
    ]
}
#endif
