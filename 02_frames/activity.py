"""開封動画の「動き」と「音」を 0.5 秒ごとに測る。カットの候補 (手が止まっている所) を探す材料。

使い方: python activity.py <動画> <出力 dir>
出力: <dir>/activity.json ({"step": 0.5, "motion": [...], "rms_db": [...]})
motion は 160x90 の灰色で 10fps の隣どうしの差の平均 (0〜255)。rms_db は音の大きさ (dBFS)。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np

W, H, FPS, STEP = 160, 90, 10, 0.5


def motion(src: Path) -> np.ndarray:
    cmd = ["ffmpeg", "-v", "error", "-i", str(src), "-vf", f"fps={FPS},scale={W}:{H},format=gray",
           "-f", "rawvideo", "-"]
    raw = subprocess.run(cmd, check=True, capture_output=True).stdout
    frames = np.frombuffer(raw, dtype=np.uint8).reshape(-1, H, W).astype(np.int16)
    diff = np.abs(np.diff(frames, axis=0)).mean(axis=(1, 2))
    per = int(FPS * STEP)
    n = len(diff) // per
    return diff[: n * per].reshape(n, per).mean(axis=1)


def loudness(src: Path) -> np.ndarray:
    sr = 16000
    cmd = ["ffmpeg", "-v", "error", "-i", str(src), "-vn", "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"]
    raw = subprocess.run(cmd, check=True, capture_output=True).stdout
    pcm = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768
    per = int(sr * STEP)
    n = len(pcm) // per
    rms = np.sqrt((pcm[: n * per].reshape(n, per) ** 2).mean(axis=1) + 1e-12)
    return 20 * np.log10(rms)


def main() -> None:
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    m, a = motion(src), loudness(src)
    n = min(len(m), len(a))
    payload = {"source": str(src), "step": STEP, "motion": [round(float(x), 2) for x in m[:n]],
               "rms_db": [round(float(x), 1) for x in a[:n]]}
    (out / "activity.json").write_text(json.dumps(payload), encoding="utf-8")
    print(f"{src.name}: {n * STEP:.0f}s motion p10={np.percentile(m, 10):.2f} p50={np.percentile(m, 50):.2f} "
          f"p90={np.percentile(m, 90):.2f}")


if __name__ == "__main__":
    main()
