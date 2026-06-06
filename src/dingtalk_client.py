from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import urllib.parse
import urllib.request
from typing import Any


class DingTalkSendError(RuntimeError):
    pass


class DingTalkClient:
    def __init__(self, webhook: str = "", secret: str = "") -> None:
        self.webhook = webhook
        self.secret = secret

    def enabled(self) -> bool:
        return bool(self.webhook)

    def send_markdown(self, title: str, markdown: str) -> None:
        if not self.webhook:
            return
        payload = {"msgtype": "markdown", "markdown": {"title": title, "text": markdown}}
        self._post(payload)

    def send_text(self, text: str) -> None:
        if not self.webhook:
            return
        self._post({"msgtype": "text", "text": {"content": text}})

    def _post(self, payload: dict[str, Any]) -> None:
        url = self._signed_url()
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8")
        data = json.loads(raw or "{}")
        if data.get("errcode") not in (None, 0):
            raise DingTalkSendError(raw)

    def _signed_url(self) -> str:
        if not self.secret:
            return self.webhook
        timestamp = str(round(time.time() * 1000))
        string_to_sign = f"{timestamp}\n{self.secret}".encode("utf-8")
        digest = hmac.new(self.secret.encode("utf-8"), string_to_sign, hashlib.sha256).digest()
        sign = urllib.parse.quote_plus(base64.b64encode(digest).decode("utf-8"))
        sep = "&" if "?" in self.webhook else "?"
        return f"{self.webhook}{sep}timestamp={timestamp}&sign={sign}"
