import Foundation
import Security
import Combine

enum Vault {
    static let service = "com.davidfwatson.partymail.private.\(Config.baseURL.host ?? "production").\(Config.baseURL.port ?? 443)"
    static func read(_ key: String) -> Data? {
        let q: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service,
                               kSecAttrAccount as String: key, kSecReturnData as String: true, kSecMatchLimit as String: kSecMatchLimitOne]
        var result: CFTypeRef?
        guard SecItemCopyMatching(q as CFDictionary, &result) == errSecSuccess else { return nil }
        return result as? Data
    }
    @discardableResult static func write(_ data: Data, key: String) -> Bool {
        let q: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service, kSecAttrAccount as String: key]
        let values: [String: Any] = [kSecValueData as String: data, kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly]
        let updated = SecItemUpdate(q as CFDictionary, values as CFDictionary)
        if updated == errSecSuccess { return true }
        guard updated == errSecItemNotFound else { return false }
        return SecItemAdd(q.merging(values) { _, new in new } as CFDictionary, nil) == errSecSuccess
    }
    static func delete(_ key: String) {
        SecItemDelete([kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service, kSecAttrAccount as String: key] as CFDictionary)
    }
    static func responseToken(slug: String) -> String? { read("rsvp.\(slug)").flatMap { String(data: $0, encoding: .utf8) } }
    @discardableResult static func saveResponseToken(_ token: String, slug: String) -> Bool { write(Data(token.utf8), key: "rsvp.\(slug)") }
}

struct StoredCookie: Codable {
    let name: String; let value: String; let domain: String; let path: String; let secure: Bool; let expires: Date?
    init(_ c: HTTPCookie) { name = c.name; value = c.value; domain = c.domain; path = c.path; secure = c.isSecure; expires = c.expiresDate }
    func matches(_ url: URL) -> Bool {
        (expires == nil || expires! > Date()) && url.host == domain.trimmingCharacters(in: CharacterSet(charactersIn: ".")) && url.path.hasPrefix(path) && (!secure || url.scheme == "https")
    }
}
final class OriginDelegate: NSObject, URLSessionTaskDelegate {
    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse, newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) {
        // APIs must never silently navigate to a login page or send cookies elsewhere.
        completionHandler(nil)
    }
}

struct APIError: LocalizedError {
    let status: Int; let message: String
    var errorDescription: String? { message }
}

@MainActor final class AppStore: ObservableObject {
    @Published var admin: Admin?
    @Published var bootstrapped = false
    @Published var emailEnabled = false
    @Published var error: String?
    @Published var events: [Event] = []
    @Published var loading = false
    private(set) var csrf = ""
    private var cookies: [StoredCookie] = []
    private var requestRunning = false
    private var requestWaiters: [CheckedContinuation<Void, Never>] = []
    private let session: URLSession
    private let persistCredentials: Bool
    let passkeys = PasskeyAuthenticator()
    static let decoder: JSONDecoder = { let d = JSONDecoder(); d.keyDecodingStrategy = .convertFromSnakeCase; return d }()
    static let encoder: JSONEncoder = { let e = JSONEncoder(); e.keyEncodingStrategy = .convertToSnakeCase; return e }()
    init(configuration: URLSessionConfiguration? = nil, persistCredentials: Bool = true) {
        self.persistCredentials = persistCredentials
        #if DEBUG
        if ProcessInfo.processInfo.environment["PARTYMAIL_RESET_PRIVATE_DATA"] == "1", Config.baseURL.host == "127.0.0.1" {
            SecItemDelete([kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: Vault.service] as CFDictionary)
        }
        #endif
        let config = configuration ?? URLSessionConfiguration.ephemeral
        config.httpCookieStorage = nil; config.httpShouldSetCookies = false
        config.urlCache = nil; config.requestCachePolicy = .reloadIgnoringLocalCacheData
        config.timeoutIntervalForRequest = 30; config.timeoutIntervalForResource = 60
        session = URLSession(configuration: config, delegate: OriginDelegate(), delegateQueue: nil)
        if persistCredentials, let saved = Vault.read("cookies"), let decoded = try? JSONDecoder().decode([StoredCookie].self, from: saved) { cookies = decoded }
    }
    func raw(_ path: String, method: String = "GET", body: Data? = nil, contentType: String = "application/json") async throws -> Data {
        let url = Config.url(path)
        if method != "GET" && csrf.isEmpty { try await refreshSession() }
        // Flask signs the entire session into one cookie. Serialize responses so a
        // late pre-login read cannot replace the freshly authenticated cookie.
        if requestRunning { await withCheckedContinuation { requestWaiters.append($0) } }
        else { requestRunning = true }
        defer {
            if requestWaiters.isEmpty { requestRunning = false }
            else { requestWaiters.removeFirst().resume() }
        }
        try Task.checkCancellation()
        var request = URLRequest(url: url)
        request.httpMethod = method; request.httpBody = body
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if body != nil { request.setValue(contentType, forHTTPHeaderField: "Content-Type") }
        if method != "GET" { request.setValue(csrf, forHTTPHeaderField: "X-CSRF-Token") }
        let matching = cookies.filter { $0.matches(url) }
        if !matching.isEmpty { request.setValue(matching.map { "\($0.name)=\($0.value)" }.joined(separator: "; "), forHTTPHeaderField: "Cookie") }
        let data: Data; let response: URLResponse
        do { (data, response) = try await session.data(for: request) }
        catch { throw APIError(status: 0, message: "Couldn’t reach Party Mail. Check your connection and try again.") }
        guard let http = response as? HTTPURLResponse else { throw APIError(status: 0, message: "The server returned an unexpected response.") }
        let headers = http.allHeaderFields.reduce(into: [String: String]()) { if let key = $1.key as? String { $0[key] = String(describing: $1.value) } }
        for c in HTTPCookie.cookies(withResponseHeaderFields: headers, for: url) {
            guard c.domain.trimmingCharacters(in: CharacterSet(charactersIn: ".")) == Config.baseURL.host else { continue }
            cookies.removeAll { $0.name == c.name && $0.path == c.path }
            if c.expiresDate == nil || c.expiresDate! > Date() { cookies.append(StoredCookie(c)) }
        }
        if persistCredentials, let encoded = try? JSONEncoder().encode(cookies) { Vault.write(encoded, key: "cookies") }
        guard (200...299).contains(http.statusCode) else {
            if http.statusCode == 401 { admin = nil; events = [] }
            let object = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
            if http.statusCode == 403 { csrf = "" }
            if http.statusCode == 400 && (object?["error"] as? String)?.contains("Your session expired") == true { csrf = ""; admin = nil; events = [] }
            let defaultMessage = http.statusCode == 409 ? "This event changed on another device. Reload it before saving again." : http.statusCode == 401 ? "Your session expired. Please sign in again." : "This request couldn’t be completed. Please try again."
            throw APIError(status: http.statusCode, message: object?["error"] as? String ?? defaultMessage)
        }
        return data
    }
    func get<T: Decodable>(_ path: String, as type: T.Type = T.self) async throws -> T {
        try decode(try await raw(path), as: type)
    }
    func send<T: Decodable>(_ path: String, _ body: [String: Any] = [:], method: String = "POST", as type: T.Type = T.self) async throws -> T {
        try decode(try await raw(path, method: method, body: JSONSerialization.data(withJSONObject: body)), as: type)
    }
    func send<T: Decodable, B: Encodable>(_ path: String, value: B, method: String = "POST", as type: T.Type = T.self) async throws -> T {
        try decode(try await raw(path, method: method, body: Self.encoder.encode(value)), as: type)
    }
    private func decode<T: Decodable>(_ data: Data, as type: T.Type) throws -> T {
        do { return try Self.decoder.decode(type, from: data) }
        catch { throw APIError(status: 0, message: "Party Mail returned an unexpected response. Please update the app or try again later.") }
    }
    func refreshSession() async throws {
        let payload: SessionPayload = try await get("/api/mobile/session")
        csrf = payload.csrfToken; admin = payload.admin; emailEnabled = payload.emailEnabled && payload.emailConnected
        bootstrapped = true
        if admin == nil { events = [] }
    }
    func bootstrap() async { do { try await refreshSession() } catch { self.error = error.localizedDescription; bootstrapped = true } }
    func loadEvents() async {
        guard admin != nil else { return }
        loading = true; defer { loading = false }
        do { events = try await get("/api/mobile/events", as: EventsPayload.self).events } catch { self.error = error.localizedDescription }
    }
    func passwordLogin(_ password: String) async throws {
        let _: SessionPayload = try await send("/api/mobile/login", ["password": password]); try await refreshSession()
    }
    func signin(_ token: String) async throws {
        let _: SessionPayload = try await send("/api/mobile/signin", ["token": token]); try await refreshSession()
    }
    func logout() async throws {
        let _: Success = try await send("/api/mobile/logout")
        admin = nil; events = []; csrf = ""; cookies = []; if persistCredentials { Vault.delete("cookies") }
        try await refreshSession()
    }
    func authenticate() async throws {
        let options = try await raw("/admin/passkey/auth/options", method: "POST", body: Data("{}".utf8))
        let result = try await passkeys.authenticate(options)
        let _: Success = try await send("/admin/passkey/auth/verify", result)
        try await refreshSession()
    }
    func registerPasskey(name: String, invite: String? = nil) async throws {
        let prefix = invite.map { "/admin/invite/\($0)/register" } ?? "/admin/passkey/register"
        let options = try await raw(prefix + "/options", method: "POST", body: JSONSerialization.data(withJSONObject: ["name": name]))
        var credential = try await passkeys.register(options)
        credential["name"] = name.isEmpty ? "iPhone passkey" : name
        let _: Success = try await send(prefix + "/verify", credential)
        try await refreshSession()
    }
    func upload(slug: String, image: Data) async throws -> String {
        let boundary = UUID().uuidString
        var body = Data("--\(boundary)\r\nContent-Disposition: form-data; name=\"image\"; filename=\"artwork.png\"\r\nContent-Type: image/png\r\n\r\n".utf8)
        body.append(image); body.append(Data("\r\n--\(boundary)--\r\n".utf8))
        return try decode(try await raw("/api/mobile/events/\(slug)/upload", method: "POST", body: body, contentType: "multipart/form-data; boundary=\(boundary)"), as: UploadResult.self).url
    }
}
