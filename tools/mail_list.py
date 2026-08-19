from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from utils.flags import FLAG_UNREAD, decode_flag, decode_label, parse_flag_filter, to_jst_iso
from utils.plugin import create_client, get_bool, get_int, get_str

VALID_SORT_BY = {
    "date",
    "rdate",
    "subject",
    "rsubject",
    "sender",
    "rsender",
    "size",
    "rsize",
}


class MailListTool(Tool):
    def _invoke(
        self, tool_parameters: dict[str, Any]
    ) -> Generator[ToolInvokeMessage, None, None]:
        client = create_client(self)

        folder_id = get_str(tool_parameters, "folder_id", "@")
        sort_by = get_str(tool_parameters, "sort_by", "date")
        if sort_by not in VALID_SORT_BY:
            raise ValueError(f"sort_by の値が不正です: {sort_by}")

        # flag_filter を明示指定した場合はそちらを優先し、無ければ unread_only を反映する。
        flag_filter = parse_flag_filter(tool_parameters.get("flag_filter"))
        if flag_filter is None and get_bool(tool_parameters, "unread_only"):
            flag_filter = parse_flag_filter(FLAG_UNREAD)

        params: dict[str, Any] = {
            "folder_id": folder_id,
            "info_type": "info",
            "sort_by": sort_by,
            "flag_filter": flag_filter,
            "label_filter": get_str(tool_parameters, "label_filter") or None,
        }

        # max_entry を省略すると仕様上フォルダー内の全件が返るため、既定値で歯止めをかける。
        max_entry = get_int(tool_parameters, "max_entry")
        params["max_entry"] = 20 if max_entry is None else max_entry
        bgn_idx = get_int(tool_parameters, "bgn_idx")
        if bgn_idx is not None:
            params["bgn_idx"] = bgn_idx

        # API_KEY 方式ではログインユーザ用 API が使えないため、ユーザ指定版を呼ぶ。
        api_name = (
            "Mail.SystemMailListGet" if client.is_api_key_auth else "Mail.MailListGet"
        )
        data = client.call(api_name, params)

        mails = [self._normalize(entry) for entry in (data or []) if entry is not None]
        result = {"folder_id": folder_id, "count": len(mails), "mails": mails}

        yield self.create_json_message(result)
        yield self.create_text_message(self._summarize(folder_id, mails))

    @staticmethod
    def _normalize(entry: Any) -> dict[str, Any]:
        # info_type=info を指定してもランタイムによっては ID 文字列だけが返ることがある。
        if not isinstance(entry, dict):
            return {"mail_id": str(entry)}

        flags = decode_flag(entry.get("flag"))
        return {
            "mail_id": entry.get("id"),
            "subject": entry.get("subject", ""),
            "sender_name": entry.get("sender_nickname", ""),
            "sender_email": entry.get("sender_email", ""),
            "date": to_jst_iso(entry.get("ctime")),
            "timestamp": entry.get("ctime"),
            "size_kb": entry.get("size"),
            "label": decode_label(entry.get("label")),
            **flags,
        }

    @staticmethod
    def _summarize(folder_id: str, mails: list[dict[str, Any]]) -> str:
        if not mails:
            return f"フォルダー {folder_id} に該当するメールはありませんでした。"

        lines = [f"フォルダー {folder_id} のメール {len(mails)} 件:"]
        for mail in mails:
            marks = "".join(
                [
                    "[未読]" if mail.get("unread") else "",
                    "[重要]" if mail.get("important") else "",
                    "[添付]" if mail.get("has_attachment") else "",
                ]
            )
            sender = mail.get("sender_email") or mail.get("sender_name") or "(不明)"
            lines.append(
                f"- {mail.get('date') or '日時不明'} | {sender} | "
                f"{mail.get('subject') or '(件名なし)'} {marks}".rstrip()
            )
            lines.append(f"  mail_id: {mail.get('mail_id')}")
        return "\n".join(lines)
