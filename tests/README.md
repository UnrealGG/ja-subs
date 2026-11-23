# 测试与基准

这些脚本是手动集成测试，不是单元测试。部分脚本会实际播放音频、抓取系统回环或调用 Ollama，运行前请确认对应设备和模型已就绪。

从项目根目录运行，例如：

```powershell
.venv\Scripts\python.exe tests\test_asr.py
.venv\Scripts\python.exe tests\test_mt.py
.venv\Scripts\python.exe tests\bench_pipe.py model_ja\1.wav
```

常用脚本：

- `test_asr.py`：日语识别速度与准确率
- `test_mt.py`、`bench_mt.py`：翻译模型质量与延迟
- `test_loopback.py`、`test_capture_follow.py`：回环采集与设备跟随
- `test_loopback_select.py`：确认默认设备是回环端点，而不是同名麦克风
- `test_stereo_channels.py`：左右声道分别识别；相同内容自动去重
- `test_model_switch.py`、`test_ws_client.py`：插件后端协议
- `test_overlay_check.py`、`test_overlay_opts.py`、`probe_overlay.py`、`gui_probe.py`：悬浮字幕样式与交互

`samples/` 存放历史输出样例。
