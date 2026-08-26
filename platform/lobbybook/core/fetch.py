"""Compliance-aware HTTP client.

Encodes the audit's compliance posture so no connector can violate it by
accident (docs/texas-politics-audit/01-executive-findings.md, finding #4):

* a hard DENYLIST for paths the sources forbid to automated clients
  (lrl.texas.gov PDFs/exports, TAMES, capitol.texas.gov robots-disallowed
  UI paths) — requests raise ``DeniedURL`` before any bytes move;
* per-host minimum intervals (politeness even where robots is silent);
* an identified default User-Agent, with a browser-profile escape hatch for
  hosts whose bot mitigation fingerprints tooling but whose content is
  public (texasattorneygeneral.gov — verified in the audit);
* retry with exponential backoff on 403/429/5xx and transport errors;
* conditional-GET helpers (ETag / Last-Modified).
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

import httpx

UA = "LobbyBookBot/0.1 (+https://github.com/mattmichaelree/cms-detector; data-platform research)"
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

# Hosts whose bot mitigation blocks tool UAs but serve identical public content
# to browser UAs (verified in the audit). We still throttle them.
BROWSER_PROFILE_HOSTS = {"www.texasattorneygeneral.gov", "texasattorneygeneral.gov"}

# Never fetch these, ever. Sources' own stated policy.
DENYLIST = [
    re.compile(r"https?://(www\.)?lrl\.texas\.gov/.*\.(pdf|doc|txt)$", re.I),
    re.compile(r"https?://(www\.)?lrl\.texas\.gov/legis/billsearch/exportproc\.cfm", re.I),
    re.compile(r"https?://search\.txcourts\.gov/", re.I),          # robots: Disallow /
    re.compile(r"https?://research\.txcourts\.gov/", re.I),        # re:SearchTX, bot-walled
    re.compile(r"https?://capitol\.texas\.gov/BillLookup/BillNumber\.aspx", re.I),
]

# Seconds between requests, per host. Default applies to everything else.
HOST_INTERVALS = {
    "capitol.texas.gov": 3.0,
    "www.sos.state.tx.us": 3.0,
    "lrl.texas.gov": 5.0,
    "www.lrl.texas.gov": 5.0,
    "www.txcourts.gov": 5.0,
    "hro.house.texas.gov": 2.0,
}
DEFAULT_INTERVAL = 1.5


class DeniedURL(Exception):
    """URL is on the compliance denylist; the fetch was refused locally."""


@dataclass
class Fetcher:
    timeout: float = 30.0
    max_retries: int = 3
    _last_hit: dict[str, float] = field(default_factory=dict)
    _client: httpx.Client | None = None

    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                timeout=self.timeout, follow_redirects=True, headers={"User-Agent": UA}
            )
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def _check_denylist(self, url: str) -> None:
        for pat in DENYLIST:
            if pat.search(url):
                raise DeniedURL(f"refused by compliance denylist: {url}")

    def _throttle(self, host: str) -> None:
        interval = HOST_INTERVALS.get(host, DEFAULT_INTERVAL)
        last = self._last_hit.get(host, 0.0)
        wait = last + interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last_hit[host] = time.monotonic()

    def get(
        self,
        url: str,
        *,
        headers: dict | None = None,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> httpx.Response:
        self._check_denylist(url)
        host = httpx.URL(url).host or ""
        hdrs = dict(headers or {})
        if host in BROWSER_PROFILE_HOSTS:
            hdrs.setdefault("User-Agent", BROWSER_UA)
        if etag:
            hdrs["If-None-Match"] = etag
        if last_modified:
            hdrs["If-Modified-Since"] = last_modified

        delay = 2.0
        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            self._throttle(host)
            try:
                resp = self.client().get(url, headers=hdrs)
            except httpx.TransportError as exc:
                last_exc = exc
                if attempt == self.max_retries:
                    raise
                time.sleep(delay)
                delay *= 2
                continue
            if resp.status_code in (403, 429) or resp.status_code >= 500:
                if attempt == self.max_retries:
                    return resp
                time.sleep(delay)
                delay *= 2
                continue
            return resp
        raise last_exc if last_exc else RuntimeError(f"unreachable: {url}")

    def get_ranged(self, url: str, start: int, end: int) -> httpx.Response:
        """Ranged GET (used e.g. for TEC ZIP central-directory probes)."""
        self._check_denylist(url)
        host = httpx.URL(url).host or ""
        self._throttle(host)
        return self.client().get(url, headers={"Range": f"bytes={start}-{end}"})

    def head(self, url: str) -> httpx.Response:
        self._check_denylist(url)
        host = httpx.URL(url).host or ""
        self._throttle(host)
        return self.client().head(url)


_shared: Fetcher | None = None


def fetcher() -> Fetcher:
    """Process-wide shared fetcher, so throttling spans connectors."""
    global _shared
    if _shared is None:
        _shared = Fetcher()
    return _shared
