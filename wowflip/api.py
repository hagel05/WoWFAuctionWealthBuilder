"""Battle.net Game Data API client for WoW Forever.

The Forever endpoints are undocumented. Paths and namespaces here come from
community testing (see the data access doc), so they may change without notice:

  GET /data/wow/ruleset/index                              namespace dynamic-forever-{region}
  GET /data/wow/ruleset/{ruleset}/auctions/                (trailing slash required)
  GET /data/wow/ruleset/{ruleset}/auctions/{house}
  GET /data/wow/ruleset/{ruleset}/auctions/{house}/commodities
  GET /data/wow/item/{id}                                  namespace static-forever-{region}

Uses only the standard library so there is nothing to install.
"""

from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request

TOKEN_URL = "https://oauth.battle.net/token"
USER_AGENT = "wowflip/0.1"


class ApiError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class BlizzardClient:
    def __init__(self, client_id: str, client_secret: str, region: str = "us", timeout: float = 120):
        if not client_id or not client_secret:
            raise ApiError(
                "Battle.net API credentials are missing. Set BLIZZARD_CLIENT_ID and "
                "BLIZZARD_CLIENT_SECRET in your .env file (see README)."
            )
        self.client_id = client_id
        self.client_secret = client_secret
        self.region = region.lower()
        self.timeout = timeout
        self._token: str | None = None
        self._token_expires = 0.0

    # -- auth -------------------------------------------------------------
    def _fetch_token(self) -> None:
        basic = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        req = urllib.request.Request(
            TOKEN_URL,
            data=urllib.parse.urlencode({"grant_type": "client_credentials"}).encode(),
            headers={
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": USER_AGENT,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            raise ApiError(
                f"Battle.net rejected the API credentials (HTTP {exc.code}). "
                "Check BLIZZARD_CLIENT_ID and BLIZZARD_CLIENT_SECRET.",
                exc.code,
            ) from exc
        self._token = body["access_token"]
        # Refresh a few minutes early.
        self._token_expires = time.time() + int(body.get("expires_in", 3600)) - 300

    def _bearer(self) -> str:
        if not self._token or time.time() >= self._token_expires:
            self._fetch_token()
        return self._token  # type: ignore[return-value]

    # -- requests ---------------------------------------------------------
    def get(self, path: str, namespace_kind: str = "dynamic", params: dict | None = None):
        """GET a Game Data path. Returns parsed JSON, or None on 404."""
        query = {"namespace": f"{namespace_kind}-forever-{self.region}", "locale": "en_US"}
        if params:
            query.update(params)
        url = f"https://{self.region}.api.blizzard.com{path}?{urllib.parse.urlencode(query)}"

        refreshed = False
        for attempt in range(4):
            req = urllib.request.Request(
                url,
                headers={"Authorization": f"Bearer {self._bearer()}", "User-Agent": USER_AGENT},
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return json.loads(resp.read())
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    return None
                if exc.code == 401 and not refreshed:
                    self._token = None
                    refreshed = True
                    continue
                if exc.code == 429 or exc.code >= 500:
                    time.sleep(2 ** attempt)
                    continue
                raise ApiError(f"GET {path} failed: HTTP {exc.code}", exc.code) from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt == 3:
                    raise ApiError(f"GET {path} failed: {exc}") from exc
                time.sleep(2 ** attempt)
        raise ApiError(f"GET {path} failed after retries")

    # -- endpoints --------------------------------------------------------
    def rulesets(self):
        return self.get("/data/wow/ruleset/index")

    def houses(self, ruleset_id: int):
        return self.get(f"/data/wow/ruleset/{ruleset_id}/auctions/")

    def auctions(self, ruleset_id: int, house_id: int) -> list[dict]:
        data = self.get(f"/data/wow/ruleset/{ruleset_id}/auctions/{house_id}")
        if data is None:
            raise ApiError(f"Auction house {house_id} not found (404). The API paths may have changed.", 404)
        return data.get("auctions") or []

    def commodities(self, ruleset_id: int, house_id: int) -> list[dict]:
        data = self.get(f"/data/wow/ruleset/{ruleset_id}/auctions/{house_id}/commodities")
        if data is None:
            return []
        return data.get("auctions") or []

    def item(self, item_id: int) -> dict | None:
        return self.get(f"/data/wow/item/{item_id}", namespace_kind="static")
