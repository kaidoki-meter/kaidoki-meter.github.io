"""使い方:  python -m kaidoki <命令>

  collect   楽天APIから今日の価格を取り、data/ に記録する(鍵が必要)
  build     data/ から public/ にサイトを作る        (--sample で見本データから作る)
  sample    見本データを data_sample/ に作る
  report    いまの記録の状態を表で出す               (--sample で見本データを見る)
  check     設定ファイルにまちがいがないか確かめる
"""
from __future__ import annotations

import sys

from . import core, rakuten, sample, site

DATA = core.ROOT / "data"
DATA_SAMPLE = core.ROOT / "data_sample"
PUBLIC = core.ROOT / "public"
FAIL_RATIO = 0.5  # これ以上の割合で取得に失敗したら、その日は記録も公開もしない


def cmd_collect() -> int:
    site_cfg, catalog = core.load_config()
    client = rakuten.Client.from_env(site_cfg["base_url"])
    today, fetched = core.today_jst(), core.now_jst().isoformat(timespec="seconds")
    ok, empty, failed, pending = [], [], [], []
    for p in catalog["products"]:
        hist = core.load_hist(DATA, p["id"])
        band = core.price_band(p, hist)
        try:
            items = client.search(p["q"], band[0], band[1])
        except rakuten.RakutenError as e:
            failed.append({"id": p["id"], "error": str(e)})
            print(f"  失敗  {p['id']}: {e}")
            continue
        offers = core.pick_offers(p, items, catalog["ng_words"], band)
        if not offers:
            empty.append(p["id"])
            print(f"  なし  {p['id']} (検索{len(items)}件のうち、条件に合う出品なし)")
            continue
        core.record_day(hist, today, offers, fetched)
        pending.append((p["id"], hist))
        ok.append(p["id"])
        print(f"  記録  {p['id']}: 実質{core.yen(offers[0]['eff'])} / {len(offers)}店")
    total = len(catalog["products"])
    bad = len(failed) / total if total else 1
    summary = {"date": today, "fetched": fetched, "sample": False, "ok": len(ok), "empty": empty, "failed": failed}
    if not ok or bad >= FAIL_RATIO:
        print(f"\n取得の失敗が多すぎます(成功{len(ok)} / 失敗{len(failed)} / 全{total})。今日は記録せずに止めます。")
        return 2
    for pid, hist in pending:
        core.save_json(core.hist_path(DATA, pid), hist)
    core.save_json(DATA / "last_run.json", summary)
    print(f"\n記録{len(ok)}件 / 該当なし{len(empty)}件 / 失敗{len(failed)}件")
    return 0


def cmd_build(use_sample: bool) -> int:
    site_cfg, catalog = core.load_config()
    data_dir = DATA_SAMPLE if use_sample else DATA
    if not (data_dir / "history").exists():
        print(f"{data_dir.name}/history がありません。先に {'sample' if use_sample else 'collect'} を実行してください。")
        return 1
    n = site.build(site_cfg, catalog, data_dir, PUBLIC, core.today_jst(), sample=use_sample)
    print(f"public/ に {n} ページ作りました。")
    return 0


def cmd_sample() -> int:
    _, catalog = core.load_config()
    n = sample.generate(DATA_SAMPLE, catalog, core.today_jst())
    print(f"見本データを {n} 商品ぶん作りました(data_sample/)。")
    return 0


def cmd_report(use_sample: bool) -> int:
    _, catalog = core.load_config()
    data_dir = DATA_SAMPLE if use_sample else DATA
    today = core.today_jst()
    print(f"{'商品':<34}{'日数':>4}  {'判定':<6}{'今日の実質':>10}{'30日中央値':>11}")
    for p in catalog["products"]:
        a = core.analyze(core.load_hist(data_dir, p["id"]), today)
        eff = f"{a['eff']:,}" if a["ok"] else "-"
        med = f"{a['med30']:,}" if a.get("med30") else "-"
        print(f"{p['id']:<34}{a['days']:>4}  {a['label']:<6}{eff:>10}{med:>11}")
    run = core.load_json(data_dir / "last_run.json", {})
    if run:
        print(f"\n最後の実行: {run.get('date')} 記録{run.get('ok')}件 / 該当なし{len(run.get('empty', []))}件 / 失敗{len(run.get('failed', []))}件")
        for pid in run.get("empty", []):
            print(f"  該当なし: {pid} (products.json の q / must / typical を見直す)")
    return 0


def main(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    core.load_env_file()
    cmd = argv[1] if len(argv) > 1 else ""
    use_sample = "--sample" in argv
    try:
        if cmd == "collect":
            return cmd_collect()
        if cmd == "build":
            return cmd_build(use_sample)
        if cmd == "sample":
            return cmd_sample()
        if cmd == "report":
            return cmd_report(use_sample)
        if cmd == "check":
            _, catalog = core.load_config()
            print(f"設定OK: {len(catalog['products'])} 商品 / {len(catalog['categories'])} カテゴリ")
            return 0
    except rakuten.RakutenError as e:
        print(f"楽天APIの設定に問題があります: {e}")
        return 2
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
