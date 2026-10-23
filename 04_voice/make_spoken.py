"""台本 (script.txt) から、声を作るための spoken_zunda.json を作る。

使い方: python make_spoken.py <script.txt> <out.json>

台本の話す行 (## の見出し ・ [画面] ・ [指示] ・ # 以外) を 1 行 1 段落として並べる。
字幕に出す字 (zunda) と、読みが違う所だけ別に持つ読み (yomi) を分けるのが目的。
数字と助数詞の読み (1箱 → ヒトハコ など) は TTS 任せだと外れるので、YOMI の表で直す。
build_audio.py は yomi があればそちらを、無ければ zunda を読ませる。

出力の 1 要素: {"cue": 区切りの通し番号, "cue_id": 台本の ID, "zunda": 台本の行, "i": 行の通し番号,
               "pause_before": null, ("yomi": 読み替えた行)}
"""
import json
import re
import sys

# 表記 → 読み。TTS 向けの読み替えの表。足したい物はここに足す。
YOMI = [
    ("1パック", "いちパック"),
    ("20パック", "にじゅっパック"),
    ("3パック目", "さんパックめ"),
    ("1箱", "ひとはこ"),
    ("2箱", "ふたはこ"),
    ("4枚入り", "よんまいいり"),
    ("80枚", "はちじゅうまい"),
    ("1枚目", "いちまいめ"),
]


def _kata(s):
    return "".join(chr(ord(c) + 0x60) if "ぁ" <= c <= "ゖ" else c for c in s)


# 読みはカタカナにして渡す。平仮名だと「は」が助詞に読まれる (1箱 → ヒトワコ のように) ため
YOMI = [(a, _kata(b)) for a, b in YOMI]
# 長い語から当てる (12パック目 が 1 + 2パック目 に割れないように)
YOMI.sort(key=lambda ab: -len(ab[0]))


def yomi(t):
    for a, b in YOMI:
        t = t.replace(a, b)
    return t


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    src, out_path = sys.argv[1], sys.argv[2]
    out, cue, i, cur = [], -1, 0, None
    for ln in open(src, encoding="utf-8").read().split("\n"):
        m = re.match(r"^## (\S+) ", ln)
        if m:
            cue += 1
            cur = m.group(1)
            continue
        if cur is None or not ln.strip() or ln.startswith("[") or ln.startswith("#"):
            continue
        p = {"cue": cue, "cue_id": cur, "zunda": ln.strip(), "i": i, "pause_before": None}
        if yomi(p["zunda"]) != p["zunda"]:
            p["yomi"] = yomi(p["zunda"])
        out.append(p)
        i += 1
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(len(out), "paragraphs", cue + 1, "cues")


if __name__ == "__main__":
    main()
