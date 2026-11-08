// The Docmost sign-in window on macOS: a Mac window with the system's WebKit. session.py builds it from this file the
// first time it is needed (xcrun swiftc, from Xcode or its Command Line Tools) and runs it:
//
//   docmost-login --url https://docs.example.com --out FILE [--timeout S] [--headless]
//   docmost-login --clear
//
// The researcher signs in as usual in the window, single sign-on included. Once the site has set Docmost's authToken
// cookie and /api/users/me answers (asked with those cookies, never following a redirect), the site's cookies, the
// window's user agent and who signed in are written to FILE (mode 0600) and the window closes. Only cookies for the
// site's own host (or a domain above it) are written. The window keeps its own website data under a fixed identifier,
// so --headless can renew a sign-in that is still valid without showing anything; --clear forgets that data.
// Exit codes, as login.py: 0 signed in, 2 bad arguments, 3 the window was closed, 4 timed out, 6 the site could not be
// opened.
import AppKit
import WebKit

let storeIdentifier = UUID(uuidString: "6D1C9B52-3E1A-4F0B-9A55-2B0A7C4D1E11")!

struct Options {
    var url = ""
    var out = ""
    var timeout = 300.0
    var headless = false
    var clear = false
}

func parseOptions() -> Options {
    var o = Options()
    var args = Array(CommandLine.arguments.dropFirst())
    while !args.isEmpty {
        let a = args.removeFirst()
        switch a {
        case "--url": o.url = args.isEmpty ? "" : args.removeFirst()
        case "--out": o.out = args.isEmpty ? "" : args.removeFirst()
        case "--timeout": o.timeout = Double(args.isEmpty ? "" : args.removeFirst()) ?? 300.0
        case "--headless": o.headless = true
        case "--clear": o.clear = true
        default:
            FileHandle.standardError.write("unknown argument: \(a)\n".data(using: .utf8)!)
            exit(2)
        }
    }
    return o
}

func websiteDataStore() -> WKWebsiteDataStore {
    if #available(macOS 14.0, *) {
        return WKWebsiteDataStore(forIdentifier: storeIdentifier)
    }
    return WKWebsiteDataStore.default()
}

final class NoRedirects: NSObject, URLSessionTaskDelegate {
    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) {
        completionHandler(nil)
    }
}

final class SignIn: NSObject, NSApplicationDelegate, NSWindowDelegate, WKNavigationDelegate {
    let options: Options
    let site: URL
    let host: String
    var window: NSWindow!
    var web: WKWebView!
    var loadedOnce = false
    var checking = false
    var finished = false
    let noRedirects = NoRedirects()

    init(options: Options, site: URL) {
        self.options = options
        self.site = site
        self.host = (site.host ?? "").lowercased()
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        let config = WKWebViewConfiguration()
        config.websiteDataStore = websiteDataStore()
        web = WKWebView(frame: NSRect(x: 0, y: 0, width: 1040, height: 780), configuration: config)
        web.navigationDelegate = self
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1040, height: 780),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "Sign in to Docmost — Research Deck"
        window.contentView = web
        window.isReleasedWhenClosed = false
        window.delegate = self
        window.center()
        if !options.headless {
            window.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
        }
        web.load(URLRequest(url: site))
        Timer.scheduledTimer(withTimeInterval: 1.0, repeats: true) { [weak self] _ in self?.poll() }
        DispatchQueue.main.asyncAfter(deadline: .now() + options.timeout) { [weak self] in self?.finish(4) }
    }

    func windowWillClose(_ notification: Notification) {
        finish(3)
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        loadedOnce = true
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        let e = error as NSError
        // Only the first page matters here: later failures happen inside the sign-in pages and are theirs to show.
        if !loadedOnce && !(e.domain == NSURLErrorDomain && e.code == NSURLErrorCancelled) && e.code != 102 {
            FileHandle.standardError.write("could not open \(site.absoluteString): \(e.localizedDescription)\n".data(using: .utf8)!)
            finish(6)
        }
    }

    func belongsToSite(_ cookie: HTTPCookie) -> Bool {
        var domain = cookie.domain.lowercased()
        if domain.hasPrefix(".") { domain.removeFirst() }
        return host == domain || host.hasSuffix("." + domain)
    }

    func poll() {
        if checking || finished { return }
        web.configuration.websiteDataStore.httpCookieStore.getAllCookies { all in
            let mine = all.filter { self.belongsToSite($0) }
            if !mine.contains(where: { $0.name == "authToken" }) { return }
            self.checking = true
            self.verify(mine)
        }
    }

    func verify(_ cookies: [HTTPCookie]) {
        web.evaluateJavaScript("navigator.userAgent") { value, _ in
            let agent = (value as? String) ?? ""
            var request = URLRequest(url: self.site.appendingPathComponent("api/users/me"))
            request.httpMethod = "POST"
            request.httpBody = "{}".data(using: .utf8)
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.setValue("application/json", forHTTPHeaderField: "Accept")
            request.setValue(cookies.map { "\($0.name)=\($0.value)" }.joined(separator: "; "), forHTTPHeaderField: "Cookie")
            if !agent.isEmpty { request.setValue(agent, forHTTPHeaderField: "User-Agent") }
            let config = URLSessionConfiguration.ephemeral
            config.httpShouldSetCookies = false
            config.httpCookieAcceptPolicy = .never
            let session = URLSession(configuration: config, delegate: self.noRedirects, delegateQueue: nil)
            session.dataTask(with: request) { data, response, _ in
                DispatchQueue.main.async {
                    guard let http = response as? HTTPURLResponse, http.statusCode == 200, let data = data,
                          let json = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] else {
                        self.checking = false          // not signed in yet (or the proxy wants more): keep waiting
                        return
                    }
                    let body = (json["data"] as? [String: Any]) ?? json
                    let user = (body["user"] as? [String: Any]) ?? body
                    if self.write(cookies: cookies, agent: agent, user: user) {
                        self.finish(0)
                    } else {
                        self.finish(6)
                    }
                }
            }.resume()
        }
    }

    func write(cookies: [HTTPCookie], agent: String, user: [String: Any]) -> Bool {
        let list: [[String: Any]] = cookies.map { c in
            var d: [String: Any] = ["name": c.name, "value": c.value, "domain": c.domain, "path": c.path,
                                    "secure": c.isSecure, "httpOnly": c.isHTTPOnly]
            if let expires = c.expiresDate { d["expires"] = expires.timeIntervalSince1970 }
            return d
        }
        let who: [String: Any] = ["id": user["id"] ?? NSNull(), "name": user["name"] ?? NSNull(), "email": user["email"] ?? NSNull()]
        let out: [String: Any] = ["url": options.url, "user_agent": agent, "at": ISO8601DateFormatter().string(from: Date()),
                                  "cookies": list, "user": who]
        guard let data = try? JSONSerialization.data(withJSONObject: out) else { return false }
        let tmp = options.out + ".tmp"
        let fm = FileManager.default
        try? fm.removeItem(atPath: tmp)
        guard fm.createFile(atPath: tmp, contents: data, attributes: [.posixPermissions: 0o600]) else { return false }
        try? fm.removeItem(atPath: options.out)
        return (try? fm.moveItem(atPath: tmp, toPath: options.out)) != nil
    }

    func finish(_ code: Int32) {
        if finished { return }
        finished = true
        exit(code)
    }
}

final class Clear: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        websiteDataStore().removeData(ofTypes: WKWebsiteDataStore.allWebsiteDataTypes(), modifiedSince: .distantPast) {
            exit(0)
        }
    }
}

let options = parseOptions()
let app = NSApplication.shared
if options.clear {
    let clear = Clear()
    app.delegate = clear
    app.setActivationPolicy(.prohibited)
    app.run()
} else {
    guard let site = URL(string: options.url), let scheme = site.scheme, ["http", "https"].contains(scheme), site.host != nil,
          !options.out.isEmpty else {
        FileHandle.standardError.write("usage: docmost-login --url https://… --out FILE [--timeout S] [--headless] | --clear\n".data(using: .utf8)!)
        exit(2)
    }
    let signIn = SignIn(options: options, site: site)
    app.delegate = signIn
    app.setActivationPolicy(options.headless ? .prohibited : .regular)
    app.run()
}
