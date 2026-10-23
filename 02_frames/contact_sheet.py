"""ffmpeg で fps ごとのコマを出し、PIL でタイル状に並べて左上に元の時刻を焼く。

札が見える所 ・ 手が止まる所を目で探すためのコンタクトシート。
使い方: python contact_sheet.py <動画> <開始秒> <終了秒> <fps> <列数> <出力.jpg> [--width 480]
コマは一時 dir に出し、シートを書いたら消す。コマの高さは 16:9 として幅から決める。
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video")
    ap.add_argument("start", type=float)
    ap.add_argument("end", type=float)
    ap.add_argument("fps", type=float)
    ap.add_argument("cols", type=int)
    ap.add_argument("out")
    ap.add_argument("--width", type=int, default=480)
    args = ap.parse_args()

    w = args.width
    h = int(w * 720 / 1280)
    frames_dir = Path(tempfile.mkdtemp(prefix="contact_sheet_"))
    try:
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-ss", str(args.start), "-t", str(args.end - args.start),
             "-i", args.video, "-vf", f"fps={args.fps},scale={w}:-1", "-q:v", "3", str(frames_dir / "%04d.jpg")],
            check=True,
        )
        files = sorted(frames_dir.iterdir())
        rows = (len(files) + args.cols - 1) // args.cols
        sheet = Image.new("RGB", (args.cols * w, rows * h))
        for i, f in enumerate(files):
            im = Image.open(f)
            t = args.start + i / args.fps
            draw = ImageDraw.Draw(im)
            draw.rectangle([0, 0, 95, 18], fill=(0, 0, 0))
            draw.text((3, 3), f"{int(t // 60):02d}:{t % 60:04.1f}", fill=(255, 255, 0))
            sheet.paste(im, ((i % args.cols) * w, (i // args.cols) * h))
        sheet.save(args.out, quality=85)
        print(sheet.size, len(files))
    finally:
        shutil.rmtree(frames_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
