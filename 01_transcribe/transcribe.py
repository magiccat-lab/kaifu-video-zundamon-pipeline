"""開封動画の音を faster-whisper large-v3 で文字起こしする (単語の時刻つき)。

使い方: python transcribe.py <動画> <出力 dir>
出力: <dir>/transcript.json (segments と words、秒) と <dir>/transcript.md ([mm:ss] 行)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from faster_whisper import WhisperModel


def main() -> None:
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    model = WhisperModel("large-v3", device="cuda", compute_type="float16")
    segments, info = model.transcribe(
        str(src),
        language="ja",
        word_timestamps=True,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 300},
        condition_on_previous_text=False,
    )
    segs = []
    for s in segments:
        segs.append({
            "start": round(s.start, 2),
            "end": round(s.end, 2),
            "text": s.text.strip(),
            "words": [{"start": round(w.start, 2), "end": round(w.end, 2), "word": w.word, "p": round(w.probability, 2)}
                      for w in (s.words or [])],
        })
    (out / "transcript.json").write_text(
        json.dumps({"source": str(src), "duration": round(info.duration, 2), "segments": segs},
                   ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    lines = [f"[{int(s['start'] // 60):02d}:{int(s['start'] % 60):02d}] {s['text']}" for s in segs]
    (out / "transcript.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"done {len(segs)} segments, {info.duration:.0f}s -> {out}")


if __name__ == "__main__":
    main()
