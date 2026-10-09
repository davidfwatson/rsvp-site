import XCTest
import UIKit
@testable import PartyMail

final class PartyMailTests: XCTestCase {
    func testAccountSwitchErasesPreviousOwnersPrivateAccessLinks() {
        var state = SettingsAccessState()
        let owner = Admin(id: "owner", name: "Owner", isOwner: true)
        state.transition(to: owner)
        state.newLink = URL(string: "https://partymail.app/admin/signin/private-secret")
        state.invites = [AdminInvite(token: "private-invite", name: "Member", createdAt: "2026-10-09")]
        state.passkeys = [Passkey(credentialId: "owner-key", name: "Owner iPhone", createdAt: nil, lastUsedAt: nil)]
        state.transition(to: owner)
        XCTAssertNotNil(state.newLink, "Refreshing the same owner retains their freshly created link")
        state.transition(to: Admin(id: "member", name: "Member", isOwner: false))
        XCTAssertNil(state.newLink); XCTAssertTrue(state.invites.isEmpty); XCTAssertTrue(state.passkeys.isEmpty)
        XCTAssertTrue(state.accounts.isEmpty); XCTAssertTrue(state.links.isEmpty)
        state.transition(to: nil); XCTAssertNil(state.adminID)
    }
    @MainActor func testDelayedSessionReadCannotOverwriteLoginCookie() async throws {
        MockSessionProtocol.reset()
        let configuration = URLSessionConfiguration.ephemeral; configuration.protocolClasses = [MockSessionProtocol.self]
        let store = AppStore(configuration: configuration, persistCredentials: false)
        try await store.refreshSession()
        async let refresh: Void = store.refreshSession()
        async let login: Void = store.passwordLogin("fixture-password")
        _ = try await (refresh, login)
        try await store.refreshSession()
        XCTAssertEqual(store.admin?.id, "test-owner")
        XCTAssertEqual(MockSessionProtocol.maxConcurrentRequests, 1)
        XCTAssertTrue(MockSessionProtocol.lastCookie.contains("session=authenticated"))
    }
    func testLinksRequireConfiguredOriginAndKnownPaths() {
        XCTAssertEqual(DeepLink.parse(Config.url("/demo-party")), .invitation("demo-party"))
        XCTAssertEqual(DeepLink.parse(Config.url("/demo-party/update-rsvp/secret-token")), .response("demo-party", "secret-token"))
        XCTAssertEqual(DeepLink.parse(URL(string: "partymail:///admin/signin/secret-token")!), .signin("secret-token"))
        XCTAssertEqual(DeepLink.parse(URL(string: "partymail://admin/invite/secret-token")!), .enroll("secret-token"))
        for raw in ["https://evil.example/demo-party", "https://partymail.app.evil.example/demo-party", "https://user@partymail.app/demo-party", "https://partymail.app:444/demo-party", "partymail:///admin/signin/x/y", "partymail:///../admin", "partymail:///healthz", "partymail:///oauth2callback", "partymail:///admin", "partymail:///demo-party?token=private", "partymail:///demo-party/update-rsvp/%2Fbad"] { XCTAssertNil(DeepLink.parse(URL(string: raw)!), raw) }
    }
    func testCookieCannotLeakToAnotherOriginOrPlainHTTP() {
        let cookie = HTTPCookie(properties: [.name: "session", .value: "private", .domain: "partymail.app", .path: "/", .secure: "TRUE"])!
        let stored = StoredCookie(cookie)
        XCTAssertTrue(stored.matches(URL(string: "https://partymail.app/api/mobile/events")!))
        XCTAssertFalse(stored.matches(URL(string: "https://evil.example/api/mobile/events")!))
        XCTAssertFalse(stored.matches(URL(string: "https://partymail.app.evil.example/api/mobile/events")!))
        XCTAssertFalse(stored.matches(URL(string: "http://partymail.app/api/mobile/events")!))
    }
    func testDateTimeAndColorValidation() {
        XCTAssertTrue(Format.validTime("00:00")); XCTAssertTrue(Format.validTime("23:59"))
        XCTAssertFalse(Format.validTime("24:00")); XCTAssertFalse(Format.validTime("6:00 PM"))
        XCTAssertNotNil(Format.parseDay("2028-02-29")); XCTAssertNil(Format.parseDay("2027-02-29"))
        XCTAssertTrue(Format.validHex("#a64E68")); XCTAssertFalse(Format.validHex("red"))
        var draft = EventDraft(); XCTAssertNotNil(draft.validationError)
        draft.name = "Dinner"; draft.location = "Home"; XCTAssertNil(draft.validationError)
        draft.maxGuestsPerInvite = 101; XCTAssertNotNil(draft.validationError)
    }
    func testRSVPValidationAndPrivateTokenNeverSentInPayload() throws {
        var rsvp = RSVP.empty; rsvp.name = "Guest"; rsvp.email = "guest@example.test"; rsvp.token = "private-secret"
        XCTAssertNil(rsvp.validationError(limit: 2))
        rsvp.numChildren = 2; XCTAssertNotNil(rsvp.validationError(limit: 2))
        rsvp.attending = "no"; XCTAssertNil(rsvp.validationError(limit: 2))
        let encoder = JSONEncoder(); encoder.keyEncodingStrategy = .convertToSnakeCase
        let data = try encoder.encode(rsvp.payload()); let object = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        XCTAssertNil(object["token"]); XCTAssertNil(object["timestamp"]); XCTAssertEqual(object["num_children"] as? Int, 2)
    }
    func testDuplicateRSVPDoesNotRequireOrRevealResponse() throws {
        let decoder = JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase
        let duplicate = try decoder.decode(RSVPResult.self, from: Data(#"{"check_email":true,"email_delivered":false}"#.utf8))
        XCTAssertTrue(duplicate.checkEmail == true); XCTAssertNil(duplicate.response); XCTAssertNil(duplicate.updateUrl)
    }
    func testBase64URLRoundTripForWebAuthn() {
        let original = Data([0, 251, 255, 43, 124]); XCTAssertEqual(Data(base64URL: original.base64URL), original)
        XCTAssertFalse(original.base64URL.contains("=")); XCTAssertFalse(original.base64URL.contains("+")); XCTAssertFalse(original.base64URL.contains("/"))
    }
    func testInvitationArtworkPreservesTransparencyAndAspectRatio() throws {
        let format = UIGraphicsImageRendererFormat(); format.scale = 1; format.opaque = false
        let source = UIGraphicsImageRenderer(size: CGSize(width: 300, height: 600), format: format).image { context in
            UIColor.red.setFill(); context.fill(CGRect(x: 100, y: 200, width: 100, height: 200))
        }
        let encoded = try ArtworkProcessing.prepare(source)
        XCTAssertEqual(Array(encoded.prefix(8)), [137,80,78,71,13,10,26,10])
        let image = try XCTUnwrap(UIImage(data: encoded)); XCTAssertEqual(image.size.width / image.size.height, 0.5)
        let cg = try XCTUnwrap(image.cgImage)
        XCTAssertTrue([CGImageAlphaInfo.premultipliedLast, .premultipliedFirst, .last, .first].contains(cg.alphaInfo))
        let space = CGColorSpaceCreateDeviceRGB(); var pixel = [UInt8](repeating: 0, count: 4)
        let context = try XCTUnwrap(CGContext(data: &pixel, width: 1, height: 1, bitsPerComponent: 8, bytesPerRow: 4, space: space, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue))
        context.draw(cg, in: CGRect(x: 0, y: 0, width: 300, height: 600)); XCTAssertEqual(pixel[3], 0)
    }
}
final class MockSessionProtocol: URLProtocol {
    private static let lock = NSLock()
    private static var active = 0
    private(set) static var maxConcurrentRequests = 0
    private(set) static var lastCookie = ""
    static func reset() { lock.lock(); defer { lock.unlock() }; active = 0; maxConcurrentRequests = 0; lastCookie = "" }
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        Self.lock.lock(); Self.active += 1; Self.maxConcurrentRequests = max(Self.active, Self.maxConcurrentRequests); Self.lastCookie = request.value(forHTTPHeaderField: "Cookie") ?? ""; Self.lock.unlock()
        let isLogin = request.url!.path.hasSuffix("/login")
        let authenticated = isLogin || (request.value(forHTTPHeaderField: "Cookie") ?? "").contains("session=authenticated")
        let admin: Any = authenticated ? ["id": "test-owner", "name": "Test Owner", "is_owner": true] : NSNull()
        let data = try! JSONSerialization.data(withJSONObject: ["csrf_token": authenticated ? "authenticated-csrf" : "guest-csrf", "admin": admin, "public_url": "https://partymail.app", "email_enabled": false, "email_connected": false])
        let cookie = authenticated ? "authenticated" : "guest"
        let response = HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: ["Content-Type": "application/json", "Set-Cookie": "session=\(cookie); Path=/; HttpOnly; Secure"])!
        DispatchQueue.global().asyncAfter(deadline: .now() + (isLogin ? 0.01 : 0.10)) {
            Self.lock.lock(); Self.active -= 1; Self.lock.unlock()
            self.client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            self.client?.urlProtocol(self, didLoad: data); self.client?.urlProtocolDidFinishLoading(self)
        }
    }
    override func stopLoading() {}
}
