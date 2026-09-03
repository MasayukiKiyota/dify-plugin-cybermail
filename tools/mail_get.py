from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from utils.client import CybermailError
from utils.mail import normalize_mail
from utils.plugin import create_client, emit_result, get_str

VALID_BODY_FORMATS = {"text", "html", "both"}


class MailGetTool(Tool):
    def _invoke(
        self, tool_parameters: dict[str, Any]
    ) -> Generator[ToolInvokeMessage, None, None]:
        mail_id = get_str(tool_parameters, "mail_id")
        if not mail_id:
            raise ValueError("mail_id は必須です。「メール一覧取得」の結果から指定してください。")

        folder_id = get_str(tool_parameters, "folder_id", "@")
        body_format = get_str(tool_parameters, "body_format", "text")
        if body_format not in VALID_BODY_FORMATS:
            raise ValueError(f"body_format の値が不正です: {body_format}")

        client = create_client(self)
        # Mail.MailAdvanceGet は API_KEY / API_SESSION の両方式に対応しており、
        # Mail.MailGet と違って本文・宛先・添付が構造化されて返る。
        data = client.call(
            "Mail.MailAdvanceGet", {"folder_id": folder_id, "mail_id": mail_id}
        )
        if not isinstance(data, dict):
            raise CybermailError(
                f"Mail.MailAdvanceGet が想定外の応答を返しました: {str(data)[:200]!r}"
            )

        mail = normalize_mail(data, mail_id, folder_id)
        mail.pop("_inline_attachments", None)

        # HTML 本文は数百 KB になり得るため、要求された形式だけを残す。
        if body_format == "text":
            mail["body_html"] = ""
        elif body_format == "html":
            mail["body_text"] = ""

        yield from emit_result(self, mail)
        yield self.create_text_message(self._render(mail, body_format))

    @staticmethod
    def _render(mail: dict[str, Any], body_format: str) -> str:
        lines = [
            f"件名: {mail['subject'] or '(件名なし)'}",
            f"差出人: {mail['from'] or '(不明)'}",
            f"宛先: {', '.join(mail['to']) or '(なし)'}",
        ]
        if mail["cc"]:
            lines.append(f"Cc: {', '.join(mail['cc'])}")
        lines.append(f"日時: {mail['date'] or '(不明)'}")

        if mail["attachments"]:
            names = ", ".join(
                f"{item['filename']} ({item['size']} bytes)" for item in mail["attachments"]
            )
            lines.append(f"添付ファイル ({mail['attachment_count']} 件): {names}")
        if mail["inline_attachment_count"]:
            lines.append(f"インライン添付: {mail['inline_attachment_count']} 件")

        body = mail["body_html"] if body_format == "html" else mail["body_text"]
        if body_format == "both" and mail["body_html"] and not mail["body_text"]:
            body = mail["body_html"]

        lines.append("")
        lines.append(body or "(本文なし)")
        return "\n".join(lines)
