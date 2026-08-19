"""Tool 実装の結合テスト。HTTP 層だけ差し替えて _invoke を実際に回す。

dify_plugin SDK が必要なため、SDK を入れた環境で実行する:
    .venv/Scripts/python.exe tests/test_tools.py
"""

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

PLUGIN_DIR = Path(__file__).resolve().parents[1] / "cybermail"
sys.path.insert(0, str(PLUGIN_DIR))

from dify_plugin.entities.tool import ToolInvokeMessage, ToolRuntime  # noqa: E402

from tools.attachment_get import AttachmentGetTool  # noqa: E402
from tools.mail_get import MailGetTool  # noqa: E402
from tools.mail_list import MailListTool  # noqa: E402
from utils import plugin as plugin_utils  # noqa: E402
from utils.client import CybermailClient  # noqa: E402

API_KEY_CREDS = {
    "base_url": "https://example.cybermail.jp",
    "auth_method": "api_key",
    "user_id": "adm@example.co.jp",
    "api_key": "KEY123",
}


class FakeResponse:
    def __init__(self, payload, status_code=200, content_type="application/json"):
        self.status_code = status_code
        self.headers = {"Content-Type": content_type}
        self.content = payload if isinstance(payload, bytes) else json.dumps(payload).encode()

    @property
    def text(self):
        return self.content.decode("utf-8", errors="replace")

    def json(self):
        return json.loads(self.text)


class FakeHttp:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, data=None, timeout=None):
        self.calls.append((url, dict(data or {})))
        return self.responses.pop(0)


def ok(data):
    return FakeResponse({"status": {"code": 0, "message": ""}, "data": data})


def err(code, message):
    return FakeResponse({"status": {"code": code, "message": message}, "data": None})


def run_tool(tool_cls, parameters, responses):
    """Tool を実際に生成し、HTTP だけ差し替えて _invoke を実行する。"""
    http = FakeHttp(responses)

    def fake_create_client(tool):
        client = CybermailClient(tool.runtime.credentials)
        client._http = http
        return client

    original = plugin_utils.create_client
    # 各 Tool モジュールは create_client を名前で取り込んでいるため、そちらも差し替える。
    patched_modules = [sys.modules[tool_cls.__module__], plugin_utils]
    for module in patched_modules:
        module.create_client = fake_create_client
    try:
        tool = tool_cls(
            runtime=ToolRuntime(credentials=API_KEY_CREDS, user_id="tester", session_id="s1"),
            session=SimpleNamespace(storage=None),
        )
        messages = list(tool._invoke(parameters))
    finally:
        for module in patched_modules:
            module.create_client = original
    return messages, http


def messages_by_type(messages, message_type):
    return [m for m in messages if m.type == message_type]


LIST_SAMPLE = [
    {
        "label": 0,
        "sender_nickname": "adm",
        "flag": 67109120,  # 未読
        "subject": "テスト3",
        "size": 1,
        "id": "X_TOQNEGF57F",
        "class": 0,
        "sender_email": "adm@example.co.jp",
        "ctime": 1626073885,
    },
    {
        "label": 3,
        "sender_nickname": "boss",
        "flag": 0x11,  # 重要 + 添付
        "subject": "見積の件",
        "size": 92,
        "id": "W_NOQNEGBKSE",
        "class": 0,
        "sender_email": "boss@example.co.jp",
        "ctime": 1626073879,
    },
]

MAIL_SAMPLE = {
    "reply_to": '"adm" <adm@example.co.jp>',
    "attachments": [
        {
            "filename": "test.pptx",
            "hash": "967587fc",
            "size": 79479,
            "contentType": "application/vnd.openxmlformats-officedocument."
            "presentationml.presentation",
        },
        {"filename": "notes.txt", "hash": "aa11", "size": 12, "contentType": "text/plain"},
    ],
    "bcc": [],
    "subject": "テストメール",
    "from": {"addr": "adm@example.co.jp", "nick": "adm"},
    "inlineAttachments": [
        {"filename": "image.png", "hash": "bb22", "size": 3175, "contentType": "image/png"}
    ],
    "cc": [{"addr": "cc@example.co.jp", "nick": "cc"}],
    "to": [{"addr": "adm@example.co.jp", "nick": "adm"}],
    "date": 1626064602,
    "content": {"html": "<html>body</html>", "text": "aaaaaa\n\n"},
}


class MailListToolTest(unittest.TestCase):
    def test_returns_normalized_json_and_text(self):
        messages, http = run_tool(MailListTool, {"folder_id": "@"}, [ok(LIST_SAMPLE)])

        json_messages = messages_by_type(messages, ToolInvokeMessage.MessageType.JSON)
        self.assertEqual(len(json_messages), 1)
        result = json_messages[0].message.json_object
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["folder_id"], "@")

        first = result["mails"][0]
        self.assertEqual(first["mail_id"], "X_TOQNEGF57F")
        self.assertEqual(first["date"], "2021-07-12T16:11:25+09:00")
        self.assertTrue(first["unread"])
        self.assertFalse(first["has_attachment"])

        second = result["mails"][1]
        self.assertEqual(second["label"], "赤色")
        self.assertTrue(second["important"])
        self.assertTrue(second["has_attachment"])

        text = messages_by_type(messages, ToolInvokeMessage.MessageType.TEXT)[0].message.text
        self.assertIn("X_TOQNEGF57F", text)
        self.assertIn("[未読]", text)

    def test_api_key_auth_uses_system_api_and_defaults(self):
        _, http = run_tool(MailListTool, {}, [ok([])])
        _, payload = http.calls[0]
        self.assertEqual(payload["API_NAME"], "Mail.SystemMailListGet")
        self.assertEqual(payload["folder_id"], "@")
        self.assertEqual(payload["info_type"], "info")
        self.assertEqual(payload["sort_by"], "date")
        # max_entry 未指定でも全件取得にならないこと。
        self.assertEqual(payload["max_entry"], 20)

    def test_unread_only_sets_flag_filter(self):
        _, http = run_tool(MailListTool, {"unread_only": True}, [ok([])])
        self.assertEqual(http.calls[0][1]["flag_filter"], "0x00000100")

    def test_explicit_flag_filter_wins_over_unread_only(self):
        _, http = run_tool(
            MailListTool, {"unread_only": True, "flag_filter": "0x00000010"}, [ok([])]
        )
        self.assertEqual(http.calls[0][1]["flag_filter"], "0x00000010")

    def test_empty_folder_reports_no_mail(self):
        messages, _ = run_tool(MailListTool, {"folder_id": "@.trash"}, [ok([])])
        result = messages_by_type(messages, ToolInvokeMessage.MessageType.JSON)[0]
        self.assertEqual(result.message.json_object["count"], 0)
        text = messages_by_type(messages, ToolInvokeMessage.MessageType.TEXT)[0].message.text
        self.assertIn("該当するメールはありません", text)

    def test_id_only_response_is_tolerated(self):
        """info_type=info でも ID 配列が返る環境で落ちないこと。"""
        messages, _ = run_tool(MailListTool, {}, [ok(["A_1", "B_2"])])
        result = messages_by_type(messages, ToolInvokeMessage.MessageType.JSON)[0]
        self.assertEqual(
            [m["mail_id"] for m in result.message.json_object["mails"]], ["A_1", "B_2"]
        )

    def test_invalid_sort_by_rejected(self):
        with self.assertRaises(ValueError):
            run_tool(MailListTool, {"sort_by": "priority"}, [ok([])])


class MailGetToolTest(unittest.TestCase):
    def test_text_format_strips_html(self):
        messages, http = run_tool(
            MailGetTool, {"mail_id": "O_TMENEG7K8B"}, [ok(MAIL_SAMPLE)]
        )
        payload = http.calls[0][1]
        self.assertEqual(payload["API_NAME"], "Mail.MailAdvanceGet")
        self.assertEqual(payload["API_USERID"], "adm@example.co.jp")

        mail = messages_by_type(messages, ToolInvokeMessage.MessageType.JSON)[0].message.json_object
        self.assertEqual(mail["subject"], "テストメール")
        self.assertEqual(mail["cc"], ['"cc" <cc@example.co.jp>'])
        self.assertEqual(mail["body_text"], "aaaaaa\n\n")
        self.assertEqual(mail["body_html"], "")
        self.assertEqual(mail["attachment_count"], 2)
        self.assertEqual(mail["inline_attachment_count"], 1)
        self.assertEqual(mail["attachments"][0]["hash"], "967587fc")
        self.assertNotIn("_inline_attachments", mail)

    def test_html_and_both_formats(self):
        messages, _ = run_tool(
            MailGetTool, {"mail_id": "M", "body_format": "html"}, [ok(MAIL_SAMPLE)]
        )
        mail = messages_by_type(messages, ToolInvokeMessage.MessageType.JSON)[0].message.json_object
        self.assertEqual(mail["body_text"], "")
        self.assertEqual(mail["body_html"], "<html>body</html>")

        messages, _ = run_tool(
            MailGetTool, {"mail_id": "M", "body_format": "both"}, [ok(MAIL_SAMPLE)]
        )
        mail = messages_by_type(messages, ToolInvokeMessage.MessageType.JSON)[0].message.json_object
        self.assertEqual(mail["body_text"], "aaaaaa\n\n")
        self.assertEqual(mail["body_html"], "<html>body</html>")

    def test_missing_mail_id_rejected(self):
        with self.assertRaises(ValueError):
            run_tool(MailGetTool, {}, [ok(MAIL_SAMPLE)])


class AttachmentGetToolTest(unittest.TestCase):
    def test_downloads_all_attachments_as_separate_files(self):
        messages, http = run_tool(
            AttachmentGetTool,
            {"mail_id": "O_TMENEG7K8B"},
            [
                ok(MAIL_SAMPLE),
                FakeResponse(b"PPTXDATA", content_type="application/octet-stream"),
                FakeResponse(b"hello", content_type="text/plain"),
            ],
        )

        blobs = messages_by_type(messages, ToolInvokeMessage.MessageType.BLOB)
        self.assertEqual(len(blobs), 2)
        self.assertEqual(blobs[0].message.blob, b"PPTXDATA")
        self.assertEqual(blobs[1].message.blob, b"hello")

        # 添付取得はバイナリ用エンドポイントを使うこと。
        self.assertTrue(http.calls[1][0].endswith("/cgi-bin/cgi_api_binary"))
        self.assertEqual(http.calls[1][1]["hash"], "967587fc")

        result = messages_by_type(messages, ToolInvokeMessage.MessageType.JSON)[0].message.json_object
        self.assertEqual(result["downloaded_count"], 2)
        self.assertEqual(result["failed_count"], 0)
        self.assertEqual(result["files"][0]["filename"], "test.pptx")
        self.assertEqual(result["files"][0]["size"], len(b"PPTXDATA"))
        # メタ情報の contentType を優先すること。
        self.assertTrue(result["files"][0]["mime_type"].endswith("presentationml.presentation"))

    def test_single_hash_downloads_only_that_file(self):
        messages, http = run_tool(
            AttachmentGetTool,
            {"mail_id": "M", "hash": "aa11"},
            [ok(MAIL_SAMPLE), FakeResponse(b"hello", content_type="text/plain")],
        )
        blobs = messages_by_type(messages, ToolInvokeMessage.MessageType.BLOB)
        self.assertEqual(len(blobs), 1)
        self.assertEqual(blobs[0].message.blob, b"hello")
        self.assertEqual(http.calls[1][1]["hash"], "aa11")

    def test_include_inline_adds_embedded_files(self):
        messages, _ = run_tool(
            AttachmentGetTool,
            {"mail_id": "M", "include_inline": True},
            [
                ok(MAIL_SAMPLE),
                FakeResponse(b"a", content_type="application/octet-stream"),
                FakeResponse(b"b", content_type="text/plain"),
                FakeResponse(b"c", content_type="image/png"),
            ],
        )
        self.assertEqual(len(messages_by_type(messages, ToolInvokeMessage.MessageType.BLOB)), 3)
        result = messages_by_type(messages, ToolInvokeMessage.MessageType.JSON)[0].message.json_object
        self.assertTrue(result["files"][2]["inline"])

    def test_no_attachment_reports_cleanly(self):
        messages, _ = run_tool(
            AttachmentGetTool,
            {"mail_id": "M"},
            [ok({**MAIL_SAMPLE, "attachments": [], "inlineAttachments": []})],
        )
        self.assertEqual(len(messages_by_type(messages, ToolInvokeMessage.MessageType.BLOB)), 0)
        text = messages_by_type(messages, ToolInvokeMessage.MessageType.TEXT)[0].message.text
        self.assertIn("添付ファイルはありません", text)
        result = messages_by_type(messages, ToolInvokeMessage.MessageType.JSON)[0].message.json_object
        self.assertEqual(result["downloaded_count"], 0)

    def test_one_failure_does_not_abort_the_rest(self):
        messages, _ = run_tool(
            AttachmentGetTool,
            {"mail_id": "M"},
            [
                ok(MAIL_SAMPLE),
                err(102, "attachment not found"),  # 1 件目は失敗
                FakeResponse(b"hello", content_type="text/plain"),  # 2 件目は成功
            ],
        )
        blobs = messages_by_type(messages, ToolInvokeMessage.MessageType.BLOB)
        self.assertEqual(len(blobs), 1)
        self.assertEqual(blobs[0].message.blob, b"hello")

        result = messages_by_type(messages, ToolInvokeMessage.MessageType.JSON)[0].message.json_object
        self.assertEqual(result["downloaded_count"], 1)
        self.assertEqual(result["failed_count"], 1)
        self.assertFalse(result["files"][0]["success"])
        self.assertIn("attachment not found", result["files"][0]["error"])

    def test_missing_mail_id_rejected(self):
        with self.assertRaises(ValueError):
            run_tool(AttachmentGetTool, {}, [ok(MAIL_SAMPLE)])


if __name__ == "__main__":
    unittest.main(verbosity=2)
