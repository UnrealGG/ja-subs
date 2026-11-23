# -*- coding: utf-8 -*-
"""确认默认输出设备解析到真正的回环端点，而不是同名麦克风。"""
import sys

from _paths import ROOT

import live_ja as L


mic = L._resolve_loopback(None)
print(f"device   : {mic.name}")
print(f"loopback : {mic.isloopback}")
print(f"channels : {mic.channels}")

if not mic.isloopback:
    raise SystemExit("FAILED: default device is a microphone, not a loopback")
if int(mic.channels or 0) < 2:
    raise SystemExit("FAILED: loopback endpoint is mono")

print("OK")
