# -*- coding: utf-8 -*-
"""绕过被锁目录：逐个成员手动写入指定位置。"""
import tarfile, os, sys, time

sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TAR = os.path.join(ROOT, "models", "ja-reazon.tar.bz2")
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "model_ja")

os.makedirs(OUT, exist_ok=True)
probe = os.path.join(OUT, "_probe.txt")
open(probe, "w").write("ok")
os.remove(probe)
print(f"writable: {OUT}", flush=True)

t0 = time.time()
n = 0
total = 0
with tarfile.open(TAR, "r:bz2") as tf:
    for m in tf:
        if not m.isfile():
            continue
        name = os.path.basename(m.name)
        dst = os.path.join(OUT, name)
        try:
            src = tf.extractfile(m)
            with open(dst, "wb") as f:
                while True:
                    chunk = src.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
                total += m.size
            n += 1
            print(f"  {name}  {m.size/1e6:.1f}MB  ({time.time()-t0:.0f}s)", flush=True)
        except Exception as e:
            print(f"  FAIL {name}: {type(e).__name__} {e}", flush=True)
print(f"DONE {n} files, {total/1e6:.1f}MB, {time.time()-t0:.0f}s", flush=True)
