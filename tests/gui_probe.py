# -*- coding: utf-8 -*-
"""悬浮字幕窗渲染自检：显示 12 秒后自动退出，用于截图验收。"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

from _paths import ROOT
import importlib.util

spec = importlib.util.spec_from_file_location("lj", os.path.join(ROOT, "live_ja.py"))
lj = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lj)

ov = lj.Overlay()
ov.push("気象庁は雪や路面の凍結による交通への影響",
        "气象厅指出，降雪及路面结冰将对交通造成影响。")
ov.root.after(12000, lambda: ov.root.destroy())
ov.run()
print("overlay ok")
