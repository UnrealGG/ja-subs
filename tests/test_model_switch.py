# -*- coding: utf-8 -*-
"""验证插件端切换翻译模型：连 WS → 命令切 3B → 推 1.wav 看译文 → 切回 9B。"""
import json
import os
import socket
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
from _paths import ROOT

import numpy as np

import live_ja as L
from test_ws_client import Reader, connect, send


def wait_reply(r, want, timeout=120):
    t0 = time.time()
    while time.time() - t0 < timeout:
        op, data = r.frame()
        if op != 1:
            continue
        msg = json.loads(data.decode())
        if msg.get("type") == want:
            return msg
    return None


def main():
    s = connect()
    r = Reader(s)

    t = time.time()
    send(s, json.dumps({"cmd": "model", "name": "qwen2.5:3b"}).encode(), opcode=1)
    m = wait_reply(r, "model")
    print(f"→ 切 3B 回执：{m}（{time.time()-t:.2f}s）")
    assert m and m.get("ok"), "切 3B 失败"

    audio = L.read_wav(os.path.join(ROOT, "model_ja", "1.wav"))
    pcm = np.clip(audio * 32767, -32768, 32767).astype("<i2").tobytes()
    for i in range(0, len(pcm), 1024):
        send(s, pcm[i:i + 1024])

    got, t0 = [], time.time()
    deadline = time.time() + 90
    while time.time() < deadline and len(got) < 3:
        op, data = r.frame()
        if op != 1:
            continue
        msg = json.loads(data.decode())
        if msg.get("type") == "ready":
            send(s, json.dumps({"cmd": "flush"}).encode(), opcode=1)
            continue
        if msg.get("zh"):
            got.append(msg)
            print(f"  [{time.time()-t0:5.1f}s] {msg['ja']}\n            → {msg['zh']}")
    print(f"3B 收到 {len(got)} 条")

    t = time.time()
    send(s, json.dumps({"cmd": "model", "name": "qwen3.5:latest"}).encode(), opcode=1)
    m2 = wait_reply(r, "model")
    print(f"→ 切回 9B 回执：{m2}（{time.time()-t:.2f}s）")

    # 非法模型应被拒
    send(s, json.dumps({"cmd": "model", "name": "rm -rf /"}).encode(), opcode=1)
    m3 = wait_reply(r, "model")
    print(f"→ 非法模型回执：{m3}")
    assert m3 and m3.get("ok") is False, "非法模型没被拦住"

    s.close()
    return 0 if got else 1


if __name__ == "__main__":
    sys.exit(main())
