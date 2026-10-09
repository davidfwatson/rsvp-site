import SwiftUI
import PhotosUI

struct EventEditor: View {
    let event: Event?
    let saved: (Event) -> Void
    @EnvironmentObject private var store: AppStore
    @Environment(\.dismiss) private var dismiss
    @State private var draft: EventDraft
    @State private var busy = false
    @State private var error: String?
    @State private var coverSelection: PhotosPickerItem?
    @State private var backgroundSelection: PhotosPickerItem?
    @State private var coverData: Data?
    @State private var backgroundData: Data?
    @State private var createdEvent: Event?
    init(event: Event?, saved: @escaping (Event) -> Void) { self.event = event; self.saved = saved; _draft = State(initialValue: event.map(EventDraft.init) ?? EventDraft()) }
    var body: some View {
        Form {
            Section("The occasion") {
                TextField("Event name", text: $draft.name).accessibilityIdentifier("eventName")
                if event == nil && createdEvent == nil { TextField("Event code (optional)", text: Binding(get: { draft.slug ?? "" }, set: { draft.slug = $0.isEmpty ? nil : $0.lowercased() })).textInputAutocapitalization(.never).autocorrectionDisabled() }
                DatePicker("Date", selection: Binding(get: { Format.parseDay(draft.date) ?? Date() }, set: { draft.date = Format.day($0) }), displayedComponents: .date)
                DatePicker("Starts", selection: timeBinding($draft.startTime), displayedComponents: .hourAndMinute)
                Toggle("End time", isOn: Binding(get: { !draft.endTime.isEmpty }, set: { draft.endTime = $0 ? "21:00" : "" }))
                if !draft.endTime.isEmpty { DatePicker("Ends", selection: timeBinding($draft.endTime), displayedComponents: .hourAndMinute) }
                TextField("Location", text: $draft.location, axis: .vertical).lineLimit(1...3).accessibilityIdentifier("eventLocation")
                TextField("Description (Markdown supported)", text: $draft.description, axis: .vertical).lineLimit(4...12)
            }
            guestLimitSection
            Section("Design") {
                Picker("Envelope color", selection: $draft.colorScheme) { Text("Rose").tag("pink"); Text("Blue").tag("blue"); Text("Red").tag("red"); Text("Black").tag("black") }
                Picker("Background", selection: $draft.backgroundStyle) { Text("Linen").tag("linen"); Text("Gradient").tag("gradient"); Text("Solid").tag("solid"); Text("Photo").tag("image") }
                ColorPicker("Background color", selection: colorBinding($draft.backgroundColor), supportsOpacity: false)
                TextField("Background hex color", text: $draft.backgroundColor).textInputAutocapitalization(.characters).autocorrectionDisabled()
                ColorPicker("Accent color", selection: colorBinding($draft.accentColor), supportsOpacity: false)
                TextField("Accent hex color", text: $draft.accentColor).textInputAutocapitalization(.characters).autocorrectionDisabled()
                Picker("Type style", selection: $draft.fontStyle) { Text("Serif").tag("serif"); Text("Sans serif").tag("sans") }
                Picker("Envelope", selection: $draft.envelopeStyle) { Text("Classic").tag("classic"); Text("Minimal").tag("minimal") }
            }
            Section {
                photoRow("Invitation artwork", data: coverData, path: draft.coverImage)
                PhotosPicker(selection: $coverSelection, matching: .images) { Label("Choose invitation artwork", systemImage: "photo") }
                if coverData != nil || !draft.coverImage.isEmpty { Button("Remove artwork", role: .destructive) { coverData = nil; draft.coverImage = ""; coverSelection = nil } }
                photoRow("Background photo", data: backgroundData, path: draft.backgroundImage)
                PhotosPicker(selection: $backgroundSelection, matching: .images) { Label("Choose background photo", systemImage: "photo.on.rectangle") }
                if backgroundData != nil || !draft.backgroundImage.isEmpty { Button("Remove background", role: .destructive) { backgroundData = nil; draft.backgroundImage = ""; backgroundSelection = nil } }
            } header: { Text("Photos") } footer: { Text("Photos are resized for the invitation and uploaded when you save.") }
            if error != nil { Section { ErrorText(text: error) } }
            Section { BusyButton(title: event == nil && createdEvent == nil ? "Create invitation" : "Save invitation", busy: busy, icon: "envelope") { save() }.accessibilityIdentifier("saveEvent") }
        }.scrollDismissesKeyboard(.interactively).navigationTitle(event == nil ? "New gathering" : "Edit invitation").navigationBarTitleDisplayMode(.inline)
        .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() }.disabled(busy) } }
        .interactiveDismissDisabled(busy)
        .onChange(of: coverSelection) { _, item in Task { coverData = await loadPhoto(item) } }
        .onChange(of: backgroundSelection) { _, item in Task { backgroundData = await loadPhoto(item); if backgroundData != nil { draft.backgroundStyle = "image" } } }
    }
    private var guestLimitSection: some View {
        Section("Guest list") {
            Stepper(value: $draft.maxGuestsPerInvite, in: 1...100) { Text("Up to \(draft.maxGuestsPerInvite) guests per invitation") }
            Toggle("Show attendees to guests", isOn: $draft.showAttendees)
        }
    }
    private func timeBinding(_ text: Binding<String>) -> Binding<Date> { Binding(get: { let f = DateFormatter(); f.dateFormat = "HH:mm"; return f.date(from: text.wrappedValue) ?? Date() }, set: { text.wrappedValue = Format.timeValue($0) }) }
    private func colorBinding(_ text: Binding<String>) -> Binding<Color> { Binding(get: { Color(hex: text.wrappedValue) }, set: { color in let c = UIColor(color); var r: CGFloat = 0, g: CGFloat = 0, b: CGFloat = 0, a: CGFloat = 0; c.getRed(&r, green: &g, blue: &b, alpha: &a); text.wrappedValue = String(format: "#%02X%02X%02X", Int(r * 255), Int(g * 255), Int(b * 255)) }) }
    @ViewBuilder private func photoRow(_ title: String, data: Data?, path: String) -> some View {
        if let data, let image = UIImage(data: data) { Image(uiImage: image).resizable().scaledToFit().frame(maxHeight: 160).clipShape(RoundedRectangle(cornerRadius: 10)).accessibilityLabel(title) }
        else if !path.isEmpty, let url = Config.trustedURL(path) { AsyncImage(url: url) { image in image.resizable().scaledToFit() } placeholder: { ProgressView() }.frame(maxHeight: 160).clipShape(RoundedRectangle(cornerRadius: 10)).accessibilityLabel(title) }
    }
    private func loadPhoto(_ item: PhotosPickerItem?) async -> Data? {
        guard let item else { return nil }
        do {
            guard let data = try await item.loadTransferable(type: Data.self), let original = UIImage(data: data) else { throw APIError(status: 0, message: "This photo couldn’t be opened. Try a different image.") }
            return try ArtworkProcessing.prepare(original)
        } catch { self.error = error.localizedDescription; return nil }
    }
    private func save() {
        if let validation = draft.validationError { error = validation; return }
        busy = true; error = nil
        Task {
            defer { busy = false }
            do {
                // Remember creation before uploading: if a photo upload fails, retry edits
                // the newly created event instead of creating another invitation.
                var updated: Event
                if let original = createdEvent ?? event {
                    draft.version = original.version
                    updated = try await store.send("/api/mobile/events/\(original.slug)", value: draft, method: "PATCH", as: EventPayload.self).event
                } else {
                    updated = try await store.send("/api/mobile/events", value: draft, as: EventPayload.self).event
                }
                createdEvent = updated; draft.version = updated.version; draft.slug = nil
                if let data = coverData { draft.coverImage = try await store.upload(slug: updated.slug, image: data); coverData = nil }
                if let data = backgroundData { draft.backgroundImage = try await store.upload(slug: updated.slug, image: data); backgroundData = nil }
                if updated.coverImage != draft.coverImage || updated.backgroundImage != draft.backgroundImage {
                    updated = try await store.send("/api/mobile/events/\(updated.slug)", value: draft, method: "PATCH", as: EventPayload.self).event
                    createdEvent = updated
                }
                saved(updated)
            } catch { self.error = error.localizedDescription }
        }
    }
}
enum ArtworkProcessing {
    static func prepare(_ original: UIImage) throws -> Data {
        let scale = min(1, 1800 / max(original.size.width, original.size.height))
        let size = CGSize(width: original.size.width * scale, height: original.size.height * scale)
        let format = UIGraphicsImageRendererFormat(); format.scale = 1; format.opaque = false
        let image = UIGraphicsImageRenderer(size: size, format: format).image { _ in original.draw(in: CGRect(origin: .zero, size: size)) }
        guard let png = image.pngData(), png.count <= 10_000_000 else { throw APIError(status: 0, message: "Choose a smaller image.") }
        return png
    }
}
