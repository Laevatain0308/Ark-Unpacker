<!-- Welcome to the Ark-Unpacker documentation -->
<!-- Repository: https://github.com/isHarryh/Ark-Unpacker -->

<!--suppress HtmlDeprecatedAttribute -->
<div align="center" style="text-align:center">
   <h1> Ark-Unpacker </h1>
   <img alt="ArkUnpacker icon" width="64" src="https://raw.githubusercontent.com/isHarryh/Ark-Unpacker/v3.x/ArkUnpacker.ico"/>
   <p>
      Arknights Assets Unpacker | Arknights game asset batch unpacker <br>
      <code><b> v5.0 </b></code>
   </p>
   <p>
      <img alt="GitHub Top Language" src="https://img.shields.io/github/languages/top/isHarryh/Ark-Unpacker?label=Python">
      <img alt="GitHub License" src="https://img.shields.io/github/license/isHarryh/Ark-Unpacker?label=License"/>
      <img alt="Code Factor Grade" src="https://img.shields.io/codefactor/grade/github/isHarryh/Ark-Unpacker?label=CodeFactor">
      <img alt="GitHub Actions" src="https://github.com/isHarryh/Ark-Unpacker/actions/workflows/build.yml/badge.svg">
      <img alt="GitHub Downloads" src="https://img.shields.io/github/downloads/isHarryh/Ark-Unpacker/total?label=Downloads">
   </p>
      
   **English** **|** [🇨🇳中文](./README.md)

</div>

## Introduction

### End-of-Updates Notice

This project is being gradually upgraded and migrated to [ArkStudio](https://github.com/isHarryh/Ark-Studio). Stay tuned.

> [!NOTE]
> ArkStudio is currently under development and will be a more powerful integrated management platform for Arknights game assets. Once completed, this project will reach end of life and stop receiving updates. Thank you for your continued support and enthusiasm.

### Features Implemented

1. Batch unpack game asset objects from Arknights Unity AssetBundle (AB) files.
   1. Supports the special decompression algorithm for game versions v2.5.04 and above;
   2. Can distinguish Spine model files for base chibi, dynamic portraits, and battle chibi during unpacking;
   3. Can store files in separate directories named after their source AB files during unpacking.
2. Batch merge RGB channel images and Alpha channel images.
3. Batch decode FlatBuffers data files.
4. Provides both an interactive CLI and direct command-line execution.

### Supported Types

| Type      | Description           | Export Format |
| :-------- | :-------------------- | :------------ |
| Sprite    | Sprite image          | PNG image     |
| Texture2D | 2D texture image      | PNG image     |
| AudioClip | Audio clip            | WAV audio     |
| TextAsset | Text or binary data   | Unspecified   |
| Mesh      | 3D model              | OBJ file      |
| Shader    | Reconstructed Unity Shader text | `.shaderlab.txt` |
| TypeTree  | Object structure      | JSON file     |

With `--shader`, Ark-Unpacker reconstructs the available ShaderLab structure and writes it as text. Platform asset bundles often retain only compiled data, so the result is intended for analysis and is not guaranteed to compile as the original shader source.

### Stored Shader platform programs

Use `--shader-programs` independently of `--shader`, enter `p` in the interactive AB menu, or enable “导出 Shader 平台程序” in the native macOS GUI.

```shell
python Main.py -m ab -i /path/to/stylizedwater.ab -o /path/to/output --shader-programs
python Main.py -m ab -i /path/to/shaders -o /path/to/output --shader --shader-programs -g
```

Each Shader gets a stable `<safe-name>__<PathID>__<source-hash>.programs/` directory containing `manifest.json`, individual GLSL files such as `p0_9_blob000024_s0.glsl`, and binary payloads such as `p1_18_blob000024_s0.bin`. Extraction uses platform segment arrays, the versioned entry table, and UnityPy's `ShaderSubProgram` parser; it never locates code by scanning printable strings or searching for `#version`.

GLSL files preserve the exact stored program bytes. Programs containing both VERTEX and FRAGMENT guards are marked `payload_stage: combined`; their conditional structure is preserved without splitting. Vulkan `.bin` files are marked `unity-vulkan-payload`, since they may contain Unity headers and SMOL-V compressed modules rather than standalone SPIR-V. Other parsed binary programs are also saved intact.

The manifest records the Shader name, Unity version, bundle/CAB/PathID, platform enum, compression segments, entry and code offsets, GPU type, all SubShader/Pass/variant references, keywords, actual relative output paths, and SHA-256. `references[].stage` is the serialized stage slot; it may differ from `payload_stage`. Code offsets are relative to decompressed segments. Parameter entries are listed separately and are not exported as executable programs. The existing filesystem guard handles deduplication and collisions; manifests reference the actual saved/reused files.

Unity 2021.2+ indices are resolved against `m_KeywordNames`, including `m_PlayerSubPrograms`. Ambiguous platform associations remain in `unresolved_references` with diagnostics rather than being guessed. Earlier versions preserve global/local indices and embedded program keyword names without inventing missing index/name mappings. Both flat/nested compression arrays and the pre/post-2019.3 entry tables are supported. Unsupported layouts, malformed segments/programs and invalid keyword indices produce specific diagnostics without stopping other programs. Legacy `m_SubProgramBlob`/script-only layouts are not supported by this option; `--shader` retains its behavior.

**This exports stored platform programs, not original HLSL. Text is not guaranteed to recompile.** No SPIR-V/SMOL-V decompiler or Metal/DXBC disassembler is included.

Run `python -m unittest discover -s test -p test_shader_programs.py -v`; set `ARK_SHADER_SAMPLE=/path/to/stylizedwater.ab` to enable the real sample acceptance test. Its 32 combined GLES programs and BlobIndex range are sample assertions, not extraction rules.

### Related Docs

- Changelog > [Click here](./CHANGELOG.md)
- Configuration guide > [Click here](docs/en/ConfigFile.md)
- Asset lookup guide > [Click here](docs/en/AssetsGuide.md)
- Native macOS GUI > [View](./README-macOS.md)

## Usage

### 1. Asset Preparation

Whether you want to use our release build or the source code to unpack Arknights assets, you must first obtain the Arknights asset files. Arknights is built with Unity, and all game assets are packaged into **AssetBundle files** (with the `.ab` extension, referred to as "AB files" below, though in rare cases the extension is `.bin`).

<details>
<summary>📱 Android asset acquisition (expand to read)</summary>

The following explains **how to obtain Arknights AB files** using **Android** as an example. Android game assets have **two parts**:

- One part is provided by the **installation package** (`.apk`). Download it from the [Arknights official site](https://ak.hypergryph.com), open it with a compression tool (rename the extension to `.zip` before opening), then extract the `assets/AB/Android` folder;

- The other part is provided by **hot updates**. First ensure the game is updated to the latest version on your phone. Then (USB cable recommended) copy the `Android/data/com.hypergryph.arknights/files/Bundles` folder from your phone storage to your PC (rename it to `Android(2)`).

> [!TIP]
> For emulator users, you can use the emulator's file sharing feature to copy the folder directly to your PC. If you are familiar with ADB tools, you can also use ADB to copy these files.

At this point, your directory structure looks roughly like this:

```
Your directory
├─Android
└─Android(2)
```

Finally, copy the contents of `Android(2)` into `Android` and **overwrite** files with the same name to obtain the complete game assets. After that, you can use our program to unpack the assets.

Of course, you can also copy out some folders from `Android` to process specific assets only.

</details>

<details>
<summary>💻 PC asset acquisition (expand to read)</summary>

The following explains **how to obtain Arknights AB files** using **Windows** as an example. Steps:

1. Go to the [Arknights official site](https://ak.hypergryph.com) to download and install the Hypergryph launcher.
2. In the launcher, download the Arknights PC client. Then launch the game and complete the in-game hot update.
3. Close the game and return to the launcher, click the menu button at the bottom right, go to "Game Settings", then click "Open Folder" in the "Game Install Path" section.
4. In the `Arknights_Data` folder, `StreamingAssets/AB/Windows` contains the **initial resources** for the PC client, and `PersistentData/Bundles` contains the **hot update resources**.
5. Follow the Android asset acquisition approach to consolidate the assets.

</details>

<br>

To help you locate specific asset AB files, we have summarized and listed the contents stored in each subdirectory. Browse [this document](docs/en/AssetsGuide.md) for details. Note that the content of this document may not be up to date.

### 2. Download ArkUnpacker

To make it easier for general users, we provide an executable for Windows 64-bit (other operating systems are not supported yet).

Please download the exe file `ArkUnpacker-vx.x.x_x64.exe` from the Releases page: [Go to download](https://github.com/isHarryh/Ark-Unpacker/releases)

### 3. Prerequisites

Before using this program, you should have a basic understanding of:

- [RGB channel images and A channel images](docs/en/Essentials.md#rgb-channels-and-alpha-channel-images)
- [Spine animated characters](docs/en/Essentials.md#spine-animated-characters)

### 4. Example Usage

The simplest usage is to place the folder(s) to be unpacked (one or more) into the same directory as the program. At this point, the directory structure looks like this:

```
Your directory
├─Android (Unpacking the entire directory may take a long time)
├─chararts (You can choose to unpack specific subfolders)
└─ArkUnpacker.exe
```

Then run the program directly. It will open an interactive CLI, and you can follow the prompts.

> [!TIP]
> After running, the working directory will generate a configuration file `ArkUnpackerConfig.json` and a log file `ArkUnpackerLogs.log`. For configuration field descriptions, see [this document](docs/en/ConfigFile.md).

### 5. Overview of Each Mode

#### One-click Execution

Directly unpacks files in the program directory and performs image merging. Unpacked files are exported to the `Unpacked_xxxx` folder by default, and merged images are exported to the `Combined_xxxx` folder by default.

> [!WARNING]
> It is not recommended to use this feature to unpack the **entire** game asset directory. This may take a long time and consume significant system resources. It is recommended to use this feature only on partial folders, or use custom modes to unpack specific folders.

#### Custom Asset Unpacking

Unpack game assets from the specified path and export to the specified output directory. You can choose which asset types to export.

#### Custom Image Merging

Merge RGB images and Alpha images from the specified path, and export the merged results to the specified output directory.

#### Custom Text Data Decoding

Decode data files in the specified directory and export the decoded results to the specified output directory. For details, see [this document](docs/en/TextAssetsDecoding.md).

#### Custom Spine Model Export

Unpack game assets from the specified path and export Spine animated character models to the specified output directory.

#### Custom Criware USM Audio/Video Extraction

Unpack Criware USM files (usually containing cutscenes) from the specified path and export the included audio/video files to the specified output directory.

#### ArkModels Extraction and Sorting Tool

This is a custom feature. See [this document](docs/en/ArkModelsRepoKit.md) for details.

#### ArkVoice Extraction and Sorting Tool

This is a custom feature. See [this document](docs/en/ArkVoiceRepoKit.md) for details.

### 6. Command-line Usage

In addition to the **interactive** CLI shown above, the program also supports running **directly** via the command line for users who prefer it. Parameters are as follows:

```
usage: ArkUnpacker [-h] [-v] [-m {ab,cb,fb,sp,cu}] [-i INPUT] [-o OUTPUT] [-d]
                   [--image] [--text] [--audio] [--spine] [--mesh] [--typetree] [--shader] [--shader-programs] [-g]
                   [--no-video] [--no-audio] [-l {0,1,2,3,4}]

Arknights Assets Unpacker. Use no argument to run to enter the interactive CLI mode.

options:
  -h, --help            show this help message and exit
  -v, --version         show a version message and exit
  -m {ab,cb,fb,sp,cu}, --mode {ab,cb,fb,sp,cu}
                        working mode, ab=resolve-ab, cb=combine-image, fb=decode-flatbuffers, sp=resolve-spine, cu=resolve-usm
  -i INPUT, --input INPUT
                        source file or directory path
  -o OUTPUT, --output OUTPUT
                        destination directory path
  -d, -delete           delete the existed destination directory first
  --image               in resolve ab mode: export image files
  --text                in resolve ab mode: export text or binary files
  --audio               in resolve ab mode: export audio files
  --spine               in resolve ab mode: export spine asset files
  --mesh                in resolve ab mode: export mesh resources
  --typetree            in resolve ab mode: export typetree JSON files
  --shader              in resolve ab mode: reconstruct Shader objects as ShaderLab text
  --shader-programs     in resolve ab mode: export stored GPU programs and variant metadata
  -g, --group           in resolve ab mode: group files into separate directories named by their source ab file
  --no-video            in resolve usm mode: skip video processing
  --no-audio            in resolve usm mode: skip audio processing
  -l {0,1,2,3,4}, --logging-level {0,1,2,3,4}
                        logging level, 0=none, 1=error, 2=warn, 3=info, 4=debug
```

Run `ArkUnpacker -h` to display this help message. If you run a command without any `mode` parameter, the program will start in interactive CLI mode.

## Notes

1. In one-click execution mode, the program will not unpack AB files located directly in the program directory; it only unpacks AB files inside subfolders.
2. The program automatically adjusts its multiprocessing strategy based on the number of CPU cores, and it requires sufficient device performance (especially CPU and disk). Low-spec machines may run slowly.
3. Windows command line basics:
   1. Shortcut `Ctrl+C` forcibly terminates the program. To copy text, use your mouse to select the text first, then press this shortcut.
   2. Left-clicking the console enters "text selection" mode, and the main process will pause.
   3. Right-clicking the console pastes text and can also exit "text selection" mode.
   4. Drag-and-drop files into the console to quickly paste their path.
4. If you want more details or to contribute, please [see the developer guide](docs/en/ForDevelopers.md).

## Licensing

This project is licensed under the **BSD-3-Clause** license. Anyone may freely use and modify the source code in this project, provided that the author credit and original license are retained in the source code or copyright notices, and the project name or author name must not be used for promotion.

-----

<div align="center">
    <p><i>GitHub Stars History Chart</i></p>
    <a href="https://starchart.cc/isHarryh/Ark-Unpacker">
       <img alt="Stars Chart" src="https://starchart.cc/isHarryh/Ark-Unpacker.svg?variant=adaptive">
    </a>
</div>
