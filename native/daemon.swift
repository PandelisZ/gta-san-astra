import AppKit
import CoreGraphics
import ScreenCaptureKit
import Foundation
import ImageIO
import UniformTypeIdentifiers

struct BridgeError: Error, CustomStringConvertible { let description: String; init(_ message: String) { description = message } }
var operationResult: [String: Any] = [:]
func output(_ value: [String: Any]) { operationResult = value }
let application = NSApplication.shared
application.setActivationPolicy(.prohibited)
var argv: [String] = []
func option(_ name: String) -> String? { guard let i = argv.firstIndex(of: name), i + 1 < argv.count else { return nil }; return argv[i + 1] }
func emulator() throws -> NSRunningApplication {
    if let p = option("--pid") {
        guard let pid = Int32(p), let app = NSRunningApplication(processIdentifier: pid), (app.bundleIdentifier ?? "").lowercased().contains("pcsx2") || (app.localizedName ?? "").lowercased().contains("pcsx2") else { throw BridgeError("--pid must identify a running PCSX2 application") }
        return app
    }
    let candidates = NSWorkspace.shared.runningApplications.filter { ($0.bundleIdentifier ?? "").lowercased().contains("pcsx2") || ($0.localizedName ?? "").lowercased().contains("pcsx2") }
    guard !candidates.isEmpty else { throw BridgeError("PCSX2 is not running. Launch the emulator first.") }
    guard candidates.count == 1 else { throw BridgeError("Multiple PCSX2 applications are running; specify --pid for this operation") }
    let app = candidates[0]
    return app
}
func windows(_ app: NSRunningApplication) -> [[String: Any]] {
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
func run() async throws {
    guard let command = argv.first else { throw BridgeError("Usage: astra-bridge status|windows|focus|capture|input|step|release [options]") }
    let app = try emulator()
    switch command {
    case "status": output(["ok":true,"pid":app.processIdentifier,"app":app.localizedName ?? "PCSX2","screenRecording":CGPreflightScreenCaptureAccess(),"accessibility":AXIsProcessTrusted(),"windows":windows(app)])
    case "windows": output(["ok":true,"windows":windows(app)])
    case "focus":
        let activated = app.activate(options: [.activateAllWindows])
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
        try session.register(active)
        defer { active.clear(); session.unregister(active) }
        if !argv.contains("--no-focus") && (argv.contains("--focus") || command == "step") && !app.isActive {
            _ = app.activate(options:[.activateAllWindows])
            try await Task.sleep(for:.milliseconds(100))
        }
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

// Session shutdown can run on the stdin/signal thread while an action is awaiting.
final class Session: @unchecked Sendable {
    let lock = NSLock()
    var active: ActiveKeys?
    var closed = false
    func register(_ keys: ActiveKeys) throws {
        lock.lock(); defer { lock.unlock() }
        guard !closed else { throw BridgeError("Daemon stdin closed") }
        active = keys
    }
    func unregister(_ keys: ActiveKeys) {
        lock.lock(); defer { lock.unlock() }
        if active === keys { active = nil }
    }
    func interrupt() {
        lock.lock(); let keys = active; lock.unlock()
        keys?.clear()
    }
    func close() {
        lock.lock(); closed = true; let keys = active; lock.unlock()
        keys?.clear()
    }
    func isClosed() -> Bool { lock.lock(); defer { lock.unlock() }; return closed }
}
let session = Session()
func writeResponse(_ response: [String: Any]) {
    let data = try! JSONSerialization.data(withJSONObject: response, options: [.sortedKeys])
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write(Data([10]))
}
func requestArguments(_ request: [String: Any]) throws -> [String] {
    guard let op = request["op"] as? String,
          ["status", "windows", "focus", "capture", "input", "step", "release"].contains(op) else {
        throw BridgeError("op must be status, windows, focus, capture, input, step, or release")
    }
    let allowed: Set<String> = ["id", "op", "keys", "duration_ms", "frames", "frame_interval_ms", "frame_key", "output", "crop_top", "window_id", "pid", "focus", "no_focus"]
    guard Set(request.keys).isSubset(of: allowed) else { throw BridgeError("Unknown request field") }
    var args = [op]
    if let value = request["keys"] {
        if let keys = value as? [String] { args += ["--keys", keys.joined(separator:",")] }
        else if let keys = value as? String { args += ["--keys", keys] }
        else { throw BridgeError("keys must be a string array or comma-separated string") }
    } else if op == "input" || op == "step" { args += ["--keys", ""] }
    for field in ["duration_ms", "frames", "frame_interval_ms", "crop_top", "window_id", "pid"] {
        if let value = request[field] {
            guard let n = value as? NSNumber, CFGetTypeID(n) != CFBooleanGetTypeID(),
                  n.doubleValue.isFinite, n.doubleValue.rounded() == n.doubleValue,
                  abs(n.doubleValue) < 9_007_199_254_740_992 else { throw BridgeError("\(field) must be an integer") }
            args += ["--" + field.replacingOccurrences(of:"_",with:"-"), n.stringValue]
        }
    }
    for field in ["frame_key", "output"] {
        if let value = request[field] {
            guard let text = value as? String else { throw BridgeError("\(field) must be a string") }
            args += ["--" + field.replacingOccurrences(of:"_",with:"-"), text]
        }
    }
    for field in ["focus", "no_focus"] {
        if let focus = request[field] {
            guard let value = focus as? NSNumber, CFGetTypeID(value) == CFBooleanGetTypeID() else { throw BridgeError("\(field) must be boolean") }
        }
    }
    if request["no_focus"] as? Bool == true { args += ["--no-focus"] }
    if (request["focus"] as? Bool ?? true) && op == "input" { args += ["--focus"] }
    return args
}
let signalSources: [DispatchSourceSignal] = [SIGINT, SIGTERM].map { sig in
    signal(sig, SIG_IGN)
    let source = DispatchSource.makeSignalSource(signal:sig, queue:.global())
    source.setEventHandler { session.close(); exit(128 + sig) }
    source.resume()
    return source
}
var streamContinuation: AsyncStream<String>.Continuation!
let requests = AsyncStream<String> { continuation in streamContinuation = continuation }
DispatchQueue.global().async {
    while let line = readLine() {
        // An emergency release request interrupts active holds before it is processed.
        if let data = line.data(using:.utf8), let request = try? JSONSerialization.jsonObject(with:data) as? [String:Any], request["op"] as? String == "release" {
            session.interrupt()
        }
        streamContinuation.yield(line)
    }
    session.close()
    streamContinuation.finish()
    exit(0)
}
Task {
    for await line in requests {
        if session.isClosed() { break }
        let started = DispatchTime.now().uptimeNanoseconds
        var id: Any = NSNull()
        do {
            guard let data = line.data(using:.utf8), let request = try JSONSerialization.jsonObject(with:data) as? [String:Any] else { throw BridgeError("Request must be a JSON object") }
            id = request["id"] ?? NSNull()
            argv = try requestArguments(request)
            operationResult = [:]
            try await run()
            var response = operationResult
            response["id"] = id
            response["request_elapsed_ms"] = Double(DispatchTime.now().uptimeNanoseconds - started) / 1_000_000
            writeResponse(response)
        } catch {
            writeResponse(["id":id,"ok":false,"error":String(describing:error)])
        }
    }
    session.close()
    exit(0)
}
dispatchMain()
