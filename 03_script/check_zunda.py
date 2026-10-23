"""動画の原稿 (台本の script.txt) の、ずんだもん口調の検査。声を作る前に 0 件にする。

- 話す行 (## の見出し ・ [画面] ・ [指示] ・ # 以外) を 。！？ で文に割り (「」の中では割らない)、文末が「のだ」でない文を出す
- です ・ ます ・ 僕 が話す行に残っていないかも見る (一人称は「ボク」)
使い方: python check_zunda.py <script.txt>   (終了コード 1 = 直す所あり)
"""
import re
import sys


def sentences(line):
    out, buf, depth = [], '', 0
    for ch in line:
        buf += ch
        if ch == '「':
            depth += 1
        elif ch == '」':
            depth = max(0, depth - 1)
        elif ch in '。！？' and depth == 0:
            out.append(buf.strip()); buf = ''
    if buf.strip():
        out.append(buf.strip())
    return out


def check(path):
    bad, cur = [], None
    for ln in open(path, encoding='utf-8').read().split('\n'):
        m = re.match(r'^## (\S+)', ln)
        if m:
            cur = m.group(1); continue
        if cur is None or not ln.strip() or ln.startswith('[') or ln.startswith('#'):
            continue
        for s in sentences(ln.strip()):
            core = s.rstrip('。！？')
            if not s[-1:] in '。！？':
                bad.append((cur, '句点が無い', s))
            elif not core.endswith('のだ'):
                bad.append((cur, '文末が「のだ」でない', s))
        for w in ('です', 'ます', '僕'):
            if w in re.sub(r'「[^」]*」', '', ln):
                bad.append((cur, f'「{w}」が残っている', ln.strip()[:40]))
    return bad


if __name__ == '__main__':
    bad = check(sys.argv[1])
    for sid, why, s in bad:
        print(f'{sid}\t{why}\t{s}')
    print(len(bad), '件')
    sys.exit(1 if bad else 0)
