"""离线定速复放：把 wav 按实时速度喂进 Pipeline，量「句末 → 上屏」的真实滞后。
不经过 WASAPI 采集，排除掉音设备抖动，测的是管线本身。
用法：python tests/bench_pipe.py model_ja/1.wav [model_ja/4.wav ...]
"""
import io, os, sys, time, wave
from _paths import ROOT
import numpy as np
import live_ja as L

sr = L.SR


def load(path):
    with wave.open(path, "rb") as w:
        n, ch, sw, fr = w.getnframes(), w.getnchannels(), w.getsampwidth(), w.getframerate()
        raw = w.readframes(n)
    a = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0 if sw == 2 \
        else (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128) / 128.0
    if ch > 1:
        a = a.reshape(-1, ch).mean(axis=1)
    if fr != sr:
        idx = np.linspace(0, len(a) - 1, int(len(a) * sr / fr))
        a = np.interp(idx, np.arange(len(a)), a).astype(np.float32)
    return a


class Rec(L.Pipeline):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.hits = []
        self.t0 = 0.0

    def _process_one(self, samples, seg_start):
        r = super()._process_one(samples, seg_start)
        if r:
            self.hits.append((time.monotonic() - self.t0, seg_start, len(samples) / sr, r))
        return r


class Null:
    def push(self, ja, zh):
        pass


def run(path):
    p = Rec(None, Null(), verbose=False)
    a = load(path)
    p.t0 = time.monotonic()
    step, k = 512, 0
    while k * step < len(a):
        chunk = a[k * step:(k + 1) * step]
        if len(chunk) < step:
            chunk = np.pad(chunk, (0, step - len(chunk)))
        p.feed(chunk)
        k += 1
        wake = p.t0 + k * step / sr
        d = wake - time.monotonic()
        if d > 0:
            time.sleep(d)
    p.flush()
    print("\n=== %s  时长 %.1fs ===" % (os.path.basename(path), len(a) / sr))
    print("%-6s %-6s %-6s %s" % ("上屏", "句末", "滞后", "译文"))
    tot = []
    for t, s0, dur, (ja, zh) in p.hits:
        end = s0 + dur
        lag = t - end
        tot.append(lag)
        print("%5.1fs %5.1fs %5.2fs %s" % (t, end, lag, zh))
    if tot:
        print("句末→上屏：min %.2fs  中位 %.2fs  max %.2fs（%d 句）"
              % (min(tot), sorted(tot)[len(tot) // 2], max(tot), len(tot)))


for f in sys.argv[1:]:
    run(f)
