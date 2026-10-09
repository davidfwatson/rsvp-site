package com.davidfwatson.partymail

import kotlinx.serialization.Serializable
import java.net.URI
import java.time.LocalDate
import java.time.LocalTime
import java.time.LocalDateTime

@Serializable data class Admin(val id: String, val name: String, val is_owner: Boolean = false)
@Serializable data class Session(val csrf_token: String = "", val admin: Admin? = null, val public_url: String = "https://partymail.app", val email_enabled: Boolean = false, val email_connected: Boolean = false)
@Serializable data class Stats(val responses: Int = 0, val attending: Int = 0, val accepted: Int = 0, val declined: Int = 0)
@Serializable data class Event(
    val id: String = "", val slug: String = "", val version: Int = 0,
    val name: String = "", val date: String = "", val start_time: String = "", val end_time: String = "",
    val location: String = "", val description: String = "", val max_guests_per_invite: Int = 10,
    val color_scheme: String = "pink", val background_style: String = "linen", val background_color: String = "#FFF8F0",
    val accent_color: String = "#974065", val background_image: String = "", val cover_image: String = "",
    val font_style: String = "serif", val envelope_style: String = "classic", val show_attendees: Boolean = false,
    val archived: Boolean = false, val public_url: String = "", val stats: Stats = Stats()
)
@Serializable data class Response(
    val name: String = "", val email: String = "", val attending: String = "yes", val num_adults: Int = 1, val num_children: Int = 0,
    val dietary_restrictions: String = "", val comment: String = "", val timestamp: String = "", val updated_at: String = "", val token: String? = null
)
@Serializable data class Attendee(val first_name: String = "", val last_initial: String = "", val guest_info: String = "")
@Serializable data class EventsResult(val events: List<Event>)
@Serializable data class EventResult(val event: Event, val rsvps: List<Response> = emptyList())
@Serializable data class InvitationResult(val event: Event, val attendees: List<Attendee> = emptyList())
@Serializable data class ResponseResult(val response: Response, val event: Event)
@Serializable data class RSVPResult(val response: Response? = null, val update_url: String? = null, val email_delivered: Boolean = false, val check_email: Boolean = false)

sealed interface Link {
    data class Invitation(val slug: String, val token: String? = null) : Link
    data class SignIn(val token: String) : Link
    data class Enroll(val token: String) : Link
}
/** No URL decoding, query tokens, userinfo or path traversal accepted. */
object Links {
    private val reserved = setOf("admin", "api", "static", "privacy", "terms", "media", "healthz", "oauth2callback")
    private val slug = Regex("[a-z0-9]+(?:-[a-z0-9]+)*")
    private val token = Regex("[A-Za-z0-9_-]{16,256}")
    fun parse(raw: String, origin: String = "https://partymail.app"): Link? = runCatching {
        val u = URI(raw.trim())
        if (u.rawUserInfo != null || u.rawQuery != null || u.rawFragment != null) return null
        val base = URI(origin)
        val path = if (u.scheme == "partymail") {
            if (u.port != -1) return null
            // Accept partymail:///slug and partymail://slug; both map to website paths.
            (if (u.rawAuthority.isNullOrEmpty()) "" else "/${u.rawAuthority}") + (u.rawPath ?: "")
        } else {
            if (u.scheme != base.scheme || u.host != base.host || u.port != base.port) return null
            u.rawPath ?: return null
        }
        val parts = path.trimEnd('/').split('/').drop(1)
        when {
            parts.size == 1 && validSlug(parts[0]) -> Link.Invitation(parts[0])
            parts.size == 3 && validSlug(parts[0]) && parts[1] == "update-rsvp" && token.matches(parts[2]) -> Link.Invitation(parts[0], parts[2])
            parts.size == 3 && parts[0] == "admin" && parts[1] == "signin" && token.matches(parts[2]) -> Link.SignIn(parts[2])
            parts.size == 3 && parts[0] == "admin" && parts[1] == "invite" && token.matches(parts[2]) -> Link.Enroll(parts[2])
            else -> null
        }
    }.getOrNull()
    fun validToken(value: String) = token.matches(value)
    fun validSlug(value: String) = value.length <= 50 && slug.matches(value) && value !in reserved
    fun safeWeb(raw: String, origin: String): Boolean = runCatching {
        val u = URI(raw); val b = URI(origin)
        u.scheme == b.scheme && u.host == b.host && u.port == b.port && u.rawUserInfo == null
    }.getOrDefault(false)
}

object Validation {
    fun event(e: Event, creating: Boolean): String? {
        if (e.name.isBlank() || e.location.isBlank()) return "Add an event name and location."
        val date = runCatching { LocalDate.parse(e.date) }.getOrNull() ?: return "Choose a date in YYYY-MM-DD format."
        val time = runCatching { LocalTime.parse(e.start_time) }.getOrNull() ?: return "Use HH:mm for the start time."
        if (creating && !LocalDateTime.of(date, time).isAfter(LocalDateTime.now())) return "New events need a future date and start time."
        if (e.end_time.isNotBlank() && runCatching { LocalTime.parse(e.end_time) }.isFailure) return "Use HH:mm for the end time."
        if (e.max_guests_per_invite !in 1..100) return "Guest limit must be between 1 and 100."
        if (!Regex("#[0-9A-Fa-f]{6}").matches(e.background_color) || !Regex("#[0-9A-Fa-f]{6}").matches(e.accent_color)) return "Use six-digit hex colors, for example #974065."
        if (e.slug.isNotBlank() && !Links.validSlug(e.slug)) return "Use lowercase letters, numbers and single hyphens for the event URL."
        return null
    }
    fun response(r: Response, maxGuests: Int): String? = when {
        r.name.isBlank() -> "Add your name."
        !Regex("[^\\s@]+@[^\\s@]+\\.[^\\s@]+").matches(r.email) -> "Add a valid email address."
        r.attending == "yes" && (r.num_adults < 1 || r.num_children < 0 || r.num_adults + r.num_children > maxGuests) -> "Your party needs at least one adult and no more than $maxGuests guests."
        else -> null
    }
}
