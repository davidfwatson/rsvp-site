package com.davidfwatson.partymail

import org.junit.Assert.*
import org.junit.Test

class BrowserRoutesTest {
    private val origin = "https://partymail.app"
    private val token = "PrivateToken12345678901234567890"
    @Test fun websiteOnlyDestinationsUseBrowserOnIncomingIntents() {
        listOf("/privacy", "/terms", "/admin", "/admin/login", "/admin/settings", "/admin/system", "/admin/email/connect", "/oauth2callback?state=opaque&code=opaque", "/demo-party/calendar/google", "/demo-party/calendar/ics", "/demo-party/thank-you", "/admin/demo-party", "/admin/demo-party/preview", "/admin/demo-party/export").forEach { assertTrue(it, BrowserRoutes.shouldOpen(origin + it, origin)) }
    }
    @Test fun nativeAndPrivateTokenDestinationsNeverFallThrough() {
        listOf("/demo-party", "/demo-party/update-rsvp/$token", "/admin/signin/$token", "/admin/invite/$token", "/admin/signin/short", "/admin/invite/$token?next=/admin", "/demo-party/update-rsvp/$token?other=1", "/api/mobile/session", "/admin/demo-party/save", "/admin/passkey/auth/options", "/healthz/calendar/ics", "/oauth2callback/extra", "/%70rivacy").forEach { assertFalse(it, BrowserRoutes.shouldOpen(origin + it, origin)) }
        assertFalse(BrowserRoutes.shouldOpen("partymail:///privacy", origin))
        assertNull(Links.parse(origin + "/privacy")) // Pasted links remain native-only.
    }
    @Test fun browserFallbackRequiresTheConfiguredCanonicalOrigin() {
        listOf("https://partymail.app.evil.test/privacy", "https://user@partymail.app/privacy", "https://partymail.app:444/privacy", "http://partymail.app/privacy", "https://www.partymail.app/privacy", "https://evil.test/https://partymail.app/privacy").forEach { assertFalse(it, BrowserRoutes.shouldOpen(it, origin)) }
        assertTrue(BrowserRoutes.shouldOpen("https://PARTYMAIL.APP:443/privacy#details", origin))
        assertTrue(BrowserRoutes.shouldOpen("http://10.0.2.2:5000/demo-party/calendar/ics", "http://10.0.2.2:5000"))
        assertFalse(BrowserRoutes.shouldOpen("http://10.0.2.2/demo-party/calendar/ics", "http://10.0.2.2:5000"))
        assertFalse(BrowserRoutes.shouldOpen("https://partymail.app/privacy", "https://partymail.app/base"))
        assertFalse(BrowserRoutes.shouldOpen("https://partymail.app/privacy", "https://user@partymail.app"))
    }
}
