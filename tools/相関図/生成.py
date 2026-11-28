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
        for 段 in p.get('段', []):
            字 |= set(段.get('帯') or '')
            for nd in 段['ノード']:
                字 |= set(nd.get('サブ') or '')
        for 段 in p.get('段', []):
            for r in 段.get('関係', []):
                字 |= set(r.get('札') or '')
        for x in p.get('配置', []):            # 関係図
            字 |= set(x.get('サブ') or '')
        for r in p.get('関係', []):
            字 |= set(r.get('札') or '')
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


# ────────────────────────── 寸法 ──────────────────────────
def 図幅():
    return 設定['キャンバス'].get('相関図幅', 設定['キャンバス']['幅'])


def 地寸法():
    """幹の位置と帯の横位置は相関図の幅で決まる（仕様書4節の検算を一般化）"""
    地 = dict(設定['地'])
    W = 図幅()
    地['幹x'] = W // 2 + (地.get('帯ラベル幅', 0) // 2
                          if 地.get('帯ラベル位置') == '左' else 0)
    地['帯左'] = 設定['キャンバス']['外周'] - 5
    地['帯幅'] = W - 2 * 地['帯左']
    return 地


def 縦書きか():
    return 設定.get('書字方向') == '縦書き'


def 縦の列数(長さ, 上限, 名前=False):
    """縦書きの列数。**2列までに制限する。**
    3列になると読む順番が追いにくく、実機で読めないため（2026年11月28日）。
    設定「名前は1列」が true のときは、神名は折り返さず必ず1列にする。"""
    if 名前 and 設定['縦書き'].get('名前は1列'):
        return 1
    return min(2, max(1, -(-長さ // 上限)))


def 縦に割る(名, 列数):
    """2列に割るとき、「・」や「／」があればその直後で割る。
    「八咫鏡・八／尺瓊勾玉」のように語の途中で切れるのを避ける。
    CSSの縦書きは幅で折り返すので、割り位置に全角スペースを入れて調整する……
    のではなく、ここでは列の高さが変わらない範囲でのみ区切りを優先する。"""
    if 列数 < 2:
        return 名
    均等 = -(-len(名) // 列数)
    for 区切り in ('・', '／'):
        i = 名.find(区切り)
        if i >= 0:
            前, 後 = i + 1, len(名) - (i + 1)
            if 前 <= 均等 and 後 <= 均等:
                # 前の列を均等分の長さまで全角スペースで埋めて、区切りで折らせる
                return 名[:前] + '\u3000' * (均等 - 前) + 名[前:]
    return 名


def 縦の規格(幅, 名々, 小々, 役々=None):
    """縦書き：神名を縦に置く。長い名は2列に折る（右の列から読む）。

    ⚠ 段の高さは「いちばん長い名前」ではなく、**1件ずつ高さを出して最大を取る**。
      長い名ほど列が増えて背が低くなるため、逆転が起きる。
        ウガヤフキアエズ 8字 → 2列 → 192px
        タマヨリヒメ     6字 → 1列 → 288px  ← こちらのほうが高い
      最長の名前から決めると、短いほうが枠からあふれて漢字に重なる。
    """
    t = 設定['縦書き']
    字 = 設定['ノード']['神名字サイズ']
    漢 = 32 if 幅 >= 200 else (26 if 幅 >= 150 else 22)
    サ = 26 if 幅 >= 200 else 22
    列上限 = t.get('1列の最大字数', 6)
    位置 = t.get('役割の位置', '下')
    役字 = t.get('役割の字', 22)

    def 高さ(語, 文字):
        c = 縦の列数(len(語), 列上限 if 文字 == 字 else 列上限 + 2,
                     名前=(文字 == 字))
        return -(-len(語) // c) * 文字

    名高 = max((高さ(n, 字) for n in 名々 if n), default=0)
    小高 = max((高さ(k, 漢) for k in 小々 if k), default=0)
    中身 = max(名高, 小高)
    if 位置 == '左列':
        役高 = max((高さ(r, 役字) for r in (役々 or []) if r), default=0)
        中身 = max(中身, 役高)
    名列 = max((縦の列数(len(n), 列上限, 名前=True) for n in 名々 if n), default=1)
    小列 = max((縦の列数(len(k), 列上限 + 2) for k in 小々 if k), default=0)
    下の分 = (t['サブ上'] + サ) if 位置 == '下' else 0
    # 枠に重ねるタグは、カードがもともと持つ余白と、親子線の空間に収まるので
    # 縦の追加はゼロ。下辺だけは帯の下に少し出るので、その半分だけ足す
    帯の追加 = ((役字 + 10) if 位置 == '枠外下'
                else ((役字 + 12) // 2 if 位置 == '重ね下' else 0))
    上の分 = (役字 + 10) if 位置 == '上タグ' else 0
    return {'幅': 幅, '高さ': t['上余白'] + 上の分 + 中身 + 下の分 + t['下余白'],
            '中央寄せ': False, '縦': True, '字': 字, '漢字': 漢, 'サブ': サ,
            '上余白': t['上余白'], 'すきま': t['名と漢字のすきま'],
            '中身高': 中身, 'サブy': t['上余白'] + 上の分 + 中身 + t['サブ上'] + サ,
            '役割位置': 位置, '役割字': 役字, '役割すきま': t.get('役割のすきま', 8),
            '上の分': 上の分, '帯の追加': 帯の追加,
            '名列': 名列, '小列': 小列, '列上限': 列上限, '神名字数': 99}


def 規格を作る(幅, 神名行, 小行):
    """カードの幅と行数から、高さと文字のベースラインを決める。
    1行48px。神名は最大3行、小さい行（漢字・読み）は最大2行まで折る。
    幅960のときは仕様書3節の表をそのまま使うので、この関数は通らない。"""
    字 = 設定['ノード']['神名字サイズ']
    漢 = 32 if 幅 >= 340 else (24 if 幅 >= 230 else 22)
    サ = 28 if 幅 >= 340 else (26 if 幅 >= 230 else 24)
    最後の神名 = 56 + 字 * (神名行 - 1)
    小y = 最後の神名 + 38
    サブy = 小y + 38 * max(小行, 1)
    return {'幅': 幅, '高さ': サブy + 30, '中央寄せ': False,
            '神名字数': max(1, 幅 // 字), '神名行上限': 神名行,
            '漢字': 漢, 'サブ': サ,
            '神名1行目': 56, '神名2行目': 56 + 字, '神名3行目': 56 + 字 * 2,
            '神名1行のみ': 56, '漢字y': 小y, '漢字行': 小行, 'サブy': サブy}


def 幅表():
    """相関図の幅から、n個並べる行の規格を作る。
    幅960のときは共通設定.json の表（＝仕様書3節）とぴったり一致する。"""
    使える幅 = 図幅() - 設定['キャンバス']['外周'] * 2
    if 地寸法().get('帯ラベル位置') == '左':
        使える幅 -= 地寸法()['帯ラベル幅']
    余白 = 設定['ノード']['余白']
    字 = 設定['ノード']['神名字サイズ']
    表 = {}
    for n in range(1, 設定['ノード']['1行の最大数'] + 1):
        幅 = 使える幅 if n == 1 else (使える幅 - 余白 * (n - 1)) / n
        if n == 1:
            幅 = (使える幅 - 余白) / 2        # 1個の行は2個の行と同じ幅・中央寄せ
        幅 = int(幅)
        元 = 設定['ノード']['行'].get(str(n))
        # 仕様書3節の表をそのまま使えるのは、幅960で、かつ帯ラベルが帯の上にある
        # ときだけ。ラベルを左に出すと使える幅が減るので、計算し直す
        仕様どおり = (図幅() == 設定['キャンバス']['幅']
                      and 地寸法().get('帯ラベル位置') != '左')
        if 仕様どおり and 元:
            表[n] = dict(元)
        else:
            二行 = 幅 // 字 < 5               # 1行に5字入らないなら2行立てにする
            表[n] = {'幅': 幅, '高さ': 210 if 二行 else 170,
                     '中央寄せ': n == 1, '神名字数': max(1, 幅 // 字),
                     '漢字': 32 if 幅 >= 340 else 24, 'サブ': 28 if 幅 >= 340 else 26,
                     '神名1行目': 56, '神名2行目': 104, '神名1行のみ': 80 if 二行 else 60,
                     '漢字y': 142 if 二行 else 104, 'サブy': 180 if 二行 else 142}
        if not 仕様どおり:
            表[n]['幅'] = 幅
    return 表


# ────────────────────────── 検算 ──────────────────────────
def _幅の元():
    使 = 図幅() - 設定['キャンバス']['外周'] * 2
    if 地寸法().get('帯ラベル位置') == '左':
        使 -= 地寸法()['帯ラベル幅']
    return 使


def 幅を検算する(n):
    """仕様書3節：幅 ＝ (920 − 40×(n−1)) ÷ n

    ⚠ n=1 は公式の例外。式だと920pxになるが、仕様書は
      「1個だけの行は440pxにして、幹(x=1440)の真下に中央寄せする」と定めている。
    """
    表の値 = 幅表()[n]['幅']
    if n == 1:
        if 表の値 != 幅表()[2]['幅']:
            raise SystemExit('✗ n=1 の幅は n=2 と同じ440pxであること（仕様書3節）')
        return 表の値
    使える幅 = _幅の元()
    余白 = 設定['ノード']['余白']
    計算値 = (使える幅 - 余白 * (n - 1)) / n
    # 幅は切り捨てて整数にするので、式との差は1px未満なら正しい
    if not (0 <= 計算値 - 表の値 < 1):
        raise SystemExit(f'✗ 幅の検算が合わない n={n}: 式={計算値:.2f} 表={表の値}')
    return 表の値


def 字数を検算する(話データ):
    """神名・小さい行・サブタイトルが、使われる最小の幅に収まるか"""
    問題 = []
    行数 = {}   # ノード名 → そのノードが置かれる n の最大値（＝最も狭い幅）
    for ページ, p in 話データ['ページ'].items():
        for 段 in p.get('段', []):
            n = len(段['ノード'])
            for nd in 段['ノード']:
                行数[nd['名']] = max(行数.get(nd['名'], 0), n)
    if 縦書きか():
        return 縦の検算(話データ)
    for 名, n in 行数.items():
        規格 = 幅表()[n]
        上限行字 = 規格['神名字数']
        行上限 = 規格.get('神名行上限', 2 if n >= 3 else 1)
        if 図幅() != 設定['キャンバス']['幅']:
            行上限 = 3
        if len(名) > 上限行字 * 行上限:
            問題.append(f'神名「{名}」{len(名)}字 > n={n} の上限{上限行字*行上限}字')
        小 = 話データ['ノード'][名].get('小')
        小の行 = 2 if 図幅() != 設定['キャンバス']['幅'] else 1
        if 小 and len(小) > (規格['幅'] // 規格['漢字']) * 小の行:
            問題.append(f'小さい行「{小}」{len(小)}字 > n={n} の上限{規格["幅"]//規格["漢字"]}字')
    for ページ, p in 話データ['ページ'].items():
        for 段 in p.get('段', []):
            n = len(段['ノード'])
            規格 = 幅表()[n]
            上限 = 規格['幅'] // 規格['サブ']
            for nd in 段['ノード']:
                サブ = nd.get('サブ')
                if サブ and len(サブ) > 上限:
                    問題.append(f'{ページ} サブ「{サブ}」{len(サブ)}字 > n={n} の上限{上限}字')
    return 問題


def 縦の検算(話データ):
    """縦書きのときは「幅に何字入るか」ではなく「縦に収まるか」を見る"""
    問題 = []
    for ページ, p in 話データ['ページ'].items():
        for 段 in p.get('段', []):
            n = len(段['ノード'])
            幅 = 幅を検算する(n)
            規格 = 縦の規格(幅, [x['名'] for x in 段['ノード']],
                          [話データ['ノード'][x['名']].get('小') or ''
                           for x in 段['ノード']],
                          [x.get('サブ') or '' for x in 段['ノード']])
            要る = (規格['名列'] * 規格['字'] + 規格['すきま']
                    + 規格['小列'] * 規格['漢字'])
            if 規格['役割位置'] == '左列':
                役最長 = max((len(x.get('サブ') or '') for x in 段['ノード']), default=0)
                要る += 規格['役割すきま'] + 縦の列数(役最長, 規格['列上限'] + 3) * 規格['役割字']
            if 要る > 幅:
                問題.append(f'{ページ} 横に{要る}px要るが幅{幅}px（神名＋漢字の2列）')
            if 規格['役割位置'] == '下':
                for nd in 段['ノード']:
                    サブ = nd.get('サブ')
                    if サブ and len(サブ) > 幅 // 規格['サブ']:
                        問題.append(f'{ページ} サブ「{サブ}」{len(サブ)}字 > 上限{幅//規格["サブ"]}字')
    return 問題


def 縦を検算する(段数リスト):
    """仕様書3節「縦の検算」。帯の高さを積み上げて1080pxに収まるか"""
    地 = 地寸法(); 帯 = 設定['帯高さ']
    合計 = 設定['キャンバス']['外周']
    for i, n in enumerate(段数リスト):
        高さ = 幅表()[n]['高さ'] if not 縦書きか() else 0
        前 = 帯['線なし前'] if i == 0 else 帯['線あり前'] + 地['縦線']
        合計 += 前 + 高さ + 帯['下余白']
        if i < len(段数リスト) - 1:
            合計 += 地['帯間']
    return 合計


# ────────────────────────── 配置 ──────────────────────────
def 段の配置(段, 帯上端, 線あり, 話データ=None):
    """1段ぶんのノード座標と帯の高さを返す。
    幅960以外では、その段に置くノードが必要とする行数からカードの高さを決める
    （横を狭めたぶん、縦に伸ばす）。"""
    n = len(段['ノード'])
    幅 = 幅を検算する(n)
    if 縦書きか() and 話データ is not None:
        名々 = [nd['名'] for nd in 段['ノード']]
        小々 = [話データ['ノード'][nd['名']].get('小') or '' for nd in 段['ノード']]
        役々 = [nd.get('サブ') or '' for nd in 段['ノード']]
        規格 = 縦の規格(幅, 名々, 小々, 役々)
        規格['中央寄せ'] = (n == 1)   # 1個だけの行は幹の真下に中央寄せ（仕様書3節）
    elif 図幅() == 設定['キャンバス']['幅'] or 話データ is None:
        規格 = 幅表()[n]
    else:
        基 = 幅表()[n]
        上限 = 基['神名字数']
        漢 = 32 if 幅 >= 340 else (24 if 幅 >= 230 else 22)
        神名行 = max(min(3, -(-len(nd['名']) // 上限)) for nd in 段['ノード'])
        小行 = 1
        for nd in 段['ノード']:
            小 = 話データ['ノード'][nd['名']].get('小')
            if 小:
                小行 = max(小行, min(2, -(-len(小) // max(1, 幅 // 漢))))
        規格 = 規格を作る(幅, 神名行, 小行)
    高さ = 規格['高さ']
    前 = 設定['帯高さ']['線あり前'] + (地寸法()['縦線'] if 線あり else 0) if 線あり \
         else 設定['帯高さ']['線なし前']
    ノード上端 = 帯上端 + 前
    帯高 = 前 + 高さ + 設定['帯高さ']['下余白'] + 規格.get('帯の追加', 0)
    if any(r.get('表現', '囲い') == '囲い' for r in 段.get('関係', [])):
        帯高 += 設定['関係図']['札の字'] + 24   # 囲いの札のぶん

    地 = 地寸法()
    ずれ = 地['帯ラベル幅'] if 地.get('帯ラベル位置') == '左' else 0
    if 規格['中央寄せ']:
        起点 = 地['幹x'] - 幅 / 2 + ずれ / 2
    else:
        起点 = 設定['ノード']['起点x'] + ずれ
    置く = []
    寄せ = 0
    if 地.get('夫婦の見せ方') == '隣接' and 段.get('夫婦'):
        名々 = [x['名'] for x in 段['ノード']]
        組 = [(名々.index(a), 名々.index(b)) for a, b in 段['夫婦']
              if a in 名々 and b in 名々 and abs(名々.index(a) - 名々.index(b)) == 1]
        寄せ = 14 if 組 else 0
    for i, nd in enumerate(段['ノード']):
        x = 起点 + i * (幅 + 設定['ノード']['余白'])
        if 寄せ:
            for p, q in 組:
                if i == min(p, q): x += 寄せ
                elif i == max(p, q): x -= 寄せ
        置く.append({**nd, 'x': x, 'y': ノード上端, '幅': 幅, '高さ': 高さ, 'n': n, '規格': 規格})
    return 置く, 帯高, ノード上端


def ページを組む(話データ, ページid):
    p = 話データ['ページ'][ページid]
    if p.get('方式') == '関係図':
        return []
    y = 設定['キャンバス']['外周']
    if 設定['キャンバス'].get('縦の寄せ') == '中央寄せ' and p['段']:
        # 先に全体の高さを測ってから、上下の余白が等しくなる位置から始める
        仮 = 設定['キャンバス']['外周']
        for i, 段 in enumerate(p['段']):
            _, 帯高, _ = 段の配置(段, 仮, i > 0, 話データ)
            仮 += 帯高 + (地寸法()['帯間'] if i < len(p['段']) - 1 else 0)
        中身 = 仮 - 設定['キャンバス']['外周']
        y = max(設定['キャンバス']['外周'],
                (設定['キャンバス']['高さ'] - 中身) // 2)
    段リスト = []
    for i, 段 in enumerate(p['段']):
        線あり = (i > 0)
        置く, 帯高, ノード上端 = 段の配置(段, y, 線あり, 話データ)
        段リスト.append({'帯上端': y, '帯高': 帯高, 'ノード': 置く,
                         'ラベル': 段.get('帯'), '夫婦': 段.get('夫婦', []),
                         '関係': 段.get('関係', []),
                         'ノード上端': ノード上端, '線あり': 線あり})
        y += 帯高 + 地寸法()['帯間']
    return 段リスト


# ────────────────────────── 描画 ──────────────────────────
def 折る(名, 規格, n):
    """2行になるときは、なるべく均等に割る。
    「帰り道の6島」を 5+1 で割ると2行目が1字になって不格好なので 3+3 にする。
    どちらの行も 規格['神名字数'] を超えないことは字数検算で保証済み。"""
    上限 = 規格['神名字数']
    必要 = -(-len(名) // 上限)
    if 必要 <= 1:
        return [名]
    必要 = min(必要, 規格.get('神名行上限', 2))
    幅あたり = -(-len(名) // 必要)          # なるべく均等に割る
    return [名[i:i + 幅あたり] for i in range(0, len(名), 幅あたり)][:必要]


def HTMLを作る(話データ, ページid, 強調, 書体css):
    段リスト = ページを組む(話データ, ページid)
    地 = 地寸法(); 書体 = 設定['書体']; 強 = 設定['強調枠']
    W = 図幅(); H = 設定['キャンバス']['高さ']
    部品 = []

    # 帯
    for 段 in 段リスト:
        部品.append(
            f'<div class="帯" style="left:{地["帯左"]}px;top:{段["帯上端"]}px;'
            f'width:{地["帯幅"]}px;height:{段["帯高"]}px"></div>')
        if 段['ラベル']:
            if 地.get('帯ラベル位置') == '左':
                部品.append(
                    f'<div class="帯ラベル縦" style="left:{地["帯左"]+8}px;'
                    f'top:{段["帯上端"]+12}px;width:{地["帯ラベル字"]}px;'
                    f'height:{段["帯高"]-24}px">{段["ラベル"]}</div>')
            else:
                部品.append(
                    f'<div class="帯ラベル" style="left:{地["帯左"]+地["帯ラベル左"]}px;'
                    f'top:{段["帯上端"]+地["帯ラベル下端"]-地["帯ラベル字"]}px">{段["ラベル"]}</div>')

    # 線（ノードより先に描いて下に敷く）
    for i, 段 in enumerate(段リスト):
        # 段に書かれた「関係」を、色つきの囲い／線＋札で描く
        設 = 設定['関係図']
        for rel in 段.get('関係', []):
            na = next((x for x in 段['ノード'] if x['名'] == rel['a']), None)
            nb = next((x for x in 段['ノード'] if x['名'] == rel['b']), None)
            if not na or not nb:
                continue
            配 = 設['関係の色'].get(rel.get('種', 'その他'),
                                     設['関係の色']['その他'])
            色 = 配['枠']
            if rel.get('表現', '囲い') == '囲い':
                x0 = min(na['x'], nb['x']); x1 = max(na['x'] + na['幅'], nb['x'] + nb['幅'])
                y0 = min(na['y'], nb['y']); y1 = max(na['y'] + na['高さ'], nb['y'] + nb['高さ'])
                外 = 設定['強調枠']['すきま'] + 設定['強調枠']['太さ'] + 6
                部品.append(f'<div class="関係囲い" style="left:{x0-外}px;top:{y0-外}px;'
                            f'width:{x1-x0+外*2}px;height:{y1-y0+外*2}px;'
                            f'border-color:{色};background:{配["塗り"]}"></div>')
                部品.append(f'<div class="関係札" style="left:{(x0+x1)/2}px;top:{y1+14}px;'
                            f'font-size:{設["札の字"]}px;background:{配["札"]}">'
                            f'{rel["札"]}</div>')
            else:
                左, 右 = (na, nb) if na['x'] < nb['x'] else (nb, na)
                xa = 左['x'] + 左['幅']; xb = 右['x']
                cy = 左['y'] + 左['高さ'] * 0.72
                部品.append(f'<div class="関係線" style="left:{xa}px;top:{cy}px;'
                            f'width:{xb-xa}px;height:{設["線の太さ"]}px;background:{色}"></div>')
                部品.append(f'<div class="関係札" style="left:{(xa+xb)/2}px;'
                            f'top:{cy-設["札の字"]-6}px;'
                            f'font-size:{設["札の字"]}px;background:{配["札"]}">'
                            f'{rel["札"]}</div>')

        やり方 = 地.get('夫婦の見せ方', '二重線')
        for a, b in 段.get('夫婦', []):
            na = next(x for x in 段['ノード'] if x['名'] == a)
            nb = next(x for x in 段['ノード'] if x['名'] == b)
            左 = min(na['x'] + na['幅'], nb['x'] + nb['幅'])
            右 = max(na['x'], nb['x'])
            中 = na['y'] + na['高さ'] / 2
            if やり方 == '囲い':
                x0 = min(na['x'], nb['x']); x1 = max(na['x'] + na['幅'], nb['x'] + nb['幅'])
                部品.append(
                    f'<div class="夫婦囲い" style="left:{x0-10}px;top:{na["y"]-10}px;'
                    f'width:{x1-x0+20}px;height:{na["高さ"]+20}px"></div>')
            太 = 地['夫婦線太さ'] * (2 if やり方 == '太い二重線' else 1)
            間 = 地['夫婦線間隔'] * (2 if やり方 == '太い二重線' else 1)
            半 = (間 / 2 + 太 / 2)
            for d in (-半, 半):
                部品.append(f'<div class="線" style="left:{左}px;top:{中+d-太/2}px;'
                            f'width:{右-左}px;height:{太}px"></div>')
        if i + 1 < len(段リスト):
            下 = 段リスト[i + 1]
            子 = [nd for nd in 下['ノード'] if nd.get('続柄', '子') == '子']
            他 = [nd for nd in 下['ノード'] if nd.get('続柄', '子') != '子']
            # 幹：親の高さ中央（または夫婦線）から兄弟バーまで
            幹上 = 段['ノード'][0]['y'] + 段['ノード'][0]['高さ'] / 2
            バーy = 下['ノード上端'] - 地['縦線']
            if any(nd.get('続柄', '子') == '子' for nd in 下['ノード']) or \
               設定['地'].get('血縁でない線') == '点線':
                部品.append(f'<div class="線" style="left:{地["幹x"]-地["親子線太さ"]/2}px;'
                            f'top:{幹上}px;width:{地["親子線太さ"]}px;'
                            f'height:{バーy-幹上}px"></div>')
            中心 = [nd['x'] + nd['幅'] / 2 for nd in 子]
            if 中心:
                左, 右 = min(中心 + [地['幹x']]), max(中心 + [地['幹x']])
                if 右 > 左:
                    部品.append(f'<div class="線" style="left:{左}px;'
                                f'top:{バーy-地["親子線太さ"]/2}px;'
                                f'width:{右-左}px;height:{地["親子線太さ"]}px"></div>')
                for c in 中心:
                    部品.append(f'<div class="線" style="left:{c-地["親子線太さ"]/2}px;'
                                f'top:{バーy}px;width:{地["親子線太さ"]}px;'
                                f'height:{地["縦線"]}px"></div>')
            # 血縁でないノード（続柄が「子」でないもの）の描き方
            やり方 = 設定['地'].get('血縁でない線', 'なし')
            if やり方 == '点線':
                for nd in 他:
                    c = nd['x'] + nd['幅'] / 2
                    部品.append(f'<div class="点線" style="left:{min(c,地["幹x"])}px;'
                                f'top:{バーy-地["親子線太さ"]/2}px;'
                                f'width:{abs(c-地["幹x"])}px;height:{地["親子線太さ"]}px"></div>')
                    部品.append(f'<div class="点線縦" style="left:{c-地["親子線太さ"]/2}px;'
                                f'top:{バーy}px;width:{地["親子線太さ"]}px;'
                                f'height:{地["縦線"]}px"></div>')

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
            if 規格.get('縦'):
                名 = nd['名']
                小 = 話データ['ノード'][nd['名']].get('小')
                字 = 規格['字']; 漢 = 規格['漢字']
                役 = nd.get('サブ') or ''
                位置 = 規格['役割位置']; 役字 = 規格['役割字']
                名列 = 縦の列数(len(名), 規格['列上限'], 名前=True)
                名 = 縦に割る(名, 名列)
                小列 = 縦の列数(len(小 or ''), 規格['列上限'] + 2) if 小 else 0
                名幅 = 名列 * 字; 小幅 = 小列 * 漢
                役列 = 縦の列数(len(役), 規格['列上限'] + 3) if (役 and 位置 == '左列') else 0
                役幅 = 役列 * 役字
                幅合計 = (名幅 + (規格['すきま'] + 小幅 if 小 else 0)
                          + (規格['役割すきま'] + 役幅 if 役列 else 0))
                右端 = nd['x'] + (nd['幅'] + 幅合計) / 2       # 神名は右の列
                名x = 右端 - 名幅
                # 枠の高さは、そのノードが実際に必要とする高さにする。
                # 段の最大高さを当てると、短い名前が折り返して隣の列に重なる
                名高 = -(-len(nd['名']) // 名列) * 字
                上 = nd['y'] + 規格['上余白'] + 規格['上の分']
                部品.append(
                    f'<div class="縦名" style="left:{名x}px;top:{上}px;'
                    f'width:{名幅}px;height:{名高}px;font-size:{字}px;'
                    f'color:{文字色}">{名}</div>')
                if 小:
                    小高 = -(-len(小) // 小列) * 漢
                    部品.append(
                        f'<div class="縦小" style="left:{名x-規格["すきま"]-小幅}px;'
                        f'top:{上}px;width:{小幅}px;'
                        f'height:{小高}px;font-size:{漢}px;'
                        f'color:{文字色}">{小}</div>')
                if 役:
                    if 位置 == '左列':
                        rx = 名x - (規格['すきま'] + 小幅 if 小 else 0) - 規格['役割すきま'] - 役幅
                        部品.append(
                            f'<div class="縦役" style="left:{rx}px;top:{上}px;'
                            f'width:{役幅}px;height:{-(-len(役)//役列)*役字}px;'
                            f'font-size:{役字}px;color:{文字色}">{役}</div>')
                    elif 位置 in ('重ね上', '重ね下', '重ね左'):
                        tz = 規格['役割字']; th = tz + 12
                        地色 = 系['塗り'] if not 退場 else 地寸法()['背景']
                        if 位置 == '重ね左':
                            tw = tz + 12
                            部品.append(
                                f'<div class="重ねタグ縦" style="left:{nd["x"]-tw/2}px;'
                                f'top:{nd["y"]+24}px;width:{tw}px;'
                                f'height:{len(役)*tz+22}px;font-size:{tz}px;'
                                f'color:{地色};background:{文字色};'
                                f'border:2px solid {地色}">{役}</div>')
                        else:
                            y = (nd['y'] - th / 2 if 位置 == '重ね上'
                                 else nd['y'] + nd['高さ'] - th / 2)
                            部品.append(
                                f'<div class="重ねタグ" style="left:{nd["x"]+28}px;'
                                f'top:{y}px;height:{th}px;font-size:{tz}px;'
                                f'color:{地色};background:{文字色};'
                                f'border:2px solid {地色}">{役}</div>')
                    elif 位置 == '枠外下':
                        sz = 規格['役割字']
                        部品.append(
                            f'<div class="サブ" style="left:{nd["x"]}px;'
                            f'top:{nd["y"]+nd["高さ"]+8}px;width:{nd["幅"]}px;'
                            f'height:{sz}px;font-size:{sz}px;color:{地["帯ラベル色"]}">{役}</div>')
                    elif 位置 == '上タグ':
                        部品.append(
                            f'<div class="タグ" style="left:{nd["x"]+10}px;'
                            f'top:{nd["y"]+8}px;height:{役字+8}px;'
                            f'font-size:{役字}px;color:{系["塗り"] if not 退場 else 系["輪郭"]};'
                            f'background:{文字色}">{役}</div>')
                    else:
                        sz = 規格['サブ']
                        部品.append(
                            f'<div class="サブ" style="left:{nd["x"]}px;'
                            f'top:{nd["y"]+規格["サブy"]-sz}px;width:{nd["幅"]}px;'
                            f'height:{sz}px;font-size:{sz}px;color:{文字色}">{サブ if False else 役}</div>')
                continue
            行 = 折る(nd['名'], 規格, nd['n'])
            字 = 設定['ノード']['神名字サイズ']
            if len(行) == 1:
                ys = [規格['神名1行のみ']]
            else:
                ys = [規格['神名1行目'], 規格['神名2行目'],
                      規格.get('神名3行目', 規格['神名2行目'] + 字)][:len(行)]
            for t, by in zip(行, ys):
                部品.append(
                    f'<div class="神名" style="left:{nd["x"]}px;top:{nd["y"]+by-字}px;'
                    f'width:{nd["幅"]}px;height:{字}px;font-size:{字}px;color:{文字色}">{t}</div>')
            小 = 話データ['ノード'][nd['名']].get('小')
            if 小:
                s = 規格['漢字']
                上限 = max(1, nd['幅'] // s)
                小行 = [小[i:i + 上限] for i in range(0, len(小), 上限)][:規格.get('漢字行', 1)]
                for j, t in enumerate(小行):
                    部品.append(
                        f'<div class="小" style="left:{nd["x"]}px;'
                        f'top:{nd["y"]+規格["漢字y"]+38*j-s}px;'
                        f'width:{nd["幅"]}px;height:{s}px;font-size:{s}px;color:{文字色}">{t}</div>')
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
.点線{{position:absolute;background:repeating-linear-gradient(to right,
     {地["線"]} 0 8px,transparent 8px 16px)}}
.点線縦{{position:absolute;background:repeating-linear-gradient(to bottom,
     {地["線"]} 0 8px,transparent 8px 16px)}}
.ノード{{position:absolute;z-index:2}}
.神名{{position:absolute;z-index:3;text-align:center;font-weight:{書体["神名太さ"]};line-height:1;
     font-feature-settings:"palt" 0}}
.小{{position:absolute;text-align:center;font-family:'{m}',serif;
     font-weight:{書体["漢字太さ"]};line-height:1}}
.サブ{{position:absolute;z-index:3;text-align:center;font-weight:{書体["サブ太さ"]};line-height:1}}
.強調{{position:absolute;z-index:10}}
.夫婦囲い{{position:absolute;border:3px solid {地["線"]};border-radius:24px}}
.関係囲い{{position:absolute;border:4px solid;border-radius:26px;z-index:1}}
.関係線{{position:absolute;z-index:4}}
.関係札{{position:absolute;transform:translate(-50%,-50%);color:#fff;
     padding:5px 12px;border-radius:6px;line-height:1;white-space:nowrap;
     font-weight:{書体["サブ太さ"]};z-index:9}}
.帯ラベル縦{{position:absolute;writing-mode:vertical-rl;text-orientation:upright;
     font-size:{地["帯ラベル字"]}px;color:{地["帯ラベル色"]};
     font-weight:{書体["帯ラベル太さ"]};line-height:1}}
.縦名{{position:absolute;z-index:3;writing-mode:vertical-rl;text-orientation:upright;
     font-weight:{書体["神名太さ"]};line-height:1;letter-spacing:0;
     font-feature-settings:"palt" 0}}
.縦役{{position:absolute;writing-mode:vertical-rl;text-orientation:upright;
     font-weight:{書体["サブ太さ"]};line-height:1;opacity:.85}}
.重ねタグ{{position:absolute;border-radius:{強["太さ"]}px;padding:4px 10px;
     line-height:1;font-weight:{書体["サブ太さ"]};white-space:nowrap;z-index:6;
     display:flex;align-items:center}}
.重ねタグ縦{{position:absolute;writing-mode:vertical-rl;text-orientation:upright;
     border-radius:{強["太さ"]}px;padding:6px 4px;line-height:1;z-index:6;
     font-weight:{書体["サブ太さ"]}}}
.タグ{{position:absolute;border-radius:4px;padding:3px 7px;line-height:1;
     font-weight:{書体["サブ太さ"]};white-space:nowrap}}
.縦小{{position:absolute;z-index:3;writing-mode:vertical-rl;text-orientation:upright;
     font-family:'{m}',serif;font-weight:{書体["漢字太さ"]};line-height:1}}
</style></head><body>
<div class="外枠"></div>
{chr(10).join(部品)}
</body></html>'''




# ──────────────── 関係図（漫画式）────────────────
def 関係図を組む(話データ, ページid):
    """漫画のキャラ相関図のように、格子に置いて関係に札をつける。
    帯（世代）は使わない。配置は データ の 行・列 で指定する。"""
    p = 話データ['ページ'][ページid]
    地 = 地寸法(); 外周 = 設定['キャンバス']['外周']; 余白 = 設定['ノード']['余白']
    列数 = max(x['列'] for x in p['配置']) + 1
    行数 = max(x['行'] for x in p['配置']) + 1
    幅 = int((図幅() - 外周 * 2 - 余白 * (列数 - 1)) / 列数)
    札高 = 設定['関係図']['札の字'] + 10
    # 行ごとの高さ＝その行のノードが必要とする高さの最大
    高さ = {}
    for r in range(行数):
        組 = [x for x in p['配置'] if x['行'] == r]
        if not 組: 高さ[r] = 0; continue
        規格 = 縦の規格(幅, [x['名'] for x in 組],
                        [話データ['ノード'][x['名']].get('小') or '' for x in 組],
                        [x.get('サブ') or '' for x in 組])
        高さ[r] = 規格['高さ']
    行間 = 設定['関係図']['行間']
    中身 = sum(高さ.values()) + 行間 * (行数 - 1)
    y0 = max(外周, (設定['キャンバス']['高さ'] - 中身) // 2)
    置く = []
    y = y0
    for r in range(行数):
        組 = sorted([x for x in p['配置'] if x['行'] == r], key=lambda x: x['列'])
        規格 = 縦の規格(幅, [x['名'] for x in 組],
                        [話データ['ノード'][x['名']].get('小') or '' for x in 組],
                        [x.get('サブ') or '' for x in 組]) if 組 else None
        for x in 組:
            置く.append({**x, 'x': 外周 + x['列'] * (幅 + 余白), 'y': y,
                         '幅': 幅, '高さ': 高さ[r], '規格': 規格, 'n': 列数})
        y += 高さ[r] + 行間
    return 置く, 幅


def 関係図のHTML(話データ, ページid, 強調, 書体css):
    p = 話データ['ページ'][ページid]
    置く, 幅 = 関係図を組む(話データ, ページid)
    地 = 地寸法(); 設 = 設定['関係図']; 強 = 設定['強調枠']
    W = 図幅(); H = 設定['キャンバス']['高さ']
    場所 = {x['名']: x for x in 置く}
    部品 = []
    # 関係の線と札
    for rel in p.get('関係', []):
        a, b = 場所.get(rel['a']), 場所.get(rel['b'])
        if not a or not b: continue
        色 = 設['線の色'].get(rel.get('種', 'その他'), 地['線'])
        太 = 設['線の太さ']
        if a['行'] == b['行']:
            左, 右 = (a, b) if a['x'] < b['x'] else (b, a)
            x0 = 左['x'] + 左['幅']; x1 = 右['x']
            cy = 左['y'] + 左['高さ'] / 2
            部品.append(f'<div class="関係線" style="left:{x0}px;top:{cy-太/2}px;'
                        f'width:{x1-x0}px;height:{太}px;background:{色}"></div>')
            lx, ly = (x0 + x1) / 2, cy
        else:
            上, 下 = (a, b) if a['y'] < b['y'] else (b, a)
            ux = 上['x'] + 上['幅'] / 2; dx = 下['x'] + 下['幅'] / 2
            y0 = 上['y'] + 上['高さ']; y1 = 下['y']
            my = (y0 + y1) / 2
            部品.append(f'<div class="関係線" style="left:{ux-太/2}px;top:{y0}px;'
                        f'width:{太}px;height:{my-y0}px;background:{色}"></div>')
            if abs(ux - dx) > 1:
                部品.append(f'<div class="関係線" style="left:{min(ux,dx)}px;top:{my-太/2}px;'
                            f'width:{abs(ux-dx)}px;height:{太}px;background:{色}"></div>')
            部品.append(f'<div class="関係線" style="left:{dx-太/2}px;top:{my}px;'
                        f'width:{太}px;height:{y1-my}px;background:{色}"></div>')
            lx, ly = (ux + dx) / 2, my
        部品.append(f'<div class="関係札" style="left:{lx}px;top:{ly}px;'
                    f'font-size:{設["札の字"]}px;background:{色}">{rel["札"]}</div>')
    # ノード
    for nd in 置く:
        系 = 設定['系統'][話データ['ノード'][nd['名']]['系統']]
        規格 = nd['規格']; 退場 = nd.get('退場', False)
        塗り = 地['背景'] if 退場 else 系['塗り']
        文字色 = 系['輪郭'] if 退場 else 系['文字']
        部品.append(
            f'<div class="ノード" style="left:{nd["x"]}px;top:{nd["y"]}px;'
            f'width:{nd["幅"]}px;height:{nd["高さ"]}px;background:{塗り};'
            f'border:{設定["ノード"]["輪郭線"]}px solid {系["輪郭"]};'
            f'border-radius:{設定["ノード"]["角丸"]}px"></div>')
        名 = nd['名']; 小 = 話データ['ノード'][名].get('小')
        字 = 規格['字']; 漢 = 規格['漢字']
        名列 = 縦の列数(len(名), 規格['列上限'], 名前=True)
        小列 = 縦の列数(len(小 or ''), 規格['列上限'] + 2) if 小 else 0
        名幅 = 名列 * 字; 小幅 = 小列 * 漢
        右端 = nd['x'] + (nd['幅'] + 名幅 + (規格['すきま'] + 小幅 if 小 else 0)) / 2
        名x = 右端 - 名幅
        上 = nd['y'] + 規格['上余白']
        部品.append(f'<div class="縦名" style="left:{名x}px;top:{上}px;width:{名幅}px;'
                    f'height:{-(-len(名)//名列)*字}px;font-size:{字}px;color:{文字色}">{名}</div>')
        if 小:
            部品.append(f'<div class="縦小" style="left:{名x-規格["すきま"]-小幅}px;top:{上}px;'
                        f'width:{小幅}px;height:{-(-len(小)//小列)*漢}px;'
                        f'font-size:{漢}px;color:{文字色}">{小}</div>')
        役 = nd.get('サブ')
        if 役:
            tz = 規格['役割字']; th = tz + 12
            部品.append(f'<div class="重ねタグ" style="left:{nd["x"]+28}px;'
                        f'top:{nd["y"]-th/2}px;height:{th}px;font-size:{tz}px;'
                        f'color:{系["塗り"] if not 退場 else 地["背景"]};background:{文字色};'
                        f'border:2px solid {系["塗り"] if not 退場 else 地["背景"]}">{役}</div>')
    for nd in 置く:
        if nd['名'] in 強調:
            す = 強['すきま']; 太 = 強['太さ']
            部品.append(
                f'<div class="強調" style="left:{nd["x"]-す-太}px;top:{nd["y"]-す-太}px;'
                f'width:{nd["幅"]+2*(す+太)}px;height:{nd["高さ"]+2*(す+太)}px;'
                f'border:{太}px solid {強["色"]};'
                f'border-radius:{設定["ノード"]["角丸"]+す+太}px"></div>')
    書 = 設定['書体']; g, m = 書['ゴシック'], 書['明朝']
    return f'''<!doctype html><html lang="ja"><head><meta charset="utf-8">
<style>
{書体css}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{width:{W}px;height:{H}px;background:{地["背景"]};position:relative;overflow:hidden;
     font-family:'{g}',sans-serif;-webkit-font-smoothing:antialiased}}
.外枠{{position:absolute;inset:0;border:{設定["キャンバス"]["外周"]}px solid {地["外枠"]}}}
.ノード{{position:absolute;z-index:2}}
.関係線{{position:absolute}}
.関係札{{position:absolute;transform:translate(-50%,-50%);color:#fff;
     padding:5px 12px;border-radius:6px;line-height:1;white-space:nowrap;
     font-weight:{書["サブ太さ"]};z-index:8}}
.縦名{{position:absolute;z-index:3;writing-mode:vertical-rl;text-orientation:upright;
     font-weight:{書["神名太さ"]};line-height:1}}
.縦小{{position:absolute;z-index:3;writing-mode:vertical-rl;text-orientation:upright;
     font-family:'{m}',serif;font-weight:{書["漢字太さ"]};line-height:1}}
.重ねタグ{{position:absolute;border-radius:8px;padding:4px 10px;line-height:1;
     font-weight:{書["サブ太さ"]};white-space:nowrap;z-index:6;
     display:flex;align-items:center}}
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
            規格 = 幅表()[n]
            はば.append(f'n={n}・{規格["幅"]}×{規格["高さ"]}')
        if not 段リスト:
            もの, はば = ['なし（枠のみ）'], ['—']
        行.append(f'| **{pid}** | {はん} | {時} | {" ／ ".join(もの)} | '
                  f'{" ／ ".join(はば)} | {len(段リスト)}段 |')
    return '\n'.join(行)


def 生成(話番号, 表だけ=False, 強行=False, 固定段階=False):
    経路 = os.path.join(ここ, 'データ', f'{話番号}.json')
    話データ = json.load(open(経路, encoding='utf-8'))

    if 縦書きか() and not 固定段階:
        見つけた = 収まる段階を探す(話データ)
        if 見つけた is None:
            段階を当てる(len(設定['詰める段階']) - 1)
            print(f'⚠ 第{話番号}話 どの段階でも収まらない（いちばん詰めた設定で続行）')
        else:
            print(f'  詰める段階：{設定["詰める段階"][見つけた]["名"]}')

    問題 = 字数を検算する(話データ)
    for pid in 話データ['ページ']:
        段数 = [len(s['ノード']) for s in 話データ['ページ'][pid].get('段', [])]
        if 段数:
            縦 = 縦を検算する(段数)
            if 縦 > 設定['キャンバス']['高さ']:
                問題.append(f'{pid} 縦が{縦}px（上限{設定["キャンバス"]["高さ"]}px）')
        if len(段数) > 3:
            問題.append(f'{pid} 帯が{len(段数)}段（上限3段・仕様書3節）')
    for pid in 話データ['ページ']:
        if 話データ['ページ'][pid].get('方式') == '関係図':
            置く, _ = 関係図を組む(話データ, pid)
            if 置く:
                下端 = max(x['y'] + x['高さ'] for x in 置く)
                if 下端 > 設定['キャンバス']['高さ']:
                    問題.append(f'{pid} 関係図の縦が{下端}pxで、'
                                f'{設定["キャンバス"]["高さ"]}pxに収まらない')
            continue
        段 = ページを組む(話データ, pid)
        if 段:
            下端 = 段[-1]['帯上端'] + 段[-1]['帯高']
            if 下端 > 設定['キャンバス']['高さ']:
                問題.append(f'{pid} 縦が{下端}pxで、{設定["キャンバス"]["高さ"]}pxに収まらない')
    if 問題:
        print(f'{"⚠" if 強行 else "✗"} 第{話番号}話 検算で{len(問題)}件の問題')
        for x in 問題:
            print('   ', x)
        if not 強行:
            raise SystemExit(1)
        print('   → --強行 が指定されたので、収まらないまま書き出す（確認用）')
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
        作る = (関係図のHTML
                if 話データ['ページ'][w['ページ']].get('方式') == '関係図'
                else HTMLを作る)
        open(h, 'w', encoding='utf-8').write(
            作る(話データ, w['ページ'], w['強調'], 書体css))
        指示.append({'html': h, 'png': os.path.join(出力, w['名'])})
    json.dump({'指示': 指示, '幅': 図幅(),
               '高さ': 設定['キャンバス']['高さ'], '倍率': 設定['キャンバス']['倍率']},
              open(os.path.join(一時, '_指示.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    subprocess.run(['node', os.path.join(ここ, '撮る.js'),
                    os.path.join(一時, '_指示.json')], check=True)
    print(f'✓ 第{話番号}話 {len(仕事)}枚を {出力} に出力')
    shutil.rmtree(一時)


def 段階を当てる(i):
    """詰める段階を設定に反映する。神名48pxは どの段階でも変えない。"""
    t = 設定['詰める段階'][i]
    設定['地']['帯ラベル位置'] = t['帯ラベル位置']
    設定['地']['縦線'] = t['縦線']
    設定['地']['帯間'] = t['帯間']
    設定['帯高さ']['線なし前'] = t['線なし前']
    設定['帯高さ']['線あり前'] = t['線あり前']
    設定['縦書き']['上余白'] = t['上余白']
    設定['縦書き']['サブ上'] = t['サブ上']
    設定['縦書き']['下余白'] = t['下余白']
    設定['縦書き']['1列の最大字数'] = t['1列の最大字数']
    return t['名']


def 収まる段階を探す(話データ):
    """その話の全ページが収まる、いちばんゆるい段階を返す。
    見つからなければ None（そのときは神名を短くするしかない）。"""
    for i in range(len(設定['詰める段階'])):
        段階を当てる(i)
        だめ = 字数を検算する(話データ)
        for pid in 話データ['ページ']:
            段 = ページを組む(話データ, pid)
            if 段 and 段[-1]['帯上端'] + 段[-1]['帯高'] > 設定['キャンバス']['高さ']:
                だめ.append(pid)
        if not だめ:
            return i
    return None


if __name__ == '__main__':
    引数 = [a for a in sys.argv[1:] if not a.startswith('--')]
    表だけ = '--表' in sys.argv
    強行 = '--強行' in sys.argv
    固定段階 = False
    for a in sys.argv:
        if a.startswith('--段階='):
            段階を当てる(int(a.split('=')[1])); 固定段階 = True
    話 = 引数 or [f'{i:02d}' for i in range(1, 16)
                  if os.path.exists(os.path.join(ここ, 'データ', f'{i:02d}.json'))]
    for t in 話:
        生成(t, 表だけ, 強行, 固定段階)
