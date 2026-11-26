#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
相関図（L1）のPNGを台本データから生成する。

  データ/NN.json  ＋  共通設定.json   ──→   出力/NN/カットXX_PY.png

準拠：docs/相関図仕様書.md v3（決定#48〜#61）
使い方：python3 生成.py 01        # 第1話だけ
        python3 生成.py           # 全話
        python3 生成.py 01 --表    # 台本に貼るページ割り表を出力（PNGは作らない）
"""
import json, sys, os, subprocess, shutil

ここ = os.path.dirname(os.path.abspath(__file__))
設定 = json.load(open(os.path.join(ここ, '共通設定.json'), encoding='utf-8'))


# ────────────────────────── 書体 ──────────────────────────
import base64, hashlib, re, urllib.parse

書体置き場 = os.path.join(ここ, '書体')
ブラウザのふり = ('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')


def 字を集める(話データ):
    """台本データに出てくる文字をすべて集める（この字だけ書体を取り寄せる）"""
    字 = set('　 ・／（）0123456789')
    for 名, v in 話データ['ノード'].items():
        字 |= set(名) | set(v.get('小') or '')
    for p in 話データ['ページ'].values():
        for 段 in p['段']:
            字 |= set(段.get('帯') or '')
            for nd in 段['ノード']:
                字 |= set(nd.get('サブ') or '')
    return ''.join(sorted(字))


def 書体を取り寄せる(家, 太さ, 字):
    """Google Fonts から、必要な字だけに絞った woff2 を取り寄せて base64 で返す。
    一度取ったものは 書体/ に残すので、2回目からは通信しない。"""
    os.makedirs(書体置き場, exist_ok=True)
    鍵 = hashlib.sha256(f'{家}|{太さ}|{字}'.encode()).hexdigest()[:16]
    殻 = os.path.join(書体置き場, f'{家.replace(" ", "_")}-{太さ}-{鍵}.woff2')
    if not os.path.exists(殻):
        url = (f'https://fonts.googleapis.com/css2?family={家.replace(" ", "+")}'
               f':wght@{太さ}&text={urllib.parse.quote(字)}')
        css = subprocess.run(['curl', '-sS', '-A', ブラウザのふり, url],
                             capture_output=True, text=True, check=True).stdout
        見つけた = re.findall(r'url\((https://[^)]+)\)', css)
        if not 見つけた:
            raise SystemExit(f'✗ 書体を取り寄せられない: {家} {太さ}\n{css[:200]}')
        subprocess.run(['curl', '-sS', '-o', 殻, 見つけた[0]], check=True)
        print(f'  書体を取り寄せた: {家} {太さ}（{os.path.getsize(殻):,} bytes）')
    return base64.b64encode(open(殻, 'rb').read()).decode()


def 書体のCSS(話データ):
    字 = 字を集める(話データ)
    書 = 設定['書体']
    欲しい = [(書['ゴシック'], 書['神名太さ']), (書['ゴシック'], 書['サブ太さ']),
              (書['明朝'], 書['漢字太さ'])]
    出 = []
    for 家, 太さ in dict.fromkeys(欲しい):
        b = 書体を取り寄せる(家, 太さ, 字)
        出.append(f"@font-face{{font-family:'{家}';font-style:normal;font-weight:{太さ};"
                  f"font-display:block;src:url(data:font/woff2;base64,{b}) format('woff2')}}")
    return '\n'.join(出)


# ────────────────────────── 検算 ──────────────────────────
def 幅を検算する(n):
    """仕様書3節：幅 ＝ (920 − 40×(n−1)) ÷ n

    ⚠ n=1 は公式の例外。式だと920pxになるが、仕様書は
      「1個だけの行は440pxにして、幹(x=1440)の真下に中央寄せする」と定めている。
    """
    表の値 = 設定['ノード']['行'][str(n)]['幅']
    if n == 1:
        if 表の値 != 設定['ノード']['行']['2']['幅']:
            raise SystemExit('✗ n=1 の幅は n=2 と同じ440pxであること（仕様書3節）')
        return 表の値
    使える幅 = 設定['キャンバス']['幅'] - 設定['キャンバス']['外周'] * 2
    余白 = 設定['ノード']['余白']
    計算値 = (使える幅 - 余白 * (n - 1)) / n
    if abs(計算値 - 表の値) > 0.5:
        raise SystemExit(f'✗ 幅の検算が合わない n={n}: 式={計算値} 表={表の値}')
    return 表の値


def 字数を検算する(話データ):
    """神名・小さい行・サブタイトルが、使われる最小の幅に収まるか"""
    問題 = []
    行数 = {}   # ノード名 → そのノードが置かれる n の最大値（＝最も狭い幅）
    for ページ, p in 話データ['ページ'].items():
        for 段 in p['段']:
            n = len(段['ノード'])
            for nd in 段['ノード']:
                行数[nd['名']] = max(行数.get(nd['名'], 0), n)
    for 名, n in 行数.items():
        規格 = 設定['ノード']['行'][str(n)]
        上限行字 = 規格['神名字数']
        行上限 = 2 if n >= 3 else 1
        if len(名) > 上限行字 * 行上限:
            問題.append(f'神名「{名}」{len(名)}字 > n={n} の上限{上限行字*行上限}字')
        小 = 話データ['ノード'][名].get('小')
        if 小 and len(小) > 規格['幅'] // 規格['漢字']:
            問題.append(f'小さい行「{小}」{len(小)}字 > n={n} の上限{規格["幅"]//規格["漢字"]}字')
    for ページ, p in 話データ['ページ'].items():
        for 段 in p['段']:
            n = len(段['ノード'])
            規格 = 設定['ノード']['行'][str(n)]
            上限 = 規格['幅'] // 規格['サブ']
            for nd in 段['ノード']:
                サブ = nd.get('サブ')
                if サブ and len(サブ) > 上限:
                    問題.append(f'{ページ} サブ「{サブ}」{len(サブ)}字 > n={n} の上限{上限}字')
    return 問題


def 縦を検算する(段数リスト):
    """仕様書3節「縦の検算」。帯の高さを積み上げて1080pxに収まるか"""
    地 = 設定['地']; 帯 = 設定['帯高さ']
    合計 = 設定['キャンバス']['外周']
    for i, n in enumerate(段数リスト):
        高さ = 設定['ノード']['行'][str(n)]['高さ']
        前 = 帯['線なし前'] if i == 0 else 帯['線あり前'] + 地['縦線']
        合計 += 前 + 高さ + 帯['下余白']
        if i < len(段数リスト) - 1:
            合計 += 地['帯間']
    return 合計


# ────────────────────────── 配置 ──────────────────────────
def 段の配置(段, 帯上端, 線あり):
    """1段ぶんのノード座標と帯の高さを返す"""
    n = len(段['ノード'])
    規格 = 設定['ノード']['行'][str(n)]
    幅 = 幅を検算する(n)
    高さ = 規格['高さ']
    前 = 設定['帯高さ']['線あり前'] + (設定['地']['縦線'] if 線あり else 0) if 線あり \
         else 設定['帯高さ']['線なし前']
    ノード上端 = 帯上端 + 前
    帯高 = 前 + 高さ + 設定['帯高さ']['下余白']

    if 規格['中央寄せ']:
        起点 = 設定['地']['幹x'] - 幅 / 2
    else:
        起点 = 設定['ノード']['起点x']
    置く = []
    for i, nd in enumerate(段['ノード']):
        x = 起点 + i * (幅 + 設定['ノード']['余白'])
        置く.append({**nd, 'x': x, 'y': ノード上端, '幅': 幅, '高さ': 高さ, 'n': n, '規格': 規格})
    return 置く, 帯高, ノード上端


def ページを組む(話データ, ページid):
    p = 話データ['ページ'][ページid]
    y = 設定['キャンバス']['外周']
    if 設定['キャンバス'].get('縦の寄せ') == '中央寄せ' and p['段']:
        # 先に全体の高さを測ってから、上下の余白が等しくなる位置から始める
        仮 = 設定['キャンバス']['外周']
        for i, 段 in enumerate(p['段']):
            _, 帯高, _ = 段の配置(段, 仮, i > 0)
            仮 += 帯高 + (設定['地']['帯間'] if i < len(p['段']) - 1 else 0)
        中身 = 仮 - 設定['キャンバス']['外周']
        y = max(設定['キャンバス']['外周'],
                (設定['キャンバス']['高さ'] - 中身) // 2)
    段リスト = []
    for i, 段 in enumerate(p['段']):
        線あり = (i > 0)
        置く, 帯高, ノード上端 = 段の配置(段, y, 線あり)
        段リスト.append({'帯上端': y, '帯高': 帯高, 'ノード': 置く,
                         'ラベル': 段.get('帯'), '夫婦': 段.get('夫婦', []),
                         'ノード上端': ノード上端, '線あり': 線あり})
        y += 帯高 + 設定['地']['帯間']
    return 段リスト


# ────────────────────────── 描画 ──────────────────────────
def 折る(名, 規格, n):
    """2行になるときは、なるべく均等に割る。
    「帰り道の6島」を 5+1 で割ると2行目が1字になって不格好なので 3+3 にする。
    どちらの行も 規格['神名字数'] を超えないことは字数検算で保証済み。"""
    上限 = 規格['神名字数']
    if n < 3 or len(名) <= 上限:
        return [名]
    一行目 = min(-(-len(名) // 2), 上限)
    if len(名) - 一行目 > 上限:
        一行目 = len(名) - 上限
    return [名[:一行目], 名[一行目:]]


def HTMLを作る(話データ, ページid, 強調, 書体css):
    段リスト = ページを組む(話データ, ページid)
    地 = 設定['地']; 書体 = 設定['書体']; 強 = 設定['強調枠']
    W = 設定['キャンバス']['幅']; H = 設定['キャンバス']['高さ']
    部品 = []

    # 帯
    for 段 in 段リスト:
        部品.append(
            f'<div class="帯" style="left:{地["帯左"]}px;top:{段["帯上端"]}px;'
            f'width:{地["帯幅"]}px;height:{段["帯高"]}px"></div>')
        if 段['ラベル']:
            部品.append(
                f'<div class="帯ラベル" style="left:{地["帯左"]+地["帯ラベル左"]}px;'
                f'top:{段["帯上端"]+地["帯ラベル下端"]-地["帯ラベル字"]}px">{段["ラベル"]}</div>')

    # 線（ノードより先に描いて下に敷く）
    for i, 段 in enumerate(段リスト):
        for a, b in 段['夫婦']:
            na = next(x for x in 段['ノード'] if x['名'] == a)
            nb = next(x for x in 段['ノード'] if x['名'] == b)
            左 = min(na['x'] + na['幅'], nb['x'] + nb['幅'])
            右 = max(na['x'], nb['x'])
            中 = na['y'] + na['高さ'] / 2
            半 = (地['夫婦線間隔'] / 2 + 地['夫婦線太さ'] / 2)
            for d in (-半, 半):
                部品.append(f'<div class="線" style="left:{左}px;top:{中+d-地["夫婦線太さ"]/2}px;'
                            f'width:{右-左}px;height:{地["夫婦線太さ"]}px"></div>')
        if i + 1 < len(段リスト):
            下 = 段リスト[i + 1]
            # 幹：親の高さ中央（または夫婦線）から兄弟バーまで
            幹上 = 段['ノード'][0]['y'] + 段['ノード'][0]['高さ'] / 2
            バーy = 下['ノード上端'] - 地['縦線']
            部品.append(f'<div class="線" style="left:{地["幹x"]-地["親子線太さ"]/2}px;top:{幹上}px;'
                        f'width:{地["親子線太さ"]}px;height:{バーy-幹上}px"></div>')
            中心 = [nd['x'] + nd['幅'] / 2 for nd in 下['ノード']]
            左, 右 = min(中心 + [地['幹x']]), max(中心 + [地['幹x']])
            if 右 > 左:
                部品.append(f'<div class="線" style="left:{左}px;top:{バーy-地["親子線太さ"]/2}px;'
                            f'width:{右-左}px;height:{地["親子線太さ"]}px"></div>')
            for c in 中心:
                部品.append(f'<div class="線" style="left:{c-地["親子線太さ"]/2}px;top:{バーy}px;'
                            f'width:{地["親子線太さ"]}px;height:{地["縦線"]}px"></div>')

    # ノード
    for 段 in 段リスト:
        for nd in 段['ノード']:
            系 = 設定['系統'][話データ['ノード'][nd['名']]['系統']]
            規格 = nd['規格']
            退場 = nd.get('退場', False)
            # 退場＝塗りを抜く。ただし「透明」にしてはいけない。
            # 帯の中にあるので、透明だと背景が帯#D6C39Cになり、輪郭線と文字の
            # コントラストが 3.86〜4.59 に落ちて4系統が基準4.5を下回る。
            # 和紙色で塗れば、仕様書0節の数値（6.19〜7.36）どおりになる。
            塗り = 設定['地']['背景'] if 退場 else 系['塗り']
            文字色 = 系['輪郭'] if 退場 else 系['文字']
            部品.append(
                f'<div class="ノード" style="left:{nd["x"]}px;top:{nd["y"]}px;'
                f'width:{nd["幅"]}px;height:{nd["高さ"]}px;background:{塗り};'
                f'border:{設定["ノード"]["輪郭線"]}px solid {系["輪郭"]};'
                f'border-radius:{設定["ノード"]["角丸"]}px"></div>')
            行 = 折る(nd['名'], 規格, nd['n'])
            字 = 設定['ノード']['神名字サイズ']
            ys = [規格['神名1行のみ']] if len(行) == 1 else [規格['神名1行目'], 規格['神名2行目']]
            for t, by in zip(行, ys):
                部品.append(
                    f'<div class="神名" style="left:{nd["x"]}px;top:{nd["y"]+by-字}px;'
                    f'width:{nd["幅"]}px;height:{字}px;font-size:{字}px;color:{文字色}">{t}</div>')
            小 = 話データ['ノード'][nd['名']].get('小')
            if 小:
                s = 規格['漢字']
                部品.append(
                    f'<div class="小" style="left:{nd["x"]}px;top:{nd["y"]+規格["漢字y"]-s}px;'
                    f'width:{nd["幅"]}px;height:{s}px;font-size:{s}px;color:{文字色}">{小}</div>')
            サブ = nd.get('サブ')
            if サブ:
                s = 規格['サブ']
                部品.append(
                    f'<div class="サブ" style="left:{nd["x"]}px;top:{nd["y"]+規格["サブy"]-s}px;'
                    f'width:{nd["幅"]}px;height:{s}px;font-size:{s}px;color:{文字色}">{サブ}</div>')

    # 強調枠（最後に描いて最前面）
    for 段 in 段リスト:
        for nd in 段['ノード']:
            if nd['名'] in 強調:
                す = 強['すきま']; 太 = 強['太さ']
                # ノードは box-sizing:border-box なので、3pxの輪郭線は幅の内側にある。
                # 強調枠の外側 ＝ ノードの外周 ＋ すきま ＋ 枠の太さ。
                # ⚠ いちばん右／左のノードでは、この枠が外枠(20px)に14px重なる。
                #   枠を全部見せるため、外枠より前面に描く（仕様書の未記載事項）。
                部品.append(
                    f'<div class="強調" style="left:{nd["x"]-す-太}px;top:{nd["y"]-す-太}px;'
                    f'width:{nd["幅"]+2*(す+太)}px;height:{nd["高さ"]+2*(す+太)}px;'
                    f'border:{太}px solid {強["色"]};'
                    f'border-radius:{設定["ノード"]["角丸"]+す+太}px"></div>')

    g, m = 書体['ゴシック'], 書体['明朝']
    return f'''<!doctype html><html lang="ja"><head><meta charset="utf-8">
<style>
{書体css}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{width:{W}px;height:{H}px;background:{地["背景"]};position:relative;overflow:hidden;
     font-family:'{g}',sans-serif;-webkit-font-smoothing:antialiased}}
.外枠{{position:absolute;inset:0;border:{設定["キャンバス"]["外周"]}px solid {地["外枠"]}}}
.帯{{position:absolute;background:{地["帯塗り"]};border:{地["帯枠太さ"]}px solid {地["帯枠"]};
     border-radius:{地["帯角丸"]}px}}
.帯ラベル{{position:absolute;font-size:{地["帯ラベル字"]}px;color:{地["帯ラベル色"]};
     font-weight:{書体["帯ラベル太さ"]};line-height:{地["帯ラベル字"]}px}}
.線{{position:absolute;background:{地["線"]}}}
.ノード{{position:absolute}}
.神名{{position:absolute;text-align:center;font-weight:{書体["神名太さ"]};line-height:1;
     font-feature-settings:"palt" 0}}
.小{{position:absolute;text-align:center;font-family:'{m}',serif;
     font-weight:{書体["漢字太さ"]};line-height:1}}
.サブ{{position:absolute;text-align:center;font-weight:{書体["サブ太さ"]};line-height:1}}
.強調{{position:absolute;z-index:10}}
</style></head><body>
<div class="外枠"></div>
{chr(10).join(部品)}
</body></html>'''


# ────────────────────────── 出力 ──────────────────────────
def 仕事を並べる(話データ):
    仕事 = []
    for c in 話データ['カット']:
        状態 = c['強調'] or [[]]
        for i, 強調 in enumerate(状態):
            枝 = f'_{i+1}' if len(状態) > 1 else ''
            名 = f'カット{c["カット"]:02d}_{c["ページ"]}{枝}.png'
            仕事.append({'名': 名, 'ページ': c['ページ'], '強調': 強調, 'カット': c['カット']})
    return 仕事


def 表を作る(話データ):
    """台本に貼るページ割り表（Markdown）"""
    ページ順 = list(話データ['ページ'].keys())
    使う = {}
    for c in 話データ['カット']:
        使う.setdefault(c['ページ'], []).append(c['カット'])
    行 = ['| ページ | カット | 時刻 | 画面に出るノード | 行の数と幅 | 帯 |',
          '|---|---|---|---|---|---|']
    for pid in ページ順:
        cs = 使う.get(pid, [])
        if not cs:
            continue
        時刻 = [c['時刻'] for c in 話データ['カット'] if c['ページ'] == pid]
        はん = f'{cs[0]}〜{cs[-1]}' if len(cs) > 1 else f'{cs[0]}'
        時 = f'{時刻[0].split("-")[0]}-{時刻[-1].split("-")[1]}'
        段リスト = ページを組む(話データ, pid)
        もの, はば = [], []
        for 段 in 段リスト:
            もの.append('・'.join(nd['名'] + ('（輪郭だけ）' if nd.get('退場') else '')
                                  for nd in 段['ノード']))
            n = len(段['ノード'])
            規格 = 設定['ノード']['行'][str(n)]
            はば.append(f'n={n}・{規格["幅"]}×{規格["高さ"]}')
        if not 段リスト:
            もの, はば = ['なし（枠のみ）'], ['—']
        行.append(f'| **{pid}** | {はん} | {時} | {" ／ ".join(もの)} | '
                  f'{" ／ ".join(はば)} | {len(段リスト)}段 |')
    return '\n'.join(行)


def 生成(話番号, 表だけ=False):
    経路 = os.path.join(ここ, 'データ', f'{話番号}.json')
    話データ = json.load(open(経路, encoding='utf-8'))

    問題 = 字数を検算する(話データ)
    for pid in 話データ['ページ']:
        段数 = [len(s['ノード']) for s in 話データ['ページ'][pid]['段']]
        if 段数:
            縦 = 縦を検算する(段数)
            if 縦 > 設定['キャンバス']['高さ']:
                問題.append(f'{pid} 縦が{縦}px（上限{設定["キャンバス"]["高さ"]}px）')
        if len(段数) > 3:
            問題.append(f'{pid} 帯が{len(段数)}段（上限3段・仕様書3節）')
    if 問題:
        print(f'✗ 第{話番号}話 検算で{len(問題)}件の問題')
        for x in 問題:
            print('   ', x)
        raise SystemExit(1)
    print(f'✓ 第{話番号}話 検算OK（字数・縦・段数）')

    if 表だけ:
        print()
        print(表を作る(話データ))
        return

    出力 = os.path.join(ここ, '出力', 話番号)
    os.makedirs(出力, exist_ok=True)
    仕事 = 仕事を並べる(話データ)
    一時 = os.path.join(ここ, '.html')
    os.makedirs(一時, exist_ok=True)
    書体css = 書体のCSS(話データ)
    指示 = []
    for w in 仕事:
        h = os.path.join(一時, w['名'].replace('.png', '.html'))
        open(h, 'w', encoding='utf-8').write(
            HTMLを作る(話データ, w['ページ'], w['強調'], 書体css))
        指示.append({'html': h, 'png': os.path.join(出力, w['名'])})
    json.dump({'指示': 指示, '幅': 設定['キャンバス']['幅'],
               '高さ': 設定['キャンバス']['高さ'], '倍率': 設定['キャンバス']['倍率']},
              open(os.path.join(一時, '_指示.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    subprocess.run(['node', os.path.join(ここ, '撮る.js'),
                    os.path.join(一時, '_指示.json')], check=True)
    print(f'✓ 第{話番号}話 {len(仕事)}枚を {出力} に出力')
    shutil.rmtree(一時)


if __name__ == '__main__':
    引数 = [a for a in sys.argv[1:] if not a.startswith('--')]
    表だけ = '--表' in sys.argv
    話 = 引数 or [f'{i:02d}' for i in range(1, 16)
                  if os.path.exists(os.path.join(ここ, 'データ', f'{i:02d}.json'))]
    for t in 話:
        生成(t, 表だけ)
