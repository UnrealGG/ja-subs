# -*- coding: utf-8 -*-
"""日语 ASR 测试：sherpa-onnx + ReazonSpeech zipformer (transducer)。

用法:
  python test_asr.py            # 自动找 models 下的日语模型并用其自带 test_wavs
  python test_asr.py a.wav b.wav
"""
import sys, os, glob, time, wave

from _paths import ROOT

sys.stdout.reconfigure(encoding="utf-8")

import sherpa_onnx  # noqa: E402
import numpy as np  # noqa: E402


def load_wav(path, target_sr=16000):
    """读 wav -> (采样率, float32 单声道 [-1,1])，sherpa 2.0.1 没有 read_wave。"""
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
        sr = target_sr
    return sr, a


def find_model_dir():
    roots = [os.path.join(ROOT, "model_ja")] + sorted(glob.glob(os.path.join(ROOT, "models", "*")))
    for d in roots:
        if not os.path.isdir(d):
            continue
        try:
            if glob.glob(os.path.join(d, "**", "*encoder*.onnx"), recursive=True):
                return d
        except OSError:
            continue  # 跳过被 Windows 权限锁死的目录
    raise SystemExit("没找到模型目录")


def pick(d, pattern):
    hits = glob.glob(os.path.join(d, "**", pattern), recursive=True)
    # 优先 int8
    int8 = [h for h in hits if "int8" in os.path.basename(h)]
    return (int8 or hits or [None])[0]


def build(mdir):
    enc = pick(mdir, "*encoder*.onnx")
    dec = pick(mdir, "*decoder*.onnx")
    joi = pick(mdir, "*joiner*.onnx")
    tok = pick(mdir, "tokens.txt")
    print(f"model dir : {os.path.relpath(mdir, ROOT)}")
    for k, v in (("encoder", enc), ("decoder", dec), ("joiner", joi), ("tokens", tok)):
        print(f"  {k:8}: {os.path.relpath(v, ROOT) if v else 'MISSING'} "
              f"({round(os.path.getsize(v)/1e6,1)}MB)" if v else f"  {k:8}: MISSING")
    return sherpa_onnx.OfflineRecognizer.from_transducer(
        encoder=enc, decoder=dec, joiner=joi, tokens=tok,
        num_threads=4, sample_rate=16000, feature_dim=80,
        decoding_method="greedy_search", provider="cpu",
    )


def dur_of(path):
    with wave.open(path, "rb") as w:
        return w.getnframes() / w.getframerate()


def main():
    wavs = sys.argv[1:]
    mdir = find_model_dir()
    if not wavs:
        wavs = sorted(glob.glob(os.path.join(mdir, "test_wavs", "*.wav")))
        if not wavs:
            wavs = sorted(glob.glob(os.path.join(mdir, "**", "*.wav"), recursive=True))[:5]
    if not wavs:
        raise SystemExit("没有可测的 wav")
    print(f"wavs      : {len(wavs)}\n")
    t0 = time.time()
    rec = build(mdir)
    print(f"load      : {time.time()-t0:.2f}s\n")

    total_audio = total_time = 0.0
    for w in wavs:
        sr, samples = load_wav(w)
        t = time.time()
        st = rec.create_stream()
        st.accept_waveform(sr, samples)
        rec.decode_stream(st)
        dt = time.time() - t
        d = dur_of(w)
        total_audio += d
        total_time += dt
        print(f"[{os.path.basename(w)}] {d:.1f}s audio -> {dt:.2f}s ({d/dt:.1f}x RT)")
        print(f"  {st.result.text}\n")
    if total_time:
        print(f"合计 {total_audio:.1f}s 音频 / {total_time:.2f}s 解码 = {total_audio/total_time:.1f}x 实时")


if __name__ == "__main__":
    main()
