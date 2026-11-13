"""楽天市場 商品検索API の呼び出し。

2026年の新しい仕組み(openapi.rakuten.co.jp)に合わせてある:
  - アプリID(applicationId)とアクセスキー(accessKey)の両方が必要
  - Referer ヘッダが必須(アプリ登録時に届け出たサイトのURLを送る)
  - エラーの形が2通りある(error/error_description と errors.errorCode/errorMessage)

APIの住所(URL)が変わったときは、環境変数 RAKUTEN_SEARCH_URL で差し替えられる。
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_SEARCH_URL = "https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/20260701"
MIN_INTERVAL = 1.2  # 秒。呼びすぎないように、1回ごとに間をあける


class RakutenError(Exception):
    pass


def parse_error(body: str, status: int) -> str:
    """エラーの本文から、人が読める1行を作る。"""
    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        return f"HTTP {status}: {(body or '')[:200]}"
    errs = data.get("errors")
    if isinstance(errs, list) and errs:
        errs = errs[0]
    if isinstance(errs, dict):
        return f"HTTP {status}: {errs.get('errorCode', '')} {errs.get('errorMessage', '')}".strip()
    if data.get("error") or data.get("error_description"):
        return f"HTTP {status}: {data.get('error', '')} {data.get('error_description', '')}".strip()
    return f"HTTP {status}: {body[:200]}"


class Client:
    def __init__(self, app_id: str, access_key: str, affiliate_id: str, referer: str, url: str | None = None):
        if not app_id or not access_key:
            raise RakutenError("RAKUTEN_APP_ID と RAKUTEN_ACCESS_KEY が設定されていません。")
        if not referer:
            raise RakutenError("サイトのURL(SITE_BASE_URL か config/site.json の base_url)が空です。楽天APIは Referer が必須です。")
        self.app_id, self.access_key, self.affiliate_id = app_id, access_key, affiliate_id
        self.referer = referer.rstrip("/") + "/"
        self.url = url or os.environ.get("RAKUTEN_SEARCH_URL") or DEFAULT_SEARCH_URL
        self._last = 0.0

    @classmethod
    def from_env(cls, referer: str) -> "Client":
        return cls(os.environ.get("RAKUTEN_APP_ID", ""), os.environ.get("RAKUTEN_ACCESS_KEY", ""),
                   os.environ.get("RAKUTEN_AFFILIATE_ID", ""), referer)

    def search(self, keyword: str, min_price: int, max_price: int, ng_keyword: str = "", hits: int = 30) -> list[dict]:
        params = {
            "applicationId": self.app_id,
            "accessKey": self.access_key,
            "format": "json",
            "formatVersion": 2,
            "keyword": keyword,
            "minPrice": max(int(min_price), 1),
            "maxPrice": int(max_price),
            "availability": 1,
            "sort": "+itemPrice",
            "hits": hits,
        }
        if self.affiliate_id:
            params["affiliateId"] = self.affiliate_id
        if ng_keyword:
            params["NGKeyword"] = ng_keyword
        data = self._get(params)
        return data.get("Items") or data.get("items") or []

    def _get(self, params: dict) -> dict:
        url = self.url + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={
            "Referer": self.referer,
            "Origin": self.referer.rstrip("/"),
            "User-Agent": "kaidoki-meter/1.0",
            "Accept": "application/json",
        })
        last_err = "不明なエラー"
        for attempt in range(4):
            wait = MIN_INTERVAL - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            try:
                with urllib.request.urlopen(req, timeout=30) as res:
                    return json.loads(res.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", "replace")
                last_err = parse_error(body, e.code)
                if e.code == 429 or e.code >= 500:  # 混雑・一時的な不調は、間をあけてやり直す
                    time.sleep(3 * (attempt + 1))
                    continue
                raise RakutenError(last_err) from None  # 鍵のまちがいなどは、やり直しても直らない
            except (urllib.error.URLError, TimeoutError, ValueError) as e:
                last_err = f"通信エラー: {e}"
                time.sleep(3 * (attempt + 1))
        raise RakutenError(last_err)
