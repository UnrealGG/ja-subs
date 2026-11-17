# -*- coding: utf-8 -*-
"""对比不同 ollama 模型做日→中字幕翻译：质量 + 延迟。"""
import sys, os, time
sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

from _paths import ROOT
import live_ja

CASES = [
    "時間に間に合わなくなるから、このワンピースに着替えて。",
    "一回の打ち上げ費用がおよそ100億円かかるそうです。",
    "気象庁は雪や路面の凍結による交通への影響に注意するよう呼びかけています。",
    "私の名前は美春っていいます。よろしくお願いしますね。",
    "そんなこと言われても、急には決められませんよ。",
    "早くおじいさんにあの男の話をきかせたかったのです。",
]

models = sys.argv[1:] or ["qwen3.5:latest"]
for m in models:
    live_ja.MT_MODEL = m
    print(f"\n===== {m} =====")
    t = time.time()
    r = live_ja.translate("こんにちは", timeout=600)
    print(f"预热 {time.time() - t:.1f}s → {r}")
    ts = []
    for s in CASES:
        t = time.time()
        out = live_ja.translate(s, timeout=600)
        ts.append(time.time() - t)
        print(f"  [{ts[-1]:5.2f}s] {s}\n         → {out}")
    ts.sort()
    print(f"  延迟 中位 {ts[len(ts)//2]:.2f}s  最慢 {ts[-1]:.2f}s  平均 {sum(ts)/len(ts):.2f}s")
