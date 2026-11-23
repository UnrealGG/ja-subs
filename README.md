# JaSubs

Windows 本地离线的日语视频实时字幕工具。它抓取系统播放音频，经 VAD 整句切分、日语识别和本地 LLM 翻译后，显示「日文原句 + 中文译文」。

## 仓库内容

仓库包含源码、浏览器扩展、桌面启动器源码、测试和文档。以下内容属于本机运行产物，不纳入 Git：

- `.venv/`、`libs/`：Python 运行环境与依赖。
- `model_ja/`、`models/ja-reazon.tar.bz2`：日语识别模型与原始压缩包。
- `installer/wheels/`：离线 wheel 缓存。
- `logs/`、`archive/`：日志和历史归档。
- `JaSubs.exe`、`native/ja_host.exe`：本地编译产物。

`models/vad/silero_vad.onnx` 体积较小，已随仓库提供。

## 从源码准备

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

还需要准备：

- 将 ReazonSpeech 日语 int8 模型放入 `model_ja/`。
- 安装 Ollama，并拉取 `qwen3.5:latest`；显存不足时改用 `qwen2.5:3b`。
- 如需自动启动插件后端，用 `csc` 从 `native/Launcher.cs` 编译 `native/ja_host.exe`。

## 快速开始

桌面字幕：

```powershell
.\start.bat
```

也可以双击本地编译出的 `JaSubs.exe`，在设置面板中选择字幕样式和翻译模型。

浏览器插件：

1. 在 `edge://extensions` 或 `chrome://extensions` 打开开发人员模式。
2. 加载解压缩的扩展，目录选 `ext`。
3. 双击 `setup-native.bat` 注册自动启动器。
4. 打开视频页，在插件弹窗中点击「开启字幕」。

手动启动插件后端：

```powershell
.\start-server.bat
```

## 运行链路

```text
WASAPI 系统回环
  -> Silero VAD 切句
  -> ReazonSpeech 日语 ASR（CPU）
  -> Ollama 日译中（GPU）
  -> 桌面悬浮字幕 / 网页字幕
```

## 目录

- `live_ja.py`：桌面版主程序、识别翻译管线、悬浮字幕。
- `server_ws.py`：插件本地服务；插件自动启动链路会加 `--loopback` 抓系统声音。
- `ext/`：Edge/Chrome Manifest V3 扩展，只负责显示和交互。
- `gui/`、`native/`：Windows 启动器源码与 native messaging host。
- `docs/`：完整方案、开发存档和界面截图。
- `tests/`：手动集成测试、基准和样例字幕。
- `tools/`：模型解压与图标生成工具。
- `installer/`：离线依赖包缓存。
- `logs/`：运行日志。
- `archive/`：历史补丁、旧版插件链路和备份。
- `.venv/`、`libs/`、`model_ja/`、`models/`：运行依赖与模型，不能随意移动。

## 运行要求

- Windows 10/11。
- Python 3.12 虚拟环境 `.venv`，依赖已解压到 `libs`。
- 日语识别模型位于 `model_ja`，VAD 位于 `models/vad`。
- 本机 Ollama 已安装 `qwen3.5:latest`，或使用 `qwen2.5:3b` 轻量模型。
- 程序启动时会自动检查并拉起未运行的 Ollama 服务。
- NVIDIA 显卡建议至少 8GB 显存；3B 模型约需 2GB。

## 说明

- 这是句末翻译，不是逐词流式翻译；一句话结束后通常还要约 1 秒出字幕。
- 连续说话超过约 5 秒时会在当前采样点提前切段，不再等整段结束；可用 `--long-cut` 调整。
- 音频采集始终使用真正的回环端点，以 48kHz 立体声抓取后在软件中降混，避免蓝牙耳机被切到通话单声道。
- 双声道内容会分别识别：左右相同则自动去重，左右不同则同时显示“左/右”两行字幕。
- 浏览器插件抓取整机回环音频，其他软件的声音也可能被识别。
- WASAPI 独占模式、ASIO 播放和部分 DRM 内容无法捕获。
- 当前目录不是可直接分发的单文件版本，迁移时需连同 `.venv`、`libs`、`model_ja` 和 `models` 一起保留。

详细设计与实测记录见 `docs/方案.md`。
