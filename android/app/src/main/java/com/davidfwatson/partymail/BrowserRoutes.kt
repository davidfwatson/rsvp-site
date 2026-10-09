package com.davidfwatson.partymail

import java.net.URI

/** Website-only GET destinations intercepted by the verified host intent filter.
 * Native invitation, RSVP-update, enrollment and one-use sign-in URLs never fall
 * through to a browser. Pasted links keep using the stricter native parser. */
object BrowserRoutes {
    private val pages = setOf("/privacy", "/terms", "/admin", "/admin/login", "/admin/settings", "/admin/system", "/admin/email/connect", "/oauth2callback")
    private val adminPaths = setOf("login", "settings", "system", "email", "invite", "signin", "passkey", "accounts", "invites", "signin-links", "logout", "new_event")
    fun shouldOpen(raw: String, origin: String): Boolean = runCatching {
        val url = URI(raw); val base = URI(origin)
        if (!sameOrigin(url, base) || !base.rawPath.isNullOrEmpty() && base.rawPath != "/" || base.rawQuery != null || base.rawFragment != null) return false
        val path = url.rawPath ?: return false
        if (path in pages) return true
        val parts = path.split('/').drop(1)
        when {
            parts.size == 3 && Links.validSlug(parts[0]) && parts[1] == "calendar" && parts[2] in setOf("google", "ics") -> true
            parts.size == 2 && Links.validSlug(parts[0]) && parts[1] == "thank-you" -> true
            parts.size == 2 && parts[0] == "admin" && Links.validSlug(parts[1]) && parts[1] !in adminPaths -> true
            parts.size == 3 && parts[0] == "admin" && Links.validSlug(parts[1]) && parts[1] !in adminPaths && parts[2] in setOf("preview", "export") -> true
            else -> false
        }
    }.getOrDefault(false)
    private fun sameOrigin(url: URI, base: URI): Boolean {
        if (url.scheme !in setOf("https", "http") || base.scheme !in setOf("https", "http")) return false
        if (url.rawUserInfo != null || base.rawUserInfo != null || url.host == null || base.host == null) return false
        fun port(u: URI) = if (u.port != -1) u.port else if (u.scheme == "https") 443 else 80
        return url.scheme == base.scheme && url.host.equals(base.host, ignoreCase = true) && port(url) == port(base)
    }
}
