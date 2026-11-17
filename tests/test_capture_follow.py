"""验证改造后的 capture_loopback：默认设备能抓、非零、不死循环。"""
import os, sys, threading, time, wave
from _paths import ROOT
import numpy as np
import soundcard as sc
import live_ja as L

peak = {"v": 0.0, "n": 0}


def play():
    time.sleep(1.0)
    spk = sc.default_speaker()
    with wave.open(os.path.join(ROOT, "model_ja", "2.wav"), "rb") as w:
        sr, n, ch, sw = w.getframerate(), w.getnframes(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(n)
    a = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        a = a.reshape(-1, ch).mean(axis=1)
    idx = np.linspace(0, len(a) - 1, int(len(a) * 48000 / sr))
    a = np.interp(idx, np.arange(len(a)), a).astype(np.float32)
    with spk.player(samplerate=48000, channels=1) as p:
        p.play(a)


threading.Thread(target=play, daemon=True).start()
t0 = time.time()
for x in L.capture_loopback(None):
    peak["n"] += 1
    v = float(np.abs(x).max()) if len(x) else 0.0
    peak["v"] = max(peak["v"], v)
    if time.time() - t0 > 8:
        break
print("块数=%d 峰值=%.4f 用时=%.1fs" % (peak["n"], peak["v"], time.time() - t0))
print("结论：", "OK" if peak["v"] > 0.01 else "没抓到声音")
