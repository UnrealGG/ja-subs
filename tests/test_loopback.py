"""端到端验证：服务端 --loopback 抓系统声音 → /subs 出字幕。
用法：先起服务，再跑本脚本（默认会外放 model_ja/1.wav）。"""
import io, json, os, sys, time, threading, urllib.request
from _paths import ROOT
import numpy as np
import soundcard as sc
import wave

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8790
WAV = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "model_ja", "1.wav")
BASE = "http://127.0.0.1:%d" % PORT


def poll(since=0):
    with urllib.request.urlopen(BASE + "/subs?since=%d" % since, timeout=3) as r:
        return json.loads(r.read().decode("utf-8"))


def play(path):
    with wave.open(path, "rb") as w:
        sr, n, ch, sw = w.getframerate(), w.getnframes(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(n)
    if sw == 2:
        a = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    else:
        a = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128) / 128.0
    if ch > 1:
        a = a.reshape(-1, ch).mean(axis=1)
    if sr != 48000:  # 播放用默认设备，简单线性重采样到 48k
        idx = np.linspace(0, len(a) - 1, int(len(a) * 48000 / sr))
        a = np.interp(idx, np.arange(len(a)), a).astype(np.float32)
    spk = sc.default_speaker()
    print("外放到：", spk.name, flush=True)
    with spk.player(samplerate=48000, channels=1) as p:
        p.play(a)


print("起始 last =", poll()["last"], flush=True)
t0 = time.time()
th = threading.Thread(target=play, args=(WAV,), daemon=True)
th.start()
last = 0
deadline = time.time() + 25
seen = []
while time.time() < deadline:
    try:
        d = poll(last)
    except Exception as e:
        print("轮询失败", e, flush=True)
        time.sleep(1)
        continue
    for it in d["items"]:
        seen.append(it)
        print("[%5.1fs] %s\n         %s" % (time.time() - t0, it["ja"], it["zh"]), flush=True)
        last = it["i"]
    if last and not th.is_alive() and time.time() - t0 > 12:
        break
    time.sleep(0.3)

print("\n共 %d 条，用时 %.1fs，src=%s" % (len(seen), time.time() - t0, d.get("src")), flush=True)
print("PASS" if seen else "FAIL: 一条都没出来")
