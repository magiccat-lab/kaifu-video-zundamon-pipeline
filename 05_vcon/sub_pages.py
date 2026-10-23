"""台本 (script.txt) の話す行を、字幕の帯に出す「ページ」に分ける。

前提の画面: 1920x1080 で、字幕は下の帯の全幅の真ん中、長い時は読点の後で 2 行。
SIZE (68px) と WIDTH (1216px) はその画面に合わせた定数で、帯の左右にキャラクターの画像などを置く余白を
取った残りの幅。別の解像度や帯の幅で使う時は、この 2 つを変える。
字の幅は指定したフォントで実際に測り、WIDTH に収める。
- 文 (。！？ で切る) ごとに行を作る。行の切れ目は読点 ・ 「…」の後を選び、無理な時は BudouX の文節の切れ目
- 2 行を超える文はページを分ける。ページの切れ目も読点の後を選ぶ
- 1 行に収まる短い文が続く時は、2 文で 1 ページ (1 文 1 行)
- 行末の「。」は出さない (！ ？ … は出す)
出力 subs.json は後段 (05_vcon) が読む。
使い方: python sub_pages.py <script.txt> <subs.json> --font <フォント.ttf> [--fix <手の折り方.json>]
フォントは環境変数 SUB_FONT でも渡せる (--font が先)。
手の折り方 json: {"節": ["行", "行"]} で行の折り方、{"文": [["行", "行"], ["行"]]} でページの分け方を直す。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

import budoux
from PIL import ImageFont

SIZE = 68
WIDTH = 1872 - 2 * (318 - 14 + 24)  # 帯の幅 1872 から左右に画像の幅と間を取った残り (= 1216)
BREAK_AFTER = "、…！？"

_font: ImageFont.FreeTypeFont | None = None  # main() で --font / SUB_FONT から読む
_parser = budoux.load_default_japanese_parser()


def load_font(path: str | None) -> None:
    global _font
    path = path or os.environ.get("SUB_FONT")
    if not path:
        sys.exit("font is required: pass --font <path to .ttf/.otf> or set SUB_FONT")
    if not Path(path).is_file():
        sys.exit(f"font not found: {path}")
    _font = ImageFont.truetype(path, SIZE)


def width(text: str) -> float:
    assert _font is not None, "load_font() first"
    return _font.getlength(text)


def paragraphs(script: Path) -> list[dict]:
    out, cur = [], None
    for ln in script.read_text(encoding="utf-8").split("\n"):
        m = re.match(r"^## (\S+) ", ln)
        if m:
            cur = m.group(1)
            continue
        if cur is None or not ln.strip() or ln.startswith("[") or ln.startswith("#"):
            continue
        out.append({"cue_id": cur, "text": ln.strip()})
    return out


def sentences(text: str) -> list[str]:
    parts = re.findall(r".+?(?:[。！？]+(?![」』）])|$)", text)  # 「…！」の中では切らない
    return [p.strip() for p in parts if p.strip()]


def show(text: str) -> str:
    return text.rstrip("。").replace("。", "")


def break_lines(phrases: list[str]) -> list[str]:
    """文節の並びを、幅に収まる最少の行数で、読点の後 ・ 長さのそろった所で折る。"""
    n = len(phrases)
    # 1 文節が幅を超える時は字で割る (固有名詞の長いカナ)
    fixed = []
    for p in phrases:
        while width(show(p)) > WIDTH:
            k = len(p)
            while k > 1 and width(p[:k]) > WIDTH:
                k -= 1
            fixed.append(p[:k])
            p = p[k:]
        fixed.append(p)
    phrases, n = fixed, len(fixed)
    INF = float("inf")
    # best[i][k] = 先頭 i 文節を k 行にした時の費用
    best = [[INF] * (n + 1) for _ in range(n + 1)]
    back = [[-1] * (n + 1) for _ in range(n + 1)]
    best[0][0] = 0.0
    for i in range(1, n + 1):
        for k in range(1, i + 1):
            for j in range(k - 1, i):
                if best[j][k - 1] == INF:
                    continue
                line = "".join(phrases[j:i])
                w = width(show(line))
                if w > WIDTH:
                    continue
                cost = best[j][k - 1]
                if i < n and (line[-1] not in BREAK_AFTER or phrases[i][:1] in "」』）"):
                    cost += 1.5  # 読点の後でない所で折る
                if cost < best[i][k]:
                    best[i][k] = cost
                    back[i][k] = j
    lines_n = next(k for k in range(1, n + 1) if best[n][k] < INF)
    # 同じ行数の中で、行の長さがそろう物を選び直す
    cands = []

    def walk(i, k, acc):
        if k == 0:
            if i == 0:
                cands.append(list(reversed(acc)))
            return
        for j in range(k - 1, i):
            line = "".join(phrases[j:i])
            if width(show(line)) <= WIDTH and best[j][k - 1] < INF:
                walk(j, k - 1, acc + [line])

    walk(n, lines_n, [])

    def score(ls):
        ws = [width(show(x)) for x in ls]
        breaks = sum(1.5 for x in ls[:-1] if x[-1] not in BREAK_AFTER)
        return breaks + (max(ws) - min(ws)) / WIDTH * 2 if len(ws) > 1 else breaks

    return min(cands, key=score)


def clauses(sentence: str) -> list[str]:
    parts = re.findall(r".+?(?:[、]|…+|$)", sentence)
    return [p for p in parts if p]


FIX: dict[str, list[str]] = {}  # BudouX の文節が粗すぎる所の手の折り方 (行を足すと元の節になる物だけ)
PAGES: dict[str, list[list[str]]] = {}  # 2 行に収まらない文の、手のページの分け方


def fits2(text: str) -> list[str] | None:
    ls = FIX.get(text) or break_lines(_parser.parse(text))
    return ls if len(ls) <= 2 else None


def sentence_pages(sentence: str) -> list[list[str]]:
    """2 行に収まらない文は、読点の所でページを分ける (ページの数が最少で、長さがそろう分け方)。"""
    if sentence in PAGES:
        return PAGES[sentence]
    one = fits2(sentence)
    if one:
        return [one]
    cl = clauses(sentence)
    n = len(cl)
    INF = float("inf")
    best = [INF] * (n + 1)
    back = [-1] * (n + 1)
    best[0] = 0.0
    for i in range(1, n + 1):
        for j in range(i):
            if best[j] == INF or not fits2("".join(cl[j:i])):
                continue
            w = width(show("".join(cl[j:i])))
            cost = best[j] + 10 + abs(w - WIDTH * 1.4) / WIDTH  # ページは少なく、1 ページは 1.4 行分くらい
            if cost < best[i]:
                best[i], back[i] = cost, j
    if best[n] == INF:  # 読点で切っても 2 行に収まらない節がある: 文節で 2 行ずつ
        ls = break_lines(_parser.parse(sentence))
        return [ls[k:k + 2] for k in range(0, len(ls), 2)]
    cuts, i = [], n
    while i > 0:
        cuts.append((back[i], i))
        i = back[i]
    return [fits2("".join(cl[a:b])) for a, b in reversed(cuts)]


def pages_of(text: str) -> list[list[str]]:
    pages: list[list[str]] = []
    for s in sentences(text):
        for pg in sentence_pages(s):
            if len(pg) == 1 and pages and len(pages[-1]) == 1 and pages[-1][0].endswith(("。", "！", "？", "…", "」")):
                pages[-1].append(pg[0])  # 1 行の文が続く時は 2 文で 1 ページ
            else:
                pages.append(list(pg))
    return [[show(x) for x in p] for p in pages]


def main() -> None:
    ap = argparse.ArgumentParser(description="台本の話す行を字幕のページに分ける")
    ap.add_argument("script")
    ap.add_argument("out")
    ap.add_argument("--font", default=None, help="字幕のフォント (.ttf / .otf)。環境変数 SUB_FONT でも可")
    ap.add_argument("--fix", default=None, help="手の折り方の json")
    args = ap.parse_args()
    load_font(args.font)
    script, out = Path(args.script), Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if args.fix:  # 手の折り方: {"節": ["行", "行"]}
        for k, v in json.loads(Path(args.fix).read_text(encoding="utf-8")).items():
            if v and isinstance(v[0], list):  # 文 → ページの並び
                assert "".join("".join(p) for p in v) == k, k
                PAGES[k] = v
            else:
                assert "".join(v) == k, k
                FIX[k] = v
    rows = []
    for i, p in enumerate(paragraphs(script)):
        pg = pages_of(p["text"])
        rows.append({"i": i, "cue_id": p["cue_id"], "text": p["text"], "pages": pg})
        for page in pg:
            print(f"{p['cue_id']:4} {i:2} | " + " / ".join(page))
    out.write_text(json.dumps({"width": WIDTH, "size": SIZE, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
