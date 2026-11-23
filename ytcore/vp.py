"""Generic explainer-video pipeline (card compositor).  Replaces the per-video copies (nj_*, gm_*): everything is driven by
  data/<slug>_spec.json   (chapters -> scene items, images, bgm plan, description/thumbnail fields)
  docs/themes/<theme_dir>/09_script_v2.md   (narration: "## 章N　title" + numbered lines)
usage:  python scripts/vp.py <slug> story|kana|audio|bgm|parts|build|qa|desc|thumb|pack
  build = render all parts in parallel -> concat -> loudnorm -> BGM remix -> out/<slug>_video.mp4 (+ qa)
Scene item types (all optional 'at' = sentence index at which the item appears, 'until' = index at which it disappears):
  stack, panel, image, timeline, chips, bars, table, cols2, big, flow
"""
from pathlib import Path
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import wave

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from ytcore import hn_text, thin_commas, rich_text as rich
from ytcore.hn_text import display
from ytcore.subtitles import write_srt
from ytcore.thin_commas import thin
from ytkit import loudness as yloud, qa as yqa, voicevox as vv
from ytkit.ffmpeg_tools import find_ffmpeg, find_ffprobe
from ytkit.project import load_config, project_root, require, section

# チャンネル設定 ROOT/channel.toml（環境変数 YT_PROJECT_ROOT でプロジェクトの場所を変えられる）
ROOT = project_root(__file__)
CFG = load_config(ROOT)
CH = section(CFG, 'channel', ('about', 'terms_check'))
VOICE = section(CFG, 'voice', ('speaker', 'style', 'speed', 'label', 'credit_long'))
BGM = section(CFG, 'bgm', ('dir', 'pattern', 'credit_long'))
BGM_NAMES = require(CFG, 'bgm.names')
FONTS = section(CFG, 'fonts', ('dir', 'sans', 'serif'))

FD = FONTS['dir']
BASE = vv.base_url()
SPEED = VOICE['speed']   # VOICEVOX_URL は ytkit.voicevox が読む
# プロジェクト側のプラグイン（vp_anim*・make_upload_pack・ffmpeg_skill_check）を import できるように。
# 置き場所は channel.toml の [project] plugin_dir。
PLUGIN_DIR = ROOT / require(CFG, 'project.plugin_dir')
sys.path.insert(0, str(PLUGIN_DIR))

XFADE = 0.35   # 章の切れ目のクロスフェード（秒）
BG = (7, 24, 36, 240)
GOLD = (239, 201, 118)
WHITE = (245, 243, 232)
DIM = (190, 205, 208)
EDGE = (176, 153, 100)
NAVY = (9, 22, 34)
ORG = (255, 150, 90)
BLUE = (120, 190, 255)
VIO = (170, 135, 255)
GRN = (120, 210, 150)
RED = (235, 90, 80)
COL = {'gold': GOLD, 'white': WHITE, 'dim': DIM, 'org': ORG,
       'blue': BLUE, 'vio': VIO, 'grn': GRN, 'red': RED}
SPEC_F = {'sans': (FONTS['sans'], 560), 'sub': (FONTS['sans'], 640), 'serif': (FONTS['serif'], 800)}


def vfont(kind, size):
    k = (kind, size)
    if k not in STATE.font_cache:
        f = ImageFont.truetype(FONTS['dir'] + SPEC_F[kind][0], size)
        f.set_variation_by_axes([SPEC_F[kind][1]])
        STATE.font_cache[k] = f
    return STATE.font_cache[k]


class _Fam:
    def __init__(s, kind):
        s.kind = kind

    def __getitem__(s, n):
        return vfont(s.kind, n)


F = _Fam('sans')
FB = _Fam('serif')
FSUB = _Fam('sub')


class _StateProxy(dict):
    """vp_anim / vp_check などに渡す、現在の RenderState を読む辞書。

    bind(g) は g['SPEC'] のようにキーアクセスする。辞書をコピーすると
    load_spec() 後の差し替えに追従できないので、属性へ都度読みに行く。
    """

    def __init__(self, state):
        super().__init__()
        self._state = state

    # 旧 globals() のキー -> RenderState の属性名
    _KEYS = {
        'SLUG': 'slug', 'SPEC': 'spec', 'TL': 'tl', 'SEGS': 'segs',
        'N': 'n', 'KEYS': 'keys', 'IMAGES': 'images', 'ART': 'arts',
    }

    def __getitem__(self, key):
        name = self._KEYS.get(key, key)
        if hasattr(self._state, name):
            return getattr(self._state, name)
        # P / ITEMS / F / header / wrapn など、旧 globals() にあった関数・定数
        return globals()[key]

    def get(self, key, default=None):
        try:
            return self[key]
        except (AttributeError, KeyError):
            return default

    def __contains__(self, key):
        name = self._KEYS.get(key, key)
        return hasattr(self._state, name) or key in globals()


class RenderState:
    """1つの動画の描画に必要な状態。複数インスタンスを同時に保持できる。"""

    def __init__(self):
        self.slug = None
        self.spec = None
        self.tl = None
        self.segs = None
        self.n = 0
        self.keys = []
        self.images = {}      # get_img のキャッシュ
        self.arts = {}        # it_art のキャッシュ
        self.subp = {}        # sub_lines のキャッシュ
        self.font_cache = {}  # vfont のキャッシュ（共有でも可だが state に置く）
        self.anim_bound = [False]

    def as_dict(self):
        """旧 globals() と同じように使える proxy 辞書を返す。"""
        return _StateProxy(self)

    def load_spec(self, slug):
        self.slug = slug
        self.spec = _conv_display(json.loads(P(f'data/{slug}_spec.json').read_text(encoding='utf8')))
        return self.spec

    def load_runtime(self):
        self.tl = json.loads(P(f'data/{self.slug}_timeline.json').read_text(encoding='utf8'))
        self.segs = json.loads(P(f'out/{self.slug}_audio_report.json').read_text(encoding='utf8'))['segments']
        self.n = round(self.tl[-1]['end'] * 30)
        self.keys = [c['key'] for c in self.tl]


STATE = RenderState()


def P(rel):
    return ROOT / rel


def _ffmpeg():
    return find_ffmpeg()


def _ffprobe():
    return find_ffprobe(find_ffmpeg(), default='ffprobe')
# 画面に出す文字は、数量・回数・順序を算用数字にする（字幕と同じ規則。慣用句は hn_text.KEEP で保護）
_TXT={'text','title','sub','chapter_title','opener','cells','lines'}
def _cv(v):
    if isinstance(v,str):return thin(display(v)) if len(v)>12 else display(v)
    if isinstance(v,list):return [_cv(x) for x in v]
    return v
def _conv_display(o):
    if isinstance(o,dict):return {k:(_cv(v) if k in _TXT else _conv_display(v)) for k,v in o.items()}
    if isinstance(o,list):return [_conv_display(v) for v in o]
    return o
def load_spec(slug, state=None):
    state = state or STATE
    return state.load_spec(slug)


def theme_dir(state=None):
    state = state or STATE
    return P('docs/themes') / state.spec['theme_dir']


def load_runtime(state=None):
    state = state or STATE
    state.load_runtime()
    return state
# ---------------------------------------------------------------- text helpers
def tw(d, t, f):
    return d.textlength(t, font=f)


def wrap(d, text, font, maxw):
    """Wrap text into two lines at the best clause boundary."""
    if tw(d, text, font) <= maxw:
        return [text]
    best = None
    for k in range(1, len(text)):
        l1, l2 = text[:k], text[k:]
        w1, w2 = tw(d, l1, font), tw(d, l2, font)
        if w1 > maxw or w2 > maxw or _nobreak(text[k - 1], text[k]):
            continue
        katakana_bonus = 400 if ('゠' <= text[k - 1] <= 'ヿ' and '゠' <= text[k] <= 'ヿ') else 0
        if text[k - 1] in '、，。':
            punct_cost = 0
        elif (text[k - 1] in 'はがをにのでとも'
              and not ('\u4e00' <= text[k] <= '\u9fff' and '\u4e00' <= text[k - 1] <= '\u9fff')):
            punct_cost = 70
        else:
            punct_cost = 150
        score = max(w1, w2) + katakana_bonus + punct_cost
        if best is None or score < best[0]:
            best = (score, [l1, l2])
    if best:
        return best[1]
    lines, cur = [], ''
    for ch in text:
        if tw(d, cur + ch, font) > maxw and cur:
            lines.append(cur)
            cur = ch
        else:
            cur += ch
    lines.append(cur)
    return lines


_UNIT = '分秒時間年月日倍％度回世紀万千円人歳'


def _nobreak(a, b):
    """True if a line break between characters a|b is not allowed (digits, units, opening/closing brackets)"""
    return (a.isdigit() and (b.isdigit() or b in _UNIT or b in '.:：点')) or (a in '.:：点' and b.isdigit()) or a in '（「『(' or b in '）」』、。,)'


def wrapn(d, text, font, maxw):
    """wrap to any number of lines: greedy, backtracking to the last allowed break position"""
    out, cur = [], ''
    for ch in text:
        if tw(d, cur + ch, font) > maxw and cur:
            k = len(cur)
            while k > 0 and _nobreak(cur[k - 1], cur[k] if k < len(cur) else ch):
                k -= 1
            if k == 0:
                k = len(cur)
            out.append(cur[:k])
            cur = cur[k:] + ch
        else:
            cur += ch
    if cur:
        out.append(cur)
    return out


def ease(x):
    x = min(1, max(0, x))
    return x * x * (3 - 2 * x)


def line_text(d, xy, text, font, fill=WHITE, a=1.0):
    d.text(xy, text, font=font, fill=tuple(fill[:3]) + (int(255 * a),))
def box_fill(d, box, a, col=EDGE, w=2, fill=BG):
    d.rounded_rectangle(box, 12,
                        fill=tuple(fill[:3]) + (int(fill[3] * a) if len(fill) > 3 else int(255 * a),),
                        outline=tuple(col[:3]) + (int(255 * a),), width=w)


def text_block(d, x, y, text, size, maxw, col=WHITE, a=1.0, fam='sans', lh=1.3):
    f = (F if fam == 'sans' else FB)[size]
    for ln in wrapn(d, text, f, maxw):
        line_text(d, (x, y), ln, f, col, a)
        y += int(size * lh)
    return y


def measure(d, text, size, maxw, fam='sans', lh=1.3):
    f = (F if fam == 'sans' else FB)[size]
    return len(wrapn(d, text, f, maxw)) * int(size * lh)


class Ctx:
    """現在の章・時刻から、部品の表示状態と出現アニメーションを計算する。"""

    def __init__(s, ci, t):
        s.ci = ci
        s.t = t
        s.key = STATE.keys[ci]
        s.segl = [x for x in STATE.segs if x['scene'] == ci]
        s.st = [x['start'] for x in s.segl]

    def on(s, i):
        return i is None or (i < len(s.st) and s.t >= s.st[i])

    def a(s, i, dur=.5):
        if i is None:
            return 1.0
        return 0.0 if not s.on(i) else min(1, (s.t - s.st[i]) / dur)

    def idx(s):
        return sum(1 for x in s.st if s.t >= x) - 1

    def vis(s, it):
        at, un = it.get('at'), it.get('until')
        return s.on(at) and not (un is not None and s.on(un))


# ---------------------------------------------------------------- images


def get_img(name, w, h):
    k = (name, w, h)
    if k not in STATE.images:
        meta = STATE.spec['images'][name]
        im = Image.open(P(meta['file'])).convert('RGB')
        c = meta.get('crop')
        if c:
            im = im.crop((int(im.width * c[0]), int(im.height * c[1]),
                          int(im.width * c[2]), int(im.height * c[3])))
        s = min(w / im.width, h / im.height)
        STATE.images[k] = im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))), Image.LANCZOS)
    return STATE.images[k]
def it_image(im,d,cx,it):
    a=cx.a(it.get('at'))
    if a<=0 or not cx.vis(it):return
    x0,y0,x1,y1=it['box'];cap=it.get('cap','');capn=len(wrapn(d,cap,F[26],x1-x0-28)[:2]) if cap else 0;reserve=(capn*34+16) if cap else 8
    pic=get_img(it['name'],x1-x0-16,y1-y0-reserve-8);W_,H_=pic.size;layer=Image.new('RGBA',(x1-x0,y1-y0),(0,0,0,0));ld=ImageDraw.Draw(layer)
    ld.rounded_rectangle((0,0,x1-x0-1,y1-y0-1),12,fill=BG,outline=EDGE+(255,),width=2);layer.paste(pic,((x1-x0-W_)//2,8))
    for j,l in enumerate(wrapn(d,cap,F[26],x1-x0-28)[:2]):ld.text((14,y1-y0-reserve+8+j*34),l,font=F[26],fill=WHITE+(255,))
    if a<1:r,g,b,al=layer.split();layer=Image.merge('RGBA',(r,g,b,al.point(lambda v:int(v*a))))
    im.alpha_composite(layer,(x0,y0))
# ---------------------------------------------------------------- item renderers
def it_stack(im,d,cx,it):
    x0,x1,y=it.get('x0',60),it.get('x1',930),it.get('y0',170);size=it.get('size',34);gap=it.get('gap',14);ymax=it.get('ymax',850)
    pop=STATE.spec.get('style')=='pop'
    if pop:size=min(size+6,42);gap=gap+2
    for e in it['items']:
        if not cx.vis(e):continue
        a=cx.a(e.get('at'));col=COL.get(e.get('col','white'),WHITE);hi=e.get('hi',False);title=e.get('title')
        th=(size+18) if title else 0;bh=measure(d,e['text'],size,x1-x0-52)+30+th
        assert y+bh<=ymax,f'stack overflow in {cx.key}: {e["text"][:20]}'
        if pop:
            d.rounded_rectangle((x0+6,y+8,x1+6,y+bh+8),20,fill=(0,0,0,int(80*a)))
            d.rounded_rectangle((x0,y,x1,y+bh),20,fill=(255,255,255,int(248*a)),outline=(0,0,0,int(255*a)),width=4)
            yy=y+16
            if title:
                ft=FB[size-4];ww=int(tw(d,title,ft))+36
                pc=(255,120,90) if hi else (255,214,64)
                d.rounded_rectangle((x0+18,yy,x0+18+ww,yy+size+12),12,fill=pc+(int(255*a),),outline=(0,0,0,int(255*a)),width=3)
                line_text(d,(x0+36,yy+5),title,ft,(20,20,20),a);yy+=size+20
            text_block(d,x0+26,yy,e['text'],size,x1-x0-52,(24,24,24),a)
        else:
            box_fill(d,(x0,y,x1,y+bh),a,col=GOLD if hi else EDGE,w=3 if hi else 2)
            yy=y+14
            if title:line_text(d,(x0+24,yy),title,FB[size-4],GOLD,a);yy+=size+16
            text_block(d,x0+26,yy,e['text'],size,x1-x0-52,GOLD if hi else col,a)
        y+=bh+gap
def it_panel(im, d, cx, it):
    if not cx.vis(it):
        return
    a = cx.a(it.get('at'))
    x0, y0, x1, y1 = it['box']
    size = it.get('size', 40)
    col = COL.get(it.get('col', 'white'), WHITE)
    title = it.get('title')
    fam = it.get('fam', 'sans')
    box_fill(d, (x0, y0, x1, y1), a, col=GOLD if it.get('hi') else EDGE,
             w=3 if it.get('hi') else 2)
    yy = y0 + 14
    if title:
        line_text(d, (x0 + 22, yy), title, FB[34], GOLD, a)
        yy += 48
    need = measure(d, it['text'], size, x1 - x0 - 48, fam)
    assert yy + need <= y1 + 4, f'panel overflow in {cx.key}: {it["text"][:20]} need {yy + need - y1}'
    text_block(d, x0 + 24, yy, it['text'], size, x1 - x0 - 48, col, a, fam)


def it_timeline(im, d, cx, it):
    y = it.get('y', 430)
    x0 = it.get('x0', 160)
    x1 = it.get('x1', 1760)
    w = it.get('w', 400)
    size = it.get('size', 36)
    ymax = it.get('ymax', 850)
    if not any(cx.vis(n) for n in it['nodes']):
        return
    d.line([(x0, y), (x1, y)], fill=EDGE + (255,), width=5)
    for n in it['nodes']:
        if not cx.vis(n):
            continue
        a = cx.a(n.get('at'))
        x = n['x']
        col = COL.get(n.get('col', 'org'), ORG)
        d.ellipse((x - 14, y - 14, x + 14, y + 14), fill=tuple(col) + (int(255 * a),),
                  outline=WHITE + (int(255 * a),), width=3)
        line_text(d, (x - w / 2, y + 28), n['label'], F[40], WHITE, a)
        yy = y + 80
        for ln in wrapn(d, n.get('sub', ''), F[size], w):
            line_text(d, (x - w / 2, yy), ln, F[size], (215, 224, 226), a)
            yy += int(size * 1.28)
        assert yy <= ymax, f'timeline overflow in {cx.key}: {n["label"]}'


def it_chips(im, d, cx, it):
    n = len(it['items'])
    w = it.get('w', 480)
    h = it.get('h', 150)
    y = it.get('y', 230)
    gap = it.get('gap', 60)
    tot = n * w + (n - 1) * gap
    x = (1920 - tot) // 2
    size = it.get('size', 72)
    for k, e in enumerate(it['items']):
        if cx.vis(e):
            a = cx.a(e.get('at'))
            xx = x + k * (w + gap)
            d.rounded_rectangle((xx, y, xx + w, y + h), 14,
                                outline=GOLD + (int(255 * a),), width=3,
                                fill=(12, 34, 50, int(255 * a)))
            f = FB[size]
            while tw(d, e['text'], f) > w - 30 and size > 30:
                size -= 4
                f = FB[size]
            line_text(d, (xx + (w - tw(d, e['text'], f)) / 2, y + (h - size * 1.25) / 2),
                      e['text'], f, WHITE, a)


def it_big(im, d, cx, it):
    if not cx.vis(it):
        return
    a = cx.a(it.get('at'))
    size = it.get('size', 56)
    col = COL.get(it.get('col', 'white'), WHITE)
    x0 = it.get('x0', 120)
    x1 = it.get('x1', 1800)
    fam = it.get('fam', 'serif')
    text_block(d, x0, it.get('y', 400), it['text'], size, x1 - x0, col, a, fam)
def it_bars(im,d,cx,it):
    x0,y0,x1,y1=it['box'];title=it.get('title');unit=it.get('unit','');data=it['data'];mx=it.get('max') or max(e['value'] for e in data)
    vis_any=any(cx.vis(e) for e in data)
    if not vis_any:return
    box_fill(d,(x0,y0,x1,y1),1.0);yy=y0+12
    if title:line_text(d,(x0+22,yy),title,FB[34],GOLD,1.0);yy+=52
    pop=STATE.spec.get('style')=='pop'
    rh=min(96 if pop else 70,(y1-yy-14)//len(data));lab_w=it.get('lab_w',300);fs=32
    if pop:
        fs=max(32,min(48,rh-26))
        lab_w=max(lab_w,min(int((x1-x0)*.5),int(max(tw(d,e['label'],F[fs]) for e in data))+50))
    bw=x1-x0-lab_w-(260 if pop else 220)
    for k,e in enumerate(data):
        if not cx.vis(e):continue
        a=cx.a(e.get('at'));ry=yy+k*rh;col=COL.get(e.get('col','org'),ORG)
        line_text(d,(x0+22,ry+4),e['label'],F[fs],WHITE,a);L=int(bw*min(1,e['value']/mx)*ease(a*1.6))
        d.rounded_rectangle((x0+lab_w,ry+6,x0+lab_w+max(4,L),ry+rh-12),6,fill=tuple(col)+(int(235*a),))
        line_text(d,(x0+lab_w+L+14,ry+4),e.get('vlabel',f"{e['value']:,}{unit}"),F[fs],WHITE,a)
def it_table(im,d,cx,it):
    x0,y0,x1,y1=it['box'];cols=it['cols'];rows=it['rows'];size=it.get('size',32);cw=it.get('colw') or [ (x1-x0-40)/len(cols) ]*len(cols)
    pop=STATE.spec.get('style')=='pop'
    if pop and '_fit' in it:size=it['_fit']
    elif pop:
        _d0=ImageDraw.Draw(Image.new('RGBA',(8,8)));best=24
        for sz in range(56,23,-2):
            need=sz+26
            for r in rows:
                need+=max(len(wrapn(_d0,str(c),F[sz],w-16)) for c,w in zip(r['cells'],cw))*int(sz*1.25)+14
            if y0+12+need<=y1:best=sz;break
        size=best;it['_fit']=best
    if not any(cx.vis(r) for r in rows):return
    if pop:
        d.rounded_rectangle((x0+6,y0+8,x1+6,y1+8),20,fill=(0,0,0,80))
        d.rounded_rectangle((x0,y0,x1,y1),20,fill=(255,255,255,250),outline=(0,0,0,255),width=4)
    else:
        box_fill(d,(x0,y0,x1,y1),1.0)
    x=x0+20
    for c,w in zip(cols,cw):line_text(d,(x,y0+12),c,F[size],(70,70,70) if pop else GOLD,1.0);x+=w
    d.line([(x0+16,y0+12+size+14),(x1-16,y0+12+size+14)],fill=(0,0,0,255) if pop else EDGE+(255,),width=3 if pop else 2);yy=y0+12+size+26
    for r in rows:
        if not cx.vis(r):continue
        a=cx.a(r.get('at'));x=x0+20;hmax=0
        tcol=(200,60,0) if (pop and r.get('col')=='gold') else ((30,30,30) if pop else COL.get(r.get('col','white'),WHITE))
        for cell,w in zip(r['cells'],cw):
            ls=wrapn(d,str(cell),F[size],w-16)
            for j,l in enumerate(ls):line_text(d,(x,yy+j*int(size*1.25)),l,F[size],tcol,a)
            hmax=max(hmax,len(ls)*int(size*1.25));x+=w
        yy+=hmax+14;assert yy<=y1+4,f'table overflow in {cx.key}'
def it_cols2(im, d, cx, it):
    if not cx.vis(it):
        return
    sides = (('left', (it.get('x0', 60), it.get('xm', 940))),
             ('right', (it.get('xm2', 980), it.get('x1', 1860))))
    for side, (bx0, bx1) in sides:
        sp = it.get(side)
        if not sp:
            continue
        e = dict(t='stack', x0=bx0, x1=bx1, y0=sp.get('y0', 170),
                 size=it.get('size', 34), items=sp['items'], gap=12)
        if sp.get('title') and cx.on(sp.get('title_at')):
            box_fill(d, (bx0, 170, bx1, 250), cx.a(sp.get('title_at')), col=GOLD, w=3)
            line_text(d, (bx0 + 22, 180), sp['title'], FB[40], GOLD, cx.a(sp.get('title_at')))
            e['y0'] = 266
        it_stack(im, d, cx, e)
def it_flow(im,d,cx,it):
    nodes=it['nodes'];n=len(nodes);y=it.get('y',400);h=it.get('h',140);gap=60;w=(1800-(n-1)*gap)//n;x=60;size=it.get('size',34)
    for k,e in enumerate(nodes):
        xx=x+k*(w+gap)
        if cx.vis(e):
            a=cx.a(e.get('at'));box_fill(d,(xx,y,xx+w,y+h),a,col=GOLD if e.get('hi') else EDGE,w=3 if e.get('hi') else 2)
            ls=wrapn(d,e['text'],F[size],w-30);yy=y+(h-len(ls)*int(size*1.25))/2
            for l in ls:line_text(d,(xx+(w-tw(d,l,F[size]))/2,yy),l,F[size],WHITE,a);yy+=int(size*1.25)
            if k<n-1:d.polygon([(xx+w+12,y+h/2-14),(xx+w+gap-12,y+h/2),(xx+w+12,y+h/2+14)],fill=GOLD+(int(255*a),))
def it_daybar(im, d, cx, it):
    """1-day bar (0-24h): day part (mk..bk minutes) split into 6, night part split into 6. rows: [{label,mk,bk,at}]"""
    x0 = it.get('x0', 150)
    x1 = it.get('x1', 1770)
    y = it.get('y', 230)
    rh = it.get('rh', 190)
    bh = it.get('bh', 64)
    X = lambda m: x0 + (x1 - x0) * m / 1440
    if any(cx.vis(r) for r in it['rows']):
        for h in range(0, 25, 3):
            xx = X(h * 60)
            bottom = y + max(k for k, r in enumerate(it['rows']) if cx.vis(r)) * rh + bh
            d.line([(xx, y - 52), (xx, bottom)], fill=(70, 90, 110, 255), width=1)
            tl = f'{h}時'
            line_text(d, (xx - tw(d, tl, F[26]) / 2, y - 88), tl, F[26], DIM, 1.0)
    for k, r in enumerate(it['rows']):
        if not cx.vis(r):
            continue
        a = cx.a(r.get('at'))
        yy = y + k * rh
        mk, bk = r['mk'], r['bk']
        dk = (bk - mk) / 6
        nk = (1440 - (bk - mk)) / 6
        line_text(d, (x0, yy - 44), r['label'], F[34], WHITE, a)
        d.rectangle((X(0), yy, X(1440), yy + bh), fill=(26, 54, 92, int(255 * a)))
        d.rectangle((X(mk), yy, X(bk), yy + bh), fill=(206, 164, 78, int(235 * a)))
        for q in range(7):
            xx = X(mk + q * dk)
            d.line([(xx, yy), (xx, yy + bh)], fill=(30, 24, 10, int(255 * a)), width=2)
        for q in range(7):
            m = (bk + q * nk) % 1440
            xx = X(m)
            d.line([(xx, yy), (xx, yy + bh)], fill=(150, 185, 235, int(255 * a)), width=2)
        dtxt = r.get('dlabel', f'昼の一刻 {int(dk // 60)}時間{int(dk % 60 + 0.5)}分')
        ntxt = r.get('nlabel', f'夜の一刻 {int(nk // 60)}時間{int(nk % 60 + 0.5)}分')
        if cx.on(r.get('dat')):
            x = X(mk) + (X(bk) - X(mk)) / 2 - tw(d, dtxt, F[32]) / 2
            line_text(d, (x, yy + bh + 10), dtxt, F[32], GOLD, cx.a(r.get('dat')))
        if cx.on(r.get('nat')):
            nx = X(bk) + (X(1440) - X(bk)) / 2
            w_ = tw(d, ntxt, F[32])
            x = max(X(bk) + 6, min(nx - w_ / 2, x1 - w_))
            line_text(d, (x, yy + bh + 10), ntxt, F[32], BLUE, cx.a(r.get('nat')))
def it_line(im, d, cx, it):
    """line chart: x labels, one series; points appear one by one by sentence index. series=[{label,value,at}], y range ymin..ymax, unit"""
    x0, y0, x1, y1 = it['box']
    ser = it['series']
    ymin = it.get('ymin', 0)
    ymax = it.get('ymax', 30)
    unit = it.get('unit', '％')
    title = it.get('title')
    if not any(cx.vis(s) for s in ser):
        return
    box_fill(d, (x0, y0, x1, y1), 1.0)
    yy = y0 + 10
    if title:
        line_text(d, (x0 + 22, yy), title, FB[32], GOLD, 1.0)
        yy += 48
    px0, px1, py0, py1 = x0 + 150, x1 - 90, yy + 50, y1 - 70
    for g in range(0, int(ymax) + 1, 10):
        gy = py1 - (py1 - py0) * (g - ymin) / (ymax - ymin)
        d.line([(px0, gy), (px1, gy)], fill=(60, 80, 100, 255), width=1)
        line_text(d, (x0 + 20, gy - 16), f'{g}{unit}', F[26], DIM, 1.0)
    n = len(ser)
    pts = []
    for k, s in enumerate(ser):
        y0_, y1_ = ser[0].get('year', 0), ser[-1].get('year', n - 1)
        yr = s.get('year', k)
        X = px0 + (px1 - px0) * (yr - y0_) / max(1, (y1_ - y0_))
        Y = py1 - (py1 - py0) * (s['value'] - ymin) / (ymax - ymin)
        pts.append((X, Y))
        line_text(d, (X - tw(d, s['label'], F[26]) / 2, py1 + 12), s['label'], F[26], DIM, 1.0)
    for k, s in enumerate(ser):
        if not cx.vis(s):
            continue
        a = cx.a(s.get('at'))
        X, Y = pts[k]
        col = COL.get(s.get('col', 'org'), ORG)
        if k > 0 and cx.vis(ser[k - 1]):
            d.line([pts[k - 1], (X, Y)], fill=tuple(col) + (int(255 * a),), width=5)
        d.ellipse((X - 9, Y - 9, X + 9, Y + 9), fill=tuple(col) + (int(255 * a),),
                  outline=WHITE + (int(255 * a),), width=2)
        if s.get('show', True):
            v = s.get('vlabel', f"{s['value']}{unit}")
            line_text(d, (X - tw(d, v, F[30]) / 2, Y - 48), v, F[30], WHITE, a)
def it_swirl(im, d, cx, it):
    """concept sketch of a swirl seen from above: dir 'ccw'|'cw' (as seen on screen), centre (x,y), radius r, label under it"""
    if not cx.vis(it):
        return
    a = cx.a(it.get('at'))
    x, y = it['c']
    R = it.get('r', 150)
    ccw = it.get('dir', 'ccw') == 'ccw'
    col = COL.get(it.get('col', 'blue'), BLUE)
    turns, n, pts = 2.2, 160, []
    for k in range(n + 1):
        u = k / n
        th = (turns * 2 * math.pi * u) * (1 if ccw else -1) + it.get('phase', 0)
        r = R * (1 - 0.88 * u)
        pts.append((x + r * math.cos(th), y - r * math.sin(th)))
    d.line(pts, fill=tuple(col) + (int(255 * a),), width=7, joint='curve')
    (x1_, y1_), (x2_, y2_) = pts[-6], pts[-1]
    ang = math.atan2(y2_ - y1_, x2_ - x1_)
    hl = 26
    d.polygon([(x2_, y2_),
               (x2_ - hl * math.cos(ang - 0.5), y2_ - hl * math.sin(ang - 0.5)),
               (x2_ - hl * math.cos(ang + 0.5), y2_ - hl * math.sin(ang + 0.5))],
              fill=tuple(col) + (int(255 * a),))
    d.ellipse((x - R - 14, y - R - 14, x + R + 14, y + R + 14),
              outline=EDGE + (int(120 * a),), width=2)
    lab = it.get('label', '')
    f = F[it.get('lsize', 34)]
    yy = y + R + 26
    for ln in wrapn(d, lab, f, it.get('lw', 520)):
        line_text(d, (x - tw(d, ln, f) / 2, yy), ln, f, WHITE, a)
        yy += int(it.get('lsize', 34) * 1.3)




def it_art(im, d, cx, it):
    """生成イラストを、箱いっぱいに敷く（ゆっくり拡大・移動）。spec: dict(t='art',name='<images のキー>',box=[...],at=N,until=M,dim=0.7)
    note= の注意書きは既定で箱の右下。note_y= を渡すと、その高さ（画面座標）に置く（例：本文に重なる章で header の右へ逃がす）。"""
    if not cx.vis(it):
        return
    a = cx.a(it.get('at'), .8)
    if a <= 0:
        return
    x0, y0, x1, y1 = it['box']
    w, h, name = x1 - x0, y1 - y0, it['name']
    if name not in STATE.arts:
        src = Image.open(P(STATE.spec['images'][name]['file'])).convert('RGB')
        sc = max(w / src.width, h / src.height) * 1.14
        base = src.resize((int(src.width * sc) + 1, int(src.height * sc) + 1), Image.BILINEAR)
        STATE.arts[name] = base
    base = STATE.arts[name]
    prog = min(1.0, max(0.0, cx.t / max(8.0, it.get('drift', 30.0))))
    if it.get('dir', 1) > 0:
        ox = int((base.width - w) * (0.15 + 0.7 * prog) * it.get('dir', 1))
    else:
        ox = int((base.width - w) * (0.85 - 0.7 * prog))
    oy = int((base.height - h) * 0.5)
    crop = base.crop((ox, oy, ox + w, oy + h)).convert('RGBA')
    dim = it.get('dim', 0.7)
    crop = Image.blend(crop, Image.new('RGBA', crop.size, (5, 16, 26, 255)), 1 - dim)
    mask = Image.new('L', (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), 18, fill=int(255 * a))
    layer = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    layer.paste(crop, (0, 0), mask)
    im.alpha_composite(layer, (x0, y0))
    if it.get('note'):
        f = F[it.get('note_size', 24)]
        tw_ = int(d.textlength(it['note'], font=f))
        ln = ImageDraw.Draw(im, 'RGBA')
        nx = x1 - tw_ - 34
        ny = it.get('note_y', y1 - (36 + it.get('note_size', 24)))
        ln.rounded_rectangle((nx - 12, ny - 6, x1 - 14, ny + 34), 10,
                             fill=(5, 16, 26, int(215 * a)))
        ln.text((nx, ny), it['note'], font=f, fill=(215, 224, 226, int(255 * a)))


def it_shade(im, d, cx, it):
    """暗い下地（文字を読みやすくする）。spec: dict(t='shade',box=[...],at=N,until=M,alpha=0.8)"""
    if not cx.vis(it):
        return
    a = cx.a(it.get('at'), .5)
    if a <= 0:
        return
    x0, y0, x1, y1 = it['box']
    lay = Image.new('RGBA', (x1 - x0, y1 - y0), (0, 0, 0, 0))
    ImageDraw.Draw(lay).rounded_rectangle((0, 0, x1 - x0 - 1, y1 - y0 - 1), 16,
                                          fill=(6, 18, 29, int(255 * it.get('alpha', 0.8) * a)))
    im.alpha_composite(lay, (x0, y0))




def it_anim(im, d, cx, it):
    """自作アニメーション部品（scripts/vp_anim.py）。spec: dict(t='anim',name='...',box=[...],at=N,until=M,...)"""
    if not cx.vis(it):
        return
    a = cx.a(it.get('at'))
    if a <= 0:
        return
    import vp_anim
    if not STATE.anim_bound[0]:
        vp_anim.bind(STATE.as_dict())
        STATE.anim_bound[0] = True
    vp_anim.DRAW[it['name']](im, d, cx, it, a)


ITEMS = dict(
    shade=it_shade, art=it_art, anim=it_anim, swirl=it_swirl, line=it_line,
    daybar=it_daybar, stack=it_stack, panel=it_panel, image=it_image,
    timeline=it_timeline, chips=it_chips, big=it_big, bars=it_bars,
    table=it_table, cols2=it_cols2, flow=it_flow,
)


def opener(im, d, cx):
    ch = STATE.spec['chapters'][cx.ci]
    un = ch.get('opener_until', 0)
    if cx.idx() >= un:
        return
    a = cx.a(0, 0.4) if cx.idx() >= 0 else 1.0
    txt = ch.get('opener', ch.get('chapter_title', ''))
    f = FB[64]
    ls = wrapn(d, txt, f, 1500)
    h = len(ls) * int(64 * 1.35)
    y = ch.get('opener_y', 520) - h // 2
    box_fill(d, (160, y - 30, 1760, y + h + 22), a, col=GOLD, w=3)
    for ln in ls:
        line_text(d, ((1920 - tw(d, ln, f)) / 2, y), ln, f, GOLD, a)
        y += int(64 * 1.35)


def render_scene(im, d, cx):
    opener(im, d, cx)
    for it in STATE.spec['chapters'][cx.ci]['scene']:
        ITEMS[it['t']](im, d, cx, it) if it['t'] != 'image' else it_image(im, d, cx, it)
        d = ImageDraw.Draw(im, 'RGBA')


def header(d, ci):
    if STATE.spec.get('style') == 'pop':
        import vp_anim_pop as PP
        PP.bind(STATE.as_dict())
        return PP.header(d, ci)
    d.text((48, 16), STATE.spec['chapters'][ci].get('title', ''),
           font=FB[60], fill=WHITE, stroke_width=5, stroke_fill=(5, 10, 16))
    d.text((48, 94), STATE.spec['header_sub'],
           font=F[28], fill=(200, 210, 214), stroke_width=4, stroke_fill=(5, 10, 16))
# ---------------------------------------------------------------- subtitles / frames
def split_clauses(txt,maxc=42):
    """42字を超える字幕は、読点の切れ目で分け、1回に出す量を減らす（時間は文字数に比例）"""
    if len(txt)<=maxc:return [txt]
    parts=[x+'、' for x in txt.split('、')];parts[-1]=parts[-1][:-1]
    out=[];cur=''
    for x in parts:
        if cur and len(cur)+len(x)>maxc:out.append(cur);cur=x
        else:cur+=x
    if cur:out.append(cur)
    return out
def sub_lines(d, seg, f, t):
    k = seg['start']
    if k not in STATE.subp:
        txt = thin(display(seg['text']))
        ls = wrap(d, txt, f, 1720)
        ch = split_clauses(txt)
        ct = seg.get('cue_times')
        if len(ch) > 1:
            if ct and len(ct) == len(ch) + 1:
                ts = ct
            else:
                tot = sum(len(c) for c in ch)
                cum, fr = 0, []
                for c in ch:
                    fr.append(cum / tot)
                    cum += len(c)
                fr.append(1.0)
                ts = snap_bounds(seg, fr)
            STATE.subp[k] = [(wrap(d, c, f, 1720), ts[i], ts[i + 1]) for i, c in enumerate(ch)]
        elif len(ls) <= 2:
            STATE.subp[k] = [(ls, seg['start'], seg['end'])]
        else:
            allw = wrapn(d, txt, f, 1720)
            pages = [allw[i:i + 2] for i in range(0, len(allw), 2)]
            tot = sum(len(''.join(p)) for p in pages)
            cum, fr = 0, []
            for p in pages:
                fr.append(cum / tot)
                cum += len(''.join(p))
            fr.append(1.0)
            ts = snap_bounds(seg, fr)
            STATE.subp[k] = [(p, ts[i], ts[i + 1]) for i, p in enumerate(pages)]
    for ls, s0, s1 in STATE.subp[k]:
        if t < s1:
            return ls
    return STATE.subp[k][-1][0]


def _base_frame(ci, t, with_header=True):
    """字幕なしの 1 コマ（ヘッダー＋シーン＋章の見出し）。"""
    if STATE.spec.get('style') == 'pop':
        import vp_anim_pop as PP
        PP.bind(STATE.as_dict())
        im = PP.background(ci, t)
    else:
        im = Image.new('RGBA', (1920, 1080), NAVY + (255,))
    d = ImageDraw.Draw(im, 'RGBA')
    if with_header:
        header(d, ci)
    render_scene(im, d, Ctx(ci, t))
    return im


def _subs_layer(ci, t, alpha):
    """字幕だけの透明レイヤー。章の切れ目では alpha でフェードさせる。"""
    if alpha <= 0:
        return None
    cx = Ctx(ci, t)
    active = next((x for x in cx.segl if x['start'] <= t < x['end']), None)
    if not active:
        return None
    lay = Image.new('RGBA', (1920, 1080), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay, 'RGBA')
    if STATE.spec.get('style') == 'pop':
        import vp_anim_pop as PP
        PP.bind(STATE.as_dict())
        PP.subs_shade(lay)
        f = PP.heavy(66)
        lines = sub_lines(d, active, f, t)
        PP.subs(d, lines, f, rich)
    else:
        f = FSUB[52]
        lines = sub_lines(d, active, f, t)
        d.rounded_rectangle((60, 850, 1860, 1008), 12, fill=(5, 18, 29, 242))
        for j, txt in enumerate(lines):
            assert tw(d, txt, f) < 1760
            rich.draw_center(d, 960, 862 + j * 70, txt, f, '#fffcef', (255, 208, 122))
    if alpha < 1:
        lay.putalpha(lay.getchannel('A').point(lambda v: int(v * alpha)))
    return lay


def render_frame(i):
    t = i / 30
    ci = next(k for k, c in enumerate(STATE.tl) if t < c['end'] + 1e-9)
    # 章の切れ目は、前の章と次の章を同時に描いて混ぜる（0.35 秒）。ハードカットの「飛び」を消す。
    b = None
    if ci > 0 and t < STATE.tl[ci]['start'] + XFADE / 2:
        b, A, B = STATE.tl[ci]['start'], ci - 1, ci
    elif ci < len(STATE.tl) - 1 and t > STATE.tl[ci]['end'] - XFADE / 2:
        b, A, B = STATE.tl[ci]['end'], ci, ci + 1
    if b is None:
        im = _base_frame(ci, t)
        layers = ((ci, 1.0),)
    else:
        w = min(1.0, max(0.0, (t - (b - XFADE / 2)) / XFADE))
        im = Image.blend(_base_frame(A, t, False), _base_frame(B, t, False), w)
        # 見出しは混ぜず、切り替わりで入れ替える（二重に重なって読めなくなるのを防ぐ）
        header(ImageDraw.Draw(im), B if w >= 0.5 else A)
        layers = ((A, 1 - w), (B, w))
    for k, a in layers:
        lay = _subs_layer(k, t, a)
        if lay:
            im.alpha_composite(lay)
    d = ImageDraw.Draw(im)
    yb = 1066 if STATE.spec.get('style') == 'pop' else 1012
    d.rectangle((48, yb, 48 + 1824 * (i + 1) / STATE.n, yb + 6),
                fill=(255, 226, 40) if STATE.spec.get('style') == 'pop' else (201, 173, 112))
    return im
def render_part(a,b):
    stills=[int(x) for x in os.environ['STILLS'].split(',')] if os.environ.get('STILLS') else None
    out = P(f'cache/{STATE.slug}_part_{a}_{b}.mp4')
    P('logs').mkdir(exist_ok=True)
    log = P(f'logs/{STATE.slug}_enc_{a}.log').open('wb')

    class _P:
        class stdin:
            write = staticmethod(lambda b: None)
            close = staticmethod(lambda: None)

        def wait(self):
            pass

        returncode = 0

    if stills:
        proc = _P()
    else:
        codec = (['-c:v', 'libx264', '-preset', 'veryfast', '-crf', '19']
                 if os.environ.get('VP_ENC') == 'libx264'
                 else ['-c:v', 'h264_nvenc', '-preset', 'p4', '-cq', '19', '-b:v', '0'])
        cmd = [_ffmpeg(), '-y', '-v', 'warning', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
               '-s', '1920x1080', '-r', '30', '-i', 'pipe:0', '-an', *codec,
               '-pix_fmt', 'yuv420p', str(out)]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=log)
    try:
        for i in (stills or range(a, min(b, STATE.n))):
            im = render_frame(i)
            proc.stdin.write(im.convert('RGB').tobytes())
            if stills:
                im.convert('RGB').save(P(f'cache/{STATE.slug}_still_{i}.png'))
    finally:
        proc.stdin.close()
        proc.wait()
        log.close()
    assert proc.returncode == 0
# ---------------------------------------------------------------- stages
def stage_story():
    t = (theme_dir() / '09_script_v2.md').read_text(encoding='utf8')
    chs = re.split(r'\n## ', t)[1:]
    scenes = []
    keys = [c['key'] for c in STATE.spec['chapters']]
    for c in chs:
        head = c.split('\n')[0]
        m = re.match(r'章(\d+)　(.*)', head)
        if not m:
            continue
        n = int(m.group(1))
        lines = [re.sub(r'〔[^〕]*〕', '', re.sub(r'^\d+\. ', '', l)).strip()
                 for l in c.split('\n') if re.match(r'^\d+\. ', l)]
        scenes.append(dict(id=n - 1, key=keys[n - 1], title=m.group(2), narration=''.join(lines)))
    assert len(scenes) == len(keys), f'{len(scenes)} chapters in script vs {len(keys)} in spec'
    P(f'data/{STATE.slug}_scenes.json').write_text(json.dumps(scenes, ensure_ascii=False, indent=1), encoding='utf8')
    pr = P(f'data/{STATE.slug}_pronunciations.json')
    if not pr.exists():
        pr.write_text('{}', encoding='utf8')
    n = sum(len(s['narration']) for s in scenes)
    print(len(scenes), 'scenes', n, 'chars  est. minutes', round(n / 290, 1))


def _vv():
    import requests
    style = vv.speaker_id(VOICE['speaker'], VOICE['style'], base=BASE, timeout=60)
    return requests, style


def sentences(sc):
    return [x.strip() + '。' for x in sc['narration'].split('。') if x.strip()]


def load_dic():
    """読みの辞書。全動画で共有する data/pronunciations_common.json に、動画ごとの辞書を重ねる（同じ語は動画ごとの方が勝つ）"""
    d = {}
    c = P('data/pronunciations_common.json')
    if c.exists():
        d.update(json.loads(c.read_text(encoding='utf8')))
    d.update(json.loads(P(f'data/{STATE.slug}_pronunciations.json').read_text(encoding='utf8')))
    return d
def stage_kana():
    requests, style = _vv()
    dic = load_dic()
    out = []
    for s in json.loads(P(f'data/{STATE.slug}_scenes.json').read_text(encoding='utf8')):
        for x in sentences(s):
            sp_ = vv.apply_pron(x, dic)
            q = requests.post(BASE + '/audio_query', params={'text': sp_, 'speaker': style},
                              timeout=60).json()
            out.append(f"[{s['key']}] {x}\n    {q['kana']}")
    P(f'out/{STATE.slug}_kana.txt').write_text('\n'.join(out), encoding='utf8')
    print(len(out), 'sentences ->', f'out/{STATE.slug}_kana.txt')


def readwav(p):
    with wave.open(str(p), 'rb') as w:
        return np.frombuffer(w.readframes(w.getnframes()), np.int16), w.getframerate()
def writewav(p,a,rate):
    with wave.open(str(p),'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(rate);w.writeframes(a.astype(np.int16).tobytes())
SNAP_TOL=0.5;DIP_TOL=0.35;MIN_CUE=0.45
def _env(pcm,rate):
    """10ms フレームの RMS とホップ（サンプル数）"""
    hop=max(1,int(0.01*rate));n=len(pcm)//hop
    if n<3:return np.zeros(0),hop
    x=pcm[:n*hop].astype(np.float64)/32768
    return np.sqrt((x.reshape(n,hop)**2).mean(axis=1)),hop
def _silence_centers(fr,hop,rate,dur,min_len=0.12,ratio=0.08):
    """発話中の無音（息継ぎ）の中央を秒で返す。音量は発話区間の中央値に対して相対で見る（既存音声からも取れる）"""
    if len(fr)<3:return []
    loud=fr[fr>fr.max()*0.1];ref=float(np.median(loud)) if loud.size else float(fr.mean())
    thr=max(0.008,ratio*ref);sil=fr<thr;out=[];i=0;n=len(fr)
    while i<n:
        if sil[i]:
            j=i
            while j<n and sil[j]:j+=1
            if (j-i)*hop/rate>=min_len:
                c=(i+j)/2*hop/rate
                if 0.15<c<dur-0.15:out.append(c)
            i=j
        else:i+=1
    return out
def _cue_times(pcm,rate,t0,dur,fr):
    """境界を 無音 → 音量の谷 → 比例位置 の順で決める（fr は 0..1 の上り順・最後は 1.0）"""
    env,hop=_env(pcm,rate);sil=_silence_centers(env,hop,rate,dur)
    if len(env)==0:return [round(t0+dur*f,4) for f in fr]
    out=[];prev=0.0;pi=0
    for j,f in enumerate(fr):
        t=dur*f
        if j<len(fr)-1:
            lo=max(prev+MIN_CUE,t-SNAP_TOL);hi=min(dur-MIN_CUE,t+SNAP_TOL)
            cand=[p for p in sil[pi:] if lo<=p<=hi]
            if cand:
                t=min(cand,key=lambda p:abs(p-t));pi=sil.index(t)+1
            else:
                lo2=max(prev+MIN_CUE,t-DIP_TOL);hi2=min(dur-MIN_CUE,t+DIP_TOL)
                a,b=int(lo2*rate/hop),int(hi2*rate/hop)
                if b>a:t=max(prev+MIN_CUE,(a+int(np.argmin(env[a:b])))*hop/rate)
        else:t=dur
        out.append(round(t0+t,4));prev=t
    return out
def snap_bounds(seg,fr):
    """境界（0..1 の上り順、最後は 1.0）を最寄りの無音へ寄せる。無音は1つずつ順番に割り当て、SNAP_TOL/MIN_CUE を守る"""
    ps=sorted(seg.get('pauses') or []);t0=seg['start'];t1=seg['end'];span=max(1e-6,t1-t0)
    if not ps:return [t0+span*f for f in fr]
    out=[];prev=t0;pi=0
    for j,f in enumerate(fr):
        t=t0+span*f
        if j<len(fr)-1:
            lo=max(prev+MIN_CUE,t-SNAP_TOL);hi=min(t1-MIN_CUE,t+SNAP_TOL)
            best=None
            for k in range(pi,len(ps)):
                p=ps[k]
                if p<lo:continue
                if p>hi:break
                if best is None or abs(p-t)<abs(best-t):best=p
            if best is not None:
                t=best;pi=ps.index(best)+1
        else:t=t1
        out.append(t);prev=t
    return out
def stage_audio():
    requests, style = _vv()
    folder = P(f'cache/{STATE.slug}_audio')
    folder.mkdir(exist_ok=True, parents=True)
    voice = STATE.spec.get('voice', {})
    speed = float(voice.get('speed', SPEED))
    pre = float(voice.get('pre_phoneme', .15))
    post = float(voice.get('post_phoneme', .35))
    scene_hold = float(voice.get('scene_hold', 1.6))
    dic = load_dic()
    scenes = json.loads(P(f'data/{STATE.slug}_scenes.json').read_text(encoding='utf8'))
    segs, timeline, cursor, allpcm, rate = [], [], 0, [], 24000

    for sc in scenes:
        local, t = [], 0
        for i, text in enumerate(sentences(sc)):
            spoken = vv.apply_pron(text, dic)
            p = folder / f'{sc["id"]:02}_{i:02}.wav'
            key = hashlib.sha256((spoken + f'|{speed}|1.08|{pre}|{post}|' + str(style)).encode()).hexdigest()
            meta = p.with_suffix('.json')
            if not p.exists() or not meta.exists() or json.loads(meta.read_text())['key'] != key:
                q = requests.post(BASE + '/audio_query', params={'text': spoken, 'speaker': style},
                                  timeout=120).json()
                q.update(speedScale=speed, intonationScale=1.08, prePhonemeLength=pre,
                         postPhonemeLength=post, outputSamplingRate=24000)
                r = requests.post(BASE + '/synthesis', params={'speaker': style}, json=q, timeout=180)
                r.raise_for_status()
                p.write_bytes(r.content)
                meta.write_text(json.dumps({'key': key}), encoding='utf8')
            pcm, rate = readwav(p)
            dur = len(pcm) / rate
            rms = float(np.sqrt(np.mean((pcm.astype(float) / 32768) ** 2)))
            peak = float(np.abs(pcm).max() / 32768)
            ch0 = split_clauses(thin(display(text)))
            tot0 = sum(len(c) for c in ch0)
            cum0, fr0 = 0, []
            for c in ch0:
                fr0.append(cum0 / tot0)
                cum0 += len(c)
            fr0.append(1.0)
            ct = _cue_times(pcm, rate, cursor + t, dur, fr0)
            env0, hop0 = _env(pcm, rate)
            assert dur > .4 and rms > .003 and peak < .999, (sc['key'], i, dur, rms, peak)
            segs.append(dict(
                scene=sc['id'], text=text, spoken=spoken,
                start=round(cursor + t, 4), end=round(cursor + t + dur, 4),
                duration=dur, rms=rms, peak=peak, cue_times=ct,
                pauses=[round(cursor + t + x, 4) for x in _silence_centers(env0, hop0, rate, dur)],
            ))
            local.append(pcm)
            t += dur
        sd = math.ceil((t + scene_hold) * 30) / 30
        j = np.concatenate(local)
        j = np.pad(j, (0, round(sd * rate) - len(j)))
        allpcm.append(j)
        timeline.append({**sc, 'start': cursor, 'duration': sd, 'end': cursor + sd})
        cursor += sd
    writewav(P(f'out/{STATE.slug}_narration.wav'), np.concatenate(allpcm), rate)

    cues, rep = [], []
    for x in segs:
        ch = split_clauses(thin(display(x['text'])))
        tot = sum(len(c) for c in ch)
        cum, fr = 0, []
        for c in ch:
            fr.append(cum / tot)
            cum += len(c)
        fr.append(1.0)
        nom = [x['start'] + (x['end'] - x['start']) * f for f in fr]
        ct = x.get('cue_times')
        ts = ct if ct and len(ct) == len(ch) + 1 else snap_bounds(x, fr)
        rep.append(dict(
            start=x['start'], end=x['end'], n=len(ch),
            snapped=sum(1 for a, b in zip(nom, ts) if abs(a - b) > 1e-6),
            max_shift=round(max([abs(a - b) for a, b in zip(nom, ts)]), 4),
            pauses=len(x.get('pauses') or []),
        ))
        for i, c in enumerate(ch):
            cues.append((ts[i], ts[i + 1], c))
    write_srt(P(f'out/{STATE.slug}_subtitles.srt'), cues)
    P(f'out/{STATE.slug}_subtitle_timing.json').write_text(json.dumps(dict(
        tol=SNAP_TOL, min_cue=MIN_CUE,
        max_shift=max([r['max_shift'] for r in rep] or [0]),
        snapped=sum(r['snapped'] for r in rep), segments=rep,
    ), ensure_ascii=False, indent=1), encoding='utf8')
    P(f'data/{STATE.slug}_timeline.json').write_text(json.dumps(timeline, ensure_ascii=False, indent=1), encoding='utf8')
    P(f'out/{STATE.slug}_audio_report.json').write_text(json.dumps(dict(
        engine=requests.get(BASE + '/version').json(),
        speaker=VOICE['label'], style=style,
        voice_tuning=dict(speed=speed, pre_phoneme=pre, post_phoneme=post, scene_hold=scene_hold),
        segments=segs, total_seconds=cursor, all_lines_voiced=True, semantic_asr_verified=False,
    ), ensure_ascii=False, indent=1), encoding='utf8')
    print('total', round(cursor, 1), 's', int(cursor // 60), 'min', int(cursor % 60), 's')
def stage_bgm():
    SR = 48000
    D = P(BGM['dir'])
    tl = json.loads(P(f'data/{STATE.slug}_timeline.json').read_text(encoding='utf8'))
    T = {c['key']: c for c in tl}
    TOTAL = tl[-1]['end']
    XF, TARGET = 3.0, -24.0

    def load_(name):
        f = str(D / BGM['pattern'].format(name=name))
        raw = subprocess.run([_ffmpeg(), '-v', 'error', '-i', f, '-ar', str(SR),
                              '-ac', '2', '-f', 'f32le', '-'], capture_output=True).stdout
        x = np.frombuffer(raw, np.float32).reshape(-1, 2).T.astype(np.float64)
        lufs, _ = yloud.measure_ebur128(f, ffmpeg=_ffmpeg())
        if lufs is None:
            raise RuntimeError(f'BGM の音量を測れませんでした: {f}')
        return x * 10 ** ((TARGET - lufs) / 20)

    fade = lambda n, k: (lambda u: np.sin(u * np.pi / 2) if k == 'in' else np.cos(u * np.pi / 2))(np.linspace(0, 1, n))

    def fill(x, length):
        xf, out = int(XF * SR), x.copy()
        while out.shape[1] < length:
            a, b = out, x
            out = np.concatenate([a[:, :-xf], a[:, -xf:] * fade(xf, 'out') + b[:, :xf] * fade(xf, 'in'), b[:, xf:]], axis=1)
        return out[:, :length]

    n_ = int(TOTAL * SR)
    mix = np.zeros((2, n_))
    cache = {}
    for a, b, name in STATE.spec['bgm']:
        s, e = T[a]['start'], T[b]['end']
        s0, e0 = max(0, s - XF / 2), min(TOTAL, e + XF / 2)
        n = int((e0 - s0) * SR)
        if name not in cache:
            cache[name] = load_(name)
        seg = fill(cache[name], n).copy()
        fi = int(XF * SR) if s0 > 0 else 0
        fo = int(XF * SR) if e0 < TOTAL else 0
        if fi:
            seg[:, :fi] *= fade(fi, 'in')
        if fo:
            seg[:, -fo:] *= fade(fo, 'out')
        i = int(s0 * SR)
        mix[:, i:i + n] += seg[:, :n_ - i]
    fi, fo = int(2 * SR), int(6 * SR)
    env = np.ones(n_)
    env[:fi] = np.linspace(0, 1, fi)
    env[-fo:] = np.minimum(env[-fo:], np.linspace(1, 0, fo) ** 1.5)
    mix *= env
    pk = np.abs(mix).max()
    if pk > .9:
        mix *= .9 / pk
    with wave.open(str(P(f'out/{STATE.slug}_bgm.wav')), 'wb') as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((mix.T * 32767).astype(np.int16).tobytes())
    print('bgm ok', round(TOTAL, 1), 's')
def loud_args(path):
    j=yloud.measure_loudnorm(path,ffmpeg=_ffmpeg(),lra=9)
    if j is None:raise RuntimeError(f'loudnorm の測定に失敗しました: {path}')
    return yloud.loudnorm_filter(j,i=-14,tp=-1.5,lra=9),j
def _code_fp():
    """描画に関わるコード全体の指紋（コードが変わったら、全部品を作り直す）"""
    h = hashlib.sha1()
    # 実体は ytcore（shim ではなく中身の指紋を取る）。名前順にして、移す前と同じ並びで指紋を取る
    files = [Path(__file__)] + list(PLUGIN_DIR.glob('vp_anim*.py'))
    files += [Path(m.__file__) for m in (hn_text, thin_commas, rich)]
    for f in sorted(files, key=lambda f: f.name):
        if f.name.startswith(('vp_before', 'vp_check', 'vp_preview', 'vp_lock', 'vp_remix')) or not f.exists():
            continue
        # 行末(CRLF/LF)は、チェックアウトの設定でツリーごとに違う。指紋は内容だけで取る
        b = f.read_bytes().replace(b'\r', b'')
        if f.name == 'vp.py':
            # vp.py は、描画の部分（text helpers〜stages）だけを見る。
            # コマンドや段取りの変更で、部品を作り直さない
            t = b.decode('utf8').replace('\r', '')
            a_ = t.index('# ---------------------------------------------------------------- text helpers')
            z_ = t.index('# ---------------------------------------------------------------- stages')
            b = t[a_:z_].encode('utf8')
        h.update(f.name.encode())
        h.update(b)
    return h.hexdigest()


def _part_fp(a, b, codefp):
    """フレーム a〜b の部品の指紋：該当する章（と前後の章）の定義、文の時刻、画像ファイル、全体の長さ、描画コード"""
    t0, t1 = a / 30 - 1.0, b / 30 + 1.0
    cis = sorted({x for ci, c in enumerate(STATE.tl) if c['end'] >= t0 and c['start'] <= t1
                  for x in (ci - 1, ci, ci + 1) if 0 <= x < len(STATE.tl)})
    h = hashlib.sha1()
    imgs = {}
    for k, m in (STATE.spec.get('images') or {}).items():
        f = P(m['file'])
        imgs[k] = [m, f.stat().st_size if f.exists() else -1,
                   f.stat().st_mtime_ns if f.exists() else -1]
    h.update(json.dumps([STATE.spec.get('style'), imgs, STATE.n, codefp], sort_keys=True, ensure_ascii=False).encode())
    for ci in cis:
        h.update(json.dumps([ci, STATE.spec['chapters'][ci], STATE.tl[ci], [x for x in STATE.segs if x['scene'] == ci]],
                            sort_keys=True, ensure_ascii=False).encode())
    return h.hexdigest()
def stage_build(chunk=1000, bgm_db=-6.0):
    load_runtime()
    chunk = int(os.environ.get('VP_CHUNK', chunk))   # 部品の長さ（フレーム）。短くすると、差分再描画の粒度が細かくなる
    keep_parts = os.environ.get('VP_KEEP_PARTS') == '1'
    full = os.environ.get('VP_FULL') == '1'
    import time as _t
    codefp = _code_fp()
    fps = {a: _part_fp(a, min(a + chunk, STATE.n), codefp) for a in range(0, STATE.n, chunk)}
    pending, reused = [], 0
    for a in range(0, STATE.n, chunk):
        mp = P(f'cache/{STATE.slug}_part_{a}_{a + chunk}.mp4')
        fpf = P(f'cache/{STATE.slug}_part_{a}_{a + chunk}.fp')
        ok = mp.exists() and mp.stat().st_size > 0
        # 変わっていない部品は、作り直さない
        if ok and (keep_parts or (not full and fpf.exists() and fpf.read_text(encoding='utf8') == fps[a])):
            reused += 1
            continue
        if mp.exists():
            mp.unlink()
        if fpf.exists():
            fpf.unlink()
        pending.append(a)
    want = {f'{STATE.slug}_part_{a}_{a + chunk}' for a in range(0, STATE.n, chunk)}
    # 部品の長さが違う古い部品は、結合に混ざらないよう消す
    for f in list(P('cache').glob(f'{STATE.slug}_part_*.mp4')) + list(P('cache').glob(f'{STATE.slug}_part_*.fp')):
        if f.stem not in want:
            f.unlink()
    print(f'parts: {len(fps)} (reuse {reused}, render {len(pending)})', flush=True)
    from ytcore import vp_lock
    # 別の build が動いていれば、並列数を分け合う
    maxpar = int(os.environ['VP_MAXPAR']) if os.environ.get('VP_MAXPAR') else vp_lock.share_maxpar(ROOT, STATE.slug)
    running, rc, tries, why = [], [], {}, []
    TRANSIENT = ('Could not open encoder', 'OpenEncodeSessionEx', 'No capable devices',
                 'NVENC', 'nvenc', 'CUDA_ERROR', 'out of memory')
    while pending or running:   # NVENC の同時セッションは8本まで（14本同時だと、Could not open encoder で落ちる）
        while pending and not why and len(running) < maxpar:
            a = pending.pop(0)
            ef = P(f'cache/{STATE.slug}_part_{a}.err')
            fh = open(ef, 'w', encoding='utf8')
            cmd = [sys.executable, '-m', 'ytcore.vp', STATE.slug, 'part', str(a), str(a + chunk)]
            running.append((a, subprocess.Popen(cmd, cwd=str(ROOT),
                                                env={**os.environ, 'PYTHONIOENCODING': 'utf8'}, stderr=fh), fh, ef))
        _t.sleep(1)
        for q_ in [q for q in running if q[1].poll() is not None]:
            running.remove(q_)
            q_[2].close()
            err = q_[3].read_text(encoding='utf8', errors='replace') if q_[3].exists() else ''
            if why:
                continue   # すでに止めると決めたあと（kill された部品）は数えない
            if q_[1].returncode == 0:
                rc.append(0)
                P(f'cache/{STATE.slug}_part_{q_[0]}_{q_[0] + chunk}.fp').write_text(fps[q_[0]], encoding='utf8')
                continue
            transient = any(t in err for t in TRANSIENT)
            if transient and tries.get(q_[0], 0) < 2:   # GPUの一時失敗だけ、少し待って部品ごとにやり直す
                tries[q_[0]] = tries.get(q_[0], 0) + 1
                _t.sleep(10)
                pending.append(q_[0])
            else:   # 必ず失敗するエラーは、待たずに止める（残りの部品も止める）
                rc.append(q_[1].returncode)
                last = [l for l in err.strip().split('\n') if l.strip()][-3:]
                why.append(f'part {q_[0]}: ' + ' | '.join(last))
                sys.stderr.write(err[-2000:] + '\n')
                for r_ in running:
                    r_[1].kill()
                pending.clear()
    for f_ in P('cache').glob(f'{STATE.slug}_part_*.err'):
        f_.unlink(missing_ok=True)
    if why:
        raise AssertionError('part render failed (not retried: deterministic error) ' + '; '.join(why))
    assert all(r == 0 for r in rc), f'part render failed {rc}'
    parts = [P(f'cache/{STATE.slug}_part_{a}_{a + chunk}.mp4') for a in range(0, STATE.n, chunk)]
    miss = [p.name for p in parts if not p.exists() or p.stat().st_size == 0]
    assert not miss, f'部品が足りない: {miss}'
    lst = P(f'cache/{STATE.slug}_parts.txt')
    lst.write_text(''.join(f"file '{p.as_posix()}'\n" for p in parts))
    wav = P(f'out/{STATE.slug}_narration.wav')
    nob = P(f'out/{STATE.slug}_video_nobgm.mp4')
    af, j = loud_args(wav)
    subprocess.run([_ffmpeg(), '-y', '-v', 'warning', '-f', 'concat', '-safe', '0', '-i', str(lst),
                    '-i', str(wav), '-map', '0:v', '-map', '1:a', '-c:v', 'copy', '-af', af,
                    '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-movflags', '+faststart',
                    '-shortest', str(nob)], check=True)
    mix = P(f'cache/{STATE.slug}_mix.wav')
    bgm = P(f'out/{STATE.slug}_bgm.wav')
    fc = (f'[0:a]aresample=48000,pan=stereo|c0=c0|c1=c0,asplit=2[n1][n2];'
          f'[1:a]volume={bgm_db}dB[bg];'
          f'[bg][n2]sidechaincompress=threshold=0.02:ratio=4:attack=30:release=900:makeup=1[duck];'
          f'[n1][duck]amix=inputs=2:normalize=0:duration=first[m]')
    subprocess.run([_ffmpeg(), '-y', '-v', 'warning', '-i', str(wav), '-i', str(bgm),
                    '-filter_complex', fc, '-map', '[m]', '-c:a', 'pcm_s16le', str(mix)], check=True)
    af2, j2 = loud_args(mix)
    out = P(f'out/{STATE.slug}_video.mp4')
    subprocess.run([_ffmpeg(), '-y', '-v', 'warning', '-i', str(nob), '-i', str(mix),
                    '-map', '0:v', '-map', '1:a', '-c:v', 'copy', '-af', af2, '-c:a', 'aac',
                    '-b:a', '192k', '-ar', '48000', '-movflags', '+faststart', '-shortest', str(out)],
                   check=True)
    # 焼き込んだ字幕の指紋を残す（あとで「字幕だけ直して焼き直していない」を中身で判定するため）
    srt=P(f'out/{STATE.slug}_subtitles.srt')
    if srt.exists():
        import hashlib,datetime as _dt
        P(f'out/{STATE.slug}_build.json').write_text(json.dumps({
            'srt_sha256': hashlib.sha256(srt.read_bytes()).hexdigest(),
            'srt_mtime': srt.stat().st_mtime,
            'video_mtime': out.stat().st_mtime,
            'at': _dt.datetime.now().isoformat(timespec='seconds'),
        }, ensure_ascii=False, indent=1), encoding='utf8')
    stage_qa()
def stage_qa():
    load_runtime()
    v = P(f'out/{STATE.slug}_video.mp4')
    r = subprocess.run([_ffprobe(), '-v', 'error', '-show_entries', 'format=duration',
                        '-of', 'csv=p=0', str(v)], capture_output=True, text=True)
    dur = float(r.stdout.strip())
    assert abs(dur - STATE.tl[-1]['end']) < 1.0, f'video {dur:.2f}s != timeline {STATE.tl[-1]["end"]:.2f}s'
    dec = subprocess.run([_ffmpeg(), '-v', 'error', '-i', str(v), '-f', 'null', '-'],
                         capture_output=True, text=True)
    assert not dec.stderr.strip(), dec.stderr[:300]
    lufs, _ = yloud.measure_ebur128(v, ffmpeg=_ffmpeg())
    blk = [(a, a + d) for a, d in yqa.black_spans(v, ffmpeg=_ffmpeg())]
    lt = f'{lufs:.1f}' if lufs is not None else 'N/A'
    print(f'QA {STATE.slug}: {dur:.1f}s decode ok  {lt} LUFS  black segments {blk}')
    # contact sheet: first sentence of every chapter + the last-but-one sentence
    pts = []
    for c in STATE.tl:
        ss = [x for x in STATE.segs if x['scene'] == c['id']]
        pts += [ss[0]['start'] + 1.0, ss[len(ss) // 2]['start'] + 1.0, ss[-1]['start'] + 1.0]
    d = P(f'out/{STATE.slug}_review')
    d.mkdir(exist_ok=True, parents=True)
    for k, t in enumerate(pts):
        subprocess.run([_ffmpeg(), '-v', 'error', '-y', '-ss', f'{t:.2f}', '-i', str(v),
                        '-frames:v', '1', '-vf', 'scale=640:-1', str(d / f'f{k:02d}.png')])
    cols, rows, per = 3, math.ceil(len(pts) / 3), 12
    for s in range(0, len(pts), per):
        sub = list(range(s, min(s + per, len(pts))))
        sheet = Image.new('RGB', (1920, 360 * math.ceil(len(sub) / 3)))
        for q, k in enumerate(sub):
            sheet.paste(Image.open(d / f'f{k:02d}.png'), ((q % 3) * 640, (q // 3) * 360))
        sheet.save(d / f'sheet_{s // per}.png')
    print('contact sheets in', d)
    # 任意: ffmpeg-skill の外部検査を足す（既定はオフ。既存の QA 結果を上書きしない）
    #   VP_FFMPEG_SKILL_QA=1 python scripts/vp.py <slug> qa
    if os.environ.get('VP_FFMPEG_SKILL_QA') == '1':
        try:
            import ffmpeg_skill_check
            rc = ffmpeg_skill_check.main([str(v), '--platform', 'youtube', '--content'])
            print('ffmpeg-skill QA:', 'FAIL あり' if rc else 'FAIL なし')
        except Exception as e:
            print('ffmpeg-skill QA を実行できませんでした:', type(e).__name__, str(e)[:160])


def chapter_list():
    tl = json.loads(P(f'data/{STATE.slug}_timeline.json').read_text(encoding='utf8'))
    ts = lambda s: f'{int(s) // 60}:{int(s) % 60:02d}'
    chapters = [f'{ts(c["start"])} '
                f'{STATE.spec["chapters"][i].get("chapter_title", STATE.spec["chapters"][i].get("title", c["key"]))}'
                for i, c in enumerate(tl)]
    return chapters, tl[-1]['end']
class _Maou(dict):
    _JP=BGM_NAMES
    def __missing__(s,k):
        m=re.match(r'([a-z]+)(\d+)$',k);return s._JP.get(m.group(1),m.group(1))+m.group(2)
MAOU=_Maou()
def stage_desc():
    ds = STATE.spec['desc']
    chapters, dur = chapter_list()
    used = sorted({it['name'] for ch in STATE.spec['chapters'] for it in ch['scene'] if it['t'] == 'image'})
    imglines = [f"・{STATE.spec['images'][n]['credit']}:{STATE.spec['images'][n]['source_url']}"
                for n in used if STATE.spec['images'][n].get('credit')]
    tracks = ' / '.join(MAOU[x] for x in dict.fromkeys(b[2] for b in STATE.spec['bgm']))

    L = [f'# YouTube 投稿用ドラフト：{ds["title_main"]}\n', '## タイトル案']
    L += [f'{i + 1}. {t}' for i, t in enumerate(ds['titles'])]
    L += ['', '## 概要欄(そのまま貼り付け用)\n', '```', ds['intro'], '', '■ チャプター']
    L += chapters
    L += ['', '■ 動画で確かめたこと(要点)']
    L += [f'・{p}' for p in ds['points']]
    L += ['', '■ 参考資料(確認に使ったもの)']
    L += [f'・{r}' for r in ds['refs']]
    L += ['', '■ 出典・クレジット']
    L += ds.get('credit_lines', [])
    L += imglines
    L += [VOICE['credit_long'], BGM['credit_long'].format(tracks=tracks), '・図・表・年表:自作', '', '■ 注意']
    L += [f'・{n}' for n in ds['notes']]
    L += ['・詳しい出典と素材のクレジットは、この概要欄にまとめています。',
          '', '■ このチャンネルについて', CH['about'], '```\n',
          '## タグ案', ds['tags'] + '\n', '## 投稿前チェック(自分で確認が必要)']
    L += [f'- [ ] {c}' for c in ds.get('checks', [])]
    L += [
        '- [ ] YouTubeの設問(AIの使用):完成動画の表現を公式基準と照合し、Studioの「AIの使用」を設定(サムネイル背景の生成画像・合成音声(VOICEVOX)を含めて、本物の人物・出来事と誤認させる表現がないか確認)',
        '- [ ] **動画を通しで見る・聞く**(動き、ナレーションの読み、BGMの音量、画像の切り出しと説明の整合)',
        '- [ ] 概要欄の外部リンクに必要な機能利用資格をStudioで確認し、公開後にリンクが開けるか確認する',
        f'- [ ] {CH["terms_check"]}',
        f'- [ ] 字幕:`out/{STATE.slug}_subtitles.srt` をアップロード(日本語)',
        '- [ ] サムネイルを設定し、投稿後の表示(スマートフォンの小さな表示)を確認',
        '',
    ]
    P(f'out/{STATE.slug}_description.md').write_text('\n'.join(L) + '\n', encoding='utf8')
    print('\n'.join(chapters), '\nduration', f'{int(dur // 60)}分{int(dur % 60)}秒')
def stage_thumb():
    th = STATE.spec['thumb']
    W, H = 1280, 720
    FDW = FONTS['dir']

    def font(n):
        if n >= 100:
            f = ImageFont.truetype(FDW + FONTS['serif'], n)
            f.set_variation_by_axes([900])
            return f
        f = ImageFont.truetype(FDW + FONTS['sans'], n)
        f.set_variation_by_axes([800])
        return f

    def st(d, xy, text, f, fill, sw=10):
        d.text(xy, text, font=f, fill=fill, stroke_width=sw, stroke_fill=(6, 10, 18))

    if th.get('bg'):
        im = Image.open(P(th['bg'])).convert('RGBA')
        s = max(W / im.width, H / im.height)
        im = im.resize((int(im.width * s) + 1, int(im.height * s) + 1), Image.LANCZOS)
        x, y = (im.width - W) // 2, (im.height - H) // 2
        im = im.crop((x, y, x + W, y + H))
        sh = Image.new('RGBA', (W, H), tuple(th.get('shade_col', (4, 10, 20))) + (255,))
        g = Image.new('L', (W, 1))
        px = g.load()
        for xx in range(W):
            px[xx, 0] = int(235 * max(0, min(1, (th.get('shade_x', 760) - xx) / th.get('shade_w', 560))))
        sh.putalpha(g.resize((W, H)))
        im.alpha_composite(sh)
    else:
        im = Image.new('RGBA', (W, H), NAVY + (255,))
        meta = STATE.spec['images'][th['image']]
        pic = Image.open(P(meta['file'])).convert('RGB')
        c = th.get('crop') or meta.get('crop')
        if c:
            pic = pic.crop((int(pic.width * c[0]), int(pic.height * c[1]),
                            int(pic.width * c[2]), int(pic.height * c[3])))
        pw, ph = th.get('pic_w', 560), H - 80
        s = max(pw / pic.width, ph / pic.height)
        pic = pic.resize((int(pic.width * s) + 1, int(pic.height * s) + 1), Image.LANCZOS)
        x, y = (pic.width - pw) // 2, (pic.height - ph) // 2
        pic = pic.crop((x, y, x + pw, y + ph))
        if th.get('sepia', True):
            from PIL import ImageEnhance, ImageOps
            pic = ImageOps.colorize(ImageEnhance.Contrast(pic).enhance(1.15).convert('L'),
                                    (18, 14, 10), (238, 226, 196)).convert('RGB')
        im.alpha_composite(pic.convert('RGBA'), (W - pw - 40, 40))
        ImageDraw.Draw(im).rectangle((W - pw - 40, 40, W - 40, H - 40), outline=GOLD, width=6)
    d = ImageDraw.Draw(im)
    y = th.get('y0', 30)
    for text, size, col in th['lines']:
        st(d, (50, y), text, font(size),
           WHITE if col == 'white' else tuple(th.get('accent', GOLD)),
           12 if size >= 100 else 8)
        y += int(size * 1.2)
    by = th.get('bar_y', 520)
    d.rectangle((54, by, th.get('bar_w', 640), by + 12), fill=tuple(th.get('bar_col', RED)))
    st(d, (50, by + 35), th['sub'], font(th.get('sub_size', 38)), WHITE, 6)
    out = P(f'out/{STATE.slug}_thumbnail.jpg')
    im.convert('RGB').save(out, quality=92)
    print(out, round(out.stat().st_size / 1e3), 'KB')


def stage_pack():
    import make_upload_pack as M
    vid = P(f'out/{STATE.slug}_video.mp4')
    srt = P(f'out/{STATE.slug}_subtitles.srt')
    assert vid.stat().st_mtime >= srt.stat().st_mtime - 1, \
        f'{vid.name} is older than the subtitles (stale build?) - rebuild before pack'
    name = STATE.spec['pack']
    M.build(name, dict(video=f'out/{STATE.slug}_video.mp4', thumb=f'out/{STATE.slug}_thumbnail.jpg',
                       srt=f'out/{STATE.slug}_subtitles.srt', desc=f'out/{STATE.slug}_description.md',
                       title_no=STATE.spec['desc'].get('title_no', 1)))
# ---------------------------------------------------------------- CLI
def _cmd_part(args):
    load_runtime()
    render_part(int(args[0]), int(args[1]))


def _cmd_still(args):
    load_runtime()
    d = P(f'out/{STATE.slug}_review')
    d.mkdir(parents=True, exist_ok=True)
    for a in args:
        render_frame(int(float(a) * 30)).convert('RGB').save(d / f'still_{a}.png')
    print('stills', args)


def _cmd_ends(args):
    load_runtime()
    for c in STATE.tl:
        ss = [x for x in STATE.segs if x['scene'] == c['id']]
        print(c['key'], [round(x['start'] + 0.8, 1) for x in ss])


def _cmd_lint(args):
    from ytcore import script_lint
    raise SystemExit(script_lint.run(STATE.as_dict()))


def _cmd_prep(args):
    """台本→読み→音声→BGM→検査まで一括（描画の前の準備。止まる所があれば、そこで止まる）。"""
    from ytcore import vp_check, script_lint
    stage_story()
    script_lint.run(STATE.as_dict())
    stage_kana()
    stage_audio()
    stage_bgm()
    raise SystemExit(vp_check.run(STATE.as_dict()))


def _cmd_preview(args):
    load_runtime()
    from ytcore import vp_preview
    raise SystemExit(vp_preview.run(STATE.as_dict()))


def _cmd_pvpart(args):
    load_runtime()
    from ytcore import vp_preview
    vp_preview.worker(STATE.as_dict(), args[0])


def _cmd_check(args):
    from ytcore import vp_check
    raise SystemExit(vp_check.run(STATE.as_dict()))


def _cmd_sents(args):
    for s in json.loads(P(f'data/{STATE.slug}_scenes.json').read_text(encoding='utf8')):
        print(f"--- {s['id']} {s['key']}")
        for i, x in enumerate(sentences(s)):
            print(f'  {i}: {x[:60]}')


def _cmd_refp(args):
    """既存の部品に、いまの指紋を付け直す（部品が、いまの spec・音声・描画コードで作られたと分かっているときだけ）。"""
    load_runtime()
    ch = int(os.environ.get('VP_CHUNK', 1000))
    cf = _code_fp()
    n_ = 0
    for a in range(0, STATE.n, ch):
        mp = P(f'cache/{STATE.slug}_part_{a}_{a+ch}.mp4')
        if mp.exists() and mp.stat().st_size > 0:
            P(f'cache/{STATE.slug}_part_{a}_{a+ch}.fp').write_text(_part_fp(a, min(a + ch, STATE.n), cf), encoding='utf8')
            n_ += 1
    print('re-stamped', n_, 'parts')


COMMANDS = {
    'part': _cmd_part,
    'story': lambda args: stage_story(),
    'still': _cmd_still,
    'ends': _cmd_ends,
    'lint': _cmd_lint,
    'prep': _cmd_prep,
    'preview': _cmd_preview,
    'pvpart': _cmd_pvpart,
    'check': _cmd_check,
    'sents': _cmd_sents,
    'kana': lambda args: stage_kana(),
    'audio': lambda args: stage_audio(),
    'bgm': lambda args: stage_bgm(),
    'refp': _cmd_refp,
    'build': lambda args: stage_build(),
    'qa': lambda args: stage_qa(),
    'desc': lambda args: stage_desc(),
    'thumb': lambda args: stage_thumb(),
    'pack': lambda args: stage_pack(),
}
LOCKED = ('build', 'audio', 'prep')
# コマンドが受け取る最低限の追加引数（slug と cmd の後ろ）。still は時刻を1つ以上。
MIN_ARGS = {'part': 2, 'still': 1, 'pvpart': 1}
USAGE = 'usage: python scripts/vp.py <slug> ' + '|'.join(COMMANDS)


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 2:
        raise SystemExit(USAGE)
    slug, cmd = args[0], args[1]
    if cmd not in COMMANDS:
        raise SystemExit(f'unknown command: {cmd}\n{USAGE}')
    extra = args[2:]
    if len(extra) < MIN_ARGS.get(cmd, 0):
        raise SystemExit(f'{cmd} に引数が足りません\n{USAGE}')
    load_spec(slug)
    if cmd in LOCKED:
        from ytcore import vp_lock
        vp_lock.acquire(ROOT, slug, cmd)   # 二重起動を防ぐ
    return COMMANDS[cmd](extra)


if __name__ == '__main__':
    main()
