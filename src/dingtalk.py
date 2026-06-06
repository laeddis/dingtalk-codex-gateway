from __future__ import annotations

from typing import Any


def extract_text_from_callback(payload: dict[str, Any]) -> str:
    """Extract message text from future DingTalk callback payloads.

    The real callback/signature verification is intentionally not wired in MVP;
    local testing uses /local/message instead.
    """
    text = payload.get("text")
    if isinstance(text, dict):
        content = text.get("content")
        if isinstance(content, str):
            return content.strip()
    if isinstance(text, str):
        return text.strip()
    return ""


def extract_sender_from_callback(payload: dict[str, Any]) -> str:
    for key in ("senderStaffId", "senderId", "senderNick", "conversationId", "sender"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "dingtalk-user"
