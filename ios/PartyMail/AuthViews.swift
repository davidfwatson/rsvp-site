import SwiftUI

struct LoginView: View {
    @EnvironmentObject private var store: AppStore
    @State private var password = ""
    @State private var busy = false
    @State private var error: String?
    @State private var recovery = false
    var body: some View {
        ScrollView { VStack(spacing: 24) {
            Image(systemName: "envelope.open.fill").font(.system(size: 64)).foregroundStyle(Theme.accent).padding(.top, 34)
            VStack(spacing: 10) { Text("Good times start here.").font(.largeTitle.weight(.semibold)).fontDesign(.serif).multilineTextAlignment(.center); Text("Sign in to make invitations, keep track of your guests, and bring everyone together.").foregroundStyle(.secondary).multilineTextAlignment(.center) }
            BusyButton(title: "Sign in with a passkey", busy: busy, icon: "person.badge.key.fill") { run { try await store.authenticate() } }
            DisclosureGroup("Owner password recovery", isExpanded: $recovery) {
                VStack(spacing: 12) { SecureField("Owner password", text: $password).textContentType(.password).textFieldStyle(.roundedBorder).accessibilityIdentifier("ownerPassword"); BusyButton(title: "Sign in", busy: busy, icon: "key") { run { try await store.passwordLogin(password); password = "" } }.disabled(password.isEmpty) }.padding(.top)
            }.font(.subheadline)
            ErrorText(text: error)
            Text("Have an administrator invitation or a one-use sign-in link? Open it on this device to continue.").font(.footnote).foregroundStyle(.secondary).multilineTextAlignment(.center)
            Spacer()
        }.padding(28).frame(maxWidth: 520).frame(maxWidth: .infinity) }.scrollDismissesKeyboard(.interactively).navigationTitle("Party Mail")
    }
    private func run(_ operation: @escaping () async throws -> Void) { busy = true; error = nil; Task { defer { busy = false }; do { try await operation() } catch is PasskeyAuthenticator.Cancelled {} catch { self.error = error.localizedDescription } } }
}
struct SignInLinkView: View {
    let token: String
    @EnvironmentObject private var store: AppStore
    @State private var busy = false
    @State private var error: String?
    @State private var complete = false
    var body: some View {
        VStack(spacing: 24) {
            Image(systemName: complete ? "checkmark.seal.fill" : "key.fill").font(.system(size: 64)).foregroundStyle(Theme.accent)
            Text(complete ? "You’re signed in." : "Confirm sign-in").font(.largeTitle).fontDesign(.serif)
            Text(complete ? "Your host workspace is ready in the Host tab." : "This link grants administrator access to Party Mail. Continue only if you requested it or it came from the owner. It works once and expires shortly.").foregroundStyle(.secondary).multilineTextAlignment(.center)
            if !complete { BusyButton(title: "Use this sign-in link", busy: busy, icon: "key") { busy = true; Task { defer { busy = false }; do { try await store.signin(token); complete = true } catch { self.error = error.localizedDescription } } } }
            ErrorText(text: error)
        }.padding(30).frame(maxWidth: 520).navigationTitle("Sign in")
    }
}
struct EnrollmentView: View {
    let token: String
    @EnvironmentObject private var store: AppStore
    @State private var name = ""
    @State private var busy = false
    @State private var error: String?
    @State private var complete = false
    var body: some View {
        Form {
            Section { Label(complete ? "Welcome to Party Mail" : "Your seat at the table", systemImage: "party.popper").font(.title2).fontDesign(.serif); Text(complete ? "Your account and passkey are ready. Open the Host tab to create your first invitation." : "Create your administrator account with a passkey. You’ll use Face ID, Touch ID, or your device passcode to sign in.").foregroundStyle(.secondary) }
            if !complete { Section { TextField("Your name", text: $name).textContentType(.name); BusyButton(title: "Create account with a passkey", busy: busy, icon: "person.badge.key") { busy = true; Task { defer { busy = false }; do { try await store.registerPasskey(name: name, invite: token); complete = true } catch is PasskeyAuthenticator.Cancelled {} catch { self.error = error.localizedDescription } } }.disabled(name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty) } }
            if error != nil { Section { ErrorText(text: error) } }
        }.navigationTitle("Join Party Mail")
    }
}
