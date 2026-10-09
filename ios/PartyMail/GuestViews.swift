import SwiftUI

struct OpenInvitationView: View {
    @State private var input = ""
    @State private var route: RouteSheet?
    @State private var error: String?
    var body: some View {
        Form {
            Section { VStack(alignment: .leading, spacing: 12) { Image(systemName: "envelope.open").font(.largeTitle).foregroundStyle(Theme.accent); Text("You’re invited.").font(.largeTitle).fontDesign(.serif); Text("Open a Party Mail invitation link to read the details, RSVP, and save the date.").foregroundStyle(.secondary) }.padding(.vertical, 16) }
            Section("Invitation link or event code") { TextField("https://partymail.app/your-event", text: $input).keyboardType(.URL).textInputAutocapitalization(.never).autocorrectionDisabled().accessibilityIdentifier("invitationLink"); Button("Open invitation") { let text = input.trimmingCharacters(in: .whitespacesAndNewlines); let url = text.contains(":") ? URL(string: text) : Config.url("/\(text)"); if let url, let parsed = DeepLink.parse(url) { route = RouteSheet(route: parsed); error = nil } else { error = "Enter a valid Party Mail invitation link or event code." } }.disabled(input.isEmpty).accessibilityIdentifier("openInvitation") }
            if error != nil { Section { ErrorText(text: error) } }
        }.navigationTitle("Invitations")
        .sheet(item: $route) { item in NavigationStack { Group { switch item.route { case .invitation(let slug): GuestInvitationView(slug: slug); case .response(let slug, let token): GuestInvitationView(slug: slug, token: token); case .signin(let token): SignInLinkView(token: token); case .enroll(let token): EnrollmentView(token: token) } }.toolbar { ToolbarItem(placement: .topBarTrailing) { Button("Done") { route = nil } } } } }
    }
}
struct InvitationCard: View {
    let event: Event
    var body: some View {
        VStack(spacing: 22) {
            if !event.coverImage.isEmpty, let url = Config.trustedURL(event.coverImage) { AsyncImage(url: url) { image in image.resizable().scaledToFit() } placeholder: { ProgressView() }.frame(maxHeight: 520).accessibilityLabel("Invitation artwork") }
            if event.envelopeStyle == "classic" { Image(systemName: "envelope.open").font(.system(size: 38, weight: .light)).foregroundStyle(envelopeColor).accessibilityHidden(true) }
            Text("YOU’RE INVITED").font(.caption.weight(.semibold)).tracking(3).foregroundStyle(Color(hex: event.accentColor))
            Text(event.name).font(.system(.largeTitle, design: event.fontStyle == "serif" ? .serif : .default, weight: .medium)).multilineTextAlignment(.center).foregroundStyle(ink)
            VStack(spacing: 8) { Label(event.dateLabel, systemImage: "calendar"); Text(event.timeLabel); Label(event.location, systemImage: "mappin.and.ellipse") }.font(.subheadline).multilineTextAlignment(.center).foregroundStyle(ink.opacity(0.75))
            if !event.description.isEmpty { Divider(); Text((try? AttributedString(markdown: event.description)) ?? AttributedString(event.description)).font(.system(.body, design: event.fontStyle == "serif" ? .serif : .default)).foregroundStyle(ink.opacity(0.80)).frame(maxWidth: .infinity, alignment: .leading) }
            if event.archived { Label("Archived invitation", systemImage: "archivebox").font(.caption).foregroundStyle(ink.opacity(0.65)) }
        }.padding(28).frame(maxWidth: .infinity).background {
            ZStack {
                Color(hex: event.backgroundColor)
                if event.backgroundStyle == "gradient" { LinearGradient(colors: [Color(hex: event.backgroundColor), Color(hex: event.accentColor).opacity(0.25)], startPoint: .topLeading, endPoint: .bottomTrailing) }
                if event.backgroundStyle == "linen" { Canvas { context, size in for x in stride(from: 0.0, to: size.width, by: 3) { var path = Path(); path.move(to: CGPoint(x: x, y: 0)); path.addLine(to: CGPoint(x: x, y: size.height)); context.stroke(path, with: .color(.black.opacity(0.015))) } } }
                if event.backgroundStyle == "image", !event.backgroundImage.isEmpty, let url = Config.trustedURL(event.backgroundImage) { AsyncImage(url: url) { image in image.resizable().scaledToFill() } placeholder: { Color.clear }; Color.white.opacity(0.85) }
            }
        }.clipShape(RoundedRectangle(cornerRadius: 20)).overlay { RoundedRectangle(cornerRadius: 20).strokeBorder(Color(hex: event.accentColor).opacity(0.18)) }
    }
    private var envelopeColor: Color { switch event.colorScheme { case "blue": return .blue; case "red": return .red; case "black": return .black; default: return Theme.accent } }
    private var ink: Color {
        if event.backgroundStyle == "image" { return .black }
        let rgb = UInt64(event.backgroundColor.trimmingCharacters(in: CharacterSet(charactersIn: "#")), radix: 16) ?? 0xF4EFE7
        let luminance = 0.2126 * Double((rgb >> 16) & 255) + 0.7152 * Double((rgb >> 8) & 255) + 0.0722 * Double(rgb & 255)
        return luminance < 135 ? .white : .black
    }
}
struct GuestInvitationView: View {
    let slug: String
    var token: String? = nil
    @EnvironmentObject private var store: AppStore
    @State private var event: Event?
    @State private var attendees: [Attendee] = []
    @State private var response = RSVP.empty
    @State private var savedToken: String?
    @State private var error: String?
    @State private var loading = true
    @State private var busy = false
    @State private var success: String?
    @State private var browser: BrowserSheet?
    @State private var editing = true
    @State private var emailWasDelivered = false
    var body: some View {
        Group {
            if let event {
                Form {
                    Section { InvitationCard(event: event).listRowInsets(EdgeInsets()).listRowBackground(Color.clear) }
                    if let success { Section { Label(success, systemImage: "checkmark.circle.fill").foregroundStyle(.green); if savedToken != nil { Button("Update your response") { editing = true; self.success = nil } } } }
                    if editing {
                        Section(savedToken == nil ? "Your RSVP" : "Update your RSVP") {
                            TextField("Your name", text: $response.name).textContentType(.name).accessibilityIdentifier("rsvpName")
                            TextField("Email", text: $response.email).textContentType(.emailAddress).keyboardType(.emailAddress).textInputAutocapitalization(.never).autocorrectionDisabled().accessibilityIdentifier("rsvpEmail")
                            Picker("Will you join us?", selection: $response.attending) { Text("Yes, I’ll be there").tag("yes"); Text("Sorry, can’t make it").tag("no") }.pickerStyle(.segmented)
                            if response.attending == "yes" { Stepper("Adults: \(response.numAdults)", value: $response.numAdults, in: 1...event.maxGuestsPerInvite); Stepper("Children: \(response.numChildren)", value: $response.numChildren, in: 0...max(0, event.maxGuestsPerInvite - response.numAdults)); Text("Up to \(event.maxGuestsPerInvite) guests per invitation.").font(.caption).foregroundStyle(.secondary); TextField("Dietary restrictions", text: $response.dietaryRestrictions, axis: .vertical).lineLimit(1...3) }
                            TextField("A message for the host", text: $response.comment, axis: .vertical).lineLimit(2...5)
                            BusyButton(title: savedToken == nil ? "Send RSVP" : "Save response", busy: busy, icon: "paperplane") { submit() }.accessibilityIdentifier("submitRSVP")
                        }
                    }
                    Section("Save the date") {
                        Button { browser = BrowserSheet(url: Config.url("/\(slug)/calendar/google")) } label: { Label("Add to Google Calendar", systemImage: "calendar.badge.plus") }
                        Link(destination: Config.url("/\(slug)/calendar/ics")) { Label("Add to Apple Calendar", systemImage: "calendar") }
                    }
                    if !attendees.isEmpty { Section("Who’s coming") { ForEach(Array(attendees.enumerated()), id: \.offset) { _, a in HStack { Text("\(a.firstName) \(a.lastInitial)"); Spacer(); Text(a.guestInfo).foregroundStyle(.secondary).font(.caption) } } } }
                    if savedToken != nil { Section { Button("Forget saved response on this device", role: .destructive) { Vault.delete("rsvp.\(slug)"); savedToken = nil; response = .empty; success = nil; editing = true } } footer: { Text("Your response stays with the host. Your private update link is stored securely on this device.") } }
                    if error != nil { Section { ErrorText(text: error) } }
                }.refreshable { await load() }
            } else if loading { ProgressView("Opening your invitation…") }
            else { ContentUnavailableView { Label("Invitation unavailable", systemImage: "envelope.badge.shield.half.filled") } description: { Text(error ?? "This invitation may have been archived.") } actions: { Button("Try again") { Task { await load() } } } }
        }.navigationTitle(event?.name ?? "Invitation").navigationBarTitleDisplayMode(.inline).task { await load() }
        .sheet(item: $browser) { SafariView(url: $0.url) }
    }
    private func load() async {
        loading = true; defer { loading = false }
        do {
            let invitation: InvitationPayload = try await store.get("/api/mobile/invitations/\(slug)")
            event = invitation.event; attendees = invitation.attendees
            if let privateToken = token ?? savedToken ?? Vault.responseToken(slug: slug) {
                do {
                    let payload: ResponsePayload = try await store.get("/api/mobile/invitations/\(slug)/responses/\(privateToken)")
                    response = payload.response; event = payload.event; savedToken = privateToken
                    Vault.saveResponseToken(privateToken, slug: slug)
                } catch {
                    if token != nil { throw error }
                    if (error as? APIError)?.status == 404 { Vault.delete("rsvp.\(slug)"); savedToken = nil }
                    else { throw error }
                }
            }
            error = nil
        } catch { self.error = error.localizedDescription }
    }
    private func submit() {
        guard let event else { return }
        if let validation = response.validationError(limit: event.maxGuestsPerInvite) { error = validation; return }
        busy = true; error = nil
        Task {
            defer { busy = false }
            do {
                if let savedToken {
                    let payload: ResponsePayload = try await store.send("/api/mobile/invitations/\(slug)/responses/\(savedToken)", value: response.payload(), method: "PATCH")
                    response = payload.response; self.event = payload.event; success = "Your response is updated."; editing = false
                } else {
                    let payload: RSVPResult = try await store.send("/api/mobile/invitations/\(slug)/rsvp", value: response.payload())
                    if payload.checkEmail == true { success = payload.emailDelivered == true ? "You already responded. Check your email for your private update link." : "A response already exists for this email. Use your original update link, or contact the host for help."; editing = false }
                    else {
                        if let rsvp = payload.response { response = rsvp }
                        if let raw = payload.updateUrl, let url = Config.trustedURL(raw), case let .response(_, privateToken) = DeepLink.parse(url) { savedToken = privateToken; if !Vault.saveResponseToken(privateToken, slug: slug) { error = "Your response was sent, but its update link couldn’t be saved on this device. Keep the link in your confirmation email." } }
                        success = response.attending == "yes" ? "You’re on the list. See you there!" : "Your response is sent. Thanks for letting the host know."
                        if payload.emailDelivered == false { success! += " Email confirmation is unavailable; your update link is saved on this device." }
                        editing = false
                    }
                }
            } catch { self.error = error.localizedDescription }
        }
    }
}
