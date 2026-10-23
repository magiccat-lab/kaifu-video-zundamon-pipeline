"""V コンテの段取り (plan) のサンプル。03_script/script_sample.txt の 3 区切り (OP1 / B1 / K3) に対応する。内容は全部架空。

timeline.py はこの module の SECTIONS と TIGHT を読む。ほかのキーは、描き出し側 (画面 ・ 右の欄) が読む想定。

モジュールのキー:
  TITLE      動画の題 (表示用)
  SOURCE     元の録画 (proxy.mp4 など、軽くした物)
  VOICE_DIR  build_audio.py が出した p<i>.wav の dir
  TIGHT      声の無い間を速めて詰める設定。max_speed = 最高の速さ、gap = 行の間に残す秒、
             protect = 台詞の頭 (at) の手前で等速のまま残す秒
  SECTIONS   区切りの並び (台本の "## <ID>" と同じ順)
  CHUNKS     区切りを何本かの塊に分けて描き出す時の分け方 (番号, 題, [区切りの ID])

SECTIONS の 1 要素のキー:
  id         台本の区切りの ID
  segs       元の秒と速さ [(元の始め, 元の終わり, 速さ), ...]。前の終わりと次の始めが同じ所はつながった場面で、
             速さの変わり目は 0.6 秒かけて 4 段でならす。違う所はそこで切る
  at         行ごとの言い始めの元の秒 {区切りの中の行番号 (0 始まり): 元の秒}。書かない行は前の行の後ろにつづける
  moves      画面の動き。zoom = 元の秒 at から dur 秒かけて rect (x, y, w, h) へ寄る (rect 無しは全体に戻る)、
             freeze = 元の秒 at の絵を dur 秒止める
  col        右の欄 (区切りの頭の中身)。head は見出し、panels は札の並び
  col_at     行ごとに右の欄を替える {区切りの中の行番号: 右の欄}
  tight      False にすると、この区切りは声の無い間を詰めない (既定は True)
  extend_to  声が映像に収まらない時、最後の区間をこの元の秒まで延ばしてよい
  still      声が映像に収まらない時に足す止めた絵 {"src": 元の秒, "img": 画像}。あると詰めもしない
  keep_tail  区切りの終わりの絵を、次の区切りの頭まで残す (描き出し側が読む)
"""

TITLE = "トレカ開封サンプル"
SOURCE = "proxy.mp4"
VOICE_DIR = "voice/audio"
TIGHT = dict(max_speed=2.0, gap=1.0, protect=1.5)

HEAD = {"title": "サンプルパック", "sub": "x 架空シリーズ"}


def head(tab, prog):
    return dict(HEAD, tab=tab, prog=prog)


TODAY = {"tab": "今日の箱", "rows": [("商品", "サンプルパック"), ("1パック", "4枚"), ("1箱", "20パック"), ("全部", "80枚")]}
HITS = {"tab": "当たり", "list": ["まだ無し"]}

SECTIONS = [
    # tight=False: あいさつは声の無い間も詰めない
    dict(id="OP1", segs=[(1, 14, 1.0)], at={0: 1.2, 1: 6.0, 2: 10.0}, tight=False,
         col={"head": head("開封前", "1箱目"), "panels": [TODAY]}),
    # 途中から 2 倍。箱の寄りは zoom。止めた絵 (still) は声が収まらない時だけ足される
    dict(id="B1", segs=[(30, 45, 1.0), (45, 65, 2.0)], at={0: 30.5, 1: 46.0},
         still=dict(src=64.0, img="refs/box.jpg"),
         moves=[dict(kind="zoom", at=33.0, dur=1.2, rect=(240, 40, 800, 450)), dict(kind="zoom", at=44.0, dur=0.8)],
         col={"head": head("開封前", "1箱目"), "panels": [TODAY]},
         col_at={1: {"head": head("開封前", "1箱目"), "panels": [{"tab": "この箱", "rows": [("パック", "20"), ("全部", "80枚")]}]}}),
    # 袋を開ける間は 2 倍、カードが見える 128 秒から等速。131 秒で絵を 1 秒止める。声が長い時は 146 秒まで延ばす
    dict(id="K3", segs=[(120, 128, 2.0), (128, 140, 1.0)], at={0: 120.5, 1: 130.0, 2: 134.0},
         extend_to=146.0, keep_tail=True,
         moves=[dict(kind="freeze", at=131.0, dur=1.0)],
         col={"head": head("開封中", "3パック目"), "panels": [HITS]},
         col_at={1: {"head": head("開封中", "3パック目"), "panels": [{"tab": "カード", "rows": [("1枚目", "見えた")]}, HITS]}}),
]

CHUNKS = [
    ("1", "はじめに", ["OP1", "B1"]),
    ("2", "3パック目", ["K3"]),
]
