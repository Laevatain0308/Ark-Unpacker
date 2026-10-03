import AppKit
import Foundation

func shellQuote(_ value: String) -> String {
    "'" + value.replacingOccurrences(of: "'", with: "'\\''") + "'"
}

func appleScriptQuote(_ value: String) -> String {
    value
        .replacingOccurrences(of: "\\", with: "\\\\")
        .replacingOccurrences(of: "\"", with: "\\\"")
        .replacingOccurrences(of: "\n", with: "\\n")
}

let launcherURL = URL(fileURLWithPath: CommandLine.arguments[0]).standardizedFileURL
let appRoot = launcherURL
    .deletingLastPathComponent() // Contents/MacOS -> Contents
    .deletingLastPathComponent() // Contents -> .app
    .deletingLastPathComponent()
let commandURL = appRoot.appendingPathComponent("Run-ArkUnpacker.command")
let binaryURL = appRoot.appendingPathComponent("dist/ArkUnpacker-v5.2.0")

let command = "export PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH; cd \(shellQuote(appRoot.path)); exec \(shellQuote(binaryURL.path))"
let scriptSource = """
tell application \"Terminal\"
    activate
    do script \"\(appleScriptQuote(command))\"
end tell
"""

var scriptError: NSDictionary?
if let script = NSAppleScript(source: scriptSource) {
    script.executeAndReturnError(&scriptError)
}

if scriptError != nil {
    // Fall back to LaunchServices if Terminal automation is unavailable.
    NSWorkspace.shared.open(commandURL)
}
