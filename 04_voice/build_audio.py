"""ずんだもん (VOICEVOX の speaker 3、既定 1.1 倍速、48kHz モノラル) で原稿を読ませる。

使い方: python build_audio.py <spoken_zunda.json> <out_dir> [--base http://127.0.0.1:50021] [--speaker 3] [--speed 1.1]
入力: make_spoken.py の出力。各段落は yomi があればそちら、無ければ zunda を読む。
      読ませる前に tts_text_ja.preprocess (kata_numbers=True) で数字と英字を仮名にする。

作り方: 文 (。！？で切る) ごとに合成し、固定の間を入れてつなぐ。
  足す間は 文と文 0.4 秒 ・ 段落と段落 0.8 秒 ・ 区切り (cue) と区切り 1.3 秒。
  実際の無音は、声の前後の余白 (pre 0.05 秒 ・ post 0.15 秒) が付くので文の間で 0.55〜0.65 秒くらいになる。
  段落に pause_before (秒) があれば、その段落の前の間は 0.8 秒の代わりにその長さにする。

出力 (<out_dir>):
  p<i>.wav     段落ごと (i は spoken の i)
  cue<c>.wav   区切りごと (段落を間でつないだ物)
  full.wav     全部 (区切りの間 1.3 秒でつないだ物)
  lens.json    {区切り番号: 秒}

先に scripts/voicevox.sh start で VOICEVOX ENGINE を起こしておく。
"""
from __future__ import annotations

import argparse
import io
import json
import re
import urllib.parse
import urllib.request
import wave
from pathlib import Path

import numpy as np

from tts_text_ja import preprocess

SR = 48000
SENT_GAP, PARA_GAP, CUE_GAP = 0.4, 0.8, 1.3


def read_wav(data: bytes) -> np.ndarray:
    """16bit モノラルの wav (bytes) を -1〜1 の float32 に。"""
    with wave.open(io.BytesIO(data)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), "<i2").astype("float32") / 32768


def write_wav(path: Path, samples: np.ndarray) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())


def sentences(text: str) -> list[str]:
    return [x for x in re.split(r"(?<=[。！？])", text) if x.strip()]


def silence(seconds: float) -> np.ndarray:
    return np.zeros(int(SR * seconds), "float32")


def synth(text: str, base: str, speaker: int, speed: float) -> np.ndarray:
    query_url = f"{base}/audio_query?" + urllib.parse.urlencode(
        {"text": preprocess(text, kata_numbers=True), "speaker": speaker}
    )
    req = urllib.request.Request(query_url, method="POST")
    query = json.loads(urllib.request.urlopen(req, timeout=120).read())
    query.update(outputSamplingRate=SR, speedScale=speed, prePhonemeLength=0.05, postPhonemeLength=0.15)
    req = urllib.request.Request(
        f"{base}/synthesis?speaker={speaker}",
        data=json.dumps(query).encode(),
        headers={"Content-Type": "application/json"},
    )
    return read_wav(urllib.request.urlopen(req, timeout=300).read())


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("spoken")
    ap.add_argument("out_dir")
    ap.add_argument("--base", default="http://127.0.0.1:50021")
    ap.add_argument("--speaker", type=int, default=3)
    ap.add_argument("--speed", type=float, default=1.1)
    args = ap.parse_args()

    paras = json.load(open(args.spoken, encoding="utf-8"))
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    sent_gap = silence(SENT_GAP)
    cues: dict[int, list[tuple[np.ndarray, float | None]]] = {}
    for p in paras:
        # yomi: 字幕と違う読み (make_spoken.py)
        parts = [synth(s, args.base, args.speaker, args.speed) for s in sentences(p.get("yomi") or p["zunda"])]
        y = parts[0]
        for z in parts[1:]:
            y = np.concatenate([y, sent_gap, z])
        write_wav(out / f"p{p['i']}.wav", y)
        cues.setdefault(p["cue"], []).append((y, p.get("pause_before")))

    para_gap, cue_gap = silence(PARA_GAP), silence(CUE_GAP)
    full: list[np.ndarray] = []
    lens: dict[int, float] = {}
    for c in sorted(cues):
        paras_in_cue = cues[c]
        joined = paras_in_cue[0][0]
        for y, pause_before in paras_in_cue[1:]:
            # pause_before: 段落の前の間 (秒)。クイズの考える時間など
            gap = silence(pause_before) if pause_before else para_gap
            joined = np.concatenate([joined, gap, y])
        write_wav(out / f"cue{c}.wav", joined)
        lens[c] = round(len(joined) / SR, 1)
        full += [joined, cue_gap]
    full_wav = np.concatenate(full[:-1])
    write_wav(out / "full.wav", full_wav)
    json.dump(lens, open(out / "lens.json", "w"), indent=0)
    print("cues", len(cues), "full", f"{len(full_wav) / SR / 60:.1f} min", lens)


if __name__ == "__main__":
    main()
