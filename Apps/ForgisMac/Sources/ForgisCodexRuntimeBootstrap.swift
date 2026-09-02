import IntatisCodexRuntime
import IntatisCore

/// The complete Forgis-owned boundary for the shared Codex runtime host.
///
/// This bootstrap installs only the process-wide product identity required by
/// Intatis's public v1 contract. It deliberately does not create a session,
/// select a provider, register tools, or fall back to Forgis's legacy runtime.
enum ForgisCodexRuntimeBootstrap {
    private static let requiredHostAPIMajorVersion = 1

    static func configureProcess() {
        precondition(
            CodexRuntimeHostContract.publicAPIMajorVersion
                == requiredHostAPIMajorVersion,
            "Forgis requires IntatisCodexRuntime host API v1."
        )

        do {
            _ = try IntatisHostApplication.configure(name: "Forgis")
        } catch {
            preconditionFailure(
                "Forgis could not configure the shared runtime host identity: \(error.localizedDescription)"
            )
        }
    }
}
