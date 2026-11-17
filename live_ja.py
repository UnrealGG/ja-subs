# -*- coding: utf-8 -*-
"""
日语视频实时同传字幕（本地全离线）
================================================
链路：系统声音(WASAPI loopback) → Silero VAD 整句切分 → ReazonSpeech 日语 ASR
      → ollama 日译中 → 置顶透明悬浮字幕

用法：
  python live_ja.py                       # 抓系统声音（放视频即可）
  python live_ja.py --device Steam        # 指定回环设备名关键字
  python live_ja.py --list                # 列出所有可录音设备
  python live_ja.py --file a.wav          # 用音频文件跑通全链路（自测）
  python live_ja.py --srt out.srt         # 顺带存双语字幕文件
  python live_ja.py --no-gui              # 不显示悬浮窗，只打控制台

操作：拖动字幕可移动位置；右键菜单或右上角 ✕ 退出。
"""
import argparse
import json
import os
import queue
import sys
import threading
import time
import urllib.request
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "libs"))

import numpy as np  # noqa: E402
import sherpa_onnx  # noqa: E402  # noqa: E402

SR = 16000
OLLAMA = "http://127.0.0.1:11434/api/chat"
MT_MODEL = "qwen3.5:latest"
MT_SYS = ("你是日语→简体中文的同声传译引擎。把用户给的日语句子翻成自然、简洁的中文。"
          "规则：①只输出译文，不加解释、不加引号、不附原文；"
          "②原文残缺或听不懂时，按能听懂的部分直接翻，绝不写「此处需补充」这类说明；"
          "③不要输出任何括号注释；"
          "④数字必须与原文严格一致，不得添零、四舍五入或凭上下文推测；"
          "⑤译文只能是中文，绝不夹杂英文单词或日文假名（人名地名等专有名词除外）。")

# 小模型对「百億円」这类汉字数字经常读错量级（实测会把百億翻成 1000 亿）。
# 提示词管不住，就在送翻译之前把汉字数字先换成阿拉伯数字：「百億」→「100億」。
_KANJI_D = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_KANJI_U = {"十": 10, "百": 100, "千": 1000}


def _kanji_int(s):
    total = section = num = 0
    for ch in s:
        if ch in _KANJI_D:
            num = _KANJI_D[ch]
        elif ch in _KANJI_U:
            section += (num or 1) * _KANJI_U[ch]
            num = 0
        elif ch == "万":
            total += (section + num) * 10000
            section = num = 0
        elif ch == "億":
            total += (section + num) * 100000000
            section = num = 0
    return total + section + num


def normalize_numbers(text):
    import re
    text = text.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    return re.sub(r"([一二三四五六七八九十百千]+)([億万])",
                  lambda m: str(_kanji_int(m.group(1))) + m.group(2), text)


# ─────────────────────────────── 音频源 ───────────────────────────────
def list_devices():
    import soundcard as sc
    print("可录音设备（含回环）：")
    for i, m in enumerate(sc.all_microphones(include_loopback=True)):
        print(f"  [{i}] {m.name}  (loopback={m.isloopback})")
    print(f"\n默认扬声器：{sc.default_speaker().name}")


def _resolve_loopback(device_kw):
    """按关键字找回环设备；找不到就用当前默认输出设备的回环。"""
    import soundcard as sc
    if device_kw:
        cands = [m for m in sc.all_microphones(include_loopback=True)
                 if device_kw.lower() in m.name.lower() and m.isloopback]
        if not cands:
            cands = [m for m in sc.all_microphones(include_loopback=True)
                     if device_kw.lower() in m.name.lower()]
        if not cands:
            raise SystemExit(f"没找到匹配 '{device_kw}' 的设备，用 --list 看看")
        return cands[0]
    # 默认输出设备：耳机插上、蓝牙连上都会换成它，回环也就跟着走
    return sc.get_microphone(sc.default_speaker().name, include_loopback=True)


def capture_loopback(device_kw=None, chunk=1024, follow=True):
    """从系统声音回环录音，产出 float32 单声道。

    抓的是「送到该输出设备的音频流」，不是麦克风听到的声音——
    所以不外放、只插耳机、甚至把音量拉到 0，都一样能抓到。
    follow=True 时每约 2 秒看一眼默认输出设备有没有变，变了就重连。
    """
    import soundcard as sc

    mic = None
    cur = None
    while True:
        try:
            mic = _resolve_loopback(device_kw)
        except SystemExit:
            raise
        except Exception as e:
            print(f"[!] 取设备失败：{e}，1 秒后重试", flush=True)
            time.sleep(1)
            continue
        if mic.name != cur:
            print(f"录音设备：{mic.name}", flush=True)
            cur = mic.name

        native_sr = SR
        try:
            rec = mic.recorder(samplerate=SR, channels=1, blocksize=chunk)
            rec.__enter__()
        except Exception:
            native_sr = 48000
            try:
                rec = mic.recorder(samplerate=native_sr, channels=1, blocksize=chunk * 3)
                rec.__enter__()
            except Exception as e:
                print(f"[!] 打不开 {mic.name}：{e}，1 秒后重试", flush=True)
                time.sleep(1)
                continue
        if native_sr != SR:
            print(f"采样率：{native_sr}Hz（降到 {SR}Hz）", flush=True)

        sw = 0
        try:
            while True:
                try:
                    data = rec.record(numframes=chunk if native_sr == SR else chunk * 3)
                except Exception as e:
                    print(f"[!] 录音中断：{e}，重连", flush=True)
                    break
                x = np.asarray(data, dtype=np.float32)
                if x.ndim > 1:
                    x = x.mean(axis=1)
                if native_sr != SR:
                    n = len(x) // 3 * 3
                    if n == 0:
                        continue
                    x = x[:n].reshape(-1, 3).mean(axis=1)
                yield x
                # 每约 2 秒检查一次默认设备（一个 chunk ≈ 64ms）
                sw += 1
                if follow and not device_kw and sw % 32 == 0:
                    try:
                        now = sc.default_speaker().name
                    except Exception:
                        now = cur
                    if now != cur:
                        print(f"输出设备已切换到「{now}」，重连录音", flush=True)
                        break
        finally:
            try:
                rec.__exit__(None, None, None)
            except Exception:
                pass


def read_wav(path, target_sr=SR):
    with wave.open(path, "rb") as w:
        sr, n, ch, sw = w.getframerate(), w.getnframes(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(n)
    if sw == 2:
        a = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif sw == 4:
        a = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
    else:
        a = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    if ch > 1:
        a = a.reshape(-1, ch).mean(axis=1)
    if sr != target_sr:
        idx = np.arange(int(len(a) * target_sr / sr)) * (sr / target_sr)
        a = np.interp(idx, np.arange(len(a)), a).astype(np.float32)
    return a


# ─────────────────────────────── 模型 ───────────────────────────────
def find_asr_dir():
    roots = [os.path.join(HERE, "model_ja")] + sorted(
        __import__("glob").glob(os.path.join(HERE, "models", "*")))
    for d in roots:
        if not os.path.isdir(d):
            continue
        try:
            if __import__("glob").glob(os.path.join(d, "*encoder*.onnx")):
                return d
        except OSError:
            continue
    raise SystemExit("找不到日语模型目录")


def pick(d, pat, prefer_int8=True):
    import glob as g
    hits = g.glob(os.path.join(d, pat))
    if prefer_int8:
        i8 = [h for h in hits if "int8" in os.path.basename(h)]
        return (i8 or hits)[0]
    return hits[0]


def build_asr(d):
    return sherpa_onnx.OfflineRecognizer.from_transducer(
        encoder=pick(d, "*encoder*.onnx"),
        decoder=pick(d, "*decoder*.onnx"),
        joiner=pick(d, "*joiner*.onnx"),
        tokens=os.path.join(d, "tokens.txt"),
        num_threads=4, sample_rate=SR, feature_dim=80,
        decoding_method="greedy_search", provider="cpu")


def build_vad(min_silence=0.35, max_speech=15.0, threshold=0.5):
    cfg = sherpa_onnx.VadModelConfig()
    cfg.silero_vad.model = os.path.join(HERE, "models", "vad", "silero_vad.onnx")
    cfg.silero_vad.threshold = threshold
    cfg.silero_vad.min_silence_duration = min_silence
    cfg.silero_vad.min_speech_duration = 0.25
    cfg.silero_vad.max_speech_duration = max_speech
    cfg.silero_vad.window_size = 512
    cfg.sample_rate = SR
    cfg.num_threads = 2
    cfg.provider = "cpu"
    return sherpa_onnx.VoiceActivityDetector(cfg, buffer_size_in_seconds=60)


# ─────────────────────────────── 翻译 ───────────────────────────────
def unload_mt(model=None, timeout=4):
    """让 ollama 立刻把翻译模型从显存里卸掉（关字幕时调，别等它 5 分钟 keep_alive）。"""
    body = json.dumps({"model": model or MT_MODEL, "keep_alive": 0}).encode("utf-8")
    req = urllib.request.Request(
        "http://127.0.0.1:11434/api/generate", data=body,
        headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=timeout).read()
        return True
    except Exception:
        return False


def translate(ja, timeout=90):
    body = {
        "model": MT_MODEL,
        "messages": [{"role": "system", "content": MT_SYS},
                     {"role": "user", "content": ja}],
        "stream": False, "think": False,
        "options": {"num_ctx": 2048, "temperature": 0.1, "num_predict": 200},
    }
    req = urllib.request.Request(OLLAMA, json.dumps(body).encode("utf-8"),
                                 {"Content-Type": "application/json"})
    try:
        r = json.load(urllib.request.urlopen(req, timeout=timeout))
        txt = (r.get("message", {}).get("content") or "").strip()
        # 小模型偶尔自作聪明补一句「（此处需补充完整句子）」，字幕里绝不能出现。
        # 只清掉含"补充/原文/无法…"这类元话语的括号块，正常的（笑）之类保留。
        import re
        txt = re.sub(r"[（(][^（）()]*?(?:补充|此处|省略|未完整|未完|无法|原文|残缺|不明|不完整|"
                     r"句子|待补|下文|继续)[^（）()]*?[）)]", "", txt)
        return txt.strip()
    except Exception as e:
        return f"[翻译失败:{type(e).__name__}]"


def list_models():
    """列出本机 ollama 里已有的模型，方便换小一点的翻译模型。"""
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=5) as r:
            tags = json.load(r).get("models", [])
    except Exception as e:
        print(f"连不上 ollama：{type(e).__name__}: {e}")
        return
    print("本机已安装的翻译模型（越大越准、越吃显存）：")
    for m in tags:
        print(f"  {m.get('name', ''):<24} {m.get('size', 0) / 1024 ** 3:5.1f} GB")
    print(f"\n当前使用：{MT_MODEL}　要换模型加 --model 模型名")


def warmup():
    """先把 ollama 的模型拉进显存，否则首句翻译会等到超时。"""
    t = time.time()
    r = translate("こんにちは", timeout=300)
    print(f"翻译模型预热完成（{time.time()-t:.1f}s）：{r}")


# ─────────────────────────────── 管道 ───────────────────────────────
class Pipeline:
    def __init__(self, srt_path=None, gui=None, verbose=True):
        self.asr = build_asr(find_asr_dir())
        self.vad = build_vad()
        self.gui = gui
        self.verbose = verbose
        self.srt_path = srt_path
        self.idx = 0
        self.t_start = None
        self._pend = None  # 攒着太短的段落，等下一段一起翻
        self._pend_at = 0  # 攒起来那一刻的累计采样数，用于超时兜底
        self._fed = 0      # 累计喂进来的采样数
        # ASR+翻译放到独立线程：翻译一句要 0.3–4 秒，同步跑会把采集线程卡住，
        # soundcard 缓冲区一满就丢样本（日志里的 data discontinuity），
        # 表现为字幕既慢又缺字。这里只把切好的整段丢进队列，采集立刻返回。
        self._work = queue.Queue(maxsize=8)
        self._wk = threading.Thread(target=self._work_loop, daemon=True)
        self._wk.start()
        if srt_path:
            open(srt_path, "w", encoding="utf-8").close()

    def _srt_write(self, t0, t1, ja, zh):
        def fmt(t):
            h, r = divmod(int(t), 3600)
            m, s = divmod(r, 60)
            return f"{h:02d}:{m:02d}:{s:02d},{int((t%1)*1000):03d}"
        self.idx += 1
        with open(self.srt_path, "a", encoding="utf-8") as f:
            f.write(f"{self.idx}\n{fmt(t0)} --> {fmt(t1)}\n{zh}\n{ja}\n\n")

    def feed(self, chunk):
        """喂一块 16k 音频，返回这段时间内产出的字幕列表。"""
        out = []
        buf = chunk
        self._fed += len(buf)
        W = 512
        dbg = os.environ.get("DBG_FEED")
        n_acc = n_fire = 0
        for i in range(0, len(buf) - W + 1, W):
            self.vad.accept_waveform(buf[i:i + W])
            n_acc += 1
            while not self.vad.empty():
                n_fire += 1
                seg = self.vad.front
                # 必须先取出样本与起点，pop() 会让 seg 立即失效
                samples = np.asarray(seg.samples, dtype=np.float32).copy()
                seg_start = seg.start
                self.vad.pop()
                if len(samples) < SR * 0.2:
                    continue
                job = self._submit(samples, seg_start / SR)
                if job:
                    self._enqueue(*job)
        # 攒着的半句后面一直没声音时不能无限等，按音频时间兜底放出来。
        # 阈值要大于「两句话之间的自然停顿 + VAD 末端延迟」，否则还没等到下一句
        # 就先被兜底放掉，半句照样被切碎（实测 2.0s 会把「気象庁」单独放出来）。
        if self._pend is not None and (self._fed - self._pend_at) > SR * 4.0:
            s, st = self._pend
            self._pend = None
            if len(s) >= SR * 0.4:
                self._enqueue(s, st)
        if dbg:
            print(f"[dbg] bytes={len(buf)} acc={n_acc} fire={n_fire} out={len(out)} "
                  f"vad={type(self.vad).__name__}", file=sys.stderr)
        return out

    def _submit(self, samples, start):
        """太短的段落先攒着，和下一段拼起来再翻，避免"町長は"这种半句。"""
        if self._pend is not None:
            ps, pst = self._pend
            samples = np.concatenate([ps, samples])
            start = pst
            self._pend = None
        if len(samples) < SR * 2.2:
            self._pend = (samples, start)
            self._pend_at = self._fed
            return None
        return (samples, start)

    def _enqueue(self, samples, start):
        """翻译跟不上时宁可丢掉最旧的整段，也绝不阻塞采集。"""
        try:
            self._work.put_nowait((samples, start))
        except queue.Full:
            try:
                self._work.get_nowait()
                self._work.task_done()
                print("[!] 翻译跟不上，丢掉一段旧音频", file=sys.stderr)
            except queue.Empty:
                pass
            try:
                self._work.put_nowait((samples, start))
            except queue.Full:
                pass

    def _work_loop(self):
        while True:
            item = self._work.get()
            try:
                if item is not None:
                    self._process(*item)
            except Exception as e:  # 单句失败不能把整条管线带走
                print(f"[!] 处理失败：{e}", file=sys.stderr)
            finally:
                self._work.task_done()
            if item is None:
                return

    def _drain(self):
        """等队列里已有的段全部处理完。"""
        self._work.join()

    def _split_long(self, samples, max_s=6.5):
        """VAD 遇到快语速连续对话时会把十几秒并成一段（停顿都没超过 0.35s），
        等到整段结束才出字幕，观众已经看丢了。这里在能量低谷处切块，
        块数变多但音频一个采样都不丢——开头的补静音逻辑保证切开也能认对。"""
        rest = samples
        parts = []
        while len(rest) / SR > max_s:
            hi = int(max_s * SR)
            lo = int(hi * 0.55)
            win = int(0.15 * SR)
            hi = min(hi, len(rest) - win)
            if hi <= lo:
                break
            # 只看 0.15s 窗口的绝对均值，找最安静的位置当切点
            frame = np.abs(rest[:hi + win])
            step = max(1, win // 4)
            idx = range(lo, hi, step)
            energies = [frame[i:i + win].mean() for i in idx]
            cut = idx[int(np.argmin(energies))]
            parts.append(rest[:cut])
            rest = rest[cut:]
        parts.append(rest)
        return parts

    def _process(self, samples, seg_start):
        parts = self._split_long(samples)
        if len(parts) == 1:
            return self._process_one(samples, seg_start)
        res, off = None, 0.0
        for p in parts:
            r = self._process_one(p, seg_start + off)
            off += len(p) / SR
            if r:
                res = r
        return res

    def _process_one(self, samples, seg_start):
        t0 = time.time()
        dur = len(samples) / SR
        # 关键：从句中切出来的片段必须先补一段静音，否则 transducer 的首个 chunk
        # 没有左上下文，开头几个词会被吞掉。实测 "はやくおじいさんに…" 会变成
        # "いかせたかったのです"；补 0.5s 前置静音后整句完全正确。
        padded = np.concatenate([np.zeros(SR // 2, dtype=np.float32), samples])
        st = self.asr.create_stream()
        st.accept_waveform(SR, padded)
        self.asr.decode_stream(st)
        ja = st.result.text.strip()
        t_asr = time.time() - t0
        if not ja:
            return None
        t1 = time.time()
        zh = translate(normalize_numbers(ja))
        t_mt = time.time() - t1
        if self.verbose:
            print(f"\n[JA] {ja}")
            print(f"[ZH] {zh}")
            print(f"     asr {t_asr*1000:.0f}ms | mt {t_mt*1000:.0f}ms | 音频 {dur:.1f}s")
        if self.srt_path:
            self._srt_write(seg_start, seg_start + dur, ja, zh)
        if self.gui:
            self.gui.push(ja, zh)
        return (ja, zh)

    def flush(self):
        self.vad.flush()
        res = []
        while not self.vad.empty():
            seg = self.vad.front
            samples = np.asarray(seg.samples, dtype=np.float32).copy()
            seg_start = seg.start
            self.vad.pop()
            if len(samples) >= SR * 0.2:
                job = self._submit(samples, seg_start / SR)
                if job:
                    self._enqueue(*job)
        self._drain()
        if self._pend is not None:
            s, st = self._pend
            self._pend = None
            if len(s) >= SR * 0.4:
                r = self._process(s, st)
                if r:
                    res.append(r)
        return res


# ─────────────────────────────── 悬浮窗 ───────────────────────────────
class Overlay:
    """置顶字幕条。

    样式全部来自命令行（JaSubs.exe 的设置面板会翻译成这些参数）：
    color/outline/pos/fade/scale/mode，另外保留滚轮与右键临时微调。
    """

    POS_RATIO = {"low": 0.085, "mid": 0.16, "high": 0.26}
    OUTLINE_PX = {"none": 0, "thin": 2, "bold": 4}
    COLORS = {
        "white": "#ffffff", "yellow": "#ffd84d", "cyan": "#7fe7ff",
        "green": "#9bff9b", "pink": "#ffb3d1", "orange": "#ffb066",
    }
    BG = "#101010"

    def __init__(self, font_zh=22, width_ratio=0.70, alpha=0.82,
                 color="white", outline="thin", pos="low",
                 fade=True, scale=True, mode="both"):
        import tkinter as tk
        self.tk = tk
        self.q = queue.Queue()
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.sw = self.root.winfo_screenwidth()
        self.sh = self.root.winfo_screenheight()
        self.fz = int(font_zh)
        self.wr = float(width_ratio)
        self.alpha = float(alpha)
        self.color = self.COLORS.get(str(color).lower(), str(color))
        self.outline = outline if outline in self.OUTLINE_PX else "thin"
        self.pos = pos if pos in self.POS_RATIO else "low"
        self.fade = bool(fade)
        self.scale = bool(scale)
        self.mode = mode if mode in ("both", "zh", "ja") else "both"
        self._closed = False
        self._dragged = False
        self._ja = ""
        self._zh = ""
        self.root.attributes("-alpha", self.alpha)
        self.root.configure(bg=self.BG)

        self.jp = tk.Label(self.root, text="", fg="#9fd0ff", bg=self.BG,
                           font=("Yu Gothic UI", 13), justify="center", anchor="center")
        self.jp.pack(fill="x", padx=20, pady=(12, 2))

        self.cv = tk.Canvas(self.root, bg=self.BG, highlightthickness=0, bd=0, height=44)
        self.cv.pack(fill="both", expand=True, padx=20, pady=(0, 10))

        # overrideredirect 的置顶窗口一般拿不到键盘焦点，只绑 Esc 等于没有退出路径。
        # 所以保留鼠标出口：右上角 ✕ + 右键菜单。
        self.x = tk.Label(self.root, text="✕", fg="#999999", bg=self.BG,
                          font=("Segoe UI", 11), cursor="hand2")
        self.x.place(relx=1.0, rely=0.0, anchor="ne", x=-8, y=4)
        self.x.bind("<Button-1>", lambda e: self.close())

        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="字号 +", command=lambda: self._font(2))
        self.menu.add_command(label="字号 −", command=lambda: self._font(-2))
        self.menu.add_separator()
        self.menu.add_command(label="宽度 +", command=lambda: self._width(0.08))
        self.menu.add_command(label="宽度 −", command=lambda: self._width(-0.08))
        self.menu.add_separator()
        self.menu.add_command(label="更透明", command=lambda: self._alpha(-0.1))
        self.menu.add_command(label="更不透明", command=lambda: self._alpha(0.1))
        self.menu.add_separator()
        pm = tk.Menu(self.menu, tearoff=0)
        for key, label in (("low", "贴近进度条"), ("mid", "居中偏下"), ("high", "偏上")):
            pm.add_command(label=label, command=lambda k=key: self._set_pos(k))
        self.menu.add_cascade(label="位置", menu=pm)
        mm = tk.Menu(self.menu, tearoff=0)
        for key, label in (("both", "中日双语"), ("zh", "只看中文"), ("ja", "只看日文")):
            mm.add_command(label=label, command=lambda k=key: self._set_mode(k))
        self.menu.add_cascade(label="显示", menu=mm)
        self.menu.add_separator()
        self.menu.add_command(label="退出", command=self.close)

        self._drag = None
        for wdg in (self.root, self.jp, self.cv, self.x):
            wdg.bind("<Button-1>", self._down)
            wdg.bind("<B1-Motion>", self._move)
            wdg.bind("<Button-3>", self._popup)
            wdg.bind("<MouseWheel>", self._wheel)
        self.root.bind("<Escape>", lambda e: self.close())

        self._apply_mode()
        self._font_apply()
        self.root.geometry(f"{int(self.sw * self.wr)}x80")
        self.root.update_idletasks()
        self._draw("等待日语语音…", dim=True)
        self._fit()
        self.root.after(80, self._poll)

    # ── 样式 ──
    def _k(self):
        """按屏幕高度等比放大字号（720p 以下不缩）。"""
        if not self.scale:
            return 1.0
        return max(0.85, min(1.6, self.sh / 1080.0))

    def _fz(self):
        return max(11, int(round(self.fz * self._k())))

    def _font_apply(self):
        jp_size = max(9, self._fz() - 9)
        self.jp.config(font=("Yu Gothic UI", jp_size))

    def _apply_mode(self):
        if self.mode == "zh" or self.mode == "both":
            if not self.jp.winfo_ismapped() and self.mode == "both":
                self.jp.pack(fill="x", padx=20, pady=(12, 2), before=self.cv)
        if self.mode == "zh":
            self.jp.pack_forget()
        if self.mode == "ja":
            self.cv.pack_forget()
        elif not self.cv.winfo_ismapped():
            self.cv.pack(fill="both", expand=True, padx=20, pady=(0, 10))

    def _draw(self, text, dim=False):
        """用 Canvas 画中文，才能做真正的描边（Label 没有 outline）。"""
        cv = self.cv
        cv.delete("all")
        if not cv.winfo_ismapped():
            return
        self.root.update_idletasks()
        w = max(200, cv.winfo_width())
        pad = 6
        n = self.OUTLINE_PX.get(self.outline, 2)
        col = "#6b6b6b" if dim else self.color
        font = ("Microsoft YaHei UI", self._fz(), "bold")
        wrap = max(120, w - 16)
        # 8 个方向画一圈黑字当描边，最后把本色字压在上面
        if n:
            for dx, dy in ((-1, -1), (0, -1), (1, -1), (-1, 0),
                           (1, 0), (-1, 1), (0, 1), (1, 1)):
                cv.create_text(w / 2 + dx * n, pad + dy * n, text=text, fill="#000000",
                               font=font, justify="center", width=wrap, anchor="n")
        cv.create_text(w / 2, pad, text=text, fill=col,
                       font=font, justify="center", width=wrap, anchor="n")
        self.root.update_idletasks()
        box = cv.bbox("all")
        h = int(box[3]) + pad if box else self._fz() + 12
        cv.config(height=h)

    def _fit(self):
        """宽度固定、高度跟着文字行数走，避免短句时框缩成一条。"""
        w = int(self.sw * self.wr)
        self.root.update_idletasks()
        h = max(52, self.root.winfo_reqheight())
        if self._dragged:
            x, y = self.root.winfo_x(), self.root.winfo_y()
        else:
            x = int((self.sw - w) / 2)
            y = self.sh - h - int(self.sh * self.POS_RATIO.get(self.pos, 0.085))
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    def _fade_in(self):
        if not self.fade:
            return
        steps = 8
        lo = self.alpha * 0.35

        def step(i=0):
            if self._closed:
                return
            a = lo + (self.alpha - lo) * (i / steps)
            try:
                self.root.attributes("-alpha", min(self.alpha, a))
            except Exception:
                return
            if i < steps:
                self.root.after(26, lambda: step(i + 1))
        step()

    # ── 微调 ──
    def _font(self, d):
        self.fz = max(12, min(44, self.fz + d))
        self._font_apply()
        self._draw(self._zh or "等待日语语音…", dim=not self._zh)
        self._fit()

    def _width(self, d):
        self.wr = max(0.30, min(0.98, self.wr + d))
        self._fit()
        self._draw(self._zh or "等待日语语音…", dim=not self._zh)
        self._fit()

    def _alpha(self, d):
        self.alpha = max(0.25, min(1.0, self.alpha + d))
        self.root.attributes("-alpha", self.alpha)

    def _set_pos(self, key):
        self.pos = key
        self._dragged = False
        self._fit()

    def _set_mode(self, key):
        self.mode = key
        if key == "ja":
            self.jp.config(text=self._ja)
        self._apply_mode()
        self._fit()

    def _wheel(self, e):
        if e.state & 0x0004:      # Ctrl + 滚轮 = 调宽度
            self._width(0.04 if e.delta > 0 else -0.04)
        else:                     # 滚轮 = 调字号
            self._font(2 if e.delta > 0 else -2)

    def _popup(self, e):
        try:
            self.menu.tk_popup(e.x_root, e.y_root)
        finally:
            self.menu.grab_release()

    # ── 拖动 / 退出 ──
    def _down(self, e):
        self._drag = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y())

    def _move(self, e):
        if self._drag:
            self._dragged = True
            self.root.geometry(f"+{e.x_root - self._drag[0]}+{e.y_root - self._drag[1]}")

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            self.root.destroy()
        except Exception:
            pass
        # os._exit 会丢掉 stdout 缓冲区，先冲掉，否则最后几行日志看不见
        try:
            sys.stdout.flush()
            sys.stderr.flush()
        except Exception:
            pass
        os._exit(0)

    def push(self, ja, zh):
        self.q.put((ja, zh))

    def _poll(self):
        try:
            while True:
                ja, zh = self.q.get_nowait()
                self._ja, self._zh = ja, zh
                if self.mode != "zh":
                    self.jp.config(text=ja)
                self._draw(zh)
                self._font_apply()
                self._fit()
                self._fade_in()
        except queue.Empty:
            pass
        if not self._closed:
            self.root.after(80, self._poll)

    def run(self):
        self.root.mainloop()


# ─────────────────────────────── 主流程 ───────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="列出录音设备")
    ap.add_argument("--device", default=None, help="设备名关键字")
    ap.add_argument("--file", default=None, help="用音频文件跑全链路")
    ap.add_argument("--srt", default=None, help="导出双语 srt")
    ap.add_argument("--no-gui", action="store_true")
    ap.add_argument("--min-silence", type=float, default=0.35)
    ap.add_argument("--max-speech", type=float, default=15.0)
    ap.add_argument("--font", type=int, default=22, help="中文字号，默认 22")
    ap.add_argument("--width", type=float, default=0.70, help="字幕条占屏宽比例，默认 0.70")
    ap.add_argument("--alpha", type=float, default=0.82, help="背景不透明度，默认 0.82")
    ap.add_argument("--model", default=None, help="翻译模型名，默认 qwen3.5:latest")
    ap.add_argument("--models", action="store_true", help="列出本机已装的翻译模型")
    ap.add_argument("--color", default="white",
                    help="中文字色：white/yellow/cyan/green/pink/orange 或 #RRGGBB")
    ap.add_argument("--outline", default="thin", choices=["none", "thin", "bold"])
    ap.add_argument("--pos", default="low", choices=["low", "mid", "high"])
    ap.add_argument("--fade", dest="fade", action="store_true", default=True)
    ap.add_argument("--no-fade", dest="fade", action="store_false")
    ap.add_argument("--scale", dest="scale", action="store_true", default=True)
    ap.add_argument("--no-scale", dest="scale", action="store_false")
    ap.add_argument("--mode", default="both", choices=["both", "zh", "ja"])
    args = ap.parse_args()

    global MT_MODEL
    if args.model:
        MT_MODEL = args.model

    sys.stdout.reconfigure(encoding="utf-8")

    if args.list:
        list_devices()
        return
    if args.models:
        list_models()
        return

    gui = None
    if not args.no_gui:
        try:
            gui = Overlay(font_zh=args.font, width_ratio=args.width, alpha=args.alpha,
                          color=args.color, outline=args.outline, pos=args.pos,
                          fade=args.fade, scale=args.scale, mode=args.mode)
        except Exception as e:
            print(f"悬浮窗不可用（{type(e).__name__}），退回控制台模式")
            gui = None

    if args.file:
        print("加载模型…")
        pipe = Pipeline(args.srt, gui)
        pipe.vad = build_vad(args.min_silence, args.max_speech)
        warmup()
        audio = read_wav(args.file)
        print(f"文件 {args.file}：{len(audio)/SR:.1f}s，开始整句切分+识别+翻译\n")
        t0 = time.time()
        pipe.feed(audio)
        pipe.flush()
        print(f"\n总耗时 {time.time()-t0:.1f}s")
        if gui:
            gui.run()
        return

    print("加载模型…")
    pipe = Pipeline(args.srt, gui)
    pipe.vad = build_vad(args.min_silence, args.max_speech)
    warmup()
    print("就绪，开始监听系统声音")
    print("字幕条：拖动移动 · 滚轮调字号 · Ctrl+滚轮调宽度 · 右键菜单/右上角 ✕ 退出\n")

    q = queue.Queue()

    def reader():
        try:
            for chunk in capture_loopback(args.device):
                q.put(chunk)
        except Exception as e:
            print(f"[录音线程退出] {type(e).__name__}: {e}")
            q.put(None)

    threading.Thread(target=reader, daemon=True).start()

    def worker():
        while True:
            chunk = q.get()
            if chunk is None:
                break
            try:
                pipe.feed(chunk)
            except Exception as e:
                print(f"[处理异常] {type(e).__name__}: {e}")

    threading.Thread(target=worker, daemon=True).start()

    if gui:
        gui.run()
    else:
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
    pipe.flush()


if __name__ == "__main__":
    main()
