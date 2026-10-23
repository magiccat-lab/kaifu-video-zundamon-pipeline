# カード開封動画をずんだもんの声で動画化する仕組み (参考スクリプト)

Zenn の記事「[カード開封動画を撮影素材だけClaudeに渡して動画化する仕組みを作った件](https://zenn.dev/magic_ren/articles/kaifu-video-zundamon-pipeline)」で説明した仕組みのうち、動画の中身に依らない部分を抜き出して置いたものです。

このスクリプトは動画ごとに共通する処理だけを切り出した物です。動画を置けば完成品が出てくる物ではありません。記事に書いた通り、動画ごとの台本と plan.py と確認ページは Claude Code が書いて、ここにあるスクリプトをつないでいます。自分の Claude Code に同じ物を組ませる時の土台として使ってください。

## 記事の工程とファイルの対応

| 記事の工程 | ここにある物 | ここに無い物 |
| --- | --- | --- |
| 文字起こし | `01_transcribe/transcribe.py` | なし |
| カードの調べ物 | `02_frames/contact_sheet.py` (コンタクトシート) / `02_frames/activity.py` (動きと音量) | コマとチェックリストの照合は Claude Code が読んでやる作業で、コードはありません |
| 台本 | `03_script/check_zunda.py` (口調の検査) / `03_script/script_sample.txt` (台本の形の見本) | 台本を書くのは Claude Code。OK か直すかを答える確認ページはありません |
| ずんだもんの声 | `04_voice/` の 4 本 (`make_spoken.py` / `build_audio.py` / `tts_text_ja.py` / `spoken_zunda_sample.json`) と `scripts/voicevox.sh` | 読み仮名の表 (YOMI) を動画ごとに書くのは Claude Code |
| 時間管理 | `05_vcon/timeline.py` / `05_vcon/plan_sample.py` | なし。記事の「(b − a) / v」と「0.6 秒を 4 段」はこの中にあります |
| Vコンテ | `05_vcon/sub_pages.py` (字幕の改行) / `05_vcon/zunda_edl.py` (簡易版の書き出し) | 右の欄とずんだもんの絵を重ねる描画本体 (vcon13.py)、確認ページ |
| 全編と公開 | なし | 1080p の書き出しと YouTube への予約投稿 (upload.py) |
| 記事に無い物 | `extra/autocut/cutplan.py` / `extra/autocut/render.py` | 無音と手の動きからカット表を作る自動版。plan.py を書かせる前に試した物で、今の流れでは使っていません |

## 入っていない物とその理由

**Vコンテの描画本体 (vcon13.py、約 1,000 行)。** 右の欄と字幕を HTML にして Chromium で絵にし、ずんだもんの饅頭の口を声の大きさで動かしてコマごとに重ねます。チャンネルのロゴや区切りの絵と口の絵、それにフォントの前提が全体に絡んでいて、外すと動きません。時刻の計算だけを `timeline.py` に抜き出しました。声と字幕を焼き込んだ動画を 1 本作るだけなら `zunda_edl.py` で足ります。

**確認ページ。** 筆者の秘書システムのサーバ側で動いていて、単体では動きません。台本と Vコンテを見て OK か直すかとコメントを集められる物なら、何でも代わりになります。Markdown に答えを書き込むだけでも成り立ちます。

**upload.py。** YouTube Data API v3 で予約投稿する短いスクリプトです。OAuth のトークンが個人の物なので置いていません。

**フォントと効果音と BGM とロゴ。** 再配布できない物と、チャンネル固有の物です。字幕のフォントは `--font` で自分の物を渡します。

**商品のチェックリストと開けたカードの一覧 (cards_full.md)。** 商品の著作物と動画の中身なので置いていません。

**Claude Code への指示 (skill と prompt)。** 秘書システムの一部で、そのままでは動きません。代わりに、下の「Claude Code への頼み方」に、実際に頼む時の文を書きました。

## 動かし方

前提: Python 3.11 以上、ffmpeg、VOICEVOX エンジン (展開した場所を `VOICEVOX_DIR` に入れる)、CUDA の使える GPU (faster-whisper large-v3 用。無ければ `transcribe.py` の device を cpu にして small か medium にしてください)。

```bash
pip install -r requirements.txt
```

1. 文字起こし。単語ごとの時刻付きで `transcript.json` と `transcript.md` が出ます。

   ```bash
   python 01_transcribe/transcribe.py proxy.mp4 work/
   ```

2. コマ出し。元の 2 分から 3 分を 2 秒ごとに切り出し、6 列のコンタクトシートにします。左上に元の時刻が入るので、Claude Code がこれを見てカードの映った時刻を読みます。

   ```bash
   python 02_frames/contact_sheet.py proxy.mp4 120 180 0.5 6 work/sheet_0120.jpg
   python 02_frames/activity.py proxy.mp4 work/
   ```

3. 台本。Claude Code に `transcript.md` とコンタクトシートを渡し、`03_script/script_sample.txt` と同じ形で書かせます。話す行はずんだもん口調で、文末は「のだ」。検査は次の 1 行です。

   ```bash
   python 03_script/check_zunda.py work/script.txt
   ```

4. 声。台本の話す行を `spoken_zunda.json` にし、VOICEVOX で 1 行 1 wav を作ります。字幕に出す文 (`zunda`) と読ませる文 (`yomi`) を分けて持ちます。

   ```bash
   VOICEVOX_DIR=/path/to/voicevox_engine scripts/voicevox.sh start
   python 04_voice/make_spoken.py work/script.txt work/spoken_zunda.json
   python 04_voice/build_audio.py work/spoken_zunda.json work/audio
   scripts/voicevox.sh stop
   ```

5. 時間管理。区切りごとの元の秒と速さと台詞の頭を `plan.py` に書かせ (形は `05_vcon/plan_sample.py`)、声の長さと合わせて出来上がりの時刻を出します。声が映像より長い区切りは、速めた所を等速に戻し、それでも足りなければ映像を延ばすか止め絵を足します。何を変えたかは `timeline.json` の notes に残ります。

   ```bash
   python 05_vcon/timeline.py plan.py work/spoken_zunda.json --voice-dir work/audio --out work/timeline.json
   python 05_vcon/sub_pages.py work/script.txt work/subs.json --font /path/to/bold-gothic.ttf
   ```

6. 簡易版の書き出し。速さの表と台詞 (元の秒で持つ) を 1 つの JSON にして渡すと、速さをならしながら流し、ずんだもんの声と字幕を焼き込んだ mp4 を出します。右の欄と饅頭はありません。

   ```bash
   python 05_vcon/zunda_edl.py edl.json out.mp4 --report work/edl_report.json --font-name "BIZ UDGothic"
   ```

## Claude Code への頼み方

筆者が Claude Code に投げている言い方に近い物です。ファイル名は上の工程のまま出しています。

- 「`work/transcript.md` と `work/sheet_*.jpg` を読んで、`03_script/script_sample.txt` と同じ形で台本を書いて。区切りは 1 パックごと。話す行は全部ずんだもん口調で、`check_zunda.py` が 0 件になるまで直して」
- 「台本の数字と選手名で読みが揺れそうな物を `04_voice/make_spoken.py` の YOMI に足して。読みはカタカナで」
- 「台本の [画面] と `work/audio/lens.json` から `plan.py` を `05_vcon/plan_sample.py` の形で書いて。`timeline.py` を回して、台詞の頭がカードの見えた後になっているか確かめて」
- 「このカードは 1:09 でセリフが遅い。at を直して timeline を出し直して」

## データの形

- `script.txt`: `## <区切りID> <題> [<章>]` の見出しの下に、`[画面]` と `[指示]` の行と、話す行を並べます。`[画面]` と `[指示]` は読み上げません。
- `spoken_zunda.json`: 話す行ごとに 1 つの object。`cue` は区切りの番号で `cue_id` はその ID、`zunda` は字幕の文で `i` は行番号。読みが字幕と違う行だけ `yomi` を持ちます。
- `plan.py`: 区切りごとに `segs` (元の秒の始まりと終わりと速さ) と `at` (行ごとの言い始めの元の秒) を持ち、ほかに `moves` (ズームと止め) と `col` (右の欄の中身) を書きます。`timeline.py` が読むのは segs と at と止めの moves、それに tight / extend_to / still です。
- `timeline.json`: 区切りごとの出来上がりの頭と終わりの秒と切れ端の並びと変えた事の notes。行ごとに声の頭と終わりの秒。

## クレジットとライセンス

- このリポジトリのコードは MIT ライセンスです。
- 声は [VOICEVOX](https://voicevox.hiroshiba.jp/) のずんだもんです。動画に使う時は「VOICEVOX:ずんだもん」のクレジットと、キャラクターの利用規約に従ってください。
- 文字起こしは [faster-whisper](https://github.com/SYSTRAN/faster-whisper)、字幕の改行は [BudouX](https://github.com/google/budoux) を使っています。
