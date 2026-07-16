#if canImport(SwiftUI)
import Foundation

enum ForgisOpenAIChatError: LocalizedError {
    case invalidEndpoint
    case emptyMessages
    case httpStatus(Int, String)
    case invalidResponse
    case transport(String)

    var errorDescription: String? {
        switch self {
        case .invalidEndpoint:
            return "OpenAI-compatible chat endpoint is invalid."
        case .emptyMessages:
            return "Chat request has no messages."
        case .httpStatus(let status, let detail):
            return detail.isEmpty
                ? "OpenAI-compatible API request failed with HTTP \(status)."
                : "OpenAI-compatible API request failed with HTTP \(status): \(detail)"
        case .invalidResponse:
            return "OpenAI-compatible API returned an invalid chat response."
        case .transport(let detail):
            return "OpenAI-compatible API request failed: \(detail)"
        }
    }
}

struct ForgisProviderChatMessage: Codable, Equatable {
    var role: ForgisChatRole
    var content: String
}

private struct ForgisOpenAIChatRequest: Encodable {
    var model: String
    var messages: [ForgisProviderChatMessage]
}

private struct ForgisOpenAIChatResponse: Decodable {
    struct Choice: Decodable {
        struct Message: Decodable {
            let content: String?
        }

        let message: Message?
    }

    let choices: [Choice]
}

struct ForgisOpenAICompatibleChatClient {
    var urlSession: URLSession = .shared

    func complete(
        messages: [ForgisProviderChatMessage],
        configuration: ForgisChatConfiguration,
        apiKey: String?
    ) async throws -> String {
        guard !messages.isEmpty else { throw ForgisOpenAIChatError.emptyMessages }
        guard let url = Self.chatCompletionsURL(apiBase: configuration.apiBase) else {
            throw ForgisOpenAIChatError.invalidEndpoint
        }

        var request = URLRequest(url: url, timeoutInterval: configuration.timeoutSeconds)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if let apiKey, !apiKey.isEmpty {
            request.setValue("Bearer \(apiKey)", forHTTPHeaderField: "Authorization")
        }
        request.httpBody = try JSONEncoder().encode(
            ForgisOpenAIChatRequest(model: configuration.model, messages: messages)
        )

        let secretValues = apiKey.map { [$0] } ?? []
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await urlSession.data(for: request)
        } catch {
            throw ForgisOpenAIChatError.transport(
                Self.sanitizeProviderText(error.localizedDescription, secretValues: secretValues)
            )
        }

        guard let http = response as? HTTPURLResponse else {
            throw ForgisOpenAIChatError.invalidResponse
        }

        guard (200..<300).contains(http.statusCode) else {
            let detail = Self.errorDetail(data: data, secretValues: secretValues)
            throw ForgisOpenAIChatError.httpStatus(http.statusCode, detail)
        }

        let decoded = try JSONDecoder().decode(ForgisOpenAIChatResponse.self, from: data)
        guard let content = decoded.choices.first?.message?.content else {
            throw ForgisOpenAIChatError.invalidResponse
        }
        return content
    }

    static func chatCompletionsURL(apiBase: String) -> URL? {
        let trimmed = apiBase.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
        let lowered = trimmed.lowercased().trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        let raw = lowered.hasSuffix("chat/completions")
            ? trimmed.trimmingTrailingSlashes()
            : "\(trimmed.trimmingTrailingSlashes())/chat/completions"
        guard
            let url = URL(string: raw),
            let scheme = url.scheme?.lowercased(),
            (scheme == "http" || scheme == "https"),
            url.host != nil
        else {
            return nil
        }
        return url
    }

    private static func errorDetail(data: Data, secretValues: [String]) -> String {
        let raw = String(data: data, encoding: .utf8) ?? ""
        guard
            let object = try? JSONSerialization.jsonObject(with: data),
            let dictionary = object as? [String: Any]
        else {
            return sanitizeProviderText(raw, secretValues: secretValues)
        }

        if
            let error = dictionary["error"] as? [String: Any],
            let message = error["message"] as? String
        {
            return sanitizeProviderText(message, secretValues: secretValues)
        }
        if let message = dictionary["message"] as? String {
            return sanitizeProviderText(message, secretValues: secretValues)
        }
        return sanitizeProviderText(raw, secretValues: secretValues)
    }

    private static func sanitizeProviderText(
        _ text: String,
        secretValues: [String],
        limit: Int = 300
    ) -> String {
        var safe = text.replacingOccurrences(of: "\u{0}", with: "")
        for secret in secretValues where !secret.isEmpty {
            safe = safe.replacingOccurrences(of: secret, with: "[REDACTED]")
        }
        safe = safe.replacingOccurrences(
            of: #"(?i)bearer\s+[A-Za-z0-9._~+/=-]+"#,
            with: "Bearer [REDACTED]",
            options: .regularExpression
        )
        safe = safe.replacingOccurrences(
            of: #"(?i)(authorization|api[_-]?key|token|secret|cookie)\s*[:=]\s*[^,\s}\]]+"#,
            with: "$1=[REDACTED]",
            options: .regularExpression
        )
        if safe.count > limit {
            return String(safe.prefix(limit)) + "...[truncated]"
        }
        return safe
    }
}

private extension String {
    func trimmingTrailingSlashes() -> String {
        var value = self
        while value.hasSuffix("/") && !value.hasSuffix("://") {
            value.removeLast()
        }
        return value
    }
}
#endif
