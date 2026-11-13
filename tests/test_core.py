"""しくみが正しく動くかの自動テスト。毎日の実行の最初にも走る。  python -m unittest discover -s tests"""
import datetime as dt
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kaidoki import core, rakuten, sample, site  # noqa: E402

P = {"id": "x", "name": "ソニー WH-1000XM5", "cat": "audio", "q": "ソニー WH-1000XM5", "must": ["wh1000xm5"], "typical": 42000}


def item(name, price, rate=1, shop="s1", postage=0, avail=1):
    return {"itemName": name, "itemPrice": price, "pointRate": rate, "shopName": shop, "shopCode": shop,
            "postageFlag": postage, "availability": avail, "affiliateUrl": "https://example.com/" + shop,
            "mediumImageUrls": ["http://img.example.com/a.jpg"]}


def hist_from(effs, end="2026-11-13"):
    t = dt.date.fromisoformat(end)
    days = [{"d": (t - dt.timedelta(days=len(effs) - 1 - i)).isoformat(), "eff": v, "price": v, "pt": 0, "rate": 1,
             "ship": True, "shop": "s", "n": 1} for i, v in enumerate(effs)]
    return {"id": "x", "days": days, "offers": [], "fetched": end + "T06:00:00+09:00"}


class Match(unittest.TestCase):
    def test_norm_ignores_width_case_space_hyphen(self):
        self.assertEqual(core.norm("ＷＨ－１０００ＸＭ５"), "wh1000xm5")
        self.assertEqual(core.norm("MX Master 3S"), "mxmaster3s")

    def test_must_and_ng(self):
        self.assertTrue(core.name_matches("SONY WH-1000XM5 ブラック", ["wh1000xm5"], ["中古"]))
        self.assertFalse(core.name_matches("SONY WH-1000XM4", ["wh1000xm5"], []))
        self.assertFalse(core.name_matches("【中古】SONY WH-1000XM5", ["wh1000xm5"], ["中古"]))
        self.assertTrue(core.name_matches("Elgato Stream Deck MK2", ["streamdeck", "mk.2|mk2"], []))

    def test_effective_price(self):
        self.assertEqual(core.effective(10000, 10), (9000, 1000))
        self.assertEqual(core.effective(9999, None), (9900, 99))

    def test_pick_offers_filters_and_sorts(self):
        items = [
            item("WH-1000XM5 用 イヤーパッド", 1500, shop="acc"),          # 価格の幅の外
            item("【中古】WH-1000XM5", 30000, shop="used"),                 # NGワード
            item("WH-1000XM5", 40000, rate=10, shop="a"),                   # 実質36,000
            item("WH-1000XM5", 37000, rate=1, shop="b", postage=1),         # 実質36,630・送料別
            item("WH-1000XM5", 39000, rate=1, shop="c"),                    # 実質38,610
            item("WH-1000XM5", 38000, rate=1, shop="c"),                    # 同じ店の安いほうだけ残す
            item("WH-1000XM5", 35000, shop="soldout", avail=0),             # 在庫なし
            {"Item": item("WH-1000XM5", 41000, shop="v1")},                 # 古い形式の入れ子
        ]
        offers = core.pick_offers(P, items, ["中古"], core.price_band(P, None))
        self.assertEqual([o["shop"] for o in offers], ["a", "c", "v1", "b"])  # 送料込みが先、実質の安い順
        self.assertEqual(offers[0]["eff"], 36000)
        self.assertEqual(offers[1]["price"], 38000)
        self.assertTrue(offers[0]["img"].startswith("https://"))

    def test_band_follows_real_data(self):
        self.assertEqual(core.price_band(P, None), (18900, 92400))
        self.assertEqual(core.price_band(P, hist_from([30000] * 10)), (15000, 60000))


class Verdict(unittest.TestCase):
    T = "2026-11-13"

    def test_measuring_until_7_days(self):
        self.assertEqual(core.analyze(hist_from([100] * 6), self.T)["label"], "計測中")

    def test_best_when_lowest_in_period(self):
        a = core.analyze(hist_from([10000] * 20 + [9000]), self.T)
        self.assertEqual((a["label"], a["level"], a["chg1"]), ("買いどき", 3, -1000))

    def test_cheap_but_not_lowest(self):
        a = core.analyze(hist_from([8000] + [10000] * 20 + [9000]), self.T)
        self.assertEqual(a["label"], "安め")

    def test_high_and_flat(self):
        self.assertEqual(core.analyze(hist_from([9000] + [10000] * 20 + [11000]), self.T)["label"], "高め")
        self.assertEqual(core.analyze(hist_from([9000] + [10000] * 20 + [10100]), self.T)["label"], "ふつう")

    def test_suspect_drop_is_held(self):
        a = core.analyze(hist_from([10000] * 20 + [4000]), self.T)
        self.assertTrue(a["suspect"])
        self.assertEqual(a["level"], -1)

    def test_stale(self):
        a = core.analyze(hist_from([10000] * 20, end="2026-11-01"), self.T)
        self.assertTrue(a["stale"])
        self.assertEqual(a["level"], -1)

    def test_record_day_overwrites_same_date(self):
        h = hist_from([100, 100])
        o = {"eff": 90, "price": 95, "pt": 5, "rate": 5, "ship": True, "shop": "z"}
        core.record_day(h, self.T, [o], "t")
        self.assertEqual(len(h["days"]), 2)
        self.assertEqual(h["days"][-1]["eff"], 90)


class Rakuten(unittest.TestCase):
    def test_error_shapes(self):
        self.assertIn("wrong_parameter", rakuten.parse_error('{"error":"wrong_parameter","error_description":"x"}', 400))
        self.assertIn("REFERRER_MISSING", rakuten.parse_error('{"errors":{"errorCode":"REFERRER_MISSING","errorMessage":"m"}}', 403))
        self.assertIn("HTTP 503", rakuten.parse_error("<html>busy</html>", 503))

    def test_client_requires_keys_and_referer(self):
        with self.assertRaises(rakuten.RakutenError):
            rakuten.Client("", "", "", "https://example.com")
        with self.assertRaises(rakuten.RakutenError):
            rakuten.Client("a", "b", "", "")


class Build(unittest.TestCase):
    def test_sample_site_builds(self):
        cfg, catalog = core.load_config()
        with tempfile.TemporaryDirectory() as tmp:
            data, out = Path(tmp) / "d", Path(tmp) / "o"
            sample.generate(data, catalog, "2026-11-13")
            n = site.build(cfg, catalog, data, out, "2026-11-13", sample=True)
            self.assertGreaterEqual(n, len(catalog["products"]) + 3)
            home = (out / "index.html").read_text(encoding="utf-8")
            self.assertIn("アフィリエイト広告を利用しています", home)
            self.assertIn("見本データ", home)
            self.assertIn("noindex", home)                       # 見本は検索に出さない
            self.assertIn("Disallow: /\n", (out / "robots.txt").read_text(encoding="utf-8"))
            page = (out / "p" / catalog["products"][0]["id"] / "index.html").read_text(encoding="utf-8")
            self.assertIn("<svg", page)
            self.assertIn('rel="sponsored nofollow noopener"', page)

    def test_real_mode_has_sitemap_and_canonical(self):
        cfg, catalog = core.load_config()
        cfg = dict(cfg, base_url="https://example.com/kaidoki")
        with tempfile.TemporaryDirectory() as tmp:
            data, out = Path(tmp) / "d", Path(tmp) / "o"
            sample.generate(data, catalog, "2026-11-13")
            site.build(cfg, catalog, data, out, "2026-11-13", sample=False)
            home = (out / "index.html").read_text(encoding="utf-8")
            self.assertIn('rel="canonical" href="https://example.com/kaidoki/"', home)
            self.assertIn('href="/kaidoki/style.css"', home)
            sm = (out / "sitemap.xml").read_text(encoding="utf-8")
            self.assertIn("https://example.com/kaidoki/p/", sm)
            self.assertNotIn("/memo/", sm)


if __name__ == "__main__":
    unittest.main()
