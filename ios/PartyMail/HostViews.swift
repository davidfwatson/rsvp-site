import SwiftUI
import PhotosUI
import UniformTypeIdentifiers

struct HostView: View {
    @EnvironmentObject private var store: AppStore
    @State private var showArchived = false
    @State private var create = false
    var body: some View {
        Group {
            if !store.bootstrapped { ProgressView("Opening Party Mail…") }
            else if store.admin == nil { LoginView() }
            else {
                List {
                    Section { VStack(alignment: .leading, spacing: 8) { Text("Make room for memories.").font(.title2.weight(.semibold)).fontDesign(.serif); Text("Welcome, \(store.admin?.name ?? "host"). Your next gathering starts with an invitation.").foregroundStyle(.secondary) }.padding(.vertical, 8) }
                    Section {
                        Picker("Events", selection: $showArchived) { Text("Upcoming & past").tag(false); Text("Archived").tag(true) }.pickerStyle(.segmented)
                        let events = store.events.filter { $0.archived == showArchived }
                        if events.isEmpty { ContentUnavailableView(showArchived ? "No archived events" : "Your first invitation awaits", systemImage: "envelope", description: Text(showArchived ? "Archived events stay here with their guest responses." : "Tap + to bring your people together.")) }
                        ForEach(events) { event in NavigationLink { HostEventView(slug: event.slug) } label: { EventRow(event: event) } }
                    } header: { Text("Your gatherings") }
                }.overlay { if store.loading && store.events.isEmpty { ProgressView() } }.refreshable { await store.loadEvents() }.task(id: store.admin?.id) { await store.loadEvents() }
                .navigationTitle("Party Mail")
                .toolbar { ToolbarItem(placement: .topBarTrailing) { Button { create = true } label: { Label("Create event", systemImage: "plus") }.accessibilityIdentifier("createEvent") } }
                .sheet(isPresented: $create) { NavigationStack { EventEditor(event: nil) { _ in create = false; Task { await store.loadEvents() } } }.environmentObject(store) }
            }
        }
    }
}
struct EventRow: View {
    let event: Event
    var body: some View { HStack(spacing: 16) { ZStack { RoundedRectangle(cornerRadius: 13).fill(Color(hex: event.accentColor).opacity(0.13)); Image(systemName: "envelope.open").font(.title2).foregroundStyle(Color(hex: event.accentColor)) }.frame(width: 54, height: 64); VStack(alignment: .leading, spacing: 5) { Text(event.name).font(.headline).fontDesign(.serif); Text("\(event.dateLabel) · \(event.timeLabel)").font(.subheadline).foregroundStyle(.secondary); Text("\(event.stats?.attending ?? 0) attending · \(event.stats?.responses ?? 0) responses").font(.caption).foregroundStyle(.secondary) } }.padding(.vertical, 6) }
}
struct HostEventView: View {
    let slug: String
    @EnvironmentObject private var store: AppStore
    @State private var detail: EventDetail?
    @State private var error: String?
    @State private var busy = false
    @State private var edit = false
    @State private var preview = false
    @State private var inviteEmail = ""
    @State private var message: String?
    @State private var exportURL: URL?
    @State private var shareExport = false
    @State private var archiveConfirmation = false
    var body: some View {
        Group {
            if let detail {
                List {
                    Section { InvitationCard(event: detail.event).listRowInsets(EdgeInsets()).listRowBackground(Color.clear) }
                    Section {
                        HStack { StatView(value: detail.event.stats?.responses ?? detail.rsvps.count, label: "Responses"); Spacer(); StatView(value: detail.event.stats?.attending ?? 0, label: "Attending"); Spacer(); StatView(value: detail.event.stats?.declined ?? 0, label: "Declined") }
                    }
                    Section("Invitation") {
                        if !detail.event.archived { ShareLink(item: detail.event.invitationURL) { Label("Share invitation", systemImage: "square.and.arrow.up") } }
                        Button { preview = true } label: { Label("Preview invitation", systemImage: "eye") }
                        Button { edit = true } label: { Label("Edit details & design", systemImage: "pencil") }
                        if store.emailEnabled && !detail.event.archived {
                            TextField("Guest email address", text: $inviteEmail).textContentType(.emailAddress).keyboardType(.emailAddress).textInputAutocapitalization(.never).autocorrectionDisabled()
                            Button("Send email invitation") { run { let _: Success = try await store.send("/api/mobile/events/\(slug)/invite", ["email": inviteEmail]); message = "Invitation sent."; inviteEmail = "" } }.disabled(busy || !inviteEmail.contains("@"))
                        }
                    }
                    Section("Guest responses") {
                        if detail.rsvps.isEmpty { Text("The guest list is waiting for its first yes.").foregroundStyle(.secondary) }
                        ForEach(detail.rsvps) { rsvp in NavigationLink { RSVPDetailView(response: rsvp) } label: { VStack(alignment: .leading, spacing: 5) { HStack { Text(rsvp.name).font(.headline); Spacer(); Text(rsvp.attending == "yes" ? "\(rsvp.guests) attending" : "Declined").font(.caption).foregroundStyle(rsvp.attending == "yes" ? .green : .secondary) }; Text(rsvp.email).font(.caption).foregroundStyle(.secondary); if !rsvp.dietaryRestrictions.isEmpty { Label(rsvp.dietaryRestrictions, systemImage: "fork.knife").font(.caption) } } } }
                        Button { run { let data = try await store.raw("/api/mobile/events/\(slug)/export"); let url = FileManager.default.temporaryDirectory.appendingPathComponent("PartyMail-\(slug)-\(UUID().uuidString.prefix(8)).csv"); try data.write(to: url, options: .completeFileProtection); exportURL = url; shareExport = true } } label: { Label("Export guest list CSV", systemImage: "square.and.arrow.up") }.disabled(busy)
                    }
                    Section { Button(detail.event.archived ? "Restore event" : "Archive event", role: detail.event.archived ? nil : .destructive) { archiveConfirmation = true }.disabled(busy) } footer: { Text(detail.event.archived ? "Restoring makes the invitation available to guests again." : "Archiving closes the invitation and keeps every guest response.") }
                    if message != nil { Section { Label(message!, systemImage: "checkmark.circle").foregroundStyle(.green) } }
                    if error != nil { Section { ErrorText(text: error); Button("Reload event") { Task { await load() } } } }
                }.refreshable { await load() }
                .sheet(isPresented: $edit) { NavigationStack { EventEditor(event: detail.event) { _ in edit = false; Task { await load(); await store.loadEvents() } } }.environmentObject(store) }
                .sheet(isPresented: $preview) { NavigationStack { InvitationPreview(event: detail.event).navigationTitle("Invitation preview").toolbar { ToolbarItem(placement: .topBarTrailing) { Button("Done") { preview = false } } } }.environmentObject(store) }
                .sheet(isPresented: $shareExport, onDismiss: { if let url = exportURL { try? FileManager.default.removeItem(at: url) }; exportURL = nil }) { if let url = exportURL { ShareSheet(items: [url]) } }
                .confirmationDialog(detail.event.archived ? "Restore this event?" : "Archive this event?", isPresented: $archiveConfirmation, titleVisibility: .visible) { Button(detail.event.archived ? "Restore" : "Archive", role: detail.event.archived ? nil : .destructive) { run { let _: EventPayload = try await store.send("/api/mobile/events/\(slug)", ["version": detail.event.version ?? 0, "archived": !detail.event.archived], method: "PATCH"); await load(); await store.loadEvents() } } }
            } else if let error { ContentUnavailableView { Label("Couldn’t load event", systemImage: "wifi.exclamationmark") } description: { Text(error) } actions: { Button("Try again") { Task { await load() } } } }
            else { ProgressView("Opening invitation…") }
        }.navigationTitle(detail?.event.name ?? "Event").navigationBarTitleDisplayMode(.inline).task { await load() }
    }
    private func load() async { do { detail = try await store.get("/api/mobile/events/\(slug)"); error = nil } catch { self.error = error.localizedDescription } }
    private func run(_ action: @escaping () async throws -> Void) { busy = true; error = nil; message = nil; Task { defer { busy = false }; do { try await action() } catch { self.error = error.localizedDescription } } }
}
struct StatView: View { let value: Int; let label: String; var body: some View { VStack(alignment: .leading, spacing: 4) { Text(value.formatted()).font(.title.weight(.semibold)).fontDesign(.rounded); Text(label).font(.caption).foregroundStyle(.secondary) } } }
struct RSVPDetailView: View { let response: RSVP; var body: some View { Form { Section { LabeledContent("Name", value: response.name); LabeledContent("Email", value: response.email); LabeledContent("Response", value: response.attending == "yes" ? "Attending" : "Declined"); LabeledContent("Adults", value: "\(response.numAdults)"); LabeledContent("Children", value: "\(response.numChildren)") }; if !response.dietaryRestrictions.isEmpty { Section("Dietary restrictions") { Text(response.dietaryRestrictions) } }; if !response.comment.isEmpty { Section("Message") { Text(response.comment) } }; if let date = response.updatedAt ?? response.timestamp { Section("Last response") { Text(date).font(.footnote).foregroundStyle(.secondary) } } }.navigationTitle(response.name) } }
