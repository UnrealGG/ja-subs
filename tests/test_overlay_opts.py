import os
import sys

from _paths import ROOT

import live_ja as L

opts = dict(color="yellow", outline="bold", pos="mid", mode="both",
            fade=True, scale=True, font_zh=22, width_ratio=0.70, alpha=0.90)
for a in sys.argv[1:]:
    k, _, v = a.partition("=")
    opts[k] = (v == "1") if v in ("0", "1") else v

o = L.Overlay(**opts)
o.push("気象庁は雪や路面の凍結による交通への影響を注意喚起しています",
       "气象厅指出，降雪及路面结冰对交通的影响，提醒民众注意。")
def info():
    o.root.update_idletasks()
    print("SCREEN", o.root.winfo_screenwidth(), o.root.winfo_screenheight(), flush=True)
    print("RECT", o.root.winfo_x(), o.root.winfo_y(), o.root.winfo_width(), o.root.winfo_height(), flush=True)
    print("ALPHA", o.root.attributes("-alpha"), flush=True)

o.root.after(1500, info)
o.root.after(7000, o.close)
o.root.mainloop()
