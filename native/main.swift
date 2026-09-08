import AppKit
import CoreGraphics
import ScreenCaptureKit
import Foundation
import ImageIO
import UniformTypeIdentifiers
import Darwin

struct BridgeError: Error, CustomStringConvertible { let description: String; init(_ message: String) { description = message } }
func output(_ value: [String: Any]) { let data = try! JSONSerialization.data(withJSONObject: value, options: [.sortedKeys]); print(String(data: data, encoding: .utf8)!) }
let application = NSApplication.shared
let argv = Array(CommandLine.arguments.dropFirst())
func option(_ name: String) -> String? { guard let i = argv.firstIndex(of: name), i + 1 < argv.count else { return nil }; return argv[i + 1] }
struct EmulatorTarget {
    let processIdentifier: pid_t
    let application: NSRunningApplication?
    var localizedName: String? { application?.localizedName }
    var isActive: Bool { application?.isActive ?? false }
    func activate(options: NSApplication.ActivationOptions) throws -> Bool {
        guard let application else { throw BridgeError("PCSX2 PID \(processIdentifier) is running but macOS application metadata is unavailable for focus; use --no-focus for PID-scoped input") }
        return application.activate(options: options)
    }
}
func emulator() throws -> EmulatorTarget {
    if let p = option("--pid") {
        guard let pid = Int32(p), pid > 0 else { throw BridgeError("--pid must be a positive process ID") }
        // Validate the live executable without requiring LaunchServices metadata.
        // Same-bundle instances may temporarily lack NSRunningApplication objects.
        // PROC_PIDPATHINFO_MAXSIZE is an expression macro unavailable to Swift.
        var path = [CChar](repeating: 0, count: 4 * Int(MAXPATHLEN))
        guard proc_pidpath(pid, &path, UInt32(path.count)) > 0 else { throw BridgeError("Could not read executable path for PID \(pid): \(String(cString: strerror(errno)))") }
        guard URL(fileURLWithPath: String(cString: path)).lastPathComponent.lowercased() == "pcsx2" else { throw BridgeError("PID \(pid) executable is not PCSX2") }
        return EmulatorTarget(processIdentifier: pid, application: NSRunningApplication(processIdentifier: pid))
    }
    let candidates = NSWorkspace.shared.runningApplications.filter { ($0.bundleIdentifier ?? "").lowercased().contains("pcsx2") || ($0.localizedName ?? "").lowercased().contains("pcsx2") }
    guard !candidates.isEmpty else { throw BridgeError("PCSX2 is not running. Launch the emulator first.") }
    guard candidates.count == 1 else { throw BridgeError("Multiple PCSX2 applications are running; specify --pid for this operation") }
    let app = candidates[0]
    return EmulatorTarget(processIdentifier: app.processIdentifier, application: app)
}
func windows(_ app: EmulatorTarget) -> [[String: Any]] {
    let list = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID) as? [[String: Any]] ?? []
    return list.filter { ($0[kCGWindowOwnerPID as String] as? Int32) == app.processIdentifier && ($0[kCGWindowLayer as String] as? Int) == 0 }.compactMap { w in
        guard let id = w[kCGWindowNumber as String] as? UInt32, let bounds = w[kCGWindowBounds as String] as? [String: Any] else { return nil }
        return ["id": id, "title": w[kCGWindowName as String] as? String ?? "", "bounds": bounds]
    }
}
let keyMap: [String: CGKeyCode] = ["a":0,"s":1,"d":2,"f":3,"h":4,"g":5,"z":6,"x":7,"c":8,"v":9,"b":11,"q":12,"w":13,"e":14,"r":15,"y":16,"t":17,"1":18,"2":19,"3":20,"4":21,"6":22,"5":23,"equal":24,"9":25,"7":26,"minus":27,"8":28,"0":29,"rightbracket":30,"o":31,"u":32,"leftbracket":33,"i":34,"p":35,"enter":36,"return":36,"l":37,"j":38,"quote":39,"k":40,"semicolon":41,"backslash":42,"comma":43,"slash":44,"n":45,"m":46,"period":47,"tab":48,"space":49,"backtick":50,"backspace":51,"escape":53,"command":55,"shift":56,"capslock":57,"alt":58,"option":58,"ctrl":59,"control":59,"rightshift":60,"rightalt":61,"rightctrl":62,"f17":64,"decimal":65,"multiply":67,"plus":69,"clear":71,"divide":75,"numpadenter":76,"subtract":78,"f18":79,"f19":80,"numpad0":82,"numpad1":83,"numpad2":84,"numpad3":85,"numpad4":86,"numpad5":87,"numpad6":88,"numpad7":89,"f20":90,"numpad8":91,"numpad9":92,"f5":96,"f6":97,"f7":98,"f3":99,"f8":100,"f9":101,"f11":103,"f13":105,"f16":106,"f14":107,"f10":109,"f12":111,"f15":113,"home":115,"pageup":116,"delete":117,"f4":118,"end":119,"f2":120,"pagedown":121,"f1":122,"left":123,"right":124,"down":125,"up":126]
func event(_ key: CGKeyCode, down: Bool, pid: pid_t) throws {
    guard let e = CGEvent(keyboardEventSource: CGEventSource(stateID: .hidSystemState), virtualKey: key, keyDown: down) else { throw BridgeError("Could not create keyboard event") }
    e.flags = []
    e.setIntegerValueField(.keyboardEventAutorepeat, value: 0)
    e.postToPid(pid)
}
func release(_ keys: [CGKeyCode], pid: pid_t) { for key in keys.reversed() { try? event(key, down: false, pid: pid) } }
final class ActiveKeys: @unchecked Sendable {
    let lock = NSLock()
    var active: [CGKeyCode] = []
    var finished = false
    let pid: pid_t
    init(pid: pid_t) { self.pid = pid }
    func set(_ key: CGKeyCode, down: Bool) throws {
        lock.lock(); defer { lock.unlock() }
        guard !finished else { throw BridgeError("Input was interrupted") }
        try event(key, down: down, pid: pid)
        if down { if !active.contains(key) { active.append(key) } }
        else { active.removeAll { $0 == key } }
    }
    func clear() { lock.lock(); defer { lock.unlock() }; finished = true; release(active, pid: pid); active = [] }
}
struct BurstSegment: Decodable { let keys: [String]; let frames: Int }
struct BurstPlan {
    let segments: [BurstSegment]
    let codes: [[CGKeyCode]]
    let fps: Double
    var frames: Int { segments.reduce(0) { $0 + $1.frames } }
    init() throws {
        guard let raw = option("--segments"), let data = raw.data(using: .utf8),
              let segments = try? JSONDecoder().decode([BurstSegment].self, from: data),
              (1...6).contains(segments.count), segments.allSatisfy({ (1...120).contains($0.frames) }),
              (1...120).contains(segments.reduce(0, { $0 + $1.frames })) else {
            throw BridgeError("burst requires --segments JSON with 1..6 {keys:[string],frames:int} phases, each positive and total 1..120 frames")
        }
        guard let fps = Double(option("--fps") ?? "59.94"), fps.isFinite, (1...240).contains(fps) else { throw BridgeError("burst --fps must be finite and between 1 and 240") }
        // Only controller bindings are allowed; emulator pause/step/save/load and
        // operating-system shortcuts must never be held as gameplay controls.
        let allowed = Set("w,a,s,d,i,j,k,l,q,e,1,2,3,4,up,down,left,right,enter,return,backspace,t,f,g,h".split(separator: ",").map(String.init))
        self.codes = try segments.map { segment in
            try segment.keys.map { name in
                guard let code = keyMap[name.lowercased()], allowed.contains(name.lowercased()) else { throw BridgeError("burst key is unknown or not a controller binding: \(name)") }
                return code
            }
        }
        self.segments = segments; self.fps = fps
    }
}
final class BurstSession: @unchecked Sendable {
    let lock = NSLock()
    let pid: pid_t
    var held: [CGKeyCode] = []
    var running = false
    var finished = false
    init(pid: pid_t) { self.pid = pid }
    func togglePause() throws {
        try event(49, down: true, pid: pid)
        defer { try? event(49, down: false, pid: pid) }
        usleep(10_000)
    }
    func start(_ keys: [CGKeyCode]) throws -> UInt64 {
        lock.lock(); defer { lock.unlock() }
        guard !finished else { throw BridgeError("Burst interrupted") }
        for key in keys { held.append(key); try event(key, down: true, pid: pid) }
        // Set before posting so cleanup also covers a partially issued toggle.
        running = true
        let started = DispatchTime.now().uptimeNanoseconds
        try togglePause()
        return started
    }
    func transition(_ keys: [CGKeyCode]) throws {
        lock.lock(); defer { lock.unlock() }
        guard !finished else { throw BridgeError("Burst interrupted") }
        for key in held where !keys.contains(key) { try event(key, down: false, pid: pid) }
        held = held.filter { keys.contains($0) }
        for key in keys where !held.contains(key) { held.append(key); try event(key, down: true, pid: pid) }
    }
    func finish() {
        lock.lock(); defer { lock.unlock() }
        guard !finished else { return }
        finished = true
        if running {
            try? togglePause()
            running = false
            // Give the pause event a bounded processing interval before releasing.
            usleep(80_000)
        }
        release(held, pid: pid); held = []
        try? event(49, down: false, pid: pid)
    }
}
func run() async throws {
    guard let command = argv.first else { throw BridgeError("Usage: astra-bridge status|windows|focus|capture|input|step|burst|release [options]") }
    let burstPlan = command == "burst" ? try BurstPlan() : nil
    let app = try emulator()
    switch command {
    case "status": output(["ok":true,"pid":app.processIdentifier,"app":app.localizedName ?? "PCSX2","screenRecording":CGPreflightScreenCaptureAccess(),"accessibility":AXIsProcessTrusted(),"windows":windows(app)])
    case "windows": output(["ok":true,"windows":windows(app)])
    case "focus":
        let activated = try app.activate(options: [.activateAllWindows])
        output(["ok":activated,"pid":app.processIdentifier])
    case "capture":
        guard let path = option("--output") else { throw BridgeError("capture requires --output PATH") }
        let content = try await SCShareableContent.excludingDesktopWindows(true, onScreenWindowsOnly: true)
        let candidates = content.windows.filter { $0.owningApplication?.processID == app.processIdentifier && $0.windowLayer == 0 && $0.frame.width > 1 && $0.frame.height > 1 }
        let target: SCWindow?
        if let rawID = option("--window-id") {
            guard let id = UInt32(rawID) else { throw BridgeError("window-id must be a positive integer") }
            target = candidates.first { $0.windowID == id }
        }
        else { target = candidates.max { $0.frame.width * $0.frame.height < $1.frame.width * $1.frame.height } }
        guard let window = target else { throw BridgeError("No matching visible PCSX2 window") }
        let filter = SCContentFilter(desktopIndependentWindow: window)
        let config = SCStreamConfiguration()
        config.width = Int(window.frame.width)
        config.height = Int(window.frame.height)
        config.showsCursor = false
        config.ignoreShadowsSingleWindow = true
        guard let cropTop = Int(option("--crop-top") ?? "0"), cropTop >= 0, cropTop < config.height else { throw BridgeError("crop-top must be an integer from 0 to window height minus 1") }
        let captured = try await SCScreenshotManager.captureImage(contentFilter: filter, configuration: config)
        guard let image = captured.cropping(to: CGRect(x:0, y:cropTop, width:captured.width, height:captured.height - cropTop)) else { throw BridgeError("Could not crop captured window") }
        let url = URL(fileURLWithPath: path)
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        guard let dest = CGImageDestinationCreateWithURL(url as CFURL, UTType.png.identifier as CFString, 1, nil) else { throw BridgeError("Cannot write PNG destination") }
        CGImageDestinationAddImage(dest, image, nil)
        guard CGImageDestinationFinalize(dest) else { throw BridgeError("PNG write failed") }
        output(["ok":true,"pid":app.processIdentifier,"path":url.path,"windowId":window.windowID,"title":window.title ?? "","width":image.width,"height":image.height,"cropTop":cropTop,"timestamp":ISO8601DateFormatter().string(from:Date())])
    case "burst":
        guard AXIsProcessTrusted() else { throw BridgeError("Accessibility permission is required for burst input") }
        guard let plan = burstPlan else { throw BridgeError("Missing burst plan") }
        let burst = BurstSession(pid: app.processIdentifier)
        signal(SIGINT, SIG_IGN); signal(SIGTERM, SIG_IGN)
        let sources = [SIGINT, SIGTERM].map { sig -> DispatchSourceSignal in
            let source = DispatchSource.makeSignalSource(signal: sig, queue: .global())
            source.setEventHandler { burst.finish(); exit(128 + sig) }
            source.resume(); return source
        }
        defer { burst.finish(); sources.forEach { $0.cancel() } }
        let started = try burst.start(plan.codes[0])
        var cumulativeFrames = 0
        for (index, segment) in plan.segments.enumerated() {
            if index > 0 { try burst.transition(plan.codes[index]) }
            cumulativeFrames += segment.frames
            let deadline = started + UInt64(Double(cumulativeFrames) / plan.fps * 1_000_000_000)
            let now = DispatchTime.now().uptimeNanoseconds
            if now < deadline { try await Task.sleep(nanoseconds: deadline - now) }
        }
        let runningElapsedMs = Double(DispatchTime.now().uptimeNanoseconds - started) / 1_000_000
        burst.finish()
        output(["ok":true,"pid":app.processIdentifier,"frames":plan.frames,"requestedFrames":plan.frames,"fps":plan.fps,"requestedDurationMs":Double(plan.frames) / plan.fps * 1000,"runningElapsedMs":runningElapsedMs,"elapsedMs":Double(DispatchTime.now().uptimeNanoseconds - started) / 1_000_000,"segments":plan.segments.count,"timing":"Approximate wall-time burst; requested frames are not measured emulator frames","pauseToggleSent":true])
    case "input", "step":
        guard AXIsProcessTrusted() else { throw BridgeError("Accessibility permission is required for keyboard input. Enable your terminal/Codex app in System Settings > Privacy & Security > Accessibility.") }
        guard let names = option("--keys") else { throw BridgeError("input requires --keys comma-separated key names") }
        let keys = try names.split(separator:",").map { name -> CGKeyCode in
            guard let key = keyMap[String(name).lowercased()] else { throw BridgeError("Unknown key: \(name)") }; return key
        }
        let frameCount = Int(option("--frames") ?? "1") ?? -1
        let frameInterval = Int(option("--frame-interval-ms") ?? "90") ?? -1
        guard command != "step" || ((1...120).contains(frameCount) && (10...1000).contains(frameInterval)) else { throw BridgeError("frames must be 1..120 and frame-interval-ms 10..1000") }
        guard let frameKey = keyMap[(option("--frame-key") ?? "n").lowercased()] else { throw BridgeError("Unknown frame key") }
        guard command != "step" || !keys.contains(frameKey) else { throw BridgeError("Frame advance key cannot also be held as a control") }
        let active = ActiveKeys(pid: app.processIdentifier)
        let duration = Int(option("--duration-ms") ?? "100") ?? -1
        guard (0...10000).contains(duration) else { throw BridgeError("duration-ms must be an integer from 0 to 10000") }
        if !argv.contains("--no-focus") && (argv.contains("--focus") || command == "step") { _ = try app.activate(options:[.activateAllWindows]); try await Task.sleep(for:.milliseconds(100)) }
        // Defers release for normal exits/errors. Signal handlers release as well.
        signal(SIGINT, SIG_IGN); signal(SIGTERM, SIG_IGN)
        let sources = [SIGINT,SIGTERM].map { sig -> DispatchSourceSignal in
            let s = DispatchSource.makeSignalSource(signal:sig,queue:.global())
            s.setEventHandler { active.clear(); exit(128 + sig) }; s.resume(); return s
        }
        defer { active.clear(); sources.forEach { $0.cancel() } }
        let started = DispatchTime.now().uptimeNanoseconds
        if command == "step" {
            for frame in 0..<frameCount {
                // Qt refocuses the display on resume and may clear keyboard binds.
                // Refresh controller downs between paused frames, before each advance.
                // Key-up occurs while paused; the next simulated frame sees them held.
                if frame > 0 { for key in keys { try active.set(key, down:false) } }
                for key in keys { try active.set(key, down:true) }
                try active.set(frameKey, down:true)
                try await Task.sleep(for:.milliseconds(10))
                try active.set(frameKey, down:false)
                try await Task.sleep(for:.milliseconds(frameInterval))
            }
        } else {
            for key in keys { try active.set(key, down:true) }
            try await Task.sleep(for:.milliseconds(duration))
        }
        active.clear()
        let elapsedMs = Double(DispatchTime.now().uptimeNanoseconds - started) / 1_000_000
        let requestedMs = command == "step" ? frameCount * (frameInterval + 10) : duration
        output(["ok":true,"keys":names,"durationMs":requestedMs,"requestedDurationMs":requestedMs,"elapsedMs":elapsedMs,"frames":command == "step" ? frameCount : 0,"pid":app.processIdentifier])
    case "release":
        let names = option("--keys") ?? "w,a,s,d,i,j,k,l,q,e,1,2,3,4,up,down,left,right,enter,backspace,t,f,g,h"
        let keys = try names.split(separator: ",").map { name -> CGKeyCode in
            guard let key = keyMap[String(name).lowercased()] else { throw BridgeError("Unknown key: \(name)") }; return key
        }
        release(keys,pid:app.processIdentifier)
        output(["ok":true,"pid":app.processIdentifier])
    default: throw BridgeError("Unknown command: \(command)")
    }
}
Task { do { try await run(); exit(0) } catch { output(["ok":false,"error":String(describing:error)]); exit(1) } }
dispatchMain()
