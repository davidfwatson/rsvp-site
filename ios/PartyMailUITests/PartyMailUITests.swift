import XCTest

final class PartyMailUITests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }
    func testGuestInvitationSubmitAndUpdate() {
        let app = XCUIApplication(); app.launchEnvironment["PARTYMAIL_BASE_URL"] = ProcessInfo.processInfo.environment["PARTYMAIL_TEST_BASE_URL"] ?? "http://127.0.0.1:5000"; app.launchEnvironment["PARTYMAIL_RESET_PRIVATE_DATA"] = "1"; app.launch()
        app.tabBars.buttons["Invitations"].tap()
        let link = app.textFields["invitationLink"]; XCTAssertTrue(link.waitForExistence(timeout: 10)); link.tap(); link.typeText("demo-party"); app.buttons["openInvitation"].tap()
        let name = app.textFields["rsvpName"]; XCTAssertTrue(name.waitForExistence(timeout: 15))
        let invitation = XCTAttachment(screenshot: app.screenshot()); invitation.name = "iPhone invitation RSVP"; invitation.lifetime = .keepAlways; add(invitation)
        name.tap(); name.typeText("iOS Integration Guest")
        let email = app.textFields["rsvpEmail"]; email.tap(); email.typeText("ios-\(UUID().uuidString.prefix(8))@example.test")
        app.swipeUp(); app.buttons["submitRSVP"].tap()
        XCTAssertTrue(app.buttons["Update your response"].waitForExistence(timeout: 15)); app.buttons["Update your response"].tap()
        app.swipeUp(); XCTAssertTrue(app.buttons["submitRSVP"].waitForExistence(timeout: 5)); app.buttons["submitRSVP"].tap()
        XCTAssertTrue(app.staticTexts["Your response is updated."].waitForExistence(timeout: 15))
    }
    func testHostCreatePreviewArchiveAndRestore() {
        let app = XCUIApplication(); app.launchEnvironment["PARTYMAIL_BASE_URL"] = ProcessInfo.processInfo.environment["PARTYMAIL_TEST_BASE_URL"] ?? "http://127.0.0.1:5000"; app.launchEnvironment["PARTYMAIL_RESET_PRIVATE_DATA"] = "1"; app.launch()
        let recovery = app.buttons["Owner password recovery"]; XCTAssertTrue(recovery.waitForExistence(timeout: 10)); recovery.tap()
        let password = app.secureTextFields["ownerPassword"]; XCTAssertTrue(password.waitForExistence(timeout: 5)); password.tap(); password.typeText("test")
        reveal(app.buttons["Sign in"], in: app); app.buttons["Sign in"].tap()
        XCTAssertTrue(app.buttons["createEvent"].waitForExistence(timeout: 15))
        let dashboard = XCTAttachment(screenshot: app.screenshot()); dashboard.name = "iPhone host dashboard"; dashboard.lifetime = .keepAlways; add(dashboard)
        app.buttons["createEvent"].tap()
        let eventName = "iOS Gathering \(UUID().uuidString.prefix(6))"
        let name = app.textFields["eventName"]; XCTAssertTrue(name.waitForExistence(timeout: 5)); name.tap(); name.typeText(eventName)
        let location = app.textFields["eventLocation"]; location.tap(); location.typeText("The garden")
        reveal(app.buttons["saveEvent"], in: app); app.buttons["saveEvent"].tap()
        let created = app.staticTexts[eventName].firstMatch; XCTAssertTrue(created.waitForExistence(timeout: 15)); created.tap()
        reveal(app.buttons["Preview invitation"], in: app); app.buttons["Preview invitation"].tap()
        XCTAssertTrue(app.webViews.firstMatch.waitForExistence(timeout: 15)); app.buttons["Done"].tap()
        reveal(app.buttons["Archive event"], in: app); app.buttons["Archive event"].tap(); app.buttons["Archive"].tap()
        XCTAssertTrue(app.buttons["Restore event"].waitForExistence(timeout: 15)); app.buttons["Restore event"].tap(); app.buttons["Restore"].tap()
        XCTAssertTrue(app.buttons["Archive event"].waitForExistence(timeout: 15))
    }
    private func reveal(_ element: XCUIElement, in app: XCUIApplication) { for _ in 0..<12 { if element.isHittable { return }; app.swipeUp() }; XCTAssertTrue(element.isHittable) }
}
