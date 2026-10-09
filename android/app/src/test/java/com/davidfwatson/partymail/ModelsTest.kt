package com.davidfwatson.partymail

import kotlinx.serialization.json.Json
import org.junit.Assert.*
import org.junit.Test
import java.time.LocalDate

class ModelsTest {
    private val token = "Mysafe_PrivateToken1234567890"
    @Test fun invitationAndPrivateUpdateLinks() {
        assertEquals(Link.Invitation("demo-party"), Links.parse("https://partymail.app/demo-party"))
        assertEquals(Link.Invitation("demo-party", token), Links.parse("https://partymail.app/demo-party/update-rsvp/$token"))
        assertEquals(Link.Enroll(token), Links.parse("partymail:///admin/invite/$token"))
        assertEquals(Link.SignIn(token), Links.parse("partymail://admin/signin/$token"))
    }
    @Test fun linksRejectOriginAndPathConfusion() {
        listOf("https://partymail.app.evil.test/demo", "http://partymail.app/demo", "https://partymail.app:444/demo", "https://user@partymail.app/demo", "https://partymail.app/%2e%2e", "https://partymail.app/demo?token=$token", "https://partymail.app/demo#fragment", "https://partymail.app/admin", "https://partymail.app/healthz", "https://partymail.app/oauth2callback", "https://partymail.app/healthz/update-rsvp/$token", "partymail://evil:123/demo", "https://partymail.app/demo/update-rsvp/short").forEach { assertNull(it, Links.parse(it)) }
        assertEquals(Link.Invitation("demo"), Links.parse("http://10.0.2.2:5000/demo", "http://10.0.2.2:5000"))
        assertNull(Links.parse("http://10.0.2.2:5000/demo"))
    }
    @Test fun creationAndUpdatesHaveDifferentDateRules() {
        val old = Event(name = "Past party", date = "2020-01-01", start_time = "18:00", location = "Here")
        assertNotNull(Validation.event(old, true)); assertNull(Validation.event(old, false))
        val future = old.copy(date = LocalDate.now().plusDays(1).toString())
        assertNull(Validation.event(future, true))
        assertNotNull(Validation.event(future.copy(start_time = "25:00"), true))
        assertNotNull(Validation.event(future.copy(max_guests_per_invite = 101), true))
        assertNotNull(Validation.event(future.copy(accent_color = "red"), true))
        assertNotNull(Validation.event(future.copy(slug = "api"), true))
    }
    @Test fun partySizeRulesIncludeTheResponder() {
        val guest = Response(name = "Guest", email = "guest@example.test", num_adults = 2, num_children = 2)
        assertNull(Validation.response(guest, 4)); assertNotNull(Validation.response(guest, 3))
        assertNotNull(Validation.response(guest.copy(num_adults = 0), 4))
        assertNotNull(Validation.response(guest.copy(num_children = -1), 4))
        assertNull(Validation.response(guest.copy(attending = "no", num_adults = 0), 4))
        assertNotNull(Validation.response(guest.copy(email = "bad"), 4))
    }
    @Test fun publicInvitationOmitsPrivateHostFieldsAndHandlesExtraMetadata() {
        val parser = Json { ignoreUnknownKeys = true }
        val value = parser.decodeFromString<InvitationResult>("""{"event":{"slug":"demo-party","name":"Demo","date":"2030-01-01","start_time":"18:00","unknown_metadata":true},"attendees":[{"first_name":"Guest","last_initial":"G","guest_info":" +1"}]}""")
        assertEquals(0, value.event.stats.responses)
        assertEquals("Guest", value.attendees.single().first_name)
        val duplicate = parser.decodeFromString<RSVPResult>("""{"check_email":true,"email_delivered":false}""")
        assertNull(duplicate.update_url); assertNull(duplicate.response)
        val created = parser.decodeFromString<RSVPResult>("""{"response":{"name":"Guest","email":"guest@example.test","token":"Mysafe_PrivateToken1234567890"},"update_url":"http://127.0.0.1:5000/demo-party/update-rsvp/Mysafe_PrivateToken1234567890"}""")
        assertTrue(Links.validToken(created.response!!.token!!))
        assertNull(Links.parse(created.update_url!!, "http://10.0.2.2:5000"))
    }
}
