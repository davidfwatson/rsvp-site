package com.davidfwatson.partymail

import android.app.Activity
import android.app.Application
import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.core.content.FileProvider
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import androidx.compose.runtime.*
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.launch
import kotlinx.serialization.json.*
import java.io.File

enum class Page { HOME, LOGIN, EVENT, EDITOR, INVITATION, RESPONSE, SETTINGS, SIGNIN, ENROLL, PREVIEW }
class PartyModel(application: Application) : AndroidViewModel(application) {
    val api = PartyApi(application)
    var session by mutableStateOf<Session?>(null); private set
    var page by mutableStateOf(Page.HOME); private set
    var busy by mutableStateOf(false); private set
    var bootstrapped by mutableStateOf(false); private set
    var error by mutableStateOf<String?>(null); private set
    var notice by mutableStateOf<String?>(null); private set
    var events by mutableStateOf<List<Event>>(emptyList()); private set
    var event by mutableStateOf<Event?>(null); private set
    var responses by mutableStateOf<List<Response>>(emptyList()); private set
    var attendees by mutableStateOf<List<Attendee>>(emptyList()); private set
    var response by mutableStateOf<Response?>(null); private set
    var editor by mutableStateOf<Event?>(null)
    var previewHtml by mutableStateOf<String?>(null); private set
    var responseToken: String? = null; private set
    var pendingToken: String? = null; private set
    var settings by mutableStateOf(JsonObject(emptyMap())); private set
    var passkeys by mutableStateOf<List<JsonObject>>(emptyList()); private set
    var invites by mutableStateOf<List<JsonObject>>(emptyList()); private set
    private var initialLink: Link? = null
    private var queuedLink: Link? = null

    fun start(raw: String?) {
        if (raw != null) initialLink = Links.parse(raw, api.origin)
        run {
            session = api.session(); bootstrapped = true
            if (initialLink != null) open(initialLink!!)
            else if (session?.admin != null) loadEvents() else page = Page.LOGIN
        }
    }
    fun openRaw(raw: String) {
        val link = Links.parse(raw, api.origin)
        if (link == null) { error = "Use a Party Mail invitation or administrator link from ${api.origin}."; return }
        if (!bootstrapped) { initialLink = link; return }
        if (busy) { queuedLink = link; return }
        run { open(link) }
    }
    private suspend fun open(link: Link) {
        when (link) {
            is Link.Invitation -> {
                // A deep-linked update is explicit; a remembered response can be edited from the invitation.
                responseToken = link.token
                if (link.token != null) loadResponse(link.slug, link.token)
                else loadInvitation(link.slug)
            }
            is Link.SignIn -> { pendingToken = link.token; page = Page.SIGNIN }
            is Link.Enroll -> { pendingToken = link.token; page = Page.ENROLL }
        }
    }
    fun dismissError() { error = null }
    fun dismissNotice() { notice = null }
    fun showLogin() { page = Page.LOGIN; error = null }
    fun home() = run { pendingToken = null; responseToken = null; if (session?.admin == null) page = Page.LOGIN else loadEvents() }
    fun back() {
        error = null
        when(page) {
            Page.EDITOR, Page.PREVIEW -> page = if (event == null) Page.HOME else Page.EVENT
            Page.RESPONSE -> page = Page.INVITATION
            else -> home()
        }
    }
    private fun run(block: suspend () -> Unit) {
        if (busy) return
        busy = true; error = null
        viewModelScope.launch {
            try { block() }
            catch (_: PasskeyCancelled) { }
            catch (e: CancellationException) { throw e }
            catch (e: Exception) {
                error = e.message ?: "Couldn't complete this action. Try again."
                if (e is ApiError && (e.status == 401 || (e.status == 400 && e.message?.startsWith("Your session expired.") == true))) { session = null; api.clearSession(); page = Page.LOGIN }
                // A failed initial bootstrap remains recoverable with the Retry button.
            }
            finally {
                busy = false
                queuedLink?.let { next -> queuedLink = null; run { open(next) } }
            }
        }
    }
    fun retryStartup() = start(null)
    private suspend fun refreshSession() { session = api.session(); bootstrapped = true }
    fun login(password: String) = run {
        if (session == null) refreshSession()
        api.request("/api/mobile/login", "POST", payload("password" to password)); refreshSession(); loadEvents()
    }
    fun passkeyLogin(activity: Activity) = run { if (session == null) refreshSession(); Passkeys(activity, api).signIn(); refreshSession(); loadEvents() }
    fun confirmSignIn() = run {
        api.request("/api/mobile/signin", "POST", payload("token" to pendingToken)); pendingToken = null; refreshSession(); loadEvents()
    }
    fun enroll(activity: Activity, name: String) = run {
        if (name.isBlank()) throw ApiError("Add your name to create your administrator account.")
        Passkeys(activity, api).register(name.trim(), pendingToken); pendingToken = null; refreshSession(); loadEvents()
    }
    fun logout() = run { api.request("/api/mobile/logout", "POST", payload()); api.clearSession(); refreshSession(); events = emptyList(); event = null; responses = emptyList(); settings = JsonObject(emptyMap()); page = Page.LOGIN }
    private suspend fun loadEvents() { events = api.decode<EventsResult>(api.request("/api/mobile/events")).events; page = Page.HOME }
    fun refreshEvents() = run { refreshSession(); if (session?.admin != null) loadEvents() else page = Page.LOGIN }
    fun showEvent(slug: String) = run { loadEvent(slug) }
    private suspend fun loadEvent(slug: String) {
        val result = api.decode<EventResult>(api.request("/api/mobile/events/$slug"))
        event = result.event; responses = result.rsvps; page = Page.EVENT
    }
    fun create() { event = null; editor = Event(); page = Page.EDITOR; error = null }
    fun edit() { editor = event; page = Page.EDITOR; error = null }
    fun save() = run {
        val draft = editor ?: return@run
        val creating = draft.id.isEmpty()
        Validation.event(draft, creating)?.let { throw ApiError(it) }
        val fields = api.json.encodeToJsonElement(draft).jsonObject.toMutableMap()
        listOf("id", "stats", "public_url", "version", "archived", "slug").forEach { fields.remove(it) }
        if (creating && draft.slug.isNotBlank()) fields["slug"] = JsonPrimitive(draft.slug)
        if (!creating) fields["version"] = JsonPrimitive(draft.version)
        val result = api.decode<EventResult>(api.request(if (creating) "/api/mobile/events" else "/api/mobile/events/${draft.slug}", if (creating) "POST" else "PATCH", JsonObject(fields)))
        editor = null; loadEvent(result.event.slug); notice = if (creating) "Your invitation is ready to share." else "Changes saved."
    }
    fun archive() = run {
        val e = event ?: return@run
        api.request("/api/mobile/events/${e.slug}", "PATCH", payload("version" to e.version, "archived" to !e.archived))
        loadEvent(e.slug); notice = if (e.archived) "Event restored." else "Event archived. Existing responses remain available."
    }
    fun upload(uri: Uri, background: Boolean) = run {
        val e = editor ?: return@run
        if (e.slug.isBlank()) throw ApiError("Save this event first, then add its photos.")
        val path = api.upload(getApplication(), e.slug, uri)
        editor = if (background) e.copy(background_image = path, background_style = "image") else e.copy(cover_image = path)
        notice = "Photo uploaded. Save your changes to use it."
    }
    fun sendInvite(email: String) = run {
        if (!email.contains('@')) throw ApiError("Add a valid email address.")
        val e = event ?: return@run
        api.request("/api/mobile/events/${e.slug}/invite", "POST", payload("email" to email.trim()))
        notice = "Invitation sent to ${email.trim()}."
    }
    fun preview() = run {
        val slug = event?.slug ?: return@run
        previewHtml = api.raw("/admin/$slug/preview").decodeToString()
        page = Page.PREVIEW
    }
    fun openGuest() = run { val slug = event?.slug ?: return@run; loadInvitation(slug) }
    private suspend fun loadInvitation(slug: String) {
        val result = api.decode<InvitationResult>(api.request("/api/mobile/invitations/$slug"))
        event = result.event; attendees = result.attendees; page = Page.INVITATION
    }
    fun newResponse() { response = null; responseToken = null; page = Page.RESPONSE }
    fun editSavedResponse() = run { val slug = event?.slug ?: return@run; val token = api.savedRSVP(slug) ?: throw ApiError("Open the private update link in your RSVP email to change your response."); loadResponse(slug, token) }
    private suspend fun loadResponse(slug: String, token: String) {
        val result = api.decode<ResponseResult>(api.request("/api/mobile/invitations/$slug/responses/$token"))
        responseToken = token; event = result.event; response = result.response; page = Page.RESPONSE
    }
    fun saveResponse(draft: Response) = run {
        val e = event ?: return@run
        Validation.response(draft, e.max_guests_per_invite)?.let { throw ApiError(it) }
        val body = payload("name" to draft.name.trim(), "email" to draft.email.trim(), "attending" to draft.attending,
            "num_adults" to if (draft.attending == "yes") draft.num_adults else 0,
            "num_children" to if (draft.attending == "yes") draft.num_children else 0,
            "dietary_restrictions" to draft.dietary_restrictions, "comment" to draft.comment)
        val token = responseToken
        if (token != null) {
            api.request("/api/mobile/invitations/${e.slug}/responses/$token", "PATCH", body)
            api.rememberRSVP(e.slug, token); notice = "Your RSVP has been updated."
        } else {
            val result = api.decode<RSVPResult>(api.request("/api/mobile/invitations/${e.slug}/rsvp", "POST", body))
            if (result.check_email) notice = if (result.email_delivered) "You already responded. Check your email for your private update link." else "You already responded. Email delivery is unavailable; use your original private update link to make changes."
            else {
                val privateToken = result.response?.token?.takeIf(Links::validToken)
                    ?: result.update_url?.let { url -> (Links.parse(url, api.origin) as? Link.Invitation)?.takeIf { it.slug == e.slug }?.token }
                    ?: throw ApiError("Your RSVP was saved, but this device couldn't keep the private update link. Use the link in your confirmation email or contact the host.")
                api.rememberRSVP(e.slug, privateToken)
                notice = if (result.email_delivered) "You're all set. Your private update link is in your email." else "Your RSVP is saved. Email delivery is unavailable; use Update my RSVP on this device to make changes."
            }
        }
        loadInvitation(e.slug)
    }
    fun hasSavedResponse(): Boolean = event?.slug?.let { api.savedRSVP(it) != null } ?: false
    fun export(context: Context) = run {
        val e = event ?: return@run
        val bytes = api.raw("/api/mobile/events/${e.slug}/export")
        val folder = File(context.cacheDir, "exports").apply { mkdirs() }
        folder.listFiles()?.forEach { it.delete() }
        val file = File(folder, "${e.slug}-rsvps.csv"); file.writeBytes(bytes)
        val uri = FileProvider.getUriForFile(context, "${BuildConfig.APPLICATION_ID}.files", file)
        val intent = Intent(Intent.ACTION_SEND).setType("text/csv").putExtra(Intent.EXTRA_STREAM, uri).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        context.startActivity(Intent.createChooser(intent, "Export guest responses"))
    }
    fun showSettings() = run { loadSettings() }
    private suspend fun loadSettings() {
        passkeys = api.request("/admin/passkey/list").rows("passkeys")
        if (session?.admin?.is_owner == true) { settings = api.request("/admin/accounts"); invites = api.request("/admin/invites").rows("invites") }
        else { settings = JsonObject(emptyMap()); invites = emptyList() }
        page = Page.SETTINGS
    }
    fun registerPasskey(activity: Activity, name: String) = run { Passkeys(activity, api).register(name.trim().ifEmpty { "Android passkey" }); refreshSession(); loadSettings(); notice = "Passkey added." }
    fun settingsAction(path: String, body: JsonObject, share: ((String) -> Unit)? = null) = run {
        val result = api.request(path, "POST", body)
        if (result["signed_out"]?.jsonPrimitive?.booleanOrNull == true) { api.clearSession(); refreshSession(); page = Page.LOGIN; return@run }
        result.string("url").takeIf { it.isNotEmpty() }?.let { url -> if (Links.safeWeb(url, api.origin)) share?.invoke(url) }
        refreshSession(); loadSettings(); notice = "Saved."
    }
}
