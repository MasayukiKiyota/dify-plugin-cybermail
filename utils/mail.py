"""Mail.MailAdvanceGet の応答を扱うための共通処理。

mail_get と attachment_get の両方が同じ応答を読むため、整形はここに集約する。
"""

import re
from typing import Any

from utils.flags import to_jst_iso

DEFAULT_MIME_TYPE = "application/octet-stream"
MAX_FILENAME_BYTES = 255

_MIME_TYPE_RE = re.compile(r"^[\w.+-]+/[\w.+-]+$")
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")


def sanitize_filename(name: Any, fallback: str = "attachment") -> str:
    """サーバ応答由来のファイル名から、パス要素と制御文字を取り除く。

    添付ファイル名はメール送信者が自由に付けられるため、``../`` や
    ディレクトリ区切り、制御文字をそのまま下流に渡さない。
    """
    text = "" if name is None else str(name)
    # パス区切りで分割して最後の要素だけを使う（``..`` 要素は捨てる）。
    parts = [part for part in re.split(r"[\\/]+", text) if part not in ("", ".", "..")]
    text = parts[-1] if parts else ""
    text = _CONTROL_CHARS_RE.sub("", text).strip().lstrip(".")
    encoded = text.encode("utf-8")
    if len(encoded) > MAX_FILENAME_BYTES:
        text = encoded[:MAX_FILENAME_BYTES].decode("utf-8", errors="ignore")
    return text or fallback


def sanitize_mime_type(value: Any) -> str:
    """``type/subtype`` の形になっていない Content-Type は既定値に置き換える。"""
    text = "" if value is None else str(value).strip().lower()
    return text if _MIME_TYPE_RE.match(text) else DEFAULT_MIME_TYPE


def format_address(value: Any) -> str:
    """``{"addr": ..., "nick": ...}`` を ``"nick" <addr>`` 形式の文字列にする。

    仕様上はオブジェクトだが、素の文字列が返るケースもあるためどちらも受ける。
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        addr = str(value.get("addr") or "").strip()
        nick = str(value.get("nick") or "").strip()
        if nick and addr:
            return f'"{nick}" <{addr}>'
        return addr or nick
    return str(value)


def format_address_list(value: Any) -> list[str]:
    """To/Cc/Bcc（オブジェクトの配列）を文字列の配列にする。"""
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [formatted for formatted in (format_address(item) for item in value) if formatted]
    formatted = format_address(value)
    return [formatted] if formatted else []


def normalize_attachments(entries: Any, inline: bool = False) -> list[dict[str, Any]]:
    """``attachments`` / ``inlineAttachments`` を共通の形に整える。"""
    if not isinstance(entries, list):
        return []

    result: list[dict[str, Any]] = []
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            continue
        result.append(
            {
                "filename": sanitize_filename(entry.get("filename"), f"attachment_{index}"),
                "hash": str(entry.get("hash") or ""),
                "size": entry.get("size"),
                "content_type": sanitize_mime_type(entry.get("contentType")),
                "inline": inline,
            }
        )
    return result


def extract_body(content: Any) -> tuple[str, str]:
    """``content`` から ``(テキスト本文, HTML本文)`` を取り出す。

    Mail.MailAdvanceGet は ``{"html": ..., "text": ...}`` を返すが、
    プレーンテキストのメールでは文字列が直接返ることがある。
    """
    if isinstance(content, dict):
        return str(content.get("text") or ""), str(content.get("html") or "")
    if isinstance(content, str):
        return content, ""
    return "", ""


def normalize_mail(data: dict[str, Any], mail_id: str, folder_id: str) -> dict[str, Any]:
    """Mail.MailAdvanceGet の data を整形済みの辞書にする（本文・添付を含む）。"""
    body_text, body_html = extract_body(data.get("content"))
    attachments = normalize_attachments(data.get("attachments"))
    inline_attachments = normalize_attachments(data.get("inlineAttachments"), inline=True)
    raw_date = data.get("date")

    return {
        "mail_id": mail_id,
        "folder_id": folder_id,
        "subject": data.get("subject") or "",
        "from": format_address(data.get("from")),
        "to": format_address_list(data.get("to")),
        "cc": format_address_list(data.get("cc")),
        "bcc": format_address_list(data.get("bcc")),
        "reply_to": format_address(data.get("reply_to")),
        # date は epoch 秒で返るが、文字列日付が返る環境もあるため両方保持する。
        "date": to_jst_iso(raw_date) or (raw_date if isinstance(raw_date, str) else None),
        "timestamp": raw_date if isinstance(raw_date, int) else None,
        "body_text": body_text,
        "body_html": body_html,
        "attachments": attachments,
        "attachment_count": len(attachments),
        "inline_attachment_count": len(inline_attachments),
        "_inline_attachments": inline_attachments,
    }
