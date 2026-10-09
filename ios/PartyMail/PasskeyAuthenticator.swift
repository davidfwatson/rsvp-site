import AuthenticationServices
import UIKit

@MainActor final class PasskeyAuthenticator: NSObject, ASAuthorizationControllerDelegate, ASAuthorizationControllerPresentationContextProviding {
    struct Cancelled: Error {}
    private var continuation: CheckedContinuation<[String: Any], Error>?
    private var controller: ASAuthorizationController?
    func authenticate(_ data: Data) async throws -> [String: Any] {
        let o = try options(data)
        guard let rp = o["rpId"] as? String, rp == Config.relyingPartyID,
              let challenge = o["challenge"] as? String, let bytes = Data(base64URL: challenge) else { throw invalid() }
        let request = ASAuthorizationPlatformPublicKeyCredentialProvider(relyingPartyIdentifier: rp).createCredentialAssertionRequest(challenge: bytes)
        request.userVerificationPreference = .required
        if let ids = o["allowCredentials"] as? [[String: Any]] { request.allowedCredentials = ids.compactMap { ($0["id"] as? String).flatMap { Data(base64URL: $0) }.map { ASAuthorizationPlatformPublicKeyCredentialDescriptor(credentialID: $0) } } }
        return try await perform(request)
    }
    func register(_ data: Data) async throws -> [String: Any] {
        let o = try options(data)
        guard let rp = o["rp"] as? [String: Any], rp["id"] as? String == Config.relyingPartyID,
              let user = o["user"] as? [String: Any], let name = user["name"] as? String,
              let id = user["id"] as? String, let userID = Data(base64URL: id),
              let challenge = o["challenge"] as? String, let bytes = Data(base64URL: challenge) else { throw invalid() }
        let request = ASAuthorizationPlatformPublicKeyCredentialProvider(relyingPartyIdentifier: Config.relyingPartyID).createCredentialRegistrationRequest(challenge: bytes, name: name, userID: userID)
        request.userVerificationPreference = .required
        if #available(iOS 17.4, *), let ids = o["excludeCredentials"] as? [[String: Any]] { request.excludedCredentials = ids.compactMap { ($0["id"] as? String).flatMap { Data(base64URL: $0) }.map { ASAuthorizationPlatformPublicKeyCredentialDescriptor(credentialID: $0) } } }
        return try await perform(request)
    }
    private func options(_ data: Data) throws -> [String: Any] { guard let o = try JSONSerialization.jsonObject(with: data) as? [String: Any] else { throw invalid() }; return o }
    private func invalid() -> Error { APIError(status: 0, message: "The passkey options were invalid. Please try again.") }
    private func perform(_ request: ASAuthorizationRequest) async throws -> [String: Any] {
        guard continuation == nil else { throw APIError(status: 0, message: "A passkey request is already in progress.") }
        return try await withCheckedThrowingContinuation { continuation in
            self.continuation = continuation
            let controller = ASAuthorizationController(authorizationRequests: [request]); self.controller = controller
            controller.delegate = self; controller.presentationContextProvider = self; controller.performRequests()
        }
    }
    func presentationAnchor(for controller: ASAuthorizationController) -> ASPresentationAnchor {
        UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.flatMap { $0.windows }.first { $0.isKeyWindow } ?? ASPresentationAnchor()
    }
    func authorizationController(controller: ASAuthorizationController, didCompleteWithAuthorization authorization: ASAuthorization) {
        defer { continuation = nil; self.controller = nil }
        if let c = authorization.credential as? ASAuthorizationPlatformPublicKeyCredentialAssertion {
            continuation?.resume(returning: ["id": c.credentialID.base64URL, "rawId": c.credentialID.base64URL, "type": "public-key", "response": ["authenticatorData": c.rawAuthenticatorData.base64URL, "clientDataJSON": c.rawClientDataJSON.base64URL, "signature": c.signature.base64URL, "userHandle": c.userID.map { $0.base64URL } as Any? ?? NSNull()]])
        } else if let c = authorization.credential as? ASAuthorizationPlatformPublicKeyCredentialRegistration, let attestation = c.rawAttestationObject {
            continuation?.resume(returning: ["id": c.credentialID.base64URL, "rawId": c.credentialID.base64URL, "type": "public-key", "response": ["attestationObject": attestation.base64URL, "clientDataJSON": c.rawClientDataJSON.base64URL, "transports": ["internal"]]])
        } else { continuation?.resume(throwing: invalid()) }
    }
    func authorizationController(controller: ASAuthorizationController, didCompleteWithError error: Error) {
        defer { continuation = nil; self.controller = nil }
        continuation?.resume(throwing: (error as? ASAuthorizationError)?.code == .canceled ? Cancelled() : error)
    }
}
extension Data {
    var base64URL: String { base64EncodedString().replacingOccurrences(of: "+", with: "-").replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "=", with: "") }
    init?(base64URL: String) { var s = base64URL.replacingOccurrences(of: "-", with: "+").replacingOccurrences(of: "_", with: "/"); s += String(repeating: "=", count: (4 - s.count % 4) % 4); self.init(base64Encoded: s) }
}
