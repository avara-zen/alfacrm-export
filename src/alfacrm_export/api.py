"""Клиент AlfaCRM v2api: логин, лимит запросов, повторы, постраничное чтение."""

import json
import time
import urllib.error
import urllib.parse
import urllib.request

PAGE_SIZE = 500  # максимум, который разрешает v2api
MAX_TRIES = 6


class ApiError(Exception):
    pass


class Api:
    def __init__(self, host: str, email: str, api_key: str, rps: float = 4.0):
        self.base = f"https://{host}/v2api"
        self.email = email
        self.api_key = api_key
        self.interval = 1.0 / rps  # лимит AlfaCRM — 5 запросов/с на все методы, держим запас
        self.token: str | None = None
        self._last = 0.0
        self.requests = 0

    def _send(self, path: str, body: dict, query: dict | None) -> dict:
        url = f"{self.base}/{path}"
        if query:
            url += "?" + urllib.parse.urlencode(query)
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.token:
            headers["X-ALFACRM-TOKEN"] = self.token
        wait = self._last + self.interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        self.requests += 1
        req = urllib.request.Request(url, json.dumps(body).encode(), headers)
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.load(resp)

    def login(self) -> None:
        self.token = None
        data = self.call("auth/login", {"email": self.email, "api_key": self.api_key}, _relogin=False)
        if not data.get("token"):
            raise ApiError(f"Логин не удался: {data}")
        self.token = data["token"]

    def call(self, path: str, body: dict | None = None, query: dict | None = None, _relogin: bool = True) -> dict:
        """POST с повторами: 429/5xx/сеть — пауза и повтор, 401 — повторный логин."""
        body = body or {}
        relogged = False
        for attempt in range(MAX_TRIES):
            try:
                return self._send(path, body, query)
            except urllib.error.HTTPError as e:
                detail = e.read()[:300].decode(errors="replace")
                if e.code == 401 and _relogin and not relogged:
                    self.login()
                    relogged = True
                    continue
                if e.code == 429 or e.code >= 500:
                    delay = int(e.headers.get("Retry-After") or 0) or 2 ** attempt
                    time.sleep(min(delay, 120))
                    continue
                raise ApiError(f"{e.code} {path} {query or ''}: {detail}") from e
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                time.sleep(2 ** attempt)
        raise ApiError(f"{path} {query or ''}: не удалось после {MAX_TRIES} попыток")

    def paged(self, path: str, body: dict | None = None, query: dict | None = None):
        """Все записи списочного метода, страница за страницей."""
        page = 0
        got = 0
        while True:
            data = self.call(path, {**(body or {}), "page": page, "pageSize": PAGE_SIZE}, query)
            items = data.get("items") or []
            yield from items
            got += len(items)
            total = data.get("total")
            if len(items) < PAGE_SIZE or (total is not None and got >= int(total)):
                return
            page += 1
