import SwiftUI
import WebKit

struct InvitationPreview: View {
    let event: Event
    @EnvironmentObject private var store: AppStore
    @State private var html: String?
    @State private var error: String?
    var body: some View {
        Group {
            if let html { RenderedInvitation(html: html) }
            else if let error { ContentUnavailableView("Couldn’t load preview", systemImage: "eye.slash", description: Text(error)) }
            else { ProgressView("Rendering your invitation…") }
        }.task { do { let data = try await store.raw("/admin/\(event.slug)/preview"); guard let html = String(data: data, encoding: .utf8) else { throw APIError(status: 0, message: "The invitation preview couldn’t be read.") }; self.html = html } catch { self.error = error.localizedDescription } }
    }
}
struct RenderedInvitation: UIViewRepresentable {
    let html: String
    func makeCoordinator() -> Coordinator { Coordinator() }
    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration(); config.websiteDataStore = .nonPersistent()
        let view = WKWebView(frame: .zero, configuration: config); view.navigationDelegate = context.coordinator; view.loadHTMLString(html, baseURL: Config.baseURL); return view
    }
    func updateUIView(_ uiView: WKWebView, context: Context) {}
    final class Coordinator: NSObject, WKNavigationDelegate {
        func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
            guard let url = navigationAction.request.url else { decisionHandler(.cancel); return }
            if url.absoluteString == "about:blank" || (navigationAction.navigationType == .other && Config.trustedURL(url.absoluteString) != nil) { decisionHandler(.allow) }
            else { decisionHandler(.cancel) }
        }
    }
}
