import re
from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from utils.client import CybermailError
from utils.plugin import create_client, emit_result, get_str

# 宛先の区切りとして受け付ける文字。LLM は「;」や改行で並べがちなため、
# API が受け付けるカンマ区切りに寄せる。
_ADDRESS_SEPARATORS = re.compile(r"[,;\n\r、，；]+")


def _normalize_addresses(raw: str) -> str:
    """区切りの揺れを吸収して「a@x,b@x」形式に揃える。空要素は捨てる。"""
    parts = (part.strip() for part in _ADDRESS_SEPARATORS.split(raw or ""))
    return ",".join(part for part in parts if part)


class MailDraftCreateTool(Tool):
    def _invoke(
        self, tool_parameters: dict[str, Any]
    ) -> Generator[ToolInvokeMessage, None, None]:
        to = _normalize_addresses(get_str(tool_parameters, "to"))
        cc = _normalize_addresses(get_str(tool_parameters, "cc"))
        bcc = _normalize_addresses(get_str(tool_parameters, "bcc"))
        exclude = _normalize_addresses(get_str(tool_parameters, "exclude"))
        subject = get_str(tool_parameters, "subject")
        # 本文は改行やインデントに意味があるため strip しない。
        content = tool_parameters.get("content")
        content = "" if content is None else str(content)
        signature = get_str(tool_parameters, "signature")

        if not (to or cc or bcc):
            raise ValueError("宛先（to / cc / bcc）のいずれかを指定してください。")

        client = create_client(self)
        # Compose.ComposeInvoke は API_SESSION 専用で、API_KEY 方式の代替指定が無い。
        if client.is_api_key_auth:
            raise ValueError(
                "メール下書き作成は API_KEY 方式では利用できません。"
                "認証方式を「ユーザID/パスワード」に変更してください。"
            )

        # 空欄の項目は client._post が落とすので、パラメータ自体が送られない。
        url = client.call(
            "Compose.ComposeInvoke",
            {
                "to": to,
                "cc": cc,
                "bcc": bcc,
                "exclude": exclude,
                "subject": subject,
                "content": content,
                "signature": signature,
            },
        )
        if not isinstance(url, str) or not url.strip():
            raise CybermailError(
                f"Compose.ComposeInvoke が URL を返しませんでした: {str(url)[:200]!r}"
            )
        url = url.strip()

        # 本文は大きくなり得るうえ入力そのものなので、出力には含めない。
        result: dict[str, Any] = {
            "success": True,
            "compose_url": url,
            "to": to,
            "cc": cc,
            "bcc": bcc,
            "exclude": exclude,
            "subject": subject,
        }

        yield from emit_result(self, result)
        yield self.create_link_message(url)
        yield self.create_text_message(self._render(result))

    @staticmethod
    def _render(result: dict[str, Any]) -> str:
        lines = [
            "メール作成画面の URL を発行しました（まだ送信されていません）。",
            "URL を開いて内容を確認し、送信してください。",
        ]
        for key, label in (("to", "To"), ("cc", "Cc"), ("bcc", "Bcc"), ("exclude", "除外")):
            if result[key]:
                lines.append(f"{label}: {result[key]}")
        lines.append(f"件名: {result['subject'] or '(なし)'}")
        return "\n".join(lines)
