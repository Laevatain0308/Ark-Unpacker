import SwiftUI
import AppKit
import Combine

final class AppModel: NSObject, ObservableObject {
    @Published var inputPath = ""
    @Published var outputPath = ""
    @Published var selectedMode = "ab"
    @Published var deleteOutput = false
    @Published var exportImage = true
    @Published var exportText = true
    @Published var exportAudio = true
    @Published var exportSpine = false
    @Published var exportMesh = false
    @Published var exportShader = false
    @Published var exportTypetree = false
    @Published var groupByBundle = true
    @Published var skipVideo = false
    @Published var skipAudio = false
    @Published var log = ""
    @Published var status = "就绪"
    @Published var isRunning = false

    private var process: Process?
    private var outputPipe: Pipe?

    let modes: [(String, String)] = [
        ("ab", "AB 解包资源"),
        ("cb", "CB 合并图片"),
        ("fb", "FB 解码文本"),
        ("sp", "Spine 导出模型"),
        ("cu", "USM 转换媒体")
    ]

    func chooseInput() {
        let panel = NSOpenPanel()
        panel.title = "选择输入文件或文件夹"
        panel.canChooseFiles = true
        panel.canChooseDirectories = true
        panel.allowsMultipleSelection = false
        panel.begin { [weak self] response in
            guard response == .OK, let url = panel.url else { return }
            DispatchQueue.main.async { self?.inputPath = url.path }
        }
    }

    func chooseOutput() {
        let panel = NSOpenPanel()
        panel.title = "选择输出文件夹"
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.canCreateDirectories = true
        panel.allowsMultipleSelection = false
        panel.begin { [weak self] response in
            guard response == .OK, let url = panel.url else { return }
            DispatchQueue.main.async { self?.outputPath = url.path }
        }
    }

    func start() {
        guard !inputPath.isEmpty, !outputPath.isEmpty else {
            status = "请先选择输入路径和输出文件夹"
            return
        }
        guard let core = Bundle.main.url(forResource: "ArkUnpacker-v5.2.0", withExtension: nil) else {
            status = "应用内部处理引擎缺失"
            return
        }

        var args = ["-m", selectedMode, "-i", inputPath, "-o", outputPath]
        if deleteOutput { args.append("-d") }
        switch selectedMode {
        case "ab":
            if exportImage { args.append("--image") }
            if exportText { args.append("--text") }
            if exportAudio { args.append("--audio") }
            if exportSpine { args.append("--spine") }
            if exportMesh { args.append("--mesh") }
            if exportShader { args.append("--shader") }
            if exportTypetree { args.append("--typetree") }
            if groupByBundle { args.append("-g") }
        case "cu":
            if skipVideo { args.append("--no-video") }
            if skipAudio { args.append("--no-audio") }
        default:
            break
        }

        let support = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("ArkUnpacker", isDirectory: true)
        try? FileManager.default.createDirectory(at: support, withIntermediateDirectories: true)

        log = ""
        status = "处理中…"
        isRunning = true

        let pipe = Pipe()
        outputPipe = pipe
        let task = Process()
        task.executableURL = core
        task.arguments = args
        task.currentDirectoryURL = support
        var environment = ProcessInfo.processInfo.environment
        environment["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:" + (environment["PATH"] ?? "")
        task.environment = environment
        task.standardOutput = pipe
        task.standardError = pipe
        pipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            guard !data.isEmpty else { return }
            let text = String(decoding: data, as: UTF8.self)
            DispatchQueue.main.async { self?.log.append(text) }
        }
        task.terminationHandler = { [weak self] finished in
            DispatchQueue.main.async {
                self?.outputPipe?.fileHandleForReading.readabilityHandler = nil
                self?.outputPipe = nil
                self?.process = nil
                self?.isRunning = false
                self?.status = finished.terminationStatus == 0 ? "处理完成" : "处理失败（退出码 \(finished.terminationStatus)）"
            }
        }
        process = task
        do {
            try task.run()
        } catch {
            isRunning = false
            process = nil
            status = "无法启动处理引擎：\(error.localizedDescription)"
        }
    }

    func cancel() {
        process?.terminate()
        status = "正在取消…"
    }
}

struct PathRow: View {
    let title: String
    @Binding var path: String
    let action: () -> Void

    var body: some View {
        HStack(spacing: 10) {
            Text(title).frame(width: 92, alignment: .leading)
            TextField("请选择路径", text: $path)
                .textFieldStyle(.roundedBorder)
            Button("选择…", action: action)
        }
    }
}

struct ContentView: View {
    @ObservedObject var model: AppModel

    private let columns = [GridItem(.adaptive(minimum: 155), alignment: .leading)]

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Ark Unpacker").font(.system(size: 26, weight: .semibold))
                    Text("明日方舟资源处理工具").foregroundStyle(.secondary)
                }
                Spacer()
                Text(model.status).foregroundStyle(model.isRunning ? .blue : .secondary)
            }

            GroupBox {
                VStack(spacing: 12) {
                    PathRow(title: "输入路径", path: $model.inputPath, action: model.chooseInput)
                    PathRow(title: "输出文件夹", path: $model.outputPath, action: model.chooseOutput)
                }
                .padding(4)
            }

            HStack(spacing: 18) {
                Picker("工作模式", selection: $model.selectedMode) {
                    ForEach(model.modes, id: \.0) { mode in
                        Text(mode.1).tag(mode.0)
                    }
                }
                .frame(width: 230)
                Toggle("清理已有输出", isOn: $model.deleteOutput)
            }

            if model.selectedMode == "ab" {
                GroupBox("AB 解包选项") {
                    LazyVGrid(columns: columns, alignment: .leading, spacing: 9) {
                        Toggle("导出图片", isOn: $model.exportImage)
                        Toggle("导出文本", isOn: $model.exportText)
                        Toggle("导出音频", isOn: $model.exportAudio)
                        Toggle("导出 Spine", isOn: $model.exportSpine)
                        Toggle("导出 Mesh", isOn: $model.exportMesh)
                        Toggle("导出 Shader", isOn: $model.exportShader)
                        Toggle("导出类型树", isOn: $model.exportTypetree)
                        Toggle("按资源包分组", isOn: $model.groupByBundle)
                    }
                    .padding(4)
                }
            } else if model.selectedMode == "cu" {
                GroupBox("USM 选项") {
                    HStack(spacing: 24) {
                        Toggle("跳过视频", isOn: $model.skipVideo)
                        Toggle("跳过音频", isOn: $model.skipAudio)
                    }
                    .padding(4)
                }
            }

            HStack {
                Button(model.isRunning ? "处理中…" : "开始处理") { model.start() }
                    .keyboardShortcut(.defaultAction)
                    .disabled(model.isRunning)
                Button("取消") { model.cancel() }
                    .disabled(!model.isRunning)
                Spacer()
                Button("清空日志") { model.log = "" }
                    .disabled(model.isRunning)
            }

            TextEditor(text: $model.log)
                .font(.system(.body, design: .monospaced))
                .background(Color(nsColor: .textBackgroundColor))
                .overlay(RoundedRectangle(cornerRadius: 6).stroke(Color(nsColor: .separatorColor)))
                .frame(minHeight: 250)
        }
        .padding(20)
        .frame(minWidth: 760, minHeight: 620)
    }
}

final class ArkUnpackerAppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        NSApp.activate(ignoringOtherApps: true)
    }
}

@main
struct ArkUnpackerGUIApp: App {
    @NSApplicationDelegateAdaptor(ArkUnpackerAppDelegate.self) private var appDelegate
    @StateObject private var model = AppModel()

    var body: some Scene {
        WindowGroup("Ark Unpacker") {
            ContentView(model: model)
        }
    }
}
