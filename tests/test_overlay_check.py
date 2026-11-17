import os
import sys

from _paths import ROOT

import live_ja as L

JA = "気象庁は雪や路面の凍結による交通への影響を注意喚起しています"
ZH = "气象厅指出，降雪及路面结冰对交通的影响，提醒民众注意。"

fails = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (" " + extra if extra else ""), flush=True)
    if not cond:
        fails.append(name)


def make(**kw):
    o = L.Overlay(**kw)
    o.root.attributes("-alpha", 0.0)   # 全程透明，不在屏幕上闪
    o.root.update()
    o.push(JA, ZH)
    o.root.update()
    o._poll()
    o.root.update()
    return o


def kill(o):
    o._closed = True
    try:
        o.root.destroy()
    except Exception:
        pass


def fills(o):
    return [o.cv.itemcget(i, "fill") for i in o.cv.find_all()]


# 1) 颜色
o = make(color="yellow")
check("color=yellow 生效", "#ffd84d" in fills(o), str(sorted(set(fills(o)))))
kill(o)

# 2) 描边档位：有描边时 8 个黑字 + 1 个本色
n = {}
for key in ("none", "thin", "bold"):
    o = make(color="white", outline=key)
    n[key] = len(o.cv.find_all())
    kill(o)
check("outline=bold 共 9 个文字对象", n["bold"] == 9, str(n))
check("outline=thin 共 9 个文字对象", n["thin"] == 9, str(n))
check("outline=none 只有 1 个", n["none"] == 1, str(n))

# 3) 位置三档：y 越小越靠上，high < mid < low
ys = {}
for pos in ("low", "mid", "high"):
    o = make(pos=pos)
    ys[pos] = o.root.winfo_y()
    kill(o)
check("位置 high < mid < low", ys["high"] < ys["mid"] < ys["low"], str(ys))

# 4) 显示模式
o = make(mode="zh")
check("mode=zh 隐藏日文行", not o.jp.winfo_ismapped())
kill(o)
o = make(mode="ja")
check("mode=ja 隐藏中文画布", not o.cv.winfo_ismapped())
kill(o)
o = make(mode="both")
check("mode=both 两行都在", o.jp.winfo_ismapped() and o.cv.winfo_ismapped())
kill(o)

# 5) 等比缩放
class D(object):
    pass


d = D()
d.scale = True
d.sh = 2160
k_hi = L.Overlay._k(d)
d.sh = 720
k_lo = L.Overlay._k(d)
d.scale = False
k_off = L.Overlay._k(d)
check("高分屏放大系数随屏幕变", k_hi > k_lo and abs(k_off - 1.0) < 1e-6,
      "2160->%.2f 720->%.2f off->%.2f" % (k_hi, k_lo, k_off))

# 6) 淡入从较低 alpha 起步（_fade_in 第一步是同步的）
o = L.Overlay(fade=True, alpha=0.9)
o.root.attributes("-alpha", 0.0)
base = 0.9
o._fade_in()
mid = float(o.root.attributes("-alpha"))
check("淡入第一步 alpha 低于目标", mid < base - 0.1, "base=%.2f step=%.2f" % (base, mid))
kill(o)

print("----")
print("FAILED: %d" % len(fails))
sys.exit(1 if fails else 0)
