"""证明「不需要外放」：把音频送到一个非默认、没有任何物理扬声器的虚拟设备，
再从它的回环里录——只要能录到，就说明 loopback 抓的是数据流，不是空气。
用法：python test_dev_loopback.py "Steam Streaming Speakers"
"""
import os, sys, threading, time
from _paths import ROOT
import numpy as np
import soundcard as sc
import wave

KW = sys.argv[1] if len(sys.argv) > 1 else "Steam Streaming Speakers"
WAV = os.path.join(ROOT, "model_ja", "2.wav")

spk = None
for s in sc.all_speakers():
    if KW.lower() in s.name.lower():
        spk = s
        break
if spk is None:
    print("找不到输出设备:", KW)
    sys.exit(1)
print("输出设备：", spk.name)


def play():
    with wave.open(WAV, "rb") as w:
        sr, n, ch, sw = w.getframerate(), w.getnframes(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(n)
    a = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        a = a.reshape(-1, ch).mean(axis=1)
    if sr != 48000:
        idx = np.linspace(0, len(a) - 1, int(len(a) * 48000 / sr))
        a = np.interp(idx, np.arange(len(a)), a).astype(np.float32)
    with spk.player(samplerate=48000, channels=1) as p:
        p.play(a)


peak = {"v": 0.0}


def rec():
    mic = sc.get_microphone(spk.name, include_loopback=True)
    with mic.recorder(samplerate=16000) as r:
        t_end = time.time() + 7
        while time.time() < t_end:
            buf = r.record(numframes=1600)
            if buf is None or len(buf) == 0:
                continue
            v = float(np.abs(buf).max())
            peak["v"] = max(peak["v"], v)


tr = threading.Thread(target=rec, daemon=True)
tr.start()
time.sleep(0.8)
th = threading.Thread(target=play, daemon=True)
th.start()
th.join()
tr.join()
print("该设备回环峰值 = %.4f" % peak["v"])
print("结论：", "录到了，不需要外放" if peak["v"] > 0.01 else "没录到（设备可能不产生回环）")
