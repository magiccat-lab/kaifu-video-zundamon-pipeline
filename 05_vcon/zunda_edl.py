"""開封動画を「速さの表 + ずんだもんの台詞」から書き出す、いちばん単純なレンダラ。

声は全部ずんだもん (VOICEVOX)。開封の所は切らずに速さをなめらかに変え、台詞は映像の長さに合わせて組み直し、
テロップは台詞を全部焼き込む。元の録画の音は使わない。

使い方:
  VOICEVOX_DIR=<エンジンの dir> scripts/voicevox.sh start
  python zunda_edl.py <作業 dir>/edl.json <出力.mp4> [--report <出力.json>] [--font-name "BIZ UDGothic"]
  scripts/voicevox.sh stop
ffmpeg (libass つき) が要る。--font-name は ffmpeg が見つけられるフォントの名前。

edl の形: {"source": "proxy.mp4", "segments": [{"start", "end", "speed", "why"}], "cues": [{"at", "text", "say"?}]}
- source は edl のある dir からの相対
- segments は元の動画の秒。前の end と次の start が同じ所はつながった場面で、速さが変わる所は 1 秒かけて
  4 段でなめらかに変える。start が前の end と違う所だけが場面の切れ目 (そこは切る)
- cues の at は元の動画の秒 (「この出来事の所で言う」)。速さを変えても台詞は出来事に付いていく。
  前の台詞が終わってなければ後ろへずらし、ずれた秒を report に残す
- text はテロップに焼く字、say は読み (text と違う時だけ)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
import urllib.parse
import urllib.request
import wave
from pathlib import Path

import numpy as np

VOICEVOX = "http://127.0.0.1:50021"
SPEAKER = 3  # ずんだもん ノーマル
SPEED_SCALE = 1.1
RAMP_S = 1.0  # 速さが変わる所を、元の動画の何秒でならすか
RAMP_STEPS = 4
GAP_S = 0.15  # 台詞と台詞の間
SR = 24000
FONT = "BIZ UDGothic"  # テロップのフォント名。--font-name で替える
CACHE = Path.home() / ".cache" / "zunda_edl"


def pieces(segments: list[dict]) -> list[tuple[float, float, float]]:
    """区間を (start, end, speed) の切れ端に。つながった所の速さの変わり目に段を入れる。"""
    out: list[tuple[float, float, float]] = []
    for i, seg in enumerate(segments):
        start, end, speed = float(seg["start"]), float(seg["end"]), float(seg["speed"])
        prev = segments[i - 1] if i else None
        nxt = segments[i + 1] if i + 1 < len(segments) else None
        joined_prev = prev is not None and abs(float(prev["end"]) - start) < 1e-6 and float(prev["speed"]) != speed
        joined_next = nxt is not None and abs(float(nxt["start"]) - end) < 1e-6 and float(nxt["speed"]) != speed
        a = start + (RAMP_S / 2 if joined_prev else 0.0)
        b = end - (RAMP_S / 2 if joined_next else 0.0)
        if b - a > 0.02:
            out.append((a, b, speed))
        if joined_next:
            target = float(nxt["speed"])
            width = RAMP_S / RAMP_STEPS
            t0 = end - RAMP_S / 2
            for k in range(RAMP_STEPS):
                ratio = (k + 1) / (RAMP_STEPS + 1)
                out.append((t0 + k * width, t0 + (k + 1) * width, round(speed + (target - speed) * ratio, 3)))
    return out


def out_time(cuts: list[tuple[float, float, float]], t: float) -> float:
    """元の動画の秒を、書き出した動画の秒に。切った所の秒は次の場面の頭に寄せる。"""
    acc = 0.0
    for start, end, speed in cuts:
        if t < start:
            return acc
        if t <= end:
            return acc + (t - start) / speed
        acc += (end - start) / speed
    return acc


def synth(text: str) -> Path:
    key = hashlib.sha1(f"{SPEAKER}|{SPEED_SCALE}|{text}".encode()).hexdigest()[:16]
    path = CACHE / f"{key}.wav"
    if path.exists():
        return path
    CACHE.mkdir(parents=True, exist_ok=True)
    query_url = f"{VOICEVOX}/audio_query?" + urllib.parse.urlencode({"text": text, "speaker": SPEAKER})
    query = json.loads(urllib.request.urlopen(urllib.request.Request(query_url, method="POST"), timeout=60).read())
    query.update({"speedScale": SPEED_SCALE, "outputSamplingRate": SR, "outputStereo": False})
    req = urllib.request.Request(f"{VOICEVOX}/synthesis?speaker={SPEAKER}", data=json.dumps(query).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    path.write_bytes(urllib.request.urlopen(req, timeout=120).read())
    return path


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path)) as w:
        assert w.getframerate() == SR and w.getnchannels() == 1
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32)


def tighten(text: str) -> str:
    """テロップは数字と字の間を空けない (台本では読みやすさで「6 パック」と空けてある)。"""
    return re.sub(r"(?<=[0-9A-Za-z,.]) (?=[^ -~])|(?<=[^ -~]) (?=[0-9])", "", text)


def wrap(text: str, limit: int = 20) -> str:
    """1 行 20 字を超えたら、真ん中に近い句読点の後で折る (テロップ 2 行まで)。"""
    text = tighten(text)
    if "\n" in text:  # 台本に改行を書いた所はそのまま (商品名のように句読点で折れない行)
        return r"\N".join(part.strip() for part in text.split("\n"))
    if len(text) <= limit:
        return text
    marks = [i + 1 for i, ch in enumerate(text) if ch in "、。！？…" and 4 <= i + 1 <= len(text) - 4]
    cut = min(marks, key=lambda i: abs(i - len(text) / 2)) if marks else len(text) // 2
    return text[:cut].rstrip() + r"\N" + text[cut:].lstrip()


def ass_time(t: float) -> str:
    cs = int(round(t * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def build(edl_path: Path, out_path: Path, report_path: Path | None, font_name: str = FONT) -> dict:
    edl = json.loads(edl_path.read_text(encoding="utf-8"))
    source = (edl_path.parent / edl["source"]).resolve()
    cuts = pieces(edl["segments"])
    total = sum((b - a) / s for a, b, s in cuts)
    placed, cursor = [], 0.0
    for cue in edl["cues"]:
        clip = synth(cue.get("say") or cue["text"])
        samples = read_wav(clip)
        want = out_time(cuts, float(cue["at"]))
        start = max(want, cursor + GAP_S if placed else want)
        end = start + len(samples) / SR
        placed.append({"at": cue["at"], "text": cue["text"], "start": round(start, 2), "end": round(end, 2),
                       "late": round(start - want, 2), "samples": samples})
        cursor = end
    length = max(total, cursor + 0.5)
    track = np.zeros(int(length * SR) + SR, dtype=np.float32)
    for p in placed:
        i = int(p["start"] * SR)
        track[i:i + len(p["samples"])] += p["samples"]
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        voice = tmpdir / "voice.wav"
        with wave.open(str(voice), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes(np.clip(track, -32768, 32767).astype(np.int16).tobytes())
        subs = tmpdir / "subs.ass"
        events = "\n".join(
            f"Dialogue: 0,{ass_time(p['start'])},{ass_time(p['end'] + 0.25)},Z,,0,0,0,,{wrap(p['text'])}"
            for p in placed)
        subs.write_text(
            "[Script Info]\nScriptType: v4.00+\nPlayResX: 1280\nPlayResY: 720\nWrapStyle: 2\n\n"
            "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
            "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
            "MarginL, MarginR, MarginV, Encoding\n"
            f"Style: Z,{font_name},46,&H00FFFFFF,&H00FFFFFF,&H00305020,&H80000000,1,0,0,0,100,100,0,0,1,4,1,2,40,40,36,1\n\n"
            "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n" + events + "\n",
            encoding="utf-8")
        parts = [f"[0:v]split={len(cuts)}" + "".join(f"[s{i}]" for i in range(len(cuts)))]
        for i, (a, b, s) in enumerate(cuts):
            parts.append(f"[s{i}]trim=start={a:.3f}:end={b:.3f},setpts=(PTS-STARTPTS)/{s}[v{i}]")
        parts.append("".join(f"[v{i}]" for i in range(len(cuts))) + f"concat=n={len(cuts)}:v=1:a=0,fps=30,"
                     f"tpad=stop_mode=clone:stop_duration={max(0.0, length - total):.2f},"
                     f"subtitles=filename={subs}[vout]")
        graph = tmpdir / "graph.txt"
        graph.write_text(";\n".join(parts), encoding="utf-8")
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(source), "-i", str(voice),
               "-filter_complex_script", str(graph), "-map", "[vout]", "-map", "1:a",
               "-c:v", "libx264", "-preset", "medium", "-crf", "26", "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-b:a", "128k", "-shortest", str(out_path)]
        subprocess.run(cmd, check=True)
    report = {
        "source": str(source), "out": str(out_path), "length_s": round(length, 1), "video_s": round(total, 1),
        "pieces": len(cuts),
        "cues": [{k: v for k, v in p.items() if k != "samples"} for p in placed],
        "late_over_2s": [p["text"] for p in placed if p["late"] > 2.0],
    }
    if report_path:
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("edl")
    parser.add_argument("out")
    parser.add_argument("--report", default="")
    parser.add_argument("--font-name", default=FONT, help="テロップのフォント名 (ffmpeg / libass が見つける物)")
    args = parser.parse_args()
    report = build(Path(args.edl), Path(args.out), Path(args.report) if args.report else None, args.font_name)
    print(json.dumps({k: report[k] for k in ("length_s", "video_s", "pieces", "late_over_2s")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
