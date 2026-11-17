# -*- coding: utf-8 -*-
"""浏览器插件使用的本地字幕服务。

两种工作模式：
  --loopback  服务自己抓系统声音，插件通过 HTTP /subs 轮询字幕（当前默认链路）
  默认模式    插件通过 WebSocket 推送 16kHz Int16LE 单声道 PCM（保留给旧客户端和自检）
"""
import asyncio
import base64
import hashlib
import json
import os
import queue
import struct
import sys
import threading
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_HERE, "libs"))   # numpy 等手装的依赖在这里
LOG_DIR = os.path.join(_HERE, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

import numpy as np

# 被 pythonw.exe 静默启动时没有控制台：stdout/stderr 是 None，全部落到日志文件
if sys.stdout is None or sys.stderr is None:
    _log = open(os.path.join(LOG_DIR, "server.log"), "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = _log
else:
    try:
        sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
        sys.stderr.reconfigure(encoding="utf-8", line_buffering=True)
    except Exception:
        pass

PORT = int(os.environ.get("JA_WS_PORT", "8765"))
MT_ALLOWED = {"qwen3.5:latest", "qwen2.5:3b"}   # 允许切换的翻译模型


def _already_running():
    """端口已被占用 → 说明服务在跑，别再起第二份模型。"""
    import socket
    s = socket.socket()
    s.settimeout(0.3)
    try:
        s.connect(("127.0.0.1", PORT))
        return True
    except OSError:
        return False
    finally:
        s.close()


if _already_running():
    print(f"服务已在 {PORT} 端口运行，本次启动直接退出")
    sys.exit(0)

import live_ja as L

GUID = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
SR = L.SR

CLIENTS = 0          # 当前连着几个插件
LAST_SEEN = time.time()
IDLE_EXIT = float(os.environ.get("JA_IDLE_EXIT", "1800"))  # 无连接满 30 分钟自动退出

LOOPBACK = "--loopback" in sys.argv      # 服务自己抓系统声音，插件只负责显示
SUBS = []                                 # 已产出的字幕（供 HTTP 轮询）
SUBS_LOCK = threading.Lock()
SUBS_SEQ = 0


def push_sub(ja, zh):
    global SUBS_SEQ
    with SUBS_LOCK:
        SUBS_SEQ += 1
        SUBS.append({"i": SUBS_SEQ, "ja": ja, "zh": zh})
        del SUBS[:-200]


class SubSink:
    """回环模式出口：只写字幕缓存，不依赖任何 WS 连接。"""

    def push(self, ja, zh):
        # 回显交给 Pipeline（verbose=True 会打 [JA]/[ZH] + 耗时），这里只写缓存，
        # 否则每句都会重复打印两遍。
        push_sub(ja, zh)


def start_loopback():
    def run():
        pipe = L.Pipeline(None, SubSink(), verbose=True)
        print("[*] 回环采集已启动（抓系统声音）", flush=True)
        for chunk in L.capture_loopback(None):
            pipe.feed(chunk)
    threading.Thread(target=run, daemon=True).start()


# ─────────────────────────── 极简 WebSocket ───────────────────────────
async def handshake(reader, writer):
    req = await reader.readuntil(b"\r\n\r\n")
    if req.startswith(b"GET /quit") or req.startswith(b"POST /quit"):
        # 关字幕时让服务自己退出：显存和内存立刻还回去
        body = b'{"ok":true}'
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                     b"Access-Control-Allow-Origin: *\r\nContent-Length: "
                     + str(len(body)).encode() + b"\r\n\r\n" + body)
        await writer.drain()
        print("[*] 收到退出请求，卸载模型后退出", flush=True)
        try:
            L.unload_mt()
        except Exception:
            pass
        os._exit(0)

    if req.startswith(b"GET /subs"):
        # 插件用 HTTP 轮询取字幕：不依赖 WS，也不依赖 offscreen 文档
        line = req.split(b"\r\n", 1)[0].decode("latin1", "replace")
        q = line.split(" ")[1] if len(line.split(" ")) > 1 else "/subs"
        since = 0
        if "since=" in q:
            try:
                since = int(q.split("since=")[1].split("&")[0])
            except ValueError:
                since = 0
        with SUBS_LOCK:
            items = [x for x in SUBS if x["i"] > since]
            last = SUBS_SEQ
        body = json.dumps({"items": items, "last": last,
                           "src": "loopback" if LOOPBACK else "ws"}).encode("utf-8")
        writer.write(b"HTTP/1.1 200 OK\r\n"
                     b"Content-Type: application/json; charset=utf-8\r\n"
                     b"Access-Control-Allow-Origin: *\r\n"
                     b"Cache-Control: no-store\r\n"
                     b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body)
        await writer.drain()
        try:
            writer.close()
        except Exception:
            pass
        return False
    # 诊断上报：插件 POST /diag 一行文本，落到 diag.log（定位浏览器侧问题用）
    if req.startswith(b"POST /diag"):
        body = req.split(b"\r\n\r\n", 1)[1]
        n = 0
        for line in req.split(b"\r\n"):
            if line.lower().startswith(b"content-length:"):
                try:
                    n = int(line.split(b":", 1)[1])
                except ValueError:
                    n = 0
        while len(body) < n:
            more = await reader.read(n - len(body))
            if not more:
                break
            body += more
        try:
            with open(os.path.join(LOG_DIR, "diag.log"), "a", encoding="utf-8") as f:
                f.write(time.strftime("%H:%M:%S ") + body.decode("utf-8", "replace").strip() + "\n")
        except Exception:
            pass
        writer.write(b"HTTP/1.1 204 No Content\r\nContent-Length: 0\r\n"
                     b"Access-Control-Allow-Origin: *\r\n\r\n")
        await writer.drain()
        try:
            writer.close()
        except Exception:
            pass
        return False
    m = None
    for line in req.split(b"\r\n"):
        if line.lower().startswith(b"sec-websocket-key:"):
            m = line.split(b":", 1)[1].strip()
            break
    if not m:
        writer.close()
        return False
    acc = base64.b64encode(hashlib.sha1(m + GUID).digest()).decode()
    writer.write(
        b"HTTP/1.1 101 Switching Protocols\r\n"
        b"Upgrade: websocket\r\nConnection: Upgrade\r\n"
        b"Sec-WebSocket-Accept: " + acc.encode() + b"\r\n\r\n")
    await writer.drain()
    return True


async def read_frame(reader):
    h = await reader.readexactly(2)
    op = h[0] & 0x0F
    masked = h[1] & 0x80
    n = h[1] & 0x7F
    if n == 126:
        n = struct.unpack(">H", await reader.readexactly(2))[0]
    elif n == 127:
        n = struct.unpack(">Q", await reader.readexactly(8))[0]
    mask = await reader.readexactly(4) if masked else None
    data = await reader.readexactly(n) if n else b""
    if mask:
        k = np.frombuffer(mask * (n // 4 + 1), dtype=np.uint8)[:n]
        data = (np.frombuffer(data, dtype=np.uint8) ^ k).tobytes()
    return op, data


def encode_text(s):
    b = s.encode("utf-8")
    n = len(b)
    if n < 126:
        hdr = bytes([0x81, n])
    elif n < 65536:
        hdr = bytes([0x81, 126]) + struct.pack(">H", n)
    else:
        hdr = bytes([0x81, 127]) + struct.pack(">Q", n)
    return hdr + b


# ─────────────────────────── 每个连接一个管道 ───────────────────────────
class Sink:
    """把 Pipeline 的产出转成 WS 文本帧（跨线程安全）。"""

    def __init__(self, loop, writer):
        self.loop = loop
        self.writer = writer
        self.alive = True
        self.q = queue.Queue()

    def push(self, ja, zh):
        push_sub(ja, zh)
        if not self.alive:
            return
        payload = json.dumps({"ja": ja, "zh": zh}, ensure_ascii=False)
        self.loop.call_soon_threadsafe(lambda: self.q.put(payload))

    def drain(self):
        while True:
            try:
                p = self.q.get_nowait()
            except queue.Empty:
                return
            if self.alive:
                try:
                    self.writer.write(encode_text(p))
                except Exception:
                    self.alive = False
                    return


def worker(sink, inp):
    pipe = L.Pipeline(None, sink, verbose=True)   # 4.2s 的模型加载在这里，不挡事件循环
    pipe.vad = L.build_vad()
    print("[*] 识别管道就绪", flush=True)
    while True:
        chunk = inp.get()
        if chunk is None:
            break
        try:
            if isinstance(chunk, str):        # 控制指令
                if chunk == "flush":
                    pipe.flush()
            else:
                pipe.feed(chunk)
        except Exception as e:
            print(f"[worker] {type(e).__name__}: {e}", file=sys.stderr)
        sink.drain()


async def serve(reader, writer):
    global CLIENTS, LAST_SEEN
    # 关键：裸 TCP 连一下就断开（端口探测/扫描器）不能让整个服务崩掉
    try:
        ok = await handshake(reader, writer)
    except Exception:
        ok = False
    if not ok:
        try:
            writer.close()
        except Exception:
            pass
        return
    CLIENTS += 1
    LAST_SEEN = time.time()
    loop = asyncio.get_running_loop()
    sink = Sink(loop, writer)
    inp = queue.Queue()
    # 关键：Pipeline 会同步加载识别模型（实测阻塞 4.2 秒）。
    # 放在事件循环里会把整个服务卡住——ready 帧发不出去、客户端发来的帧也读不到，
    # 表现就是「连上就断、一句字幕都没有」。所以改到 worker 线程里建。
    th = threading.Thread(target=worker, args=(sink, inp), daemon=True)
    th.start()
    print(f"[+] 插件连上了（{writer.get_extra_info('peername')}）")
    writer.write(encode_text(json.dumps({"type": "ready"})))
    last = time.time()
    try:
        while True:
            op, data = await read_frame(reader)
            if op == 8:
                break
            if op == 9:                      # ping → pong
                writer.write(bytes([0x8A, len(data)]) + data)
                await writer.drain()
                continue
            if op == 2 and data:             # 二进制：PCM
                pcm = np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768.0
                inp.put(pcm)
            elif op == 1 and data:           # 文本：控制指令
                try:
                    cmd = json.loads(data.decode("utf-8"))
                except Exception:
                    cmd = {}
                c = cmd.get("cmd")
                if c == "hello":
                    # 插件一进来就报自己的代码版本，确认浏览器跑的是不是最新这份 JS
                    print(f"[*] 插件代码版本 build={cmd.get('build')}")
                elif c == "flush":
                    inp.put("flush")
                elif c == "model":
                    name = str(cmd.get("name") or "")
                    okm = name in MT_ALLOWED
                    if okm:
                        L.MT_MODEL = name
                        threading.Thread(target=L.warmup, daemon=True).start()
                        print(f"[*] 翻译模型切换为 {name}")
                    writer.write(encode_text(json.dumps(
                        {"type": "model", "ok": okm, "name": name})))
                    await writer.drain()
            LAST_SEEN = time.time()
            sink.drain()
            if time.time() - last > 0.2:
                await writer.drain()
                last = time.time()
    except (asyncio.IncompleteReadError, ConnectionResetError):
        pass
    except Exception as e:
        print(f"[!] {type(e).__name__}: {e}", file=sys.stderr)
    finally:
        CLIENTS = max(0, CLIENTS - 1)
        LAST_SEEN = time.time()
        sink.alive = False
        inp.put(None)
        try:
            writer.close()
        except Exception:
            pass
        print("[-] 插件断开")


async def _watchdog():
    while True:
        await asyncio.sleep(30)
        if not LOOPBACK and CLIENTS == 0 and time.time() - LAST_SEEN > IDLE_EXIT:
            print("长时间没有插件连接，自动退出")
            os._exit(0)


async def main():
    port = PORT
    print("加载模型…")
    L.warmup()
    if LOOPBACK:
        start_loopback()
    srv = await asyncio.start_server(serve, "127.0.0.1", port)
    print(f"就绪：ws://127.0.0.1:{port}   （插件里点“开启字幕”即可）")
    asyncio.create_task(_watchdog())
    async with srv:
        await srv.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n停止")
