"""見本データを作る(楽天の鍵がなくても、サイトの見た目と判定を確かめられるようにするため)。

ここで作る価格・ショップは、すべて作りもの。本番の data/ には書かない。
"""
from __future__ import annotations

import datetime as dt
import random
from pathlib import Path

from . import core

SHOPS = ["見本ショップA", "見本ショップB", "見本ショップC", "見本ショップD", "見本ショップE"]


def generate(data_dir: Path, catalog: dict, today: str, days: int = 120, seed: int = 7) -> int:
    rng = random.Random(seed)
    t = dt.date.fromisoformat(today)
    for i, p in enumerate(catalog["products"]):
        hist = {"id": p["id"], "days": [], "offers": [], "fetched": ""}
        base = p["typical"] * rng.uniform(0.92, 1.05)
        level = base
        n_days = days if i % 6 != 5 else 5  # 一部は「計測中」になるよう、記録を短くする
        offers: list[dict] = []
        for k in range(n_days - 1, -1, -1):
            d = t - dt.timedelta(days=k)
            level += (base - level) * 0.08 + base * rng.gauss(0, 0.006)
            price = level
            rate = 1
            if d.day in (5, 10, 15, 20, 25, 30):      # 5と0のつく日: ポイントが増える
                rate = rng.choice([2, 5, 5, 10])
            if d.day in (1, 2, 3, 4) and d.month % 3 == 0:  # たまに大きなセール
                price *= rng.uniform(0.86, 0.93)
                rate = rng.choice([5, 10])
            if k == 0 and i % 4 == 0:                  # 今日、値下がりしている商品を混ぜる
                price *= 0.84
                rate = 10
            if k == 0 and i % 7 == 3:                  # 今日、高くなっている商品も混ぜる
                price *= 1.09
            price = int(round(price / 10) * 10)
            offers = []
            for j, shop in enumerate(SHOPS[: rng.randint(2, 5)]):
                pr = int(round(price * (1 + 0.012 * j + (rng.uniform(0, 0.01) if j else 0)) / 10) * 10)
                rt = rate if j == 0 else rng.choice([1, 1, 2, rate])
                eff, pt = core.effective(pr, rt)
                offers.append({"shop": shop, "name": p["name"] + " (見本データ)", "price": pr, "rate": rt,
                               "pt": pt, "eff": eff, "ship": j != 3, "url": "#", "img": ""})
            offers.sort(key=core._rank)
            core.record_day(hist, d.isoformat(), offers, d.isoformat() + "T06:10:00+09:00")
        core.save_json(core.hist_path(data_dir, p["id"]), hist)
    core.save_json(data_dir / "last_run.json", {"date": today, "sample": True, "ok": len(catalog["products"]),
                                                "empty": [], "failed": []})
    return len(catalog["products"])
