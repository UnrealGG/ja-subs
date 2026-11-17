# -*- coding: utf-8 -*-
"""日译中延迟/质量测试：走 ollama 本地 API。"""
import json, time, sys, urllib.request

OLLAMA = "http://127.0.0.1:11434/api/chat"
MODEL = "qwen3.5:latest"
SYS = "你是日语同声传译。把日语字幕翻成简体中文，只输出译文本身，不要解释、不要加引号。"


def chat(ja, ctx=2048, predict=120, think=False, stream=True):
    body = {
        "model": MODEL,
        "messages": [{"role": "system", "content": SYS},
                     {"role": "user", "content": ja}],
        "stream": stream,
        "think": think,
        "options": {"num_ctx": ctx, "temperature": 0.1, "num_predict": predict},
    }
    req = urllib.request.Request(OLLAMA, json.dumps(body).encode("utf-8"),
                                 {"Content-Type": "application/json"})
    t0 = time.time()
    ttft = None
    parts = []
    with urllib.request.urlopen(req, timeout=300) as r:
        for line in r:
            line = line.strip()
            if not line:
                continue
            ev = json.loads(line)
            msg = ev.get("message") or {}
            piece = msg.get("content") or ""
            if piece:
                if ttft is None:
                    ttft = time.time() - t0
                parts.append(piece)
            if ev.get("done"):
                total = time.time() - t0
                ec = ev.get("eval_count", 0)
                ed = ev.get("eval_duration", 1) / 1e9
                return "".join(parts).strip(), ttft, total, ec, ec / ed if ed else 0
    return "".join(parts).strip(), ttft, time.time() - t0, 0, 0


CASES = [
    "今日はいい天気ですね。",
    "このゲームは思ったより難しいです。",
    "すみません、もう一度言っていただけますか。",
    "彼はその話を聞いて、少し悲しそうな顔をしました。",
    "申し訳ありませんが、その件についてはまだ検討中です。",
]


def main():
    out = sys.stdout
    out.reconfigure(encoding="utf-8")
    print(f"model={MODEL}", flush=True)
    for ja in CASES:
        try:
            zh, ttft, total, n, tps = chat(ja)
            print(f"JA  {ja}", flush=True)
            print(f"ZH  {zh}", flush=True)
            print(f"    ttft={ttft:.2f}s total={total:.2f}s tok={n} {tps:.1f}tok/s\n", flush=True)
        except Exception as e:
            print(f"ERR {type(e).__name__}: {str(e)[:200]}", flush=True)


if __name__ == "__main__":
    main()
