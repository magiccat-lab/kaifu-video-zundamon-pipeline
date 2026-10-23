"""開封動画のカット表 (どこを残すか) を作る。描き出しはしない (render.py が読む)。

使い方: python cutplan.py \
          <動画> <作業 dir> --preset b [--hold 2.5] [--range 49 210] [--out cuts_b.json]
読む物: <作業 dir>/transcript.json (01_transcribe/transcribe.py) と <作業 dir>/activity.json (02_frames/activity.py)
出す物: <作業 dir>/<out> = {"source", "preset", "segments": [{"start", "end", "speed", "why"}], ...}

決まり (ジェットカットの考え方):
- しゃべっている所は残す。しゃべりの間 (無音) は preset の長さより長ければ、その長さまで詰める
- 言い直しは <作業 dir>/retakes.json ([{"start", "end", "why"}]、人が文字起こしを読んで決めた物) を落とす。
  無ければ、ほぼ同じ文 (一致 0.95 以上 ・ 10 字以上) を 20 秒以内に言い直した所だけ自動で落とす。
  一致の度合いだけで決めると「同じ言葉を二度言っただけ」も拾い、長い区間が消えることがあった
- 無音でも手が動いている所 (袋を開ける ・ 札をめくる) は「溜め」。次にしゃべり出す直前の hold 秒だけ等速で残し、
  その前は --speed 倍速で残す (1 なら落とす)。hold を負にすると溜めを丸ごと等速で残す
- 手も止まって音も無い所は preset の長さまで詰める
カットの表をデータで持つので、画面割りが後で決まっても同じ表から描き直せる。
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
from pathlib import Path

import numpy as np
from faster_whisper.audio import decode_audio
from faster_whisper.vad import VadOptions, get_speech_timestamps

# preset: (この長さより長い無音を詰める, 詰めた後の長さ, しゃべりの前の余白, 後の余白)
PRESETS = {
    "a": (0.9, 0.45, 0.12, 0.25),  # ゆるめ
    "b": (0.5, 0.22, 0.08, 0.15),  # 標準
    "c": (0.25, 0.06, 0.04, 0.08),  # 詰め (ジェットカット)
}
MOTION_ACTIVE = 2.5  # activity.json の motion がこれより上なら「手が動いている」
RETAKE_WINDOW_S = 20.0
RETAKE_RATIO = 0.95
SR = 16000


def norm(text: str) -> str:
    return re.sub(r"[\s、。,.!?！？ー〜…]", "", text)


def speech_regions(src: Path) -> list[tuple[float, float]]:
    audio = decode_audio(str(src), sampling_rate=SR)
    opts = VadOptions(threshold=0.5, min_speech_duration_ms=120, min_silence_duration_ms=120, speech_pad_ms=0)
    return [(t["start"] / SR, t["end"] / SR) for t in get_speech_timestamps(audio, opts)]


def retakes(segments: list[dict]) -> list[tuple[float, float, str]]:
    """同じ文を言い直した所 → (落とす始め, 落とす終わり, 理由)。前の方を落とし、言い直しの頭から残す。"""
    out = []
    for i, s in enumerate(segments):
        a = norm(s["text"])
        if len(a) < 8:
            continue
        for t in segments[i + 1:]:
            if t["start"] - s["start"] > RETAKE_WINDOW_S:
                break
            b = norm(t["text"])
            if len(a) >= 10 and len(b) >= 10 and difflib.SequenceMatcher(None, a, b).ratio() >= RETAKE_RATIO:
                out.append((s["start"], t["start"], f"言い直し: {s['text'][:20]}"))
                break
    merged: list[tuple[float, float, str]] = []
    for r in sorted(out):
        if merged and r[0] <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], r[1]), merged[-1][2])
        else:
            merged.append(r)
    return merged


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("workdir")
    ap.add_argument("--preset", default="b", choices=sorted(PRESETS))
    ap.add_argument("--hold", type=float, default=2.5, help="溜めの残す秒。負なら溜めを全部残す")
    ap.add_argument("--speed", type=float, default=1.0,
                    help="溜めの hold より前を何倍速で残すか。1 なら落とす (hold>0 の時だけ効く)")
    ap.add_argument("--range", nargs=2, type=float, default=None, help="この区間だけ (秒)")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    src, wd = Path(args.src), Path(args.workdir)
    tr = json.loads((wd / "transcript.json").read_text(encoding="utf-8"))
    act = json.loads((wd / "activity.json").read_text(encoding="utf-8"))
    motion, step = np.array(act["motion"]), act["step"]
    gap_max, gap_to, pre, post = PRESETS[args.preset]
    lo, hi = args.range or (0.0, tr["duration"])

    speech = [(max(lo, s - pre), min(hi, e + post)) for s, e in speech_regions(src) if e > lo and s < hi]
    manual = wd / "retakes.json"
    found = ([(r["start"], r["end"], r["why"]) for r in json.loads(manual.read_text(encoding="utf-8"))]
             if manual.exists() else retakes(tr["segments"]))
    drops = [r for r in found if r[1] > lo and r[0] < hi]

    # しゃべりの塊 (余白込み) から言い直しの区間を引く
    def minus(spans, cut):
        out = []
        for s, e in spans:
            for c0, c1, _ in cut:
                if c1 <= s or c0 >= e:
                    continue
                if c0 > s:
                    out.append((s, c0))
                s = max(s, c1)
                if s >= e:
                    break
            if s < e:
                out.append((s, e))
        return out

    speech = minus(speech, drops)
    merged: list[list[float]] = []
    for s, e in speech:
        if merged and s - merged[-1][1] <= gap_max:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])

    segs: list[dict] = []
    for i, (s, e) in enumerate(merged):
        if i > 0:
            gs, ge = merged[i - 1][1], s
            in_drop = any(c0 <= gs and ge <= c1 + 0.5 for c0, c1, _ in drops)
            m = motion[int(gs / step): max(int(gs / step) + 1, int(ge / step))]
            active = float(np.mean(m)) >= MOTION_ACTIVE if len(m) else False
            if not in_drop and active and args.hold < 0:
                segs.append({"start": round(gs, 2), "end": round(ge, 2), "speed": 1.0, "why": "溜め (全部)"})
            elif not in_drop and active and args.hold > 0:
                h = min(args.hold, ge - gs)
                if args.speed > 1.0 and ge - h - gs > 1.0:
                    segs.append({"start": round(gs, 2), "end": round(ge - h, 2), "speed": args.speed,
                                 "why": f"手の作業 ({args.speed:g} 倍速)"})
                segs.append({"start": round(ge - h, 2), "end": round(ge, 2), "speed": 1.0,
                             "why": f"溜め (最後の {h:.1f} 秒)"})
            else:
                # 間を gap_to だけ残す: 前の塊の後ろに足す
                segs[-1]["end"] = round(min(ge, segs[-1]["end"] + gap_to), 2)
        segs.append({"start": round(s, 2), "end": round(e, 2), "speed": 1.0, "why": "しゃべり"})

    # 隣と重なった物をまとめる
    final: list[dict] = []
    for g in segs:
        if final and g["start"] <= final[-1]["end"] + 0.02 and g["speed"] == final[-1]["speed"]:
            final[-1]["end"] = max(final[-1]["end"], g["end"])
            if g["why"] not in final[-1]["why"]:
                final[-1]["why"] += " + " + g["why"]
        else:
            final.append(dict(g))

    kept = sum((g["end"] - g["start"]) / g["speed"] for g in final)
    payload = {
        "source": str(src), "preset": args.preset, "hold": args.hold, "speed": args.speed, "range": [lo, hi],
        "raw_s": round(hi - lo, 1), "kept_s": round(kept, 1),
        "retakes": [{"start": round(a, 2), "end": round(b, 2), "why": w} for a, b, w in drops],
        "segments": final,
    }
    out = wd / (args.out or f"cuts_{args.preset}.json")
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{out.name}: {hi - lo:.0f}s -> {kept:.0f}s ({kept / (hi - lo) * 100:.0f}%), {len(final)} 切れ目, "
          f"言い直し {len(drops)}")


if __name__ == "__main__":
    main()
