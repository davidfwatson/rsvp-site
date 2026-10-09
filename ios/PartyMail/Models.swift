import Foundation

enum Config {
    static let production = URL(string: "https://partymail.app")!
    static let baseURL: URL = {
        #if DEBUG
        if let value = ProcessInfo.processInfo.environment["PARTYMAIL_BASE_URL"],
           let url = URL(string: value), ["http", "https"].contains(url.scheme), url.host != nil {
            return url
        }
        #endif
        return production
    }()
    static let relyingPartyID = "partymail.app"
    static func url(_ path: String) -> URL { baseURL.appendingPathComponent(path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))) }
    static func trustedURL(_ raw: String) -> URL? {
        guard let url = URL(string: raw, relativeTo: baseURL)?.absoluteURL,
              url.scheme == baseURL.scheme, url.host == baseURL.host,
              url.port == baseURL.port, url.user == nil, url.password == nil else { return nil }
        return url
    }
}

struct Admin: Codable, Identifiable { let id: String; var name: String; let isOwner: Bool }
struct SessionPayload: Decodable { let csrfToken: String; let admin: Admin?; let publicUrl: String; let emailEnabled: Bool; let emailConnected: Bool }
struct Stats: Codable { let responses: Int; let attending: Int; let accepted: Int; let declined: Int }
struct Event: Codable, Identifiable {
    let id: String
    let slug: String
    let version: Int?
    var name: String
    var date: String
    var startTime: String
    var endTime: String
    var location: String
    var description: String
    var maxGuestsPerInvite: Int
    var colorScheme: String
    var backgroundStyle: String
    var backgroundColor: String
    var accentColor: String
    var backgroundImage: String
    var coverImage: String
    var fontStyle: String
    var envelopeStyle: String
    var showAttendees: Bool
    var archived: Bool
    var publicUrl: String?
    var stats: Stats?
    var invitationURL: URL { publicUrl.flatMap(Config.trustedURL) ?? Config.url("/\(slug)") }
    var dateLabel: String { Format.date(date) }
    var timeLabel: String { Format.time(startTime) + (endTime.isEmpty ? "" : " – " + Format.time(endTime)) }
}
struct EventDraft: Encodable {
    var slug: String?
    var name = ""
    var date = Format.day(Date().addingTimeInterval(86400))
    var startTime = "18:00"
    var endTime = ""
    var location = ""
    var description = ""
    var maxGuestsPerInvite = 6
    var colorScheme = "pink"
    var backgroundStyle = "linen"
    var backgroundColor = "#F8F2ED"
    var accentColor = "#A64E68"
    var backgroundImage = ""
    var coverImage = ""
    var fontStyle = "serif"
    var envelopeStyle = "classic"
    var showAttendees = false
    var version: Int?
    init() {}
    init(_ e: Event) {
        name = e.name; date = e.date; startTime = e.startTime; endTime = e.endTime
        location = e.location; description = e.description; maxGuestsPerInvite = e.maxGuestsPerInvite
        colorScheme = e.colorScheme; backgroundStyle = e.backgroundStyle; backgroundColor = e.backgroundColor
        accentColor = e.accentColor; backgroundImage = e.backgroundImage; coverImage = e.coverImage
        fontStyle = e.fontStyle; envelopeStyle = e.envelopeStyle; showAttendees = e.showAttendees; version = e.version
    }
    var validationError: String? {
        if name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { return "Give your event a name." }
        if let slug, !slug.isEmpty, slug.range(of: "^[a-z0-9]+(?:-[a-z0-9]+)*$", options: .regularExpression) == nil { return "Event codes use lowercase letters, numbers, and hyphens." }
        if location.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { return "Add a location." }
        if Format.parseDay(date) == nil { return "Choose a valid date." }
        if !Format.validTime(startTime) || (!endTime.isEmpty && !Format.validTime(endTime)) { return "Use a valid start and end time." }
        if !(1...100).contains(maxGuestsPerInvite) { return "Guest limits must be between 1 and 100." }
        if !Format.validHex(backgroundColor) || !Format.validHex(accentColor) { return "Colors must use #RRGGBB." }
        return nil
    }
}
struct RSVP: Codable, Identifiable {
    var name: String
    var email: String
    var attending: String
    var numAdults: Int
    var numChildren: Int
    var dietaryRestrictions: String
    var comment: String
    var timestamp: String?
    var updatedAt: String?
    var token: String?
    var id: String { email }
    var guests: Int { numAdults + numChildren }
    static let empty = RSVP(name: "", email: "", attending: "yes", numAdults: 1, numChildren: 0, dietaryRestrictions: "", comment: "")
    func payload() -> RSVPInput { RSVPInput(name: name, email: email, attending: attending, numAdults: numAdults, numChildren: numChildren, dietaryRestrictions: dietaryRestrictions, comment: comment) }
    func validationError(limit: Int) -> String? {
        if name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { return "Please enter your name." }
        if !email.contains("@") || !email.contains(".") || email.contains(" ") { return "Please enter your email address." }
        if attending == "yes" && (numAdults < 1 || numChildren < 0 || guests > limit) { return "Choose between 1 and \(limit) guests, with at least one adult." }
        return nil
    }
}
struct RSVPInput: Encodable { let name: String; let email: String; let attending: String; let numAdults: Int; let numChildren: Int; let dietaryRestrictions: String; let comment: String }
struct Attendee: Decodable, Identifiable { let firstName: String; let lastInitial: String; let guestInfo: String; var id: String { firstName + lastInitial + guestInfo } }
struct EventsPayload: Decodable { let events: [Event] }
struct EventPayload: Decodable { let event: Event }
struct EventDetail: Decodable { let event: Event; let rsvps: [RSVP] }
struct InvitationPayload: Decodable { let event: Event; let attendees: [Attendee] }
struct ResponsePayload: Decodable { let response: RSVP; let event: Event }
struct RSVPResult: Decodable { let response: RSVP?; let updateUrl: String?; let emailDelivered: Bool?; let checkEmail: Bool? }
struct UploadResult: Decodable { let url: String }
struct Success: Decodable { let success: Bool? }
struct Account: Decodable, Identifiable { let id: String; let name: String; let isOwner: Bool; let passkeyCount: Int; let lastLoginAt: String? }
struct SignInLink: Decodable, Identifiable { let id: String; let adminId: String; let expiresAt: String }
struct AccountsPayload: Decodable { let accounts: [Account]; let signinLinks: [SignInLink] }
struct AdminInvite: Decodable, Identifiable { let token: String; let name: String; let createdAt: String; var id: String { token }; var url: URL { Config.url("/admin/invite/\(token)") } }
struct InvitesPayload: Decodable { let invites: [AdminInvite] }
struct Passkey: Decodable, Identifiable { let credentialId: String; let name: String; let createdAt: String?; let lastUsedAt: String?; var id: String { credentialId } }
struct PasskeysPayload: Decodable { let passkeys: [Passkey] }
struct LinkResult: Decodable { let url: String }

enum Format {
    static func parseDay(_ value: String) -> Date? { let f = DateFormatter(); f.locale = Locale(identifier: "en_US_POSIX"); f.dateFormat = "yyyy-MM-dd"; f.isLenient = false; return f.date(from: value) }
    static func day(_ date: Date) -> String { let f = DateFormatter(); f.locale = Locale(identifier: "en_US_POSIX"); f.dateFormat = "yyyy-MM-dd"; return f.string(from: date) }
    static func date(_ value: String) -> String { guard let d = parseDay(value) else { return value }; return d.formatted(date: .abbreviated, time: .omitted) }
    static func validTime(_ value: String) -> Bool { value.range(of: "^(?:[01][0-9]|2[0-3]):[0-5][0-9]$", options: .regularExpression) != nil }
    static func validHex(_ value: String) -> Bool { value.range(of: "^#[0-9a-fA-F]{6}$", options: .regularExpression) != nil }
    static func time(_ value: String) -> String { let f = DateFormatter(); f.locale = Locale(identifier: "en_US_POSIX"); f.dateFormat = "HH:mm"; guard let d = f.date(from: value) else { return value }; return d.formatted(date: .omitted, time: .shortened) }
    static func timeValue(_ date: Date) -> String { let f = DateFormatter(); f.locale = Locale(identifier: "en_US_POSIX"); f.dateFormat = "HH:mm"; return f.string(from: date) }
}

enum DeepLink: Equatable {
    case invitation(String)
    case response(String, String)
    case signin(String)
    case enroll(String)
    static func parse(_ url: URL) -> DeepLink? {
        guard let c = URLComponents(url: url, resolvingAgainstBaseURL: false), c.user == nil, c.password == nil, c.query == nil, c.fragment == nil else { return nil }
        let path: String
        if c.scheme == "partymail" {
            guard c.port == nil else { return nil }
            path = ((c.host?.isEmpty == false) ? "/" + c.host! : "") + c.path
        } else {
            guard c.scheme == Config.baseURL.scheme, c.host == Config.baseURL.host, c.port == Config.baseURL.port else { return nil }
            path = c.path
        }
        guard !path.contains("//") else { return nil }
        let p = path.split(separator: "/").map(String.init)
        guard !p.isEmpty, p.allSatisfy({ $0.range(of: "^[A-Za-z0-9_-]{1,200}$", options: .regularExpression) != nil }) else { return nil }
        if p.count == 3 && p[0] == "admin" && p[1] == "signin" { return .signin(p[2]) }
        if p.count == 3 && p[0] == "admin" && p[1] == "invite" { return .enroll(p[2]) }
        if p.count == 3 && p[1] == "update-rsvp" { return .response(p[0], p[2]) }
        if p.count == 1 && !["admin", "api", "media", "privacy", "terms", "static", "healthz", "oauth2callback"].contains(p[0]) { return .invitation(p[0]) }
        return nil
    }
}
