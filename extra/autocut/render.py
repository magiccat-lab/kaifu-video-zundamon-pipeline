"""カット表 (cutplan.py の json) の通りに動画を書き出す。見比べ用に、版の頭へ題の札を挟んでつなげられる。

使い方:
  python render.py <元の動画> <出力.mp4> <cuts.json>[=題] [<cuts.json>[=題] ...] [--height 720] [--crf 26] [--font <フォント>]
  題を付けた版は、頭に 1.5 秒の題の札 (黒地に白字) を挟む。版を並べると見比べ用の 1 本になる。
切れ目は素のカット (ジャンプカット)。題の札のフォントは --font <path> か環境変数 TITLE_FONT (題を付けた時だけ要る)。
音は切れ目で 15ms だけフェードしてプチっと鳴らないようにする。
speed が 1 でない区間は映像を速め、音は atempo で同じだけ速める。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

FADE = 0.015


def atempo_chain(speed: float) -> str:
    parts, s = [], speed
    while s > 2.0:
        parts.append("atempo=2.0")
        s /= 2.0
    parts.append(f"atempo={s:.4f}")
    return ",".join(parts)


def render_cuts(src: Path, cuts: dict, out: Path, height: int, crf: int) -> None:
    segs = cuts["segments"]
    chains, labels = [], []
    for i, g in enumerate(segs):
        s, e, sp = g["start"], g["end"], g.get("speed", 1.0)
        d = (e - s) / sp
        v = f"[0:v]trim=start={s}:end={e},setpts=(PTS-STARTPTS)/{sp},scale=-2:{height},fps=30000/1001[v{i}]"
        a = f"[0:a]atrim=start={s}:end={e},asetpts=PTS-STARTPTS"
        if sp != 1.0:
            a += "," + atempo_chain(sp)
        a += f",afade=t=in:d={FADE},afade=t=out:st={max(0.0, d - FADE):.3f}:d={FADE}[a{i}]"
        chains += [v, a]
        labels.append(f"[v{i}][a{i}]")
    graph = ";".join(chains) + ";" + "".join(labels) + f"concat=n={len(segs)}:v=1:a=1[v][a]"
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as fh:
        fh.write(graph)
        script = fh.name
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-filter_complex_script", script,
                    "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k", "-ar", "48000", "-ac", "2", str(out)],
                   check=True)


def render_card(text: str, out: Path, height: int, crf: int, font: str) -> None:
    w = height * 16 // 9
    esc = text.replace(":", r"\:").replace("'", r"\'")
    vf = (f"drawtext=fontfile={font}:text='{esc}':fontcolor=white:fontsize={height // 12}:"
          "x=(w-text_w)/2:y=(h-text_h)/2")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=black:s={w}x{height}:r=30000/1001:d=1.5",
                    "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", "1.5", "-vf", vf,
                    "-c:v", "libx264", "-preset", "medium", "-crf", str(crf), "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "96k", str(out)], check=True)


def main() -> None:
    args = sys.argv[1:]
    height, crf = 720, 26
    if "--height" in args:
        i = args.index("--height"); height = int(args[i + 1]); del args[i:i + 2]
    if "--crf" in args:
        i = args.index("--crf"); crf = int(args[i + 1]); del args[i:i + 2]
    font = os.environ.get("TITLE_FONT", "")
    if "--font" in args:
        i = args.index("--font"); font = args[i + 1]; del args[i:i + 2]
    src, out, specs = Path(args[0]), Path(args[1]), args[2:]
    if any("=" in s for s in specs) and not font:
        sys.exit("title cards need a font: pass --font <path> or set TITLE_FONT")
    tmp = Path(tempfile.mkdtemp(prefix="ov_render_"))
    parts: list[Path] = []
    for k, spec in enumerate(specs):
        path, _, title = spec.partition("=")
        if title:
            card = tmp / f"card{k}.mp4"
            render_card(title, card, height, crf, font)
            parts.append(card)
        clip = tmp / f"clip{k}.mp4"
        render_cuts(src, json.loads(Path(path).read_text(encoding="utf-8")), clip, height, crf)
        parts.append(clip)
    if len(parts) == 1:
        parts[0].replace(out)
    else:
        lst = tmp / "list.txt"
        lst.write_text("".join(f"file '{p}'\n" for p in parts), encoding="utf-8")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy",
                        "-movflags", "+faststart", str(out)], check=True)
    dur = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                                         "default=nw=1:nk=1", str(out)]))
    print(f"{out}: {dur:.1f}s {out.stat().st_size / 1e6:.1f}MB")


if __name__ == "__main__":
    main()
