"""Mail.MailAdvanceGet の応答を扱うための共通処理。

mail_get と attachment_get の両方が同じ応答を読むため、整形はここに集約する。
"""

from typing import Any

from utils.flags import to_jst_iso


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
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        result.append(
            {
                "filename": entry.get("filename") or "",
                "hash": entry.get("hash") or "",
                "size": entry.get("size"),
                "content_type": entry.get("contentType") or "application/octet-stream",
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
