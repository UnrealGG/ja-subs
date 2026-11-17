# -*- coding: utf-8 -*-
"""悬浮窗交互自检：字号/宽度/透明度/滚轮/✕ 关闭，全部走真实控件路径。"""
import sys, os, time
sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

from _paths import ROOT
from live_ja import Overlay

JA = "時間に間に合わなくなるから、このワンピースに着替えて。ほらほら、早く早く。"
ZH = "来不及了，快换上这条连衣裙吧。看这里看这里，快点快点。"

o = Overlay()
o.push(JA, ZH)


def pump(ms=400):
    end = time.time() + ms / 1000
    while time.time() < end:
        o.root.update()
        time.sleep(0.02)


pump(600)
print(f"初始    宽={o.root.winfo_width()} 高={o.root.winfo_height()} 字号={o.fz} 不透明度={o.alpha}")

o._font(8)
pump()
print(f"字号+8  宽={o.root.winfo_width()} 高={o.root.winfo_height()} 字号={o.fz}")

o._width(-0.22)
pump()
print(f"宽度-   宽={o.root.winfo_width()} 高={o.root.winfo_height()} 比例={o.wr:.2f}")

o._alpha(-0.2)
print(f"透明度  不透明度={o.alpha:.2f} 实际={float(o.root.attributes('-alpha')):.2f}")


class Wheel:
    delta = 120
    state = 0


o._wheel(Wheel())
pump()
print(f"滚轮↑   字号={o.fz}")

# 长句要能把框撑高，短句要能缩回去
o.push("はい。" * 1, "嗯。")
pump(300)
h_short = o.root.winfo_height()
o.push(" ".join(["長い台詞です。"] * 12), "这是一句很长的台词，" * 6)
pump(300)
h_long = o.root.winfo_height()
print(f"高度自适应  短={h_short} 长={h_long}  {'OK' if h_long > h_short else 'FAIL'}")

# ✕ 关闭：走真实事件绑定
o.root.update()
print("准备点 ✕ ……")
o.x.event_generate("<Button-1>", x=2, y=2)
o.root.update()
print("FAIL: 点了 ✕ 还活着")
