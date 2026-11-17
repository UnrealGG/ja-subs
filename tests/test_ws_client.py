# -*- coding: utf-8 -*-
"""模拟浏览器插件：连本地 WS，把 1.wav 当"网页音频"推过去，看回不回字幕。"""
import base64
import json
import os
import socket
import struct
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
from _paths import ROOT

import numpy as np

import live_ja as L

PORT = int(os.environ.get("JA_WS_PORT", "8765"))


def connect():
    s = socket.create_connection(("127.0.0.1", PORT), timeout=30)
    key = base64.b64encode(os.urandom(16)).decode()
    s.sendall((
        f"GET / HTTP/1.1\r\nHost: 127.0.0.1:{PORT}\r\nUpgrade: websocket\r\n"
        f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
        f"Sec-WebSocket-Version: 13\r\n\r\n").encode())
    buf = b""
    while b"\r\n\r\n" not in buf:
        buf += s.recv(4096)
    head = buf.split(b"\r\n")[0]
    assert b"101" in head, f"握手失败: {head!r}"
    print(f"握手成功：{head.decode()}")
    return s


def send(s, payload, opcode=2):
    n = len(payload)
    hdr = bytes([0x80 | opcode])
    if n < 126:
        hdr += bytes([0x80 | n])
    elif n < 65536:
        hdr += bytes([0x80 | 126]) + struct.pack(">H", n)
    else:
        hdr += bytes([0x80 | 127]) + struct.pack(">Q", n)
    mask = os.urandom(4)
    arr = np.frombuffer(payload, dtype=np.uint8).copy()
    k = np.frombuffer(mask * (n // 4 + 1), dtype=np.uint8)[:n]
    s.sendall(hdr + mask + (arr ^ k).tobytes())


class Reader:
    def __init__(self, s):
        self.s = s
        self.buf = b""

    def _need(self, n):
        while len(self.buf) < n:
            d = self.s.recv(65536)
            if not d:
                raise ConnectionError("对端关闭")
            self.buf += d

    def frame(self):
        self._need(2)
        op = self.buf[0] & 0x0F
        n = self.buf[1] & 0x7F
        off = 2
        if n == 126:
            self._need(4)
            n = struct.unpack(">H", self.buf[2:4])[0]
            off = 4
        elif n == 127:
            self._need(10)
            n = struct.unpack(">Q", self.buf[2:10])[0]
            off = 10
        self._need(off + n)
        data = self.buf[off:off + n]
        self.buf = self.buf[off + n:]
        return op, data


def main():
    audio = L.read_wav(os.path.join(ROOT, "model_ja", "1.wav"))
    pcm = np.clip(audio * 32767, -32768, 32767).astype("<i2").tobytes()
    print(f"音频 {len(audio) / L.SR:.1f}s，切成 512 点的小块推流")

    s = connect()
    r = Reader(s)
    t0 = time.time()
    for i in range(0, len(pcm), 1024):        # 512 个采样 = 1024 字节
        send(s, pcm[i:i + 1024])

    got = []
    deadline = time.time() + 60
    # 先读 ready，再等字幕
    while time.time() < deadline:
        try:
            op, data = r.frame()
        except (socket.timeout, TimeoutError):
            break
        if op != 1:
            continue
        msg = json.loads(data.decode())
        if msg.get("type") == "ready":
            print("服务端就绪，开始等字幕…")
            send(s, json.dumps({"cmd": "flush"}).encode(), opcode=1)
            continue
        got.append(msg)
        print(f"  [{time.time() - t0:5.1f}s] {msg['ja']}\n            → {msg['zh']}")
        if len(got) >= 3:
            break
    s.close()
    print(f"\n收到 {len(got)} 条字幕，总耗时 {time.time() - t0:.1f}s")
    return 0 if got else 1


if __name__ == "__main__":
    sys.exit(main())
