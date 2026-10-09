import SwiftUI

struct SettingsView: View {
    @EnvironmentObject private var store: AppStore
    @State private var name = ""
    @State private var passkeyName = "iPhone passkey"
    @State private var inviteName = ""
    @State private var access = SettingsAccessState()
    @State private var busy = false
    @State private var error: String?
    @State private var message: String?
    private var passkeys: [Passkey] { get { access.passkeys } nonmutating set { access.passkeys = newValue } }
    private var accounts: [Account] { get { access.accounts } nonmutating set { access.accounts = newValue } }
    private var invites: [AdminInvite] { get { access.invites } nonmutating set { access.invites = newValue } }
    private var links: [SignInLink] { get { access.links } nonmutating set { access.links = newValue } }
    private var newLink: URL? { get { access.newLink } nonmutating set { access.newLink = newValue } }
    @State private var confirmation: AccessAction?
    @State private var rename: Account?
    @State private var browser: BrowserSheet?
    var body: some View {
        Group {
            if let admin = store.admin {
                Form {
                    Section("Your account") { TextField("Display name", text: $name).textContentType(.name); Button("Save name") { run { let _: Success = try await store.send("/admin/accounts/update", ["name": name]); try await store.refreshSession(); message = "Your name is updated." } }.disabled(busy || name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty); LabeledContent("Role", value: admin.isOwner ? "Owner" : "Administrator") }
                    Section {
                        ForEach(passkeys) { passkey in HStack { VStack(alignment: .leading, spacing: 5) { Label(passkey.name, systemImage: "person.badge.key"); if let date = passkey.createdAt { Text("Added \(String(date.prefix(10)))").font(.caption).foregroundStyle(.secondary) } }; Spacer(); Button(role: .destructive) { confirmation = .passkey(passkey) } label: { Image(systemName: "trash") }.disabled(busy || passkeys.count <= 1).accessibilityLabel("Remove \(passkey.name)") } }
                        TextField("Device name", text: $passkeyName)
                        Button("Add a passkey") { run { try await store.registerPasskey(name: passkeyName); message = "Your new passkey is ready."; await load() } }.disabled(busy)
                    } header: { Text("Your passkeys") } footer: { Text("Your last passkey is protected from deletion. Add a backup device so you always have a way in.") }
                    if admin.isOwner {
                        Section("People & access") { ForEach(accounts) { account in VStack(alignment: .leading, spacing: 8) { HStack { VStack(alignment: .leading) { Text(account.name).font(.headline); Text("\(account.isOwner ? "Owner" : "Administrator") · \(account.passkeyCount) passkeys").font(.caption).foregroundStyle(.secondary) }; Spacer(); Menu { Button("Rename") { rename = account }; Button("Create one-use sign-in link") { run { let result: LinkResult = try await store.send("/admin/signin-links/create", ["admin_id": account.id]); newLink = Config.trustedURL(result.url); await load() } }; Button("Sign out all sessions", role: .destructive) { confirmation = .sessions(account.id, account.name) }; if !account.isOwner { Button("Remove administrator", role: .destructive) { confirmation = .account(account) } } } label: { Image(systemName: "ellipsis.circle").font(.title3) }.disabled(busy) }; if let date = account.lastLoginAt { Text("Last sign-in \(String(date.prefix(10)))").font(.caption).foregroundStyle(.secondary) } } } }
                        Section { TextField("Invitation label / name", text: $inviteName); Button("Create invitation link") { run { let result: LinkResult = try await store.send("/admin/invites/create", ["name": inviteName]); newLink = Config.trustedURL(result.url); inviteName = ""; await load() } }.disabled(busy) } header: { Text("Invite an administrator") } footer: { Text("Administrator invitations work once and expire in seven days. Recipients create their own account and passkey.") }
                        if !invites.isEmpty { Section("Pending invitations") { ForEach(invites) { invite in HStack { VStack(alignment: .leading) { Text(invite.name); Text("Created \(String(invite.createdAt.prefix(10)))").font(.caption).foregroundStyle(.secondary) }; Spacer(); ShareLink(item: invite.url) { Image(systemName: "square.and.arrow.up") }.accessibilityLabel("Share \(invite.name) invitation"); Button(role: .destructive) { confirmation = .invite(invite) } label: { Image(systemName: "trash") }.disabled(busy) } } } }
                        if !links.isEmpty { Section("Active one-use sign-in links") { ForEach(links) { link in HStack { VStack(alignment: .leading) { Text(accounts.first { $0.id == link.adminId }?.name ?? "Administrator"); Text("Expires \(String(link.expiresAt.prefix(16)))").font(.caption).foregroundStyle(.secondary) }; Spacer(); Button("Revoke", role: .destructive) { confirmation = .link(link) }.disabled(busy) } } } }
                    }
                    if let newLink { Section("Your new private access link") { Text("Share this link only with its intended recipient.").font(.subheadline).foregroundStyle(.secondary); ShareLink(item: newLink) { Label("Share access link", systemImage: "square.and.arrow.up") }; Button("Dismiss link") { self.newLink = nil } } }
                    if let message { Section { Label(message, systemImage: "checkmark.circle").foregroundStyle(.green) } }
                    if error != nil { Section { ErrorText(text: error); Button("Reload account") { Task { await load() } } } }
                    Section("Sessions") { Button("Sign out all my sessions", role: .destructive) { confirmation = .sessions(admin.id, "your account") }.disabled(busy); Button("Sign out of this device", role: .destructive) { run { try await store.logout(); passkeys = []; accounts = []; invites = []; links = []; newLink = nil } }.disabled(busy) }
                    legalSection
                }.task(id: admin.id) { clearAccountData(); name = admin.name; await load() }.refreshable { await load() }
                .confirmationDialog(confirmation?.title ?? "Confirm action", isPresented: Binding(get: { confirmation != nil }, set: { if !$0 { confirmation = nil } }), titleVisibility: .visible) { if let action = confirmation { Button(action.button, role: .destructive) { confirmation = nil; perform(action) }; Button("Cancel", role: .cancel) { confirmation = nil } } } message: { Text(confirmation?.message ?? "") }
                .sheet(item: $rename) { account in NavigationStack { RenameAccountView(account: account) { rename = nil; Task { await load(); try? await store.refreshSession() } } }.environmentObject(store) }
            } else { Form { Section { Text("Sign in from the Host tab to manage your account, passkeys, and workspace.").foregroundStyle(.secondary) }; legalSection } }
        }.navigationTitle("Account").sheet(item: $browser) { SafariView(url: $0.url) }
        .onChange(of: store.admin?.id) { _, _ in clearAccountData() }
    }
    private var legalSection: some View { Section("Party Mail") { Button("Privacy policy") { browser = BrowserSheet(url: Config.url("/privacy")) }; Button("Terms of service") { browser = BrowserSheet(url: Config.url("/terms")) }; LabeledContent("Version", value: (Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "1.0") + " (" + (Bundle.main.infoDictionary?["CFBundleVersion"] as? String ?? "1") + ")") } }
    private func load() async {
        guard let current = store.admin else { clearAccountData(); return }
        do {
            let fetchedKeys = try await store.get("/admin/passkey/list", as: PasskeysPayload.self).passkeys
            guard store.admin?.id == current.id else { return }
            passkeys = fetchedKeys
            if current.isOwner {
                let a: AccountsPayload = try await store.get("/admin/accounts")
                let fetchedInvites = try await store.get("/admin/invites", as: InvitesPayload.self).invites
                guard store.admin?.id == current.id else { return }
                accounts = a.accounts; links = a.signinLinks; invites = fetchedInvites
            } else { accounts = []; links = []; invites = []; newLink = nil }
            error = nil
        } catch { self.error = error.localizedDescription }
    }
    private func clearAccountData() { access.transition(to: store.admin, force: true); rename = nil; confirmation = nil; error = nil; message = nil }
    private func run(_ action: @escaping () async throws -> Void) { busy = true; error = nil; message = nil; Task { defer { busy = false }; do { try await action() } catch is PasskeyAuthenticator.Cancelled {} catch { self.error = error.localizedDescription } } }
    private func perform(_ action: AccessAction) {
        run {
            let path: String; let body: [String: Any]
            switch action {
            case .passkey(let key): path = "/admin/passkey/delete"; body = ["credential_id": key.credentialId]
            case .account(let account): path = "/admin/accounts/revoke"; body = ["admin_id": account.id]
            case .sessions(let id, _): path = "/admin/accounts/sessions/revoke"; body = ["admin_id": id]
            case .invite(let invite): path = "/admin/invites/delete"; body = ["token": invite.token]
            case .link(let link): path = "/admin/signin-links/delete"; body = ["id": link.id]
            }
            let _: Success = try await store.send(path, body)
            try await store.refreshSession(); await load(); newLink = nil; message = "Access updated."
        }
    }
}
struct SettingsAccessState {
    private(set) var adminID: String?
    var passkeys: [Passkey] = []
    var accounts: [Account] = []
    var invites: [AdminInvite] = []
    var links: [SignInLink] = []
    var newLink: URL?
    mutating func transition(to admin: Admin?, force: Bool = false) {
        if force || adminID != admin?.id { passkeys = []; accounts = []; invites = []; links = []; newLink = nil }
        adminID = admin?.id
        if admin?.isOwner != true { accounts = []; invites = []; links = []; newLink = nil }
    }
}
enum AccessAction {
    case passkey(Passkey), account(Account), sessions(String, String), invite(AdminInvite), link(SignInLink)
    var title: String { switch self { case .passkey: return "Remove this passkey?"; case .account(let a): return "Remove \(a.name)?"; case .sessions(_, let name): return "Sign out all sessions for \(name)?"; case .invite: return "Revoke this invitation?"; case .link: return "Revoke this sign-in link?" } }
    var button: String { switch self { case .sessions: return "Sign out all sessions"; case .passkey, .account: return "Remove"; case .invite, .link: return "Revoke" } }
    var message: String { switch self { case .passkey: return "This passkey will no longer sign in to Party Mail."; case .account: return "Their passkeys and active sessions will stop working immediately."; case .sessions: return "Passkeys remain available, but every current session will require a new sign-in."; case .invite, .link: return "This private link will stop working immediately." } }
}
struct RenameAccountView: View {
    let account: Account; let saved: () -> Void
    @EnvironmentObject private var store: AppStore
    @Environment(\.dismiss) private var dismiss
    @State private var name: String
    @State private var busy = false
    @State private var error: String?
    init(account: Account, saved: @escaping () -> Void) { self.account = account; self.saved = saved; _name = State(initialValue: account.name) }
    var body: some View { Form { Section { TextField("Name", text: $name); BusyButton(title: "Save name", busy: busy, icon: "checkmark") { busy = true; Task { defer { busy = false }; do { let _: Success = try await store.send("/admin/accounts/update", ["admin_id": account.id, "name": name]); saved() } catch { self.error = error.localizedDescription } } }.disabled(name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty); ErrorText(text: error) } }.navigationTitle("Rename administrator").toolbar { ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } } } }
}
