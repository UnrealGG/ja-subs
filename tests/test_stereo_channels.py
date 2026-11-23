# -*- coding: utf-8 -*-
"""验证双声道分流：左右不同显示两行，左右相同自动去重。"""
import os
import sys

from _paths import ROOT

import numpy as np

import live_ja as L


def run_pipeline(stereo):
    items = []

    class Sink:
        def push(self, ja, zh):
            items.append((ja, zh))

    pipe = L.Pipeline(None, Sink(), verbose=False, early_cut=5.0)
    pipe.vad = L.build_vad()
    for i in range(0, len(stereo) - 1024 + 1, 1024):
        pipe.feed(stereo[i:i + 1024])
    pipe.flush()
    return items


left = L.read_wav(os.path.join(ROOT, "model_ja", "1.wav"))[:L.SR * 7]
right = L.read_wav(os.path.join(ROOT, "model_ja", "2.wav"))[:L.SR * 7]
n = max(len(left), len(right))
left = np.pad(left, (0, n - len(left)))
right = np.pad(right, (0, n - len(right)))

L.warmup()
dual = run_pipeline(np.stack([left, right], axis=1))
same = run_pipeline(np.stack([left, left], axis=1))

print("Dual:", dual)
print("Same:", same)
if not any(("左：" in ja and "右：" in ja) for ja, zh in dual):
    raise SystemExit("FAILED: different channels were not both transcribed")
if any("左：" in ja for ja, zh in same):
    raise SystemExit("FAILED: identical channels were duplicated")
print("OK")
