import SwiftUI
import SafariServices

@main struct PartyMailApp: App {
    @StateObject private var store = AppStore()
    var body: some Scene { WindowGroup { RootView().environmentObject(store).tint(Theme.accent) } }
}
enum Theme {
    static let accent = Color(red: 0.65, green: 0.30, blue: 0.41)
    static let paper = Color(uiColor: .secondarySystemGroupedBackground)
}
struct RouteSheet: Identifiable { let id = UUID(); let route: DeepLink }
struct RootView: View {
    @EnvironmentObject private var store: AppStore
    @Environment(\.scenePhase) private var phase
    @State private var routeSheet: RouteSheet?
    var body: some View {
        TabView {
            NavigationStack { HostView() }.tabItem { Label("Host", systemImage: "envelope.badge") }
            NavigationStack { OpenInvitationView() }.tabItem { Label("Invitations", systemImage: "party.popper") }
            NavigationStack { SettingsView() }.tabItem { Label("Account", systemImage: "person.crop.circle") }
        }
        .task { await store.bootstrap() }
        .onChange(of: phase) { _, phase in if phase == .active && store.bootstrapped { Task { try? await store.refreshSession() } } }
        .onOpenURL { url in if let route = DeepLink.parse(url) { routeSheet = RouteSheet(route: route) } }
        .onContinueUserActivity(NSUserActivityTypeBrowsingWeb) { activity in if let url = activity.webpageURL, let route = DeepLink.parse(url) { routeSheet = RouteSheet(route: route) } }
        .sheet(item: $routeSheet) { item in
            NavigationStack {
                Group {
                    switch item.route {
                    case .invitation(let slug): GuestInvitationView(slug: slug)
                    case .response(let slug, let token): GuestInvitationView(slug: slug, token: token)
                    case .signin(let token): SignInLinkView(token: token)
                    case .enroll(let token): EnrollmentView(token: token)
                    }
                }.toolbar { ToolbarItem(placement: .topBarTrailing) { Button("Done") { routeSheet = nil } } }
            }.environmentObject(store)
        }
        .alert("Party Mail", isPresented: Binding(get: { store.error != nil }, set: { if !$0 { store.error = nil } })) { Button("OK") { store.error = nil } } message: { Text(store.error ?? "") }
    }
}
struct ErrorText: View { let text: String?; var body: some View { if let text { Label(text, systemImage: "exclamationmark.circle").foregroundStyle(.red).font(.subheadline).accessibilityLabel(text) } } }
struct BusyButton: View {
    let title: String; let busy: Bool; var icon = "arrow.right"; let action: () -> Void
    var body: some View { Button(action: action) { HStack { if busy { ProgressView().tint(.white) } else { Image(systemName: icon) }; Text(title) }.frame(maxWidth: .infinity).padding(.vertical, 6) }.buttonStyle(.borderedProminent).disabled(busy) }
}
struct SafariView: UIViewControllerRepresentable {
    let url: URL
    func makeUIViewController(context: Context) -> SFSafariViewController { SFSafariViewController(url: url) }
    func updateUIViewController(_ uiViewController: SFSafariViewController, context: Context) {}
}
struct BrowserSheet: Identifiable { let id = UUID(); let url: URL }
struct ShareSheet: UIViewControllerRepresentable {
    let items: [Any]
    func makeUIViewController(context: Context) -> UIActivityViewController { UIActivityViewController(activityItems: items, applicationActivities: nil) }
    func updateUIViewController(_ uiViewController: UIActivityViewController, context: Context) {}
}
extension Color {
    init(hex: String) { let value = UInt64(hex.trimmingCharacters(in: CharacterSet(charactersIn: "#")), radix: 16) ?? 0xA64E68; self.init(red: Double((value >> 16) & 255) / 255, green: Double((value >> 8) & 255) / 255, blue: Double(value & 255) / 255) }
}
