"""共通の土台: 設定の読みこみ・商品の絞りこみ・価格の記録・買いどきの判定。標準ライブラリだけで動く。"""
from __future__ import annotations

import datetime as dt
import json
import os
import statistics
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JST = dt.timezone(dt.timedelta(hours=9))

# 判定のしきい値(ここを変えれば、サイト全体の判定が変わる)
MIN_DAYS_FOR_VERDICT = 7      # これ未満の日数しか記録がなければ「計測中」
MIN_DAYS_FOR_BEST = 14        # 「過去最安」と言うのに必要な日数
STALE_DAYS = 3                # 最後の記録がこれより古ければ「更新待ち」
SUSPECT_DROP = -0.45          # 前日比がこれより大きく下がったら、取りちがえを疑ってランキングから外す
CHEAP_VS_MEDIAN = -0.05       # 30日の中央値より5%以上安ければ「安め」
HIGH_VS_MEDIAN = 0.05         # 5%以上高ければ「高め」


def now_jst() -> dt.datetime:
    return dt.datetime.now(JST)


def today_jst() -> str:
    return now_jst().date().isoformat()


def load_json(path: Path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def save_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(tmp, path)


def load_env_file() -> None:
    """.env があれば読みこむ(すでに設定されている値は上書きしない)。"""
    p = ROOT / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def load_config() -> tuple[dict, dict]:
    site = load_json(ROOT / "config" / "site.json")
    catalog = load_json(ROOT / "config" / "products.json")
    if site is None or catalog is None:
        raise SystemExit("config/site.json か config/products.json が見つかりません。")
    if os.environ.get("SITE_BASE_URL"):
        site["base_url"] = os.environ["SITE_BASE_URL"]
    if os.environ.get("AMAZON_TAG"):
        site["amazon_tag"] = os.environ["AMAZON_TAG"]
    site["base_url"] = (site.get("base_url") or "").rstrip("/")
    cats = {c["id"] for c in catalog["categories"]}
    seen = set()
    for p in catalog["products"]:
        for key in ("id", "name", "cat", "q", "must", "typical"):
            if key not in p:
                raise SystemExit(f"products.json: {p.get('id', '?')} に {key} がありません。")
        if p["id"] in seen:
            raise SystemExit(f"products.json: id が重複しています: {p['id']}")
        if p["cat"] not in cats:
            raise SystemExit(f"products.json: {p['id']} のカテゴリ {p['cat']} がありません。")
        seen.add(p["id"])
    return site, catalog


# ---------- 商品の絞りこみ ----------

_DROP = dict.fromkeys(map(ord, " 　-‐‑–—−_/・"), None)


def norm(s: str) -> str:
    """全角半角・大文字小文字・空白・ハイフンのちがいを消して比べやすくする。"""
    return unicodedata.normalize("NFKC", s or "").lower().translate(_DROP)


def name_matches(name: str, must: list[str], ng: list[str]) -> bool:
    n = norm(name)
    for token in must:
        if not any(norm(alt) in n for alt in token.split("|")):
            return False
    return not any(norm(w) in n for w in ng if w)


def effective(price: int, rate) -> tuple[int, int]:
    """実質価格 = 価格 - もらえるポイント。ポイントは100円につき rate ポイント(最低1倍)。"""
    try:
        rate = max(int(rate or 1), 1)
    except (TypeError, ValueError):
        rate = 1
    pt = price * rate // 100
    return price - pt, pt


def price_band(product: dict, hist: dict | None) -> tuple[int, int]:
    """この商品として受け入れる価格の幅。実データが7日以上あれば、その中央値に合わせる。"""
    days = (hist or {}).get("days") or []
    recent = [d["price"] for d in days[-30:]]
    if len(recent) >= MIN_DAYS_FOR_VERDICT:
        mid = statistics.median(recent)
        return int(mid * 0.5), int(mid * 2.0)
    return int(product["typical"] * 0.45), int(product["typical"] * 2.2)


def _first_image(item: dict) -> str:
    imgs = item.get("mediumImageUrls") or []
    if not imgs:
        return ""
    first = imgs[0]
    url = first.get("imageUrl", "") if isinstance(first, dict) else str(first)
    return url.replace("http://", "https://")


def pick_offers(product: dict, items: list[dict], ng_words: list[str], band: tuple[int, int]) -> list[dict]:
    """APIの検索結果から、この商品の出品だけを残し、ショップごとに一番安いものを実質価格の安い順に返す。"""
    lo, hi = band
    ng = list(ng_words) + list(product.get("ng") or [])
    by_shop: dict[str, dict] = {}
    for it in items:
        it = it.get("Item", it)  # formatVersion 1 と 2 の両方に対応
        try:
            price = int(it["itemPrice"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (lo <= price <= hi):
            continue
        if int(it.get("availability", 1) or 0) != 1:
            continue
        name = it.get("itemName", "")
        if not name_matches(name, product["must"], ng):
            continue
        eff, pt = effective(price, it.get("pointRate"))
        offer = {
            "shop": it.get("shopName", ""),
            "name": name[:120],
            "price": price,
            "rate": max(int(it.get("pointRate") or 1), 1),
            "pt": pt,
            "eff": eff,
            "ship": int(it.get("postageFlag", 1) or 0) == 0,  # True = 送料込み
            "url": it.get("affiliateUrl") or it.get("itemUrl") or "",
            "img": _first_image(it),
        }
        key = it.get("shopCode") or offer["shop"]
        if key not in by_shop or _rank(offer) < _rank(by_shop[key]):
            by_shop[key] = offer
    return sorted(by_shop.values(), key=_rank)


def _rank(o: dict):
    return (0 if o["ship"] else 1, o["eff"], o["price"])


# ---------- 記録 ----------

def hist_path(data_dir: Path, pid: str) -> Path:
    return data_dir / "history" / f"{pid}.json"


def load_hist(data_dir: Path, pid: str) -> dict:
    return load_json(hist_path(data_dir, pid), None) or {"id": pid, "days": [], "offers": [], "fetched": ""}


def record_day(hist: dict, date: str, offers: list[dict], fetched_iso: str) -> None:
    """その日の一番安い出品を1行として記録する(同じ日に2回動いたら上書き)。"""
    best = offers[0]
    row = {"d": date, "eff": best["eff"], "price": best["price"], "pt": best["pt"],
           "rate": best["rate"], "ship": best["ship"], "shop": best["shop"], "n": len(offers)}
    hist["days"] = [d for d in hist["days"] if d["d"] != date] + [row]
    hist["days"].sort(key=lambda d: d["d"])
    hist["offers"] = offers[:6]
    hist["fetched"] = fetched_iso


# ---------- 判定 ----------

def _window(days: list[dict], today: dt.date, n: int) -> list[dict]:
    start = (today - dt.timedelta(days=n - 1)).isoformat()
    return [d for d in days if d["d"] >= start]


def analyze(hist: dict, today: str) -> dict:
    """記録から、今日の位置づけ(買いどきか)を出す。"""
    days = hist.get("days") or []
    out = {"days": len(days), "ok": False, "level": -1, "label": "データなし",
           "reason": "まだ価格を記録できていません。", "suspect": False, "stale": False}
    if not days:
        return out
    t = dt.date.fromisoformat(today)
    last = days[-1]
    age = (t - dt.date.fromisoformat(last["d"])).days
    w30, w90 = _window(days, t, 30), _window(days, t, 90)
    out.update({
        "ok": True, "last": last, "eff": last["eff"], "price": last["price"], "date": last["d"],
        "first_date": days[0]["d"],
    })
    if age > STALE_DAYS:
        out.update({"stale": True, "label": "更新待ち",
                    "reason": f"最後に価格を確認できたのは{_md(last['d'])}です。在庫切れの可能性があります。"})
        return out

    prev = days[-2] if len(days) >= 2 else None
    if prev:
        out["prev_eff"] = prev["eff"]
        out["chg1"] = last["eff"] - prev["eff"]
        out["chg1_pct"] = (last["eff"] - prev["eff"]) / prev["eff"] if prev["eff"] else 0.0
        if out["chg1_pct"] <= SUSPECT_DROP:
            out["suspect"] = True
    week_ago = [d for d in days if d["d"] <= (t - dt.timedelta(days=7)).isoformat()]
    if week_ago:
        base = week_ago[-1]["eff"]
        out["chg7"] = last["eff"] - base
        out["chg7_pct"] = (last["eff"] - base) / base if base else 0.0

    if w30:
        out["med30"] = int(statistics.median(d["eff"] for d in w30))
        out["min30"] = min(d["eff"] for d in w30)
        out["vs_med"] = (last["eff"] - out["med30"]) / out["med30"] if out["med30"] else 0.0
    if w90:
        lo = min(w90, key=lambda d: (d["eff"], d["d"]))
        hi = max(w90, key=lambda d: (d["eff"], d["d"]))
        out.update({"min90": lo["eff"], "min90_date": lo["d"], "max90": hi["eff"], "max90_date": hi["d"]})

    n = len(days)
    span = min(n, 90)
    if out["suspect"]:
        out.update({"level": -1, "label": "確認中",
                    "reason": "前日から大きく下がっています。別の商品を拾った可能性があるため、判定を保留しています。"})
    elif n < MIN_DAYS_FOR_VERDICT:
        out.update({"level": -1, "label": "計測中",
                    "reason": f"記録を始めて{n}日目です。{MIN_DAYS_FOR_VERDICT}日分たまると判定が出ます。"})
    elif n >= MIN_DAYS_FOR_BEST and last["eff"] <= out["min90"]:
        out.update({"level": 3, "label": "買いどき",
                    "reason": f"記録のある過去{span}日でいちばん安い水準です。"})
    elif out["vs_med"] <= CHEAP_VS_MEDIAN:
        out.update({"level": 2, "label": "安め",
                    "reason": f"この30日のふだんの価格(中央値)より{abs(out['vs_med']) * 100:.0f}%安くなっています。"})
    elif out["vs_med"] >= HIGH_VS_MEDIAN:
        out.update({"level": 0, "label": "高め",
                    "reason": f"この30日のふだんの価格(中央値)より{out['vs_med'] * 100:.0f}%高くなっています。急がないなら待つのも手です。"})
    else:
        out.update({"level": 1, "label": "ふつう",
                    "reason": "この30日のふだんの価格とほぼ同じです。"})
    return out


def _md(date: str) -> str:
    d = dt.date.fromisoformat(date)
    return f"{d.month}月{d.day}日"


def yen(n) -> str:
    return f"{int(n):,}円"
