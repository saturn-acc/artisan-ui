import AppKit
import WebKit

// Motion parameters follow Coucou's IslandRootView (Louis-CFM/coucou):
// spring(response: 0.5, dampingFraction: 0.72), closing cubic (0.45, 0, 0.2, 1).
// The AppKit interpolation below is implemented locally for Artisan's web chat.
struct IslandMotion {
    static let response = 0.5
    static let damping = 0.72
    static let settleDuration = 0.85
    static let closeDuration = 0.34

    static func spring(_ time: Double) -> CGFloat {
        let omega = 2 * Double.pi / response
        let decay = damping * omega
        let frequency = omega * sqrt(1 - damping * damping)
        return CGFloat(1 - exp(-decay * time) *
            (cos(frequency * time) + decay / frequency * sin(frequency * time)))
    }

    static func closing(_ progress: Double) -> CGFloat {
        let progress = min(1, max(0, progress))
        // Invert the Bezier's x coordinate to evaluate its y at elapsed time.
        var low = 0.0, high = 1.0
        for _ in 0..<24 {
            let t = (low + high) / 2
            let x = 3 * (1 - t) * (1 - t) * t * 0.45 + 3 * (1 - t) * t * t * 0.2 + t * t * t
            if x < progress { low = t } else { high = t }
        }
        let t = (low + high) / 2
        return CGFloat(3 * (1 - t) * t * t + t * t * t)
    }
}

final class IslandPanel: NSPanel {
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { false }
}

final class Island: NSObject, NSApplicationDelegate, WKScriptMessageHandler, WKNavigationDelegate {
    var panel: IslandPanel!
    var web: WKWebView!
    var surface: NSView!
    let backdrop = CAGradientLayer()
    var screen: NSScreen!
    var timer: Timer?
    var animationTimer: Timer?
    var transitionID = 0
    var expanded = false
    var waitingForPointerExit = false
    var desiredHeight: CGFloat = 240
    var inset: CGFloat = 0
    let url: URL

    init(url: URL) { self.url = url; super.init() }

    func applicationDidFinishLaunching(_ notification: Notification) {
        screen = NSScreen.screens.first(where: { $0.safeAreaInsets.top > 0 }) ?? NSScreen.main ?? NSScreen.screens[0]
        inset = screen.safeAreaInsets.top
        let configuration = WKWebViewConfiguration()
        configuration.userContentController.add(self, name: "island")
        web = WKWebView(frame: .zero, configuration: configuration)
        web.navigationDelegate = self
        web.setValue(false, forKey: "drawsBackground")
        panel = IslandPanel(contentRect: .zero, styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        panel.title = "Artisan Island"
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = true
        panel.hidesOnDeactivate = false
        panel.level = .statusBar
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary]
        surface = NSView(frame: .zero)
        surface.wantsLayer = true
        surface.layer?.masksToBounds = true
        backdrop.colors = [NSColor(red: 0.06, green: 0.10, blue: 0.08, alpha: 1).cgColor,
                           NSColor(red: 0.07, green: 0.21, blue: 0.14, alpha: 1).cgColor]
        surface.layer?.addSublayer(backdrop)
        panel.contentView = surface
        web.autoresizingMask = []
        surface.addSubview(web)
        var components = URLComponents(url: url, resolvingAgainstBaseURL: false)!
        components.queryItems = [URLQueryItem(name: "island", value: "1"), URLQueryItem(name: "inset", value: String(Double(inset)))]
        web.load(URLRequest(url: components.url!))
        web.setFrameSize(expandedFrame.size)
        drawPanel(tuckedFrame, alpha: 0)
        timer = Timer(timeInterval: 1.0 / 60, repeats: true) { [weak self] _ in self?.trackPointer() }
        RunLoop.main.add(timer!, forMode: .common)
        NotificationCenter.default.addObserver(self, selector: #selector(screenChanged), name: NSApplication.didChangeScreenParametersNotification, object: nil)
    }

    var expandedFrame: NSRect {
        let width = min(640.0, screen.frame.width - 24)
        let maxHeight = max(1, min(900, screen.frame.height - 80))
        let height = min(maxHeight, max(240, desiredHeight))
        return NSRect(x: screen.frame.midX - width / 2, y: screen.frame.maxY - height,
                      width: width, height: height)
    }

    var tuckedFrame: NSRect {
        let width = min(230, expandedFrame.width)
        let height = max(2, inset)
        return NSRect(x: screen.frame.midX - width / 2, y: screen.frame.maxY - height,
                      width: width, height: height)
    }

    func drawPanel(_ frame: NSRect, alpha: CGFloat) {
        CATransaction.begin()
        CATransaction.setDisableActions(true)
        panel.setFrame(frame, display: false)
        // Keep the web layout at its final size; only the surrounding surface
        // changes shape, so text does not reflow as the notch expands.
        web.setFrameOrigin(NSPoint(x: (surface.bounds.width - web.frame.width) / 2,
                                   y: surface.bounds.height - web.frame.height))
        backdrop.frame = surface.bounds
        let fraction = min(1, max(0, (frame.width - tuckedFrame.width) / max(1, expandedFrame.width - tuckedFrame.width)))
        surface.layer?.cornerRadius = 14 + 8 * fraction
        panel.alphaValue = min(1, max(0, alpha))
        CATransaction.commit()
    }

    func animatePanel(open: Bool) {
        animationTimer?.invalidate()
        animationTimer = nil
        let startFrame = panel.frame
        let startAlpha = panel.alphaValue
        let targetFrame = open ? expandedFrame : tuckedFrame
        let targetAlpha: CGFloat = open ? 1 : 0
        if open { web.setFrameSize(expandedFrame.size) }
        let finish = { [weak self] in
            guard let self else { return }
            self.drawPanel(targetFrame, alpha: targetAlpha)
            if !open {
                self.panel.orderOut(nil)
                self.web.evaluateJavaScript("document.body.classList.add('island-collapsed');")
            }
        }
        if NSWorkspace.shared.accessibilityDisplayShouldReduceMotion {
            finish()
            return
        }
        let started = CACurrentMediaTime()
        let duration = open ? IslandMotion.settleDuration : IslandMotion.closeDuration
        let animation = Timer(timeInterval: 1.0 / 120, repeats: true) { [weak self] timer in
            guard let self else { timer.invalidate(); return }
            let elapsed = CACurrentMediaTime() - started
            let progress = min(1, elapsed / duration)
            let eased = open ? IslandMotion.spring(elapsed) : IslandMotion.closing(progress)
            func blend(_ from: CGFloat, _ to: CGFloat) -> CGFloat { from + (to - from) * eased }
            let width = max(1, blend(startFrame.width, targetFrame.width))
            let height = max(1, blend(startFrame.height, targetFrame.height))
            // Grow sideways and downward from the top-center of the notch.
            let frame = NSRect(x: self.screen.frame.midX - width / 2,
                               y: self.screen.frame.maxY - height, width: width, height: height)
            let opacityProgress = open ? min(1, CGFloat(elapsed / 0.16)) : eased
            self.drawPanel(frame, alpha: startAlpha + (targetAlpha - startAlpha) * opacityProgress)
            if progress >= 1 {
                timer.invalidate()
                self.animationTimer = nil
                finish()
            }
        }
        animationTimer = animation
        RunLoop.main.add(animation, forMode: .common)
    }

    // The window is ordered out when closed. Only this invisible notch-sized
    // region can reopen it; the old expanded frame must not remain a hot zone.
    var activationFrame: NSRect {
        let height = max(8, inset + 4)
        return NSRect(x: screen.frame.midX - 115, y: screen.frame.maxY - height,
                      width: 230, height: height)
    }

    func setExpanded(_ value: Bool) {
        guard expanded != value else { return }
        expanded = value
        transitionID += 1
        let transition = transitionID
        animationTimer?.invalidate()
        animationTimer = nil
        if value {
            if !panel.isVisible {
                web.setFrameSize(expandedFrame.size)
                drawPanel(tuckedFrame, alpha: 0)
            }
            // Reveal the web content before showing the window. Keep it visible
            // throughout the closing animation, then order the window out.
            web.evaluateJavaScript("window.setIslandOpen?.(true);") { [weak self] _, _ in
                guard let self, self.expanded, self.transitionID == transition else { return }
                self.panel.ignoresMouseEvents = false
                self.panel.orderFrontRegardless()
                self.animatePanel(open: true)
            }
        } else {
            panel.resignKey()
            panel.ignoresMouseEvents = true
            web.evaluateJavaScript("window.setIslandOpen?.(false);")
            animatePanel(open: false)
        }
    }

    func trackPointer() {
        let pointer = NSEvent.mouseLocation
        let onNotch = activationFrame.contains(pointer)
        if waitingForPointerExit {
            if !onNotch { waitingForPointerExit = false }
            return
        }
        if expanded {
            if !onNotch && !expandedFrame.union(panel.frame).contains(pointer) { setExpanded(false) }
        } else if onNotch {
            setExpanded(true)
        }
    }

    @objc func screenChanged() {
        screen = NSScreen.screens.first(where: { $0.safeAreaInsets.top > 0 }) ?? NSScreen.main ?? NSScreen.screens[0]
        inset = screen.safeAreaInsets.top
        web.evaluateJavaScript("document.documentElement.style.setProperty('--notch-inset','\(inset)px');")
        if expanded && panel.isVisible { animatePanel(open: true) }
        else if !expanded { setHiddenAfterScreenChange() }
    }

    func setHiddenAfterScreenChange() {
        animationTimer?.invalidate()
        animationTimer = nil
        panel.orderOut(nil)
        web.setFrameSize(expandedFrame.size)
        drawPanel(tuckedFrame, alpha: 0)
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        guard message.frameInfo.isMainFrame, message.frameInfo.securityOrigin.host == url.host,
              let data = message.body as? [String: Any] else { return }
        if data["action"] as? String == "quit" { NSApp.terminate(nil); return }
        if data["action"] as? String == "collapse" {
            waitingForPointerExit = true
            setExpanded(false)
            return
        }
        if let height = data["height"] as? Double, height.isFinite {
            let next = CGFloat(height)
            if abs(desiredHeight - next) > 2 { desiredHeight = next; if expanded && panel.isVisible { animatePanel(open: true) } }
        }
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        webView.evaluateJavaScript("window.setIslandOpen?.(\(expanded ? "true" : "false"));")
    }

    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        let destination = navigationAction.request.url
        decisionHandler(destination?.host == url.host && destination?.port == url.port && destination?.scheme == "http" ? .allow : .cancel)
    }
}

let app = NSApplication.shared
app.setActivationPolicy(.accessory)
guard CommandLine.arguments.count == 2, let url = URL(string: CommandLine.arguments[1]) else { fatalError("Expected the local Artisan server URL") }
let delegate = Island(url: url)
app.delegate = delegate
app.run()
