"""記録から、公開するサイト(public/)を丸ごと作る。文章はすべてデータから組み立てる。"""
from __future__ import annotations

import datetime as dt
import json
import shutil
import urllib.parse
from html import escape as e
from pathlib import Path

from . import core
from .core import yen

LEVEL_CLASS = {3: "best", 2: "good", 1: "flat", 0: "high", -1: "wait"}


# ---------- 小さな道具 ----------

def md(date: str) -> str:
    d = dt.date.fromisoformat(date[:10])
    return f"{d.month}月{d.day}日"


def stamp(iso: str) -> str:
    if not iso:
        return ""
    t = dt.datetime.fromisoformat(iso)
    return f"{t.month}月{t.day}日 {t.hour}時{t.minute:02d}分"


def pct(x: float) -> str:
    return f"{abs(x) * 100:.0f}%"


def diff_text(a: dict) -> str:
    """ふだんの価格(30日の中央値)とくらべた一言。"""
    if "vs_med" not in a or a["days"] < core.MIN_DAYS_FOR_VERDICT:
        return "計測中"
    v = a["vs_med"]
    if abs(v) < 0.005:
        return "ふだんと同じ"
    return f"ふだんより{pct(v)}{'安い' if v < 0 else '高い'}"


def chg_text(a: dict) -> str:
    c = a.get("chg1")
    if c is None:
        return "—"
    if c == 0:
        return "変わらず"
    return f"{'▼' if c < 0 else '▲'}{abs(c):,}円"


def badge(a: dict) -> str:
    return f'<span class="badge {LEVEL_CLASS[a["level"]]}">{e(a["label"])}</span>'


def thumb(row: dict, cls: str = "thumb") -> str:
    offers = row["hist"].get("offers") or []
    img = offers[0].get("img") if offers else ""
    if img:
        return f'<img class="{cls}" src="{e(img)}" alt="" loading="lazy" width="128" height="128">'
    return f'<span class="{cls} noimg" aria-hidden="true">{e(row["cat"]["name"][:2])}</span>'


# ---------- 値動きのグラフ(SVG。JavaScriptなし) ----------

def chart(days: list[dict], today: str, n: int) -> str:
    t = dt.date.fromisoformat(today)
    start = t - dt.timedelta(days=n - 1)
    pts = [(dt.date.fromisoformat(d["d"]), d["eff"]) for d in days if d["d"] >= start.isoformat()]
    if len(pts) < 2:
        return '<p class="muted">グラフは、記録が2日分たまると表示されます。</p>'
    W, H, L, R, T, Bm = 720, 260, 64, 16, 16, 30
    first = pts[0][0]
    span = max((t - first).days, 1)
    lo, hi = min(v for _, v in pts), max(v for _, v in pts)
    pad = max((hi - lo) * 0.15, hi * 0.01, 1)
    y0, y1 = lo - pad, hi + pad

    def X(d):
        return L + (W - L - R) * (d - first).days / span

    def Y(v):
        return T + (H - T - Bm) * (1 - (v - y0) / (y1 - y0))

    line = " ".join(f"{X(d):.1f},{Y(v):.1f}" for d, v in pts)
    area = f"{X(pts[0][0]):.1f},{H - Bm} {line} {X(pts[-1][0]):.1f},{H - Bm}"
    grid = ""
    for v in (lo, (lo + hi) / 2, hi) if hi > lo else (lo,):
        grid += (f'<line x1="{L}" x2="{W - R}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" class="grid"/>'
                 f'<text x="{L - 8}" y="{Y(v) + 4:.1f}" text-anchor="end" class="tick">{int(v):,}</text>')
    lo_d, lo_v = min(pts, key=lambda p: (p[1], -p[0].toordinal()))
    last_d, last_v = pts[-1]
    marks = (f'<circle cx="{X(lo_d):.1f}" cy="{Y(lo_v):.1f}" r="4.5" class="dot-min"/>'
             f'<circle cx="{X(last_d):.1f}" cy="{Y(last_v):.1f}" r="4.5" class="dot-now"/>')
    xl = (f'<text x="{L}" y="{H - 8}" class="tick">{md(first.isoformat())}</text>'
          f'<text x="{W - R}" y="{H - 8}" text-anchor="end" class="tick">{md(t.isoformat())}</text>')
    label = f"過去{span + 1}日の実質価格の推移。最安は{md(lo_d.isoformat())}の{lo_v:,}円、最新は{last_v:,}円。"
    return (f'<svg class="chart" viewBox="0 0 {W} {H}" role="img" aria-label="{e(label)}">'
            f'{grid}<polygon points="{area}" class="area"/><polyline points="{line}" class="line"/>{marks}{xl}</svg>'
            f'<p class="legend"><span class="k now"></span>最新 <span class="k min"></span>この期間の最安(円・実質価格)</p>')


# ---------- ページの枠 ----------

CSS = """
:root{--bg:#f6f7f9;--card:#fff;--ink:#16202b;--sub:#5b6775;--line:#e3e7ec;--brand:#0b6e63;--brand-ink:#fff;
--best:#0a7d4f;--best-bg:#e2f5ea;--good:#0b6e8a;--good-bg:#e1f1f6;--flat:#55606c;--flat-bg:#eceff2;
--high:#9a5b00;--high-bg:#fbefd6;--wait:#6b7280;--wait-bg:#eef0f3;--down:#0a7d4f;--up:#b3401f;--warn-bg:#fff4d6;--warn:#7a5200}
@media (prefers-color-scheme:dark){:root{--bg:#10151b;--card:#19212a;--ink:#e8edf2;--sub:#9aa7b5;--line:#2a343f;--brand:#39b8a6;--brand-ink:#06201c;
--best:#5fd39a;--best-bg:#12392a;--good:#6cc7e0;--good-bg:#113543;--flat:#aab4bf;--flat-bg:#252e38;
--high:#f0b65a;--high-bg:#3d2e12;--wait:#9aa3ae;--wait-bg:#232b34;--down:#5fd39a;--up:#f08a6a;--warn-bg:#3d2e12;--warn:#f0c878}}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.7 system-ui,-apple-system,"Hiragino Sans","Noto Sans JP","Yu Gothic UI",Meiryo,sans-serif}
a{color:var(--brand)}a:hover{text-decoration:none}
.wrap{max-width:1040px;margin:0 auto;padding:0 16px}
.pr{background:var(--flat-bg);color:var(--sub);font-size:12px;text-align:center;padding:4px 8px}
.sample{background:var(--warn-bg);color:var(--warn);font-weight:700;text-align:center;padding:8px;font-size:14px}
header.top{background:var(--card);border-bottom:1px solid var(--line)}
header.top .wrap{display:flex;align-items:center;gap:16px;flex-wrap:wrap;padding-top:12px;padding-bottom:12px}
.logo{font-weight:800;font-size:19px;color:var(--ink);text-decoration:none;display:flex;align-items:center;gap:8px}
.logo svg{width:26px;height:26px}
nav.cats{display:flex;gap:4px 14px;flex-wrap:wrap;font-size:14px}nav.cats a{color:var(--sub);text-decoration:none}nav.cats a:hover{color:var(--brand)}
main{padding:24px 0 48px}
h1{font-size:26px;line-height:1.35;margin:0 0 8px}h2{font-size:20px;margin:36px 0 12px}h3{font-size:16px;margin:0}
.lead{color:var(--sub);margin:0 0 4px}.muted{color:var(--sub);font-size:14px}
.crumb{font-size:13px;color:var(--sub);margin:0 0 12px}.crumb a{color:var(--sub)}
.badge{display:inline-block;font-size:13px;font-weight:700;padding:2px 10px;border-radius:999px;white-space:nowrap}
.best{color:var(--best);background:var(--best-bg)}.good{color:var(--good);background:var(--good-bg)}.flat{color:var(--flat);background:var(--flat-bg)}
.high{color:var(--high);background:var(--high-bg)}.wait{color:var(--wait);background:var(--wait-bg)}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(228px,1fr));gap:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px;display:flex;flex-direction:column;gap:6px;text-decoration:none;color:var(--ink)}
.card:hover{border-color:var(--brand)}
.card .head{display:flex;gap:10px;align-items:center}
.thumb{width:56px;height:56px;border-radius:8px;object-fit:contain;background:#fff;flex:none}
.noimg{display:flex;align-items:center;justify-content:center;background:var(--flat-bg);color:var(--sub);font-size:13px;font-weight:700}
.price{font-size:22px;font-weight:800;font-variant-numeric:tabular-nums;line-height:1.2}.price small{font-size:12px;font-weight:400;color:var(--sub)}
.down{color:var(--down)}.up{color:var(--up)}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden;font-size:15px}
th,td{padding:10px 12px;text-align:left;border-bottom:1px solid var(--line);vertical-align:middle}
th{font-size:12px;color:var(--sub);font-weight:600;background:var(--flat-bg)}tr:last-child td{border-bottom:0}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.scroll{overflow-x:auto}
.verdict{background:var(--card);border:1px solid var(--line);border-left:6px solid var(--flat);border-radius:12px;padding:16px 18px;margin:16px 0}
.verdict.best{border-left-color:var(--best);background:var(--card);color:inherit}.verdict.good{border-left-color:var(--good);background:var(--card);color:inherit}
.verdict.high{border-left-color:var(--high);background:var(--card);color:inherit}.verdict.wait{border-left-color:var(--wait);background:var(--card);color:inherit}
.verdict.flat{background:var(--card);color:inherit}
.verdict p{margin:6px 0 0}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:16px 0}
.stat{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px}
.stat b{display:block;font-size:20px;font-variant-numeric:tabular-nums;line-height:1.3}.stat span{font-size:12px;color:var(--sub)}
.panel{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px}
.chart{width:100%;height:auto;display:block}.chart .grid{stroke:var(--line);stroke-width:1}.chart .tick{fill:var(--sub);font-size:12px}
.chart .line{fill:none;stroke:var(--brand);stroke-width:2.5;stroke-linejoin:round;stroke-linecap:round}.chart .area{fill:var(--brand);opacity:.1}
.chart .dot-min{fill:var(--best);stroke:var(--card);stroke-width:2}.chart .dot-now{fill:var(--brand);stroke:var(--card);stroke-width:2}
.legend{font-size:12px;color:var(--sub);margin:6px 0 0}.legend .k{display:inline-block;width:10px;height:10px;border-radius:50%;margin:0 4px 0 10px}
.legend .now{background:var(--brand)}.legend .min{background:var(--best)}
.btn{display:inline-block;background:var(--brand);color:var(--brand-ink);font-weight:700;text-decoration:none;padding:8px 14px;border-radius:8px;white-space:nowrap;font-size:14px;border:0;cursor:pointer}
.btn.sub{background:transparent;color:var(--brand);border:1px solid var(--brand)}
.cta{display:flex;gap:10px;flex-wrap:wrap;margin:14px 0}
.note{font-size:13px;color:var(--sub);margin:8px 0}
textarea{width:100%;min-height:320px;font:14px/1.7 inherit;padding:12px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--ink)}
footer{border-top:1px solid var(--line);background:var(--card);padding:24px 0;font-size:13px;color:var(--sub)}footer a{color:var(--sub)}
@media (max-width:560px){h1{font-size:22px}th,td{padding:8px}.hide-s{display:none}}
"""

LOGO = ('<svg viewBox="0 0 32 32" aria-hidden="true"><path d="M4 22a12 12 0 0 1 24 0" fill="none" stroke="currentColor" '
        'stroke-width="4" stroke-linecap="round" opacity=".25"/><path d="M4 22a12 12 0 0 1 9-11.6" fill="none" stroke="#0a9d6b" '
        'stroke-width="4" stroke-linecap="round"/><path d="M16 22 22 12" stroke="currentColor" stroke-width="3" stroke-linecap="round"/>'
        '<circle cx="16" cy="22" r="3" fill="currentColor"/></svg>')
FAVICON = LOGO.replace("<svg ", '<svg xmlns="http://www.w3.org/2000/svg" ').replace("currentColor", "#16202b")


class Site:
    def __init__(self, cfg: dict, catalog: dict, rows: list[dict], today: str, sample: bool):
        self.cfg, self.catalog, self.rows, self.today, self.sample = cfg, catalog, rows, today, sample
        self.base_url = cfg["base_url"]
        self.B = urllib.parse.urlparse(self.base_url).path.rstrip("/") if self.base_url else ""
        self.fetched = max((r["hist"].get("fetched") or "" for r in rows), default="")
        self.pages: dict[str, str] = {}   # 出力先のパス -> HTML
        self.urls: list[str] = []         # サイトマップに載せるパス

    def u(self, path: str) -> str:
        return f"{self.B}{path}"

    def full(self, path: str) -> str:
        return f"{self.base_url}{path}" if self.base_url else self.u(path)

    def page(self, path: str, title: str, desc: str, body: str, *, index: bool = True, jsonld: list | None = None) -> None:
        cfg = self.cfg
        noindex = self.sample or not index
        nav = "".join(f'<a href="{self.u("/c/" + c["id"] + "/")}">{e(c["name"])}</a>' for c in self.catalog["categories"])
        ld = "".join(f'<script type="application/ld+json">{json.dumps(x, ensure_ascii=False)}</script>' for x in (jsonld or []))
        html = f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}</title>
<meta name="description" content="{e(desc)}">
{'<meta name="robots" content="noindex,nofollow">' if noindex else f'<link rel="canonical" href="{e(self.full(path))}">'}
<meta property="og:title" content="{e(title)}"><meta property="og:description" content="{e(desc)}">
<meta property="og:type" content="website"><meta property="og:site_name" content="{e(cfg['site_name'])}">
<meta name="twitter:card" content="summary">
<link rel="icon" href="{self.u('/favicon.svg')}" type="image/svg+xml">
<link rel="alternate" type="application/rss+xml" title="{e(cfg['site_name'])}" href="{self.u('/feed.xml')}">
<link rel="stylesheet" href="{self.u('/style.css')}">{ld}
</head><body>
{'<div class="sample">これは見本データです。価格・ショップはすべて作りもので、実際の価格ではありません。</div>' if self.sample else ''}
<div class="pr">当サイトはアフィリエイト広告を利用しています</div>
<header class="top"><div class="wrap"><a class="logo" href="{self.u('/')}">{LOGO}{e(cfg['site_name'])}</a><nav class="cats">{nav}</nav></div></header>
<main><div class="wrap">
{body}
</div></main>
<footer><div class="wrap">
<p>価格・ポイントは{e(stamp(self.fetched)) or '取得時'}時点の楽天市場の情報です。変わることがあるので、購入前に必ずショップのページでご確認ください。</p>
<p><a href="{self.u('/about/')}">このサイトについて・広告の表示・データの見方</a></p>
<p><a href="https://webservice.rakuten.co.jp/" target="_blank" rel="noopener">Supported by Rakuten Developers</a></p>
<p>© {e(cfg['operator'])}</p>
</div></footer>
</body></html>
"""
        self.pages[path.lstrip("/") + ("index.html" if path.endswith("/") else "")] = html
        if not noindex:
            self.urls.append(path)

    # ---------- 部品 ----------

    def card(self, r: dict) -> str:
        a = r["a"]
        return (f'<a class="card" href="{self.u("/p/" + r["p"]["id"] + "/")}"><div class="head">{thumb(r)}<h3>{e(r["p"]["name"])}</h3></div>'
                f'<div>{badge(a)}</div><div class="price">{a["eff"]:,}<small>円(実質)</small></div>'
                f'<div class="muted">{e(diff_text(a))}</div></a>')

    def table(self, rows: list[dict]) -> str:
        body = ""
        for r in rows:
            a = r["a"]
            link = f'<a href="{self.u("/p/" + r["p"]["id"] + "/")}">{e(r["p"]["name"])}</a>'
            if not a["ok"]:
                body += f'<tr><td>{link}</td><td>{badge(a)}</td><td class="num">—</td><td class="num hide-s">—</td><td class="hide-s">—</td></tr>'
                continue
            c = a.get("chg1") or 0
            cls = "down" if c < 0 else "up" if c > 0 else ""
            body += (f'<tr><td>{link}</td><td>{badge(a)}</td><td class="num"><b>{yen(a["eff"])}</b></td>'
                     f'<td class="num hide-s {cls}">{e(chg_text(a))}</td><td class="hide-s">{e(diff_text(a))}</td></tr>')
        return ('<div class="scroll"><table><thead><tr><th>商品</th><th>判定</th><th class="num">今日の実質価格</th>'
                f'<th class="num hide-s">前日から</th><th class="hide-s">ふだんとくらべて</th></tr></thead><tbody>{body}</tbody></table></div>')

    def stamp_line(self) -> str:
        return f'<p class="muted">{e(stamp(self.fetched))}時点 ・ 毎日自動で更新</p>' if self.fetched else ""

    # ---------- 各ページ ----------

    def buys(self) -> list[dict]:
        rs = [r for r in self.rows if r["a"]["level"] >= 2]
        return sorted(rs, key=lambda r: (-r["a"]["level"], r["a"].get("vs_med", 0)))

    def drops(self) -> list[dict]:
        rs = [r for r in self.rows if r["a"]["ok"] and not r["a"]["suspect"] and not r["a"]["stale"] and (r["a"].get("chg1") or 0) < 0]
        return sorted(rs, key=lambda r: r["a"]["chg1_pct"])

    def home(self) -> None:
        cfg = self.cfg
        buys, drops = self.buys(), self.drops()
        tracked = sum(1 for r in self.rows if r["a"]["ok"])
        body = f'<h1>{e(cfg["tagline"])}</h1><p class="lead">{e(cfg["description"])}</p>{self.stamp_line()}'
        body += f'<h2>いま買いどきの商品({len(buys)}件)</h2>'
        body += (f'<div class="cards">{"".join(self.card(r) for r in buys[:12])}</div>' if buys else
                 '<p class="muted">いまは、ふだんより目立って安い商品はありません。記録が7日分たまった商品から判定が出ます。</p>')
        if drops:
            body += '<h2>前日から値下がりした商品</h2>' + self.table(drops[:10])
        body += f'<h2>記録している商品({tracked}件)</h2>'
        for c in self.catalog["categories"]:
            rs = [r for r in self.rows if r["p"]["cat"] == c["id"]]
            if rs:
                body += f'<h3 style="margin:20px 0 8px"><a href="{self.u("/c/" + c["id"] + "/")}">{e(c["name"])}</a></h3>' + self.table(rs)
        body += ('<h2>「実質価格」とは</h2><p>楽天市場の価格から、その買い物でもらえるポイント(ショップごとのポイント倍率ぶん)を引いた金額です。'
                 'お買い物マラソンやSPUなど、人によって変わるポイントは含めていません。くわしくは'
                 f'<a href="{self.u("/about/")}">データの見方</a>をご覧ください。</p>')
        ld = [{"@context": "https://schema.org", "@type": "WebSite", "name": cfg["site_name"], "url": self.full("/")}]
        self.page("/", f'{cfg["site_name"]}|楽天の実質価格と値動きを毎日記録', cfg["description"], body, jsonld=ld)

    def category(self, c: dict) -> None:
        rs = [r for r in self.rows if r["p"]["cat"] == c["id"]]
        if not rs:
            return
        rs.sort(key=lambda r: (-r["a"]["level"], r["a"].get("vs_med", 0)))
        title = f'{c["name"]}の楽天実質価格と買いどき一覧'
        body = (f'<p class="crumb"><a href="{self.u("/")}">トップ</a> › {e(c["name"])}</p><h1>{e(title)}</h1>'
                f'<p class="lead">{e(c["name"])}の定番{len(rs)}商品について、楽天市場での実質価格と、ふだんの価格とくらべた今日の位置づけを並べています。</p>'
                f'{self.stamp_line()}<div style="margin-top:16px">{self.table(rs)}</div>')
        self.page(f'/c/{c["id"]}/', f'{title}|{self.cfg["site_name"]}',
                  f'{c["name"]}の定番{len(rs)}商品の楽天実質価格を毎日記録。いま買いどきの商品が分かります。', body,
                  jsonld=[self.crumbs([(c["name"], f'/c/{c["id"]}/')])])

    def crumbs(self, items: list[tuple[str, str]]) -> dict:
        els = [{"@type": "ListItem", "position": 1, "name": "トップ", "item": self.full("/")}]
        els += [{"@type": "ListItem", "position": i + 2, "name": n, "item": self.full(p)} for i, (n, p) in enumerate(items)]
        return {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": els}

    def product(self, r: dict) -> None:
        p, a, hist, c = r["p"], r["a"], r["hist"], r["cat"]
        path = f'/p/{p["id"]}/'
        name = p["name"]
        title = f'{name}の楽天最安値と価格推移'
        crumb = (f'<p class="crumb"><a href="{self.u("/")}">トップ</a> › <a href="{self.u("/c/" + c["id"] + "/")}">{e(c["name"])}</a> › {e(name)}</p>')
        body = f'{crumb}<h1>{e(title)}</h1>{self.stamp_line()}'
        ld = [self.crumbs([(c["name"], f'/c/{c["id"]}/'), (name, path)])]
        if not a["ok"]:
            body += f'<div class="verdict wait">{badge(a)}<p>{e(a["reason"])}</p></div>'
            self.page(path, f'{title}|{self.cfg["site_name"]}', f'{name}の楽天市場での実質価格を記録するページです。', body, index=False, jsonld=ld)
            return
        offers = hist.get("offers") or []
        body += f'<div class="verdict {LEVEL_CLASS[a["level"]]}">{badge(a)} <b>今日の実質最安 {yen(a["eff"])}</b><p>{e(a["reason"])}</p></div>'

        c1 = a.get("chg1")
        cls = "down" if (c1 or 0) < 0 else "up" if (c1 or 0) > 0 else ""
        stats = [f'<div class="stat"><span>今日の実質最安</span><b>{yen(a["eff"])}</b><span>表示価格 {yen(a["price"])}</span></div>',
                 f'<div class="stat"><span>前日から</span><b class="{cls}">{e(chg_text(a))}</b><span>{"前日 " + yen(a["prev_eff"]) if "prev_eff" in a else "前日の記録なし"}</span></div>']
        if "med30" in a:
            stats.append(f'<div class="stat"><span>ふだんの価格(30日の中央値)</span><b>{yen(a["med30"])}</b><span>{e(diff_text(a))}</span></div>')
        if "min90" in a:
            stats.append(f'<div class="stat"><span>記録中の最安(90日以内)</span><b>{yen(a["min90"])}</b><span>{md(a["min90_date"])}</span></div>')
            stats.append(f'<div class="stat"><span>記録中の最高(90日以内)</span><b>{yen(a["max90"])}</b><span>{md(a["max90_date"])}</span></div>')
        body += f'<div class="stats">{"".join(stats)}</div>'

        if offers and not a["stale"]:
            best = offers[0]
            cta = f'<a class="btn" href="{e(best["url"])}" target="_blank" rel="sponsored nofollow noopener">楽天の最安ショップを見る({yen(best["eff"])})</a>'
            if self.cfg.get("amazon_tag"):
                q = urllib.parse.urlencode({"k": p["q"], "tag": self.cfg["amazon_tag"]})
                cta += f'<a class="btn sub" href="https://www.amazon.co.jp/s?{q}" target="_blank" rel="sponsored nofollow noopener">Amazonで価格を見る</a>'
            body += f'<div class="cta">{cta}</div>'

        body += f'<h2>{e(name)}の価格推移(実質価格)</h2><div class="panel">{chart(hist["days"], self.today, self.cfg.get("chart_days", 90))}</div>'
        body += f'<p class="note">記録を始めた日: {md(a["first_date"])}(記録 {a["days"]}日分)。記録を始める前の価格は分かりません。</p>'

        if offers and not a["stale"]:
            rows = ""
            for o in offers:
                rows += (f'<tr><td>{e(o["shop"])}</td><td class="num">{yen(o["price"])}</td>'
                         f'<td class="num hide-s">{o["pt"]:,}pt({o["rate"]}倍)</td><td class="num"><b>{yen(o["eff"])}</b></td>'
                         f'<td class="hide-s">{"送料込み" if o["ship"] else "送料別"}</td>'
                         f'<td><a class="btn" href="{e(o["url"])}" target="_blank" rel="sponsored nofollow noopener">見る</a></td></tr>')
            body += (f'<h2>今日の楽天ショップ別の価格({len(offers)}店)</h2><div class="scroll"><table><thead><tr><th>ショップ</th>'
                     '<th class="num">表示価格</th><th class="num hide-s">ポイント</th><th class="num">実質価格</th><th class="hide-s">送料</th><th></th></tr></thead>'
                     f'<tbody>{rows}</tbody></table></div>'
                     '<p class="note">送料込みのショップを先に、実質価格の安い順に並べています。「送料別」のショップは、送料を足すと順位が変わることがあります。'
                     '色ちがい・セット品が混ざることがあるので、購入前にショップのページで商品をご確認ください。</p>')

        body += f'<h2>{e(name)}は、いま買いどき?</h2><p>{e(self.summary(name, a))}</p>'

        rel = [x for x in self.rows if x["p"]["cat"] == p["cat"] and x["p"]["id"] != p["id"] and x["a"]["ok"]][:6]
        if rel:
            body += f'<h2>{e(c["name"])}のほかの商品</h2><div class="cards">{"".join(self.card(x) for x in rel)}</div>'

        if not self.sample and offers and not a["stale"]:
            ld.append({"@context": "https://schema.org", "@type": "Product", "name": name,
                       "offers": {"@type": "AggregateOffer", "priceCurrency": "JPY", "lowPrice": min(o["price"] for o in offers),
                                  "highPrice": max(o["price"] for o in offers), "offerCount": len(offers)}})
        desc = f'{name}の楽天市場での実質最安値は{yen(a["eff"])}({md(a["date"])}時点)。{a["reason"]}毎日の値動きをグラフで確認できます。'
        self.page(path, f'{title}【{md(a["date"])}更新】|{self.cfg["site_name"]}', desc, body, jsonld=ld)

    def summary(self, name: str, a: dict) -> str:
        """データだけから作る、買いどきの説明文。"""
        s = f'{md(a["date"])}時点で、{name}の楽天市場での実質最安値は{yen(a["eff"])}です。'
        if a["days"] < core.MIN_DAYS_FOR_VERDICT or a["stale"] or a["suspect"]:
            return s + a["reason"]
        s += f'この30日のふだんの価格(中央値)は{yen(a["med30"])}で、今日は{diff_text(a)}水準です。'
        if "min90" in a:
            s += f'記録のある期間の最安は{md(a["min90_date"])}の{yen(a["min90"])}、最高は{md(a["max90_date"])}の{yen(a["max90"])}でした。'
        tail = {3: "過去の記録とくらべていちばん安い水準なので、ほしい人には買いやすいタイミングです。",
                2: "ふだんより安いので、買うつもりがあるなら悪くないタイミングです。",
                1: "ふだんどおりの価格です。急がないなら、ポイントが増える日やセールを待つ手もあります。",
                0: "ふだんより高めです。急がないなら、値段が戻るのを待つほうがよさそうです。"}
        return s + tail.get(a["level"], "")

    def about(self) -> None:
        cfg = self.cfg
        contact = f'<p>お問い合わせ: {e(cfg["contact"])}</p>' if cfg.get("contact") else ""
        body = f"""<p class="crumb"><a href="{self.u('/')}">トップ</a> › このサイトについて</p>
<h1>このサイトについて</h1>
<p>{e(cfg['description'])}</p>
<h2>広告の表示</h2>
<p>当サイトは、楽天アフィリエイトなどのアフィリエイトプログラムに参加しています。商品へのリンクから購入されると、運営者が紹介料を受け取ることがあります。紹介料の有無で、掲載する順番や判定を変えることはありません(並び順と判定は、下の決まりだけで機械的に決めています)。</p>
<h2>データの見方</h2>
<ul>
<li><b>実質価格</b>: 楽天市場の表示価格から、その商品でもらえるポイント(ショップが設定したポイント倍率ぶん。100円につき1ポイント×倍率)を引いた金額です。お買い物マラソン・SPU・クーポンなど、人や時期で変わるものは含めていません。</li>
<li><b>今日の実質最安</b>: 条件に合う出品のうち、送料込みで実質価格がいちばん安いものです(送料込みの出品がなければ、送料別のなかで最安のもの)。</li>
<li><b>ふだんの価格</b>: 直近30日の「その日の実質最安」の中央値です。</li>
<li><b>判定</b>: 「買いどき」=記録のある過去90日以内でいちばん安い({core.MIN_DAYS_FOR_BEST}日以上の記録がある場合)。「安め」=ふだんより5%以上安い。「高め」=ふだんより5%以上高い。「ふつう」=その間。「計測中」=記録が{core.MIN_DAYS_FOR_VERDICT}日未満。</li>
<li><b>記録の範囲</b>: このサイトが記録を始めた日より前の価格は分かりません。「最安」は、記録のある期間のなかでの最安です。</li>
</ul>
<h2>ご注意</h2>
<ul>
<li>価格・ポイント・在庫は、1日1回、楽天市場の公式データ(楽天ウェブサービス)から自動で取得しています。取得したあとに変わることがあるので、購入前に必ずショップのページでご確認ください。</li>
<li>商品の取りちがえを防ぐしくみを入れていますが、色ちがい・セット品・別の型番が混ざることがあります。</li>
<li>このサイトは商品の使用感をレビューするものではありません。価格の記録と比較だけを行っています。</li>
<li>当サイトの情報を利用して生じた損害について、運営者は責任を負いかねます。</li>
</ul>
<h2>プライバシー</h2>
<p>当サイト自体は、Cookieやアクセス解析で個人を特定する情報を集めていません。リンク先のサービス(楽天市場など)では、各社の方針に沿ってCookieが使われます。</p>
<h2>運営者</h2>
<p>{e(cfg['operator'])}</p>{contact}"""
        self.page("/about/", f'このサイトについて|{cfg["site_name"]}', f'{cfg["site_name"]}の運営者・広告の表示・データの見方について。', body)

    def memo(self) -> None:
        """note・X にそのまま貼れる下書き(検索には出さないページ)。"""
        buys = self.buys()[:8]
        week = sorted((r for r in self.rows if r["a"].get("chg7", 0) < 0 and not r["a"]["suspect"] and not r["a"]["stale"]),
                      key=lambda r: r["a"]["chg7_pct"])[:8]
        t = dt.date.fromisoformat(self.today)
        lines = [f"【{t.month}/{t.day}版】いま買いどきのガジェットまとめ(楽天の実質価格)", "",
                 "楽天市場でのガジェットの「実質価格」(表示価格からポイント還元を引いた金額)を、毎日自動で記録しています。",
                 "そのなかから、ふだんより安くなっている商品をまとめました。", "",
                 f"※価格は{stamp(self.fetched)}時点。変わることがあるので、購入前にリンク先でご確認ください。",
                 "※リンク先のサイトはアフィリエイト広告を利用しています。", ""]
        if buys:
            lines += ["■ いま買いどきの商品", ""]
            for i, r in enumerate(buys, 1):
                a = r["a"]
                lines += [f"{i}. {r['p']['name']}", f"実質 {yen(a['eff'])}({diff_text(a)}・{a['label']})",
                          f"値動きのグラフ → {self.full('/p/' + r['p']['id'] + '/')}", ""]
        if week:
            lines += ["■ この1週間で値下がりした商品", ""]
            for r in week:
                a = r["a"]
                lines += [f"・{r['p']['name']}: 実質 {yen(a['eff'])}(1週間前より{abs(a['chg7']):,}円安い)",
                          f"  {self.full('/p/' + r['p']['id'] + '/')}"]
            lines.append("")
        if not buys and not week:
            lines += ["今週は、目立って安くなった商品はありませんでした。", ""]
        lines += ["ほかの商品の値動きは、こちらで毎日更新しています。", self.full("/")]
        note = "\n".join(lines)
        xs = []
        for r in buys[:3]:
            a = r["a"]
            xs.append(f"【{a['label']}】{r['p']['name']}\n楽天の実質価格 {yen(a['eff'])}({diff_text(a)})\n値動きのグラフ→ {self.full('/p/' + r['p']['id'] + '/')}\n#PR #楽天市場")
        xtext = "\n\n――――――\n\n".join(xs) or "今日は投稿できる商品がありません。"
        body = f"""<h1>note・X用の下書き</h1>
<p class="lead">今日のデータから自動で作った下書きです。「コピー」を押して、noteやXに貼り付けてください。このページは検索には出ません。</p>
<h2>note用(週1回くらい)</h2><textarea id="n" readonly>{e(note)}</textarea>
<p><button class="btn" onclick="cp('n',this)">noteの下書きをコピー</button></p>
<h2>X用(1件ずつ区切って使う)</h2><textarea id="x" readonly style="min-height:200px">{e(xtext)}</textarea>
<p><button class="btn" onclick="cp('x',this)">Xの下書きをコピー</button></p>
<script>function cp(id,b){{var t=document.getElementById(id);t.select();navigator.clipboard.writeText(t.value).then(function(){{b.textContent='コピーしました'}})}}</script>"""
        self.page("/memo/", f'下書き|{self.cfg["site_name"]}', "note・X用の下書き", body, index=False)

    def extras(self) -> dict[str, str]:
        out = {"style.css": CSS.strip() + "\n", "favicon.svg": FAVICON, ".nojekyll": ""}
        robots = "User-agent: *\n" + ("Disallow: /\n" if self.sample else "Disallow: /memo/\n")
        if self.base_url and not self.sample:
            robots += f"Sitemap: {self.base_url}/sitemap.xml\n"
            sm = "".join(f"<url><loc>{e(self.full(p))}</loc><lastmod>{self.today}</lastmod></url>" for p in self.urls)
            out["sitemap.xml"] = f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{sm}</urlset>\n'
        out["robots.txt"] = robots
        items = ""
        for r in self.buys()[:20]:
            a, link = r["a"], self.full("/p/" + r["p"]["id"] + "/")
            items += (f"<item><title>{e('【' + a['label'] + '】' + r['p']['name'] + ' 実質' + yen(a['eff']))}</title><link>{e(link)}</link>"
                      f"<guid isPermaLink=\"false\">{e(r['p']['id'] + '-' + a['date'])}</guid><description>{e(a['reason'])}</description></item>")
        out["feed.xml"] = (f'<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>{e(self.cfg["site_name"])}</title>'
                           f'<link>{e(self.full("/"))}</link><description>{e(self.cfg["tagline"])}</description>{items}</channel></rss>\n')
        return out


def build(cfg: dict, catalog: dict, data_dir: Path, out_dir: Path, today: str, sample: bool = False) -> int:
    cats = {c["id"]: c for c in catalog["categories"]}
    rows = []
    for p in catalog["products"]:
        hist = core.load_hist(data_dir, p["id"])
        rows.append({"p": p, "hist": hist, "a": core.analyze(hist, today), "cat": cats[p["cat"]]})
    s = Site(cfg, catalog, rows, today, sample)
    s.home()
    for c in catalog["categories"]:
        s.category(c)
    for r in rows:
        s.product(r)
    s.about()
    s.memo()
    s.page("/404.html", f'ページが見つかりません|{cfg["site_name"]}', "ページが見つかりません",
           f'<h1>ページが見つかりません</h1><p><a href="{s.u("/")}">トップへ戻る</a></p>', index=False)
    files = dict(s.pages)
    files.update(s.extras())
    if out_dir.exists():
        shutil.rmtree(out_dir)
    for rel, text in files.items():
        dest = out_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8", newline="\n")
    return len(s.pages)
