"""TTS に渡す前の日本語の読み整え (数字 ・ 助数詞 ・ 英字を仮名にする)。依存は標準ライブラリだけ。

TTS エンジンの前処理は数字をそのまま残したり、マイナス記号 (−) やダッシュを消したりする。
解説動画の原稿は「−1」「AP 7」「1 周目」のような数字と英字が多いので、合成の前にここで仮名に直す。
VOICEVOX に渡す時は kata_numbers=True にする (平仮名の「は」が助詞に読まれるのを避けるため)。

順番: 読みの辞書 → 分数・スコア・塁 → 符号 → 助数詞つきの数 → 裸の数 → 英字
"""

from __future__ import annotations

import re

_DIGIT = {
    "0": "ぜろ",
    "1": "いち",
    "2": "に",
    "3": "さん",
    "4": "よん",
    "5": "ご",
    "6": "ろく",
    "7": "なな",
    "8": "はち",
    "9": "きゅう",
}


def num_to_kana(n: int) -> str:
    """整数を仮名の読みにする (0 は「ゼロ」)。"""
    if n == 0:
        return "ゼロ"
    parts: list[str] = []
    if n >= 100000000:
        parts.append(num_to_kana(n // 100000000) + "おく")
        n %= 100000000
    if n >= 10000:
        parts.append(num_to_kana(n // 10000) + "まん")
        n %= 10000
    if n >= 1000:
        k = n // 1000
        prefix = {1: "", 3: "さん", 8: "はっ"}.get(k, num_to_kana(k) if k else "")
        parts.append(prefix + ("ぜん" if k == 3 else "せん"))
        n %= 1000
    if n >= 100:
        h = n // 100
        prefix = {1: "", 3: "さん", 6: "ろっ", 8: "はっ"}.get(h, num_to_kana(h))
        hyaku = "ぴゃく" if h in (6, 8) else ("びゃく" if h == 3 else "ひゃく")
        parts.append(prefix + hyaku)
        n %= 100
    if n >= 10:
        t = n // 10
        parts.append(("" if t == 1 else num_to_kana(t)) + "じゅう")
        n %= 10
    if n > 0:
        parts.append(_DIGIT[str(n)])
    return "".join(parts)


# 助数詞: (表記, 特別な読み {数: 読み}, ふつうの読み)。長い表記を先に並べる (つ目 > つ)
_COUNTERS: list[tuple[str, dict[int, str], str]] = [
    (
        "つ目",
        {
            1: "ひとつめ",
            2: "ふたつめ",
            3: "みっつめ",
            4: "よっつめ",
            5: "いつつめ",
            6: "むっつめ",
            7: "ななつめ",
            8: "やっつめ",
            9: "ここのつめ",
        },
        "つめ",
    ),
    (
        "つ",
        {
            1: "ひとつ",
            2: "ふたつ",
            3: "みっつ",
            4: "よっつ",
            5: "いつつ",
            6: "むっつ",
            7: "ななつ",
            8: "やっつ",
            9: "ここのつ",
            10: "とお",
        },
        "つ",
    ),
    ("周目", {1: "いっしゅうめ", 8: "はっしゅうめ", 10: "じゅっしゅうめ"}, "しゅうめ"),
    ("巡目", {}, "じゅんめ"),
    (
        "回表",
        {1: "いっかいおもて", 6: "ろっかいおもて", 8: "はっかいおもて", 10: "じゅっかいおもて"},
        "かいおもて",
    ),
    (
        "回裏",
        {1: "いっかいうら", 6: "ろっかいうら", 8: "はっかいうら", 10: "じゅっかいうら"},
        "かいうら",
    ),
    ("回", {1: "いっかい", 6: "ろっかい", 8: "はっかい", 10: "じゅっかい"}, "かい"),
    ("枚目", {}, "まいめ"),
    ("枚", {}, "まい"),
    ("弾", {}, "だん"),
    ("覚", {}, "かく"),
    ("コス", {}, "コス"),
    ("ドロー", {}, "ドロー"),
    ("試合", {1: "いっしあい", 8: "はっしあい", 10: "じゅっしあい"}, "しあい"),
    ("種類", {1: "いっしゅるい", 8: "はっしゅるい", 10: "じゅっしゅるい"}, "しゅるい"),
    ("種", {1: "いっしゅ", 8: "はっしゅ", 10: "じゅっしゅ"}, "しゅ"),
    ("失点", {1: "いっしってん", 8: "はっしってん", 10: "じゅっしってん"}, "しってん"),
    ("点", {0: "れいてん", 1: "いってん", 8: "はってん", 10: "じゅってん"}, "てん"),
    ("塁打", {}, "るいだ"),
    ("塁", {}, "るい"),
    ("人目", {1: "ひとりめ", 2: "ふたりめ"}, "にんめ"),
    ("人", {1: "ひとり", 2: "ふたり", 4: "よにん"}, "にん"),
    ("番打者", {4: "よばんだしゃ"}, "ばんだしゃ"),
    ("番", {4: "よばん"}, "ばん"),
    ("族", {}, "ぞく"),
    ("歳", {1: "いっさい", 8: "はっさい", 10: "じゅっさい"}, "さい"),
    ("個", {1: "いっこ", 6: "ろっこ", 8: "はっこ", 10: "じゅっこ"}, "こ"),
    ("時間", {4: "よじかん", 7: "しちじかん", 9: "くじかん"}, "じかん"),
    ("時", {4: "よじ", 7: "しちじ", 9: "くじ"}, "じ"),
    (
        "分",
        {
            1: "いっぷん",
            3: "さんぷん",
            4: "よんぷん",
            6: "ろっぷん",
            8: "はっぷん",
            10: "じゅっぷん",
        },
        "ふん",
    ),
    ("秒", {}, "びょう"),
    ("円", {}, "えん"),
    ("日", {}, "にち"),
    ("月", {4: "しがつ", 7: "しちがつ", 9: "くがつ"}, "がつ"),
    ("年", {4: "よねん"}, "ねん"),
    ("本", {1: "いっぽん", 3: "さんぼん", 6: "ろっぽん", 8: "はっぽん", 10: "じゅっぽん"}, "ほん"),
    ("万", {}, "まん"),
    ("億", {}, "おく"),
]
_COUNTER_RE = re.compile(
    r"(?<![\d.])(\d+)[ 　]?(" + "|".join(re.escape(c) for c, _, _ in _COUNTERS) + r")"
)
_COUNTER_TABLE = {c: (special, plain) for c, special, plain in _COUNTERS}

# 読みの辞書 (表記 → 読み)。長い物から当てる。札は「ふだ」(カードゲームの文脈)、ただし札幌などは除く
READING_HINTS: dict[str, str] = {
    # 一般語
    "進捗": "しんちょく",
    "添付": "てんぷ",
    "概要": "がいよう",
    "稟議": "りんぎ",
    "施策": "しさく",
    "汎用": "はんよう",
    "脆弱": "ぜいじゃく",
    "冪等": "べきとう",
    "閾値": "しきいち",
    # カード関係
    "山札": "やまふだ",
    "手札": "てふだ",
    "札": "ふだ",
    "札幌": "さっぽろ",
    "円札": "えんさつ",
    "改札": "かいさつ",
    "落札": "らくさつ",
    "入札": "にゅうさつ",
    # VOICEVOX (OpenJTalk) の読み違いを audio_query の kana で見て直した物
    "素で": "すで",  # もとで
    "新弾": "しんだん",  # しんだま
    "強心臓": "きょうしんぞう",  # つよしんぞう
    "一択": "いったく",  # いちよ
    "十分": "じゅうぶん",  # じゅっぷん (時間の 10 分は数字で書く)
    "引きに": "ひきに",  # 「〜を引きに」が「おびきに」
    "得点圏": "とくてんけん",
}
_HINT_KEYS = sorted(READING_HINTS, key=len, reverse=True)
_HINT_RE = re.compile("|".join(re.escape(k) for k in _HINT_KEYS))

# 英字: 単語として読む物と、1 字ずつ読む略語
_WORDS = {
    "ZONE": "ゾーン",
    "OK": "オーケー",
    "MAX": "マックス",
    "note": "ノート",
    "YouTube": "ユーチューブ",
    "Discord": "ディスコード",
    "AI": "エーアイ",
    "CPU": "シーピーユー",
    "TCG": "ティーシージー",
}
_LETTER = {
    "A": "エー",
    "B": "ビー",
    "C": "シー",
    "D": "ディー",
    "E": "イー",
    "F": "エフ",
    "G": "ジー",
    "H": "エイチ",
    "I": "アイ",
    "J": "ジェー",
    "K": "ケー",
    "L": "エル",
    "M": "エム",
    "N": "エヌ",
    "O": "オー",
    "P": "ピー",
    "Q": "キュー",
    "R": "アール",
    "S": "エス",
    "T": "ティー",
    "U": "ユー",
    "V": "ブイ",
    "W": "ダブリュー",
    "X": "エックス",
    "Y": "ワイ",
    "Z": "ゼット",
}
_WORD_RE = re.compile(
    r"(?<![A-Za-z])("
    + "|".join(re.escape(w) for w in sorted(_WORDS, key=len, reverse=True))
    + r")(?![A-Za-z])"
)
_ACRONYM_RE = re.compile(r"(?<![A-Za-z])([A-Z]{2,4})(?![A-Za-z])")


def _counter(m: re.Match, nk=None) -> str:
    nk = nk or num_to_kana
    n, c = int(m.group(1)), m.group(2)
    if c == "本" and m.string[m.end() : m.end() + 1] == "塁":  # 「1 本塁打」は本数ではない
        return nk(n) + c
    special, plain = _COUNTER_TABLE[c]
    if n in special:
        return _kata(special[n]) if nk is not num_to_kana else special[n]
    return nk(n) + plain


def _kata(text: str) -> str:
    return "".join(chr(ord(c) + 0x60) if "ぁ" <= c <= "ゖ" else c for c in text)


def preprocess(text: str, kata_numbers: bool = False) -> str:
    """合成用の読みに直した文を返す (表示には使わない)。

    kata_numbers: 数の読みをカタカナで出す。VOICEVOX (OpenJTalk) は「はち」の「は」を助詞と読んで
    「わち」にしたので、VOICEVOX に渡す時は True にする。
    """
    nk = (lambda n: _kata(num_to_kana(n))) if kata_numbers else num_to_kana
    t = text.replace("　", " ")
    t = _HINT_RE.sub(lambda m: READING_HINTS[m.group(0)], t)
    # 分数「2 分の 1」、スコア「2-1」、塁「1・2 塁」
    t = re.sub(
        r"(?<!\d)(\d+)\s?分の\s?(\d+)",
        lambda m: f"{nk(int(m.group(1)))}ぶんの{nk(int(m.group(2)))}",
        t,
    )
    t = re.sub(
        r"(?<![\d.])(\d+)\s?[-－–]\s?(\d+)(?![\d.])",
        lambda m: f"{nk(int(m.group(1)))}たい{nk(int(m.group(2)))}",
        t,
    )
    t = re.sub(
        r"(?<!\d)(\d)\s?[・,、]\s?(\d)\s?塁",
        lambda m: f"{nk(int(m.group(1)))}{nk(int(m.group(2)))}るい",
        t,
    )
    # 符号: ＋1 → プラスいち、−1 → マイナスいち (− は TTS が消すので先に読みにする)
    t = re.sub(r"[＋+]\s?(\d+)", lambda m: "プラス" + nk(int(m.group(1))), t)
    t = re.sub(r"[＋+]", "プラス", t)
    t = re.sub(r"(?<![0-9A-Za-z])[−\-‐–－]\s?(\d+)", lambda m: "マイナス" + nk(int(m.group(1))), t)
    # 助数詞つきの数、裸の数 (小数は「てん」)
    t = _COUNTER_RE.sub(lambda m: _counter(m, nk), t)
    t = re.sub(
        r"(?<![\d])(\d+)\.(\d+)",
        lambda m: nk(int(m.group(1))) + "てん" + "".join(_DIGIT[d] for d in m.group(2)),
        t,
    )
    t = re.sub(r"(?<![\d])(\d+)(?![\d])", lambda m: nk(int(m.group(1))), t)
    # 英字
    t = _WORD_RE.sub(lambda m: _WORDS[m.group(1)], t)
    t = _ACRONYM_RE.sub(lambda m: "".join(_LETTER[c] for c in m.group(1)), t)
    return t
