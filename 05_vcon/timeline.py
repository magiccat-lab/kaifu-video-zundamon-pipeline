"""台本の声の長さと plan (区切りごとの元の秒 ・ 速さ) から、出来上がりの動画の時刻表 (timeline) を組む。

考え方:
- セリフは元の録画の秒で持つ。plan の segs は (元の始め, 元の終わり, 速さ) の並びで、
  区間の長さ (b − a) / v を足し合わせると、出来上がりの動画の中の秒になる。
- 行ごとの言い始め (plan の at) は元の秒で書く。速さを変えても、セリフは起きた出来事に付いていく。
  前の行が言い終わっていなければ、GAP 秒あけて後ろへずらす。
- 速さの変わり目 (つながった区間の間) は、元の秒で RAMP_S (0.6) 秒かけて RAMP_STEPS (4) 段でならす。切らない。
- 声が区切りの映像に収まらない時は、次の順に直す。
    1. 速めた所を等速へ (同じ割合で戻す)
    2. plan の extend_to まで、切っていた所へ映像を延ばす
    3. 止めた絵 (hold) を足す
- 声の無い間は、TIGHT (plan) があれば速めて詰める。台詞の頭の手前 protect 秒は等速のまま残す。

pieces の形:
  ("play", 元の始め, 元の終わり, 速さ)   映像を流す
  ("hold", 元の秒, 長さ, still または None)   同じ絵を止める

使い方:
  python timeline.py <plan.py> <spoken_zunda.json> (--voice-dir <p<i>.wav のある dir> | --lens <lens.json>) [--out timeline.json]
  --lens は {行の番号 i: 秒} の json (build_audio.py が書く lens.json は区切りごとなので別物)。
  行と区切りの対応は spoken_zunda.json の (cue_id, i) から取る。
出力: {"sections": [{id, t0, t1, pieces, notes}], "lines": [{i, sec, start, end}], "total": 秒}
  音の合成 ・ 字幕 ・ 画面の描き出しはここではしない (時刻だけ)。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import wave
from pathlib import Path

FPS = 30
SR = 48000
RAMP_S, RAMP_STEPS = 0.6, 4
LEAD, GAP, TAIL = 0.3, 0.35, 0.6
SPILL = 0.8  # 次の区切りへ切らずにつながる時は、声がこの秒まではみ出してよい (次の行が後ろへずれる)


# ---------- 時刻 ----------

def pieces_dur(pieces: list[tuple]) -> float:
    return sum((p[2] - p[1]) / p[3] if p[0] == "play" else p[2] for p in pieces)


def out_time(pieces: list[tuple], src: float) -> float:
    """元の秒 → この並びの中の秒。止めた所は、その秒の止めの頭。"""
    acc = 0.0
    for p in pieces:
        if p[0] == "play":
            a, b, s = p[1], p[2], p[3]
            if src < a:
                return acc
            if src <= b:
                return acc + (src - a) / s
            acc += (b - a) / s
        else:
            acc += p[2]
    return acc


def section_pieces(sec: dict, segs: list[tuple]) -> list[tuple]:
    """segs を pieces にする。moves の freeze (その秒で絵を止める) があれば、そこで区間を割って hold を挟む。"""
    out = [("play", a, b, s) for a, b, s in segs]
    for mv in sec.get("moves", []):
        if mv["kind"] != "freeze":
            continue
        for i, p in enumerate(out):
            if p[0] == "play" and p[1] < mv["at"] < p[2]:
                out[i:i + 1] = [("play", p[1], mv["at"], p[3]), ("hold", mv["at"], mv["dur"], None), ("play", mv["at"], p[2], p[3])]
                break
    return out


def place(sec: dict, pieces: list[tuple], lens: list[float]) -> list[float]:
    """行ごとの言い始めの秒 (区切りの頭から)。at があればその出来事の所、前の行が終わっていなければ GAP あけて後ろへ。"""
    starts, cursor = [], LEAD - GAP
    for k, ln in enumerate(lens):
        want = out_time(pieces, sec["at"][k]) if k in sec.get("at", {}) else -1.0
        st = max(want, cursor + GAP)
        starts.append(st)
        cursor = st + ln
    return starts


def fit_section(sec: dict, lens: list[float]) -> tuple[list[tuple], list[float], list[str]]:
    """声が収まる様に区切りの映像を伸ばす。返す: (並び, 行の頭の秒, 変えた事)"""
    segs = [tuple(s) for s in sec["segs"]]
    notes = []
    pieces = section_pieces(sec, segs)
    starts = place(sec, pieces, lens)
    need = starts[-1] + lens[-1] + TAIL
    if starts[-1] + lens[-1] <= pieces_dur(pieces) + (SPILL if sec.get("joined_next") else -0.15):
        return pieces, starts, notes
    # 1. 速めた所を等速へ (同じ割合で)
    for _ in range(6):
        cur = pieces_dur(pieces)
        if need <= cur + 1e-3:
            break
        fast = [s for s in segs if s[2] > 1.0]
        if not fast:
            break
        lo, hi = 0.0, 1.0  # k: 速さを 1 + (s-1)*k に
        for _ in range(40):
            k = (lo + hi) / 2
            trial = [(a, b, 1 + (s - 1) * k) for a, b, s in segs]
            if pieces_dur(section_pieces(sec, trial)) >= need:
                lo = k
            else:
                hi = k
        segs = [(a, b, round(1 + (s - 1) * lo, 3)) for a, b, s in segs]
        pieces = section_pieces(sec, segs)
        starts = place(sec, pieces, lens)
        need = starts[-1] + lens[-1] + TAIL
    if any(s[2] != o[2] for s, o in zip(segs, sec["segs"], strict=True)):
        notes.append("速さ " + " ・ ".join(f"{o[2]}→{s[2]}倍" for s, o in zip(segs, sec["segs"], strict=True) if s[2] != o[2]))
    # 2. 切っていた所まで延ばす
    short = need - pieces_dur(pieces)
    if short > 1e-3 and sec.get("extend_to"):
        a, b, s = segs[-1]
        nb = min(sec["extend_to"], b + short * s)
        segs[-1] = (a, nb, s)
        notes.append(f"映像を元の {fmt(b)} から {fmt(nb)} まで延ばした")
        pieces = section_pieces(sec, segs)
        starts = place(sec, pieces, lens)
        need = starts[-1] + lens[-1] + TAIL
    # 3. 止めた絵を足す
    short = need - pieces_dur(pieces)
    if short > 1e-3:
        still = sec.get("still")
        pieces.append(("hold", still["src"] if still else segs[-1][1], round(short, 3), still))
        notes.append(f"止めた絵を {short:.1f} 秒足した" + (f" (元の {fmt(still['src'])} の札)" if still else ""))
    return pieces, starts, notes


def src_of(pieces: list[tuple], t: float) -> float | None:
    """並びの中の秒 → 元の秒 (止めの中なら None)"""
    acc = 0.0
    for p in pieces:
        d = (p[2] - p[1]) / p[3] if p[0] == "play" else p[2]
        if t <= acc + d + 1e-9:
            return p[1] + (t - acc) * p[3] if p[0] == "play" else None
        acc += d
    return None


def speed_up(pieces: list[tuple], a: float, b: float, target: float, max_speed: float) -> list[tuple]:
    """並びの中の秒 a〜b の映像を、長さ target まで速める (速さは max_speed まで)。止めた所は触らない"""
    sa, sb = src_of(pieces, a), src_of(pieces, b)
    if sa is None or sb is None or sb - sa < 1.2:
        return pieces
    f = (b - a) / max(target, 1e-3)
    out = []
    for p in pieces:
        if p[0] != "play" or p[2] <= sa or p[1] >= sb:
            out.append(p)
            continue
        cuts = [p[1], max(p[1], sa), min(p[2], sb), p[2]]
        for x0, x1 in zip(cuts, cuts[1:], strict=False):
            if x1 - x0 < 1e-6:
                continue
            inside = x0 >= sa - 1e-9 and x1 <= sb + 1e-9
            out.append(("play", x0, x1, round(min(max_speed, p[3] * f), 3) if inside else p[3]))
    return out


def tighten(sec: dict, pieces: list[tuple], lens: list[float], tight: dict) -> tuple[list[tuple], list[str]]:
    """声と声の間の空き (と区切りの頭 ・ 終わりの空き) の映像を速めて詰める。
    間を声の無い空白にせず、しゃべりながら絵が進むようにするため。
    台詞の頭 (at = 札が見える所) の手前 protect 秒は等速のまま残す。
    tight = dict(max_speed=詰める時の最高の速さ, gap=行の間に残す秒, protect=等速で残す秒)"""
    gap, protect, mx = tight["gap"], tight["protect"], tight["max_speed"]
    before = pieces_dur(pieces)
    for k in range(len(lens)):
        starts = place(sec, pieces, lens)
        prev_end = starts[k - 1] + lens[k - 1] if k else 0.0
        keep = gap if k else LEAD
        g = starts[k] - prev_end
        if g <= keep + 0.15:
            continue
        a = prev_end + (0.1 if k else 0.0)
        b = starts[k] - (protect if k in sec.get("at", {}) else 0.0)
        if b - a > 0.3:
            pieces = speed_up(pieces, a, b, max(0.05, (b - a) - (g - keep)), mx)
    starts = place(sec, pieces, lens)
    end = starts[-1] + lens[-1] + TAIL
    if pieces_dur(pieces) - end > 0.5:
        pieces = speed_up(pieces, end, pieces_dur(pieces), 0.3, mx)
    notes = [f"声の無い間を速めて {before - pieces_dur(pieces):.1f} 秒詰めた"] if before - pieces_dur(pieces) > 0.5 else []
    return pieces, notes


def fmt(s: float) -> str:
    return f"{int(s // 60):02d}:{s % 60:04.1f}"


def ramps(pieces: list[tuple]) -> list[tuple]:
    """つながった play の速さの変わり目を、RAMP_S 秒 (元の秒) かけて段でならす。
    pieces の末尾の要素 (区切りの番号) は、そのまま引き継ぐ。"""
    out = []
    for i, p in enumerate(pieces):
        if p[0] != "play":
            out.append(p)
            continue
        a, b, s = p[1], p[2], p[3]
        prev = pieces[i - 1] if i else None
        nxt = pieces[i + 1] if i + 1 < len(pieces) else None
        jp = prev is not None and prev[0] == "play" and abs(prev[2] - a) < 1e-6 and prev[3] != s
        jn = nxt is not None and nxt[0] == "play" and abs(nxt[1] - b) < 1e-6 and nxt[3] != s
        a2 = a + (RAMP_S / 2 if jp else 0)
        b2 = b - (RAMP_S / 2 if jn else 0)
        if b2 - a2 > 0.02:
            out.append(("play", a2, b2, s, p[4]))
        if jn:
            t0, width = b - RAMP_S / 2, RAMP_S / RAMP_STEPS
            for k in range(RAMP_STEPS):
                r = (k + 1) / (RAMP_STEPS + 1)
                mid = t0 + (k + 0.5) * width
                out.append(("play", t0 + k * width, t0 + (k + 1) * width, round(s + (nxt[3] - s) * r, 3), p[4] if mid < b else nxt[4]))
    return out


# ---------- 時刻表を組む ----------

def build_timeline(plan_module, lens_by_line: dict[int, float], line_sections: dict[str, list[int]]) -> dict:
    """plan_module: SECTIONS と (あれば) TIGHT を持つ module。
    lens_by_line: 行の番号 i → 声の秒。line_sections: 区切りの ID → その区切りの行の番号 (台本の順)。
    音の合成 ・ 字幕 ・ 画面は扱わず、時刻だけ返す。"""
    sections_plan = [dict(s) for s in plan_module.SECTIONS]  # plan を書き換えない
    tight = getattr(plan_module, "TIGHT", None)
    pieces_all: list[tuple] = []
    sections: list[dict] = []
    for n, sec in enumerate(sections_plan):
        nxt = sections_plan[n + 1] if n + 1 < len(sections_plan) else None
        sec["joined_next"] = bool(nxt and abs(nxt["segs"][0][0] - sec["segs"][-1][1]) < 1e-6 and not sec.get("still"))
        if sec["id"] not in line_sections:
            raise KeyError(f"section {sec['id']} has no lines in the spoken json")
        idx = line_sections[sec["id"]]
        lens = [lens_by_line[i] for i in idx]
        if lens:
            pieces, starts, notes = fit_section(sec, lens)
            if tight and not sec.get("still") and sec.get("tight", True):
                pieces, tnotes = tighten(sec, pieces, lens, tight)
                starts = place(sec, pieces, lens)
                notes += tnotes
        else:  # 話す行が無い区切りは、segs をそのまま流す
            pieces, starts, notes = section_pieces(sec, [tuple(s) for s in sec["segs"]]), [], []
        sections.append({"id": sec["id"], "pieces": pieces, "starts": starts, "idx": idx, "notes": notes})
        pieces_all.extend(p + (n,) for p in pieces)
    smooth = ramps(pieces_all)
    # 区切りの頭の秒 (ならした後の並びで、その区切りの最初の切れ端の頭)
    acc, seen = 0.0, set()
    for p in smooth:
        if p[4] not in seen:
            seen.add(p[4])
            sections[p[4]]["t0"] = acc
        acc += (p[2] - p[1]) / p[3] if p[0] == "play" else p[2]
    total = pieces_dur(smooth)
    for k, s in enumerate(sections):
        s["t1"] = sections[k + 1]["t0"] if k + 1 < len(sections) else total
    # 声の並び
    lines = []
    for s in sections:
        for k, i in enumerate(s["idx"]):
            st = s["t0"] + s["starts"][k]
            lines.append({"i": i, "sec": s["id"], "start": round(st, 3), "end": round(st + lens_by_line[i], 3)})
    for a, b in zip(lines, lines[1:], strict=False):  # ならしで詰まった所は後ろへ
        if b["start"] < a["end"] + 0.15:
            shift = a["end"] + 0.15 - b["start"]
            b["start"] = round(b["start"] + shift, 3)
            b["end"] = round(b["end"] + shift, 3)
    return {
        "sections": [{"id": s["id"], "t0": round(s["t0"], 3), "t1": round(s["t1"], 3),
                      "pieces": [_round_piece(p) for p in s["pieces"]], "notes": s["notes"]} for s in sections],
        "lines": lines,
        "total": round(total, 3),
    }


def _round_piece(p: tuple) -> list:
    return [round(x, 3) if isinstance(x, float) else x for x in p]


# ---------- CLI ----------

def load_plan(path: Path):
    spec = importlib.util.spec_from_file_location("plan", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def wav_seconds(path: Path) -> float:
    with wave.open(str(path)) as w:
        return w.getnframes() / w.getframerate()


def main() -> None:
    ap = argparse.ArgumentParser(description="plan と声の長さから timeline.json を組む")
    ap.add_argument("plan")
    ap.add_argument("spoken")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--voice-dir", help="p<i>.wav のある dir (build_audio.py の出力)")
    src.add_argument("--lens", help="{行の番号: 秒} の json")
    ap.add_argument("--out", default="timeline.json")
    args = ap.parse_args()

    spoken = json.loads(Path(args.spoken).read_text(encoding="utf-8"))
    line_sections: dict[str, list[int]] = {}
    for r in spoken:
        line_sections.setdefault(r["cue_id"], []).append(r["i"])
    if args.voice_dir:
        lens = {r["i"]: wav_seconds(Path(args.voice_dir) / f"p{r['i']}.wav") for r in spoken}
    else:
        raw = json.loads(Path(args.lens).read_text(encoding="utf-8"))
        lens = {int(k): float(v) for k, v in raw.items()}
        missing = [r["i"] for r in spoken if r["i"] not in lens]
        if missing:
            sys.exit(f"lens json has no entry for lines {missing}")
    tl = build_timeline(load_plan(Path(args.plan)), lens, line_sections)
    Path(args.out).write_text(json.dumps(tl, ensure_ascii=False, indent=1), encoding="utf-8")
    for s in tl["sections"]:
        print(f"{s['id']:5} {fmt(s['t0'])} - {fmt(s['t1'])}  " + " / ".join(s["notes"]))
    print(f"total {tl['total']:.1f}s, {len(tl['lines'])} lines -> {args.out}")


if __name__ == "__main__":
    main()
