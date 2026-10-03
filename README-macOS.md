# Ark-Unpacker macOS 原生应用

这是 Ark-Unpacker v5.2.0 的 Apple Silicon 原生 macOS 图形应用。用户通过窗口选择输入路径、输出目录、处理模式和导出选项；原项目的处理引擎作为应用内部组件运行，不需要打开 Terminal 或输入命令。

## 使用

1. 双击 `ArkUnpacker-v5.2.0.app`。
2. 在“输入路径”中选择资源文件或目录，在“输出文件夹”中选择导出位置。
3. 选择工作模式：AB 解包资源、CB 合并图片、FB 解码文本、Spine 导出模型或 USM 转换媒体。
4. 按需要勾选模式选项，点击“开始处理”。AB 模式的“导出 Shader”会生成用于拆解分析的 `.shaderlab.txt` 重建文本；由于包体通常只保留平台编译数据，文本不保证能直接重新编译。处理输出和错误信息会显示在窗口日志区域；处理期间可以点击“取消”。

`Run-ArkUnpacker.command` 现在也只负责打开图形应用，适合 macOS 没有自动识别 `.app` 的情况。`dist/ArkUnpacker-v5.2.0` 是随包的底层处理引擎，通常不需要直接运行。

## FFmpeg

USM 转换需要系统中的 FFmpeg。启动应用时会自动搜索 `/opt/homebrew/bin`、`/usr/local/bin` 和系统 PATH。若 USM 模式提示 FFmpeg 不可用，请先安装 FFmpeg。

上游默认音频编码器是 `libvorbis`。macOS Homebrew 的 FFmpeg 有时不包含该编码器，应用会自动回退到可用的 `libopus`，不影响 USM 视频和音频转换流程。

## 构建与验证

应用入口源码位于 `source/macos/ArkUnpackerGUI.swift`，底层引擎和原项目源码位于 `source/`。本机 Apple Silicon 构建结果为 `arm64`，最低目标 macOS 12.0。

项目自带 AB、CB、FB、Spine、USM 测试全部通过；打包后的底层引擎也实际验证了 FB 解码、AB 音频导出和 USM 视频转换。

应用未进行 Apple 开发者签名或公证。首次从 Finder 打开时若系统显示安全提示，请右键应用选择“打开”，或在“系统设置 → 隐私与安全性”中允许。
