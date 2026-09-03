from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from utils.client import CybermailError
from utils.mail import normalize_attachments
from utils.plugin import create_client, emit_result, get_bool, get_str


class AttachmentGetTool(Tool):
    def _invoke(
        self, tool_parameters: dict[str, Any]
    ) -> Generator[ToolInvokeMessage, None, None]:
        mail_id = get_str(tool_parameters, "mail_id")
        if not mail_id:
            raise ValueError("mail_id は必須です。「メール一覧取得」の結果から指定してください。")

        folder_id = get_str(tool_parameters, "folder_id", "@")
        wanted_hash = get_str(tool_parameters, "hash")
        include_inline = get_bool(tool_parameters, "include_inline")

        client = create_client(self)

        # ファイル名と Content-Type は添付取得 API から得られないため、
        # hash 指定の有無にかかわらず先にメールのメタ情報を引く。
        meta = client.call(
            "Mail.MailAdvanceGet", {"folder_id": folder_id, "mail_id": mail_id}
        )
        if not isinstance(meta, dict):
            raise CybermailError(
                f"Mail.MailAdvanceGet が想定外の応答を返しました: {str(meta)[:200]!r}"
            )

        targets = normalize_attachments(meta.get("attachments"))
        if include_inline:
            targets += normalize_attachments(meta.get("inlineAttachments"), inline=True)

        if wanted_hash:
            matched = [item for item in targets if item["hash"] == wanted_hash]
            # メタ情報に無い hash でも、指定されたものはそのまま取得を試みる。
            targets = matched or [
                {
                    "filename": f"{wanted_hash}.bin",
                    "hash": wanted_hash,
                    "size": None,
                    "content_type": "application/octet-stream",
                    "inline": False,
                }
            ]

        if not targets:
            subject = meta.get("subject") or "(件名なし)"
            yield self.create_text_message(f"メール「{subject}」に添付ファイルはありません。")
            yield from emit_result(
                self,
                {
                    "mail_id": mail_id,
                    "folder_id": folder_id,
                    "downloaded_count": 0,
                    "failed_count": 0,
                    "attachments": [],
                },
            )
            return

        results: list[dict[str, Any]] = []
        for index, item in enumerate(targets, start=1):
            filename = item["filename"] or f"attachment_{index}"
            try:
                content, content_type = client.call_binary(
                    "Mail.AttachmentGet",
                    {"folder_id": folder_id, "mail_id": mail_id, "hash": item["hash"]},
                )
            except CybermailError as exc:
                # 1 件失敗しても残りの添付は取得を続ける。
                results.append({**item, "success": False, "error": str(exc)})
                yield self.create_text_message(f"添付ファイル {filename} の取得に失敗しました: {exc}")
                continue

            # メールのメタ情報にある Content-Type を優先し、無ければ応答ヘッダを使う。
            mime_type = item["content_type"] or content_type
            results.append(
                {
                    **item,
                    "size": len(content),
                    "mime_type": mime_type,
                    "success": True,
                    "error": None,
                }
            )
            yield self.create_blob_message(
                blob=content,
                meta={"mime_type": mime_type, "filename": filename},
            )

        downloaded = [item for item in results if item["success"]]
        failed = [item for item in results if not item["success"]]

        # ファイル本体は blob として Dify 組み込みの files 出力に入るため、
        # ここでは明細を attachments という別名で返して上書きを避ける。
        yield from emit_result(
            self,
            {
                "mail_id": mail_id,
                "folder_id": folder_id,
                "downloaded_count": len(downloaded),
                "failed_count": len(failed),
                "attachments": [
                    {
                        "filename": item.get("filename"),
                        "hash": item.get("hash"),
                        "size": item.get("size"),
                        "mime_type": item.get("mime_type") or item.get("content_type"),
                        "inline": item.get("inline", False),
                        "success": item.get("success", False),
                        "error": item.get("error"),
                    }
                    for item in results
                ],
            },
        )
