"""Tool 実装の結合テスト。HTTP 層だけ差し替えて _invoke を実際に回す。

dify_plugin SDK が必要なため、SDK を入れた環境で実行する:
    .venv/Scripts/python.exe tests/test_tools.py
"""

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

PLUGIN_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_DIR))

from dify_plugin.entities.tool import ToolInvokeMessage, ToolRuntime  # noqa: E402

from tools.attachment_get import AttachmentGetTool  # noqa: E402
from tools.mail_draft_create import MailDraftCreateTool  # noqa: E402
from tools.mail_flag_set import MailFlagSetTool  # noqa: E402
from tools.mail_get import MailGetTool  # noqa: E402
from tools.mail_list import MailListTool  # noqa: E402
from utils import plugin as plugin_utils  # noqa: E402
from utils.client import CybermailClient, CybermailError  # noqa: E402

API_KEY_CREDS = {
    "base_url": "https://example.cybermail.jp",
    "auth_method": "api_key",
    "user_id": "adm@example.co.jp",
    "api_key": "KEY123",
}

# API_SESSION 専用の API（Mail.MailFlagModify 等）を通すためのクレデンシャル。
PASSWORD_CREDS = {
    "base_url": "https://example.cybermail.jp",
    "auth_method": "password",
    "user_id": "adm@example.co.jp",
    "password": "pw",
}

SESSION = "$1234567890.adm@example.co.jp::example.cybermail.jp:jp"


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


def run_tool(tool_cls, parameters, responses, credentials=API_KEY_CREDS):
    """Tool を実際に生成し、HTTP だけ差し替えて _invoke を実行する。

    パスワード方式を指定した場合は最初に Core.Login が走るため、
    responses の先頭にログイン応答を置くこと。
    """
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
            runtime=ToolRuntime(credentials=credentials, user_id="tester", session_id="s1"),
            session=SimpleNamespace(storage=None),
        )
        messages = list(tool._invoke(parameters))
    finally:
        for module in patched_modules:
            module.create_client = original
    return messages, http


def messages_by_type(messages, message_type):
    return [m for m in messages if m.type == message_type]


def variables_of(messages):
    """VARIABLE メッセージを {変数名: 値} に畳む。"""
    return {
        m.message.variable_name: m.message.variable_value
        for m in messages_by_type(messages, ToolInvokeMessage.MessageType.VARIABLE)
    }


def json_of(messages, index=0):
    return messages_by_type(messages, ToolInvokeMessage.MessageType.JSON)[index].message.json_object


def assert_variables_match_json(case, messages):
    """output_schema 由来の出力変数が JSON と同じ内容で埋まっていること。"""
    result = json_of(messages)
    variables = variables_of(messages)
    case.assertEqual(variables, {k: v for k, v in result.items() if not k.startswith("_")})
    # text / files / json は Dify の組み込み出力なので変数化してはいけない。
    case.assertEqual(set(variables) & {"text", "files", "json"}, set())


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

    def test_output_variables_are_set(self):
        messages, _ = run_tool(MailListTool, {"folder_id": "@"}, [ok(LIST_SAMPLE)])
        assert_variables_match_json(self, messages)

        variables = variables_of(messages)
        self.assertEqual(variables["folder_id"], "@")
        self.assertEqual(variables["count"], 2)
        self.assertEqual(variables["mails"][0]["mail_id"], "X_TOQNEGF57F")


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

    def test_output_variables_are_set(self):
        messages, _ = run_tool(MailGetTool, {"mail_id": "O_TMENEG7K8B"}, [ok(MAIL_SAMPLE)])
        assert_variables_match_json(self, messages)

        variables = variables_of(messages)
        self.assertEqual(variables["subject"], "テストメール")
        self.assertEqual(variables["body_text"], "aaaaaa\n\n")
        self.assertEqual(variables["attachment_count"], 2)
        self.assertNotIn("_inline_attachments", variables)


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
        self.assertEqual(result["attachments"][0]["filename"], "test.pptx")
        self.assertEqual(result["attachments"][0]["size"], len(b"PPTXDATA"))
        # メタ情報の contentType を優先すること。
        self.assertTrue(result["attachments"][0]["mime_type"].endswith("presentationml.presentation"))

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
        self.assertTrue(result["attachments"][2]["inline"])

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
        self.assertFalse(result["attachments"][0]["success"])
        self.assertIn("attachment not found", result["attachments"][0]["error"])

    def test_missing_mail_id_rejected(self):
        with self.assertRaises(ValueError):
            run_tool(AttachmentGetTool, {}, [ok(MAIL_SAMPLE)])

    def test_output_variables_are_set_without_shadowing_files(self):
        messages, _ = run_tool(
            AttachmentGetTool,
            {"mail_id": "O_TMENEG7K8B"},
            [
                ok(MAIL_SAMPLE),
                FakeResponse(b"PPTXDATA", content_type="application/octet-stream"),
                FakeResponse(b"hello", content_type="text/plain"),
            ],
        )
        assert_variables_match_json(self, messages)

        variables = variables_of(messages)
        self.assertEqual(variables["downloaded_count"], 2)
        self.assertEqual(variables["attachments"][0]["filename"], "test.pptx")

    def test_output_variables_are_set_when_no_attachment(self):
        messages, _ = run_tool(
            AttachmentGetTool,
            {"mail_id": "M"},
            [ok({**MAIL_SAMPLE, "attachments": [], "inlineAttachments": []})],
        )
        assert_variables_match_json(self, messages)
        self.assertEqual(variables_of(messages)["attachments"], [])


INFO_SAMPLE = {
    "label": 0,
    "sender_nickname": "adm",
    "flag": 0x04000000,  # 未読でも重要でもない状態
    "subject": "テストメール",
    "size": 1,
    "sender_email": "adm@example.co.jp",
    "ctime": 1626073885,
}


def info(flag):
    return ok({**INFO_SAMPLE, "flag": flag})


def run_flag_tool(parameters, responses):
    """フラグ操作 Tool はパスワード方式専用なので、先頭にログイン応答を補って実行する。

    通常操作は Core.Login → Mail.MailFlagModify の 2 回。診断モード（custom）だけ
    その前後に Mail.MailInfoGet が入り、4 回になる。
    """
    return run_tool(
        MailFlagSetTool, parameters, [ok(SESSION)] + responses, credentials=PASSWORD_CREDS
    )


def run_custom(parameters, pre_flag=0x04000000, post_flag=0x04000000, post=None):
    """診断モード用。変更前後の Mail.MailInfoGet 応答を補う。"""
    return run_flag_tool(
        {**parameters, "action": "custom"},
        [info(pre_flag), ok(None), post if post is not None else info(post_flag)],
    )


def api_names(http):
    return [payload["API_NAME"] for _, payload in http.calls]


class MailFlagSetToolTest(unittest.TestCase):
    def test_mark_read_removes_the_unread_bit(self):
        _, http = run_flag_tool(
            {"mail_id": "X_TOQNEGF57F", "action": "mark_read"}, [ok(None)]
        )
        payload = http.calls[1][1]
        self.assertEqual(payload["API_NAME"], "Mail.MailFlagModify")
        self.assertEqual(payload["API_SESSION"], SESSION)
        self.assertEqual(payload["mail_id"], "X_TOQNEGF57F")
        self.assertEqual(payload["folder_id"], "@")
        self.assertEqual(payload["flag"], 256)
        # 既読にする＝未読フラグを「削除」する。
        self.assertEqual(payload["unset"], 1)

    def test_mark_unread_keeps_unset_zero_in_the_payload(self):
        """unset=0 が空値として捨てられないこと（付与が全て無効化される回帰）。"""
        _, http = run_flag_tool(
            {"mail_id": "M", "action": "mark_unread", "folder_id": "@.trash"}, [ok(None)]
        )
        payload = http.calls[1][1]
        self.assertIn("unset", payload)
        self.assertEqual(payload["unset"], 0)
        self.assertEqual(payload["flag"], 256)
        self.assertEqual(payload["folder_id"], "@.trash")

    def test_important_actions_use_the_important_bit(self):
        _, http = run_flag_tool({"mail_id": "M", "action": "add_important"}, [ok(None)])
        self.assertEqual(http.calls[1][1]["flag"], 16)
        self.assertEqual(http.calls[1][1]["unset"], 0)

        _, http = run_flag_tool({"mail_id": "M", "action": "remove_important"}, [ok(None)])
        self.assertEqual(http.calls[1][1]["flag"], 16)
        self.assertEqual(http.calls[1][1]["unset"], 1)

    def test_normal_action_does_not_read_the_state(self):
        """通常操作では Mail.MailInfoGet を呼ばず、API 呼び出しを 1 回に抑えること。"""
        messages, http = run_flag_tool({"mail_id": "M", "action": "mark_read"}, [ok(None)])
        self.assertEqual(api_names(http), ["Core.Login", "Mail.MailFlagModify"])

        result = json_of(messages)
        self.assertTrue(result["success"])
        self.assertFalse(result["verified"])
        # 操作が意図した結果は確実に分かる。
        self.assertFalse(result["unread"])
        # 読んでいない項目は None（未取得）で、False と区別できること。
        self.assertIsNone(result["important"])
        self.assertIsNone(result["flag_before"])
        self.assertIsNone(result["flag_after"])
        self.assertEqual(result["subject"], "")

        # 件名が無いので mail_id で示す。
        text = messages_by_type(messages, ToolInvokeMessage.MessageType.TEXT)[0].message.text
        self.assertIn("M", text)
        self.assertIn("既読にしました", text)
        self.assertNotIn("flag:", text)

    def test_intended_state_per_action(self):
        for action, key, expected in [
            ("mark_read", "unread", False),
            ("mark_unread", "unread", True),
            ("add_important", "important", True),
            ("remove_important", "important", False),
        ]:
            with self.subTest(action=action):
                messages, _ = run_flag_tool({"mail_id": "M", "action": action}, [ok(None)])
                result = json_of(messages)
                self.assertEqual(result[key], expected)
                other = "important" if key == "unread" else "unread"
                self.assertIsNone(result[other])

    def test_custom_action_reads_state_before_and_after(self):
        """診断モードだけ変更前後の状態を読むこと。"""
        _, http = run_custom({"mail_id": "M", "flag": "16", "unset": "0"})
        self.assertEqual(
            api_names(http),
            [
                "Core.Login",
                "Mail.MailInfoGet",
                "Mail.MailFlagModify",
                "Mail.MailInfoGet",
            ],
        )

    def test_custom_action_reports_raw_flag_values(self):
        """decode_flag が展開しない未文書ビットも見えるよう、生の値を返すこと。"""
        messages, _ = run_custom(
            {"mail_id": "M", "flag": "16", "unset": "0"},
            pre_flag=0x04000100,
            post_flag=0x04000110,
        )
        result = json_of(messages)
        self.assertTrue(result["verified"])
        self.assertEqual(result["flag_before"], 0x04000100)
        self.assertEqual(result["flag_after"], 0x04000110)
        self.assertEqual(result["flag_before_hex"], "0x04000100")
        self.assertEqual(result["flag_after_hex"], "0x04000110")
        # 生の値から未読・重要が復元されること。
        self.assertTrue(result["unread"])
        self.assertTrue(result["important"])
        self.assertEqual(result["subject"], "テストメール")

        text = messages_by_type(messages, ToolInvokeMessage.MessageType.TEXT)[0].message.text
        self.assertIn("0x04000100", text)
        self.assertIn("0x04000110", text)

    def test_custom_action_sends_values_verbatim(self):
        """0x 付き16進も10進に変換せず、入力どおり送ること。"""
        _, http = run_custom({"mail_id": "M", "flag": "0x00000010", "unset": "1"})
        payload = http.calls[2][1]
        self.assertEqual(payload["flag"], "0x00000010")
        self.assertEqual(payload["unset"], "1")

    def test_custom_action_omits_empty_values(self):
        """空欄なら flag / unset パラメータ自体を送らないこと（既定動作の確認用）。"""
        _, http = run_custom({"mail_id": "M", "flag": "", "unset": ""})
        payload = http.calls[2][1]
        self.assertNotIn("flag", payload)
        self.assertNotIn("unset", payload)

    def test_custom_action_ignores_the_preset_mapping(self):
        """custom では ACTIONS の変換（未読/重要のビット）を通らないこと。"""
        _, http = run_custom({"mail_id": "M", "flag": "512", "unset": "0"})
        self.assertEqual(http.calls[2][1]["flag"], "512")

    def test_custom_verification_failure_does_not_fail_the_change(self):
        messages, _ = run_custom(
            {"mail_id": "M", "flag": "256", "unset": "1"},
            pre_flag=0x04000100,
            post=err(101, "mail not found"),
        )
        result = json_of(messages)
        self.assertTrue(result["success"])
        self.assertFalse(result["verified"])
        self.assertIsNone(result["unread"])
        # 変更前は読めているので、そちらは返せる。
        self.assertEqual(result["flag_before_hex"], "0x04000100")
        self.assertIsNone(result["flag_after"])

        texts = [
            m.message.text
            for m in messages_by_type(messages, ToolInvokeMessage.MessageType.TEXT)
        ]
        self.assertTrue(any("確認できませんでした" in t for t in texts))

    def test_custom_pre_read_failure_does_not_stop_the_change(self):
        messages, http = run_flag_tool(
            {"mail_id": "M", "action": "custom", "flag": "256", "unset": "1"},
            [err(101, "mail not found"), ok(None), info(0x04000000)],
        )
        self.assertEqual(http.calls[2][1]["API_NAME"], "Mail.MailFlagModify")
        result = json_of(messages)
        self.assertTrue(result["success"])
        self.assertIsNone(result["flag_before"])
        self.assertEqual(result["flag_before_hex"], "")
        self.assertEqual(result["flag_after_hex"], "0x04000000")

    def test_api_key_auth_is_rejected_before_any_request(self):
        # responses が空なので、HTTP を呼んだ場合は IndexError になり区別できる。
        with self.assertRaises(ValueError) as caught:
            run_tool(MailFlagSetTool, {"mail_id": "M", "action": "mark_read"}, [])
        self.assertIn("API_KEY", str(caught.exception))

    def test_invalid_parameters_rejected(self):
        with self.assertRaises(ValueError):
            run_flag_tool({"action": "mark_read"}, [])
        with self.assertRaises(ValueError):
            run_flag_tool({"mail_id": "M", "action": "delete"}, [])

    def test_output_variables_are_set(self):
        messages, _ = run_flag_tool({"mail_id": "M", "action": "mark_read"}, [ok(None)])
        assert_variables_match_json(self, messages)

        variables = variables_of(messages)
        self.assertEqual(variables["action"], "mark_read")
        self.assertTrue(variables["success"])
        self.assertFalse(variables["unread"])

    def test_output_variables_are_set_in_custom_mode(self):
        messages, _ = run_custom(
            {"mail_id": "M", "flag": "16", "unset": "0"}, post_flag=0x04000010
        )
        assert_variables_match_json(self, messages)
        self.assertEqual(variables_of(messages)["flag_after_hex"], "0x04000010")


COMPOSE_URL = "http://example.cybermail.jp/cgi-bin/genMail?HTTP_COOKIE=key%3D$123.adm"


def run_draft_tool(parameters, responses=None):
    """下書き作成 Tool はパスワード方式専用なので、先頭にログイン応答を補って実行する。"""
    return run_tool(
        MailDraftCreateTool,
        parameters,
        [ok(SESSION)] + (responses if responses is not None else [ok(COMPOSE_URL)]),
        credentials=PASSWORD_CREDS,
    )


class MailDraftCreateToolTest(unittest.TestCase):
    def test_returns_compose_url(self):
        messages, http = run_draft_tool(
            {"to": "adm@example.co.jp", "subject": "TestMail", "content": "テストです"}
        )
        self.assertEqual(api_names(http), ["Core.Login", "Compose.ComposeInvoke"])
        payload = http.calls[1][1]
        self.assertEqual(payload["API_SESSION"], SESSION)
        self.assertEqual(payload["to"], "adm@example.co.jp")
        self.assertEqual(payload["subject"], "TestMail")
        self.assertEqual(payload["content"], "テストです")

        result = json_of(messages)
        self.assertTrue(result["success"])
        self.assertEqual(result["compose_url"], COMPOSE_URL)
        self.assertNotIn("content", result)

        links = messages_by_type(messages, ToolInvokeMessage.MessageType.LINK)
        self.assertEqual(links[0].message.text, COMPOSE_URL)
        text = messages_by_type(messages, ToolInvokeMessage.MessageType.TEXT)[0].message.text
        self.assertIn("まだ送信されていません", text)

    def test_address_separators_are_normalized(self):
        _, http = run_draft_tool(
            {"to": "a@x.jp; b@x.jp\nc@x.jp、", "bcc": " d@x.jp ,, e@x.jp "}
        )
        payload = http.calls[1][1]
        self.assertEqual(payload["to"], "a@x.jp,b@x.jp,c@x.jp")
        self.assertEqual(payload["bcc"], "d@x.jp,e@x.jp")

    def test_empty_optional_parameters_are_not_sent(self):
        _, http = run_draft_tool({"to": "a@x.jp", "cc": "", "exclude": " ", "signature": ""})
        payload = http.calls[1][1]
        for name in ("cc", "bcc", "exclude", "subject", "content", "signature"):
            self.assertNotIn(name, payload)

    def test_signature_is_sent(self):
        _, http = run_draft_tool({"cc": "a@x.jp", "signature": "1"})
        self.assertEqual(http.calls[1][1]["signature"], "1")

    def test_body_whitespace_is_preserved(self):
        body = "  お疲れ様です。\n\n  - 項目1\n"
        _, http = run_draft_tool({"to": "a@x.jp", "content": body})
        self.assertEqual(http.calls[1][1]["content"], body)

    def test_recipient_required_before_any_request(self):
        # responses が空なので、HTTP を呼んだ場合は IndexError になり区別できる。
        with self.assertRaises(ValueError):
            run_tool(
                MailDraftCreateTool,
                {"to": " ", "cc": "", "subject": "x"},
                [],
                credentials=PASSWORD_CREDS,
            )

    def test_api_key_auth_is_rejected_before_any_request(self):
        with self.assertRaises(ValueError) as caught:
            run_tool(MailDraftCreateTool, {"to": "a@x.jp"}, [])
        self.assertIn("API_KEY", str(caught.exception))

    def test_missing_url_is_an_error(self):
        for data in (None, "", {"url": COMPOSE_URL}):
            with self.subTest(data=data):
                with self.assertRaises(CybermailError):
                    run_draft_tool({"to": "a@x.jp"}, [ok(data)])

    def test_output_variables_are_set(self):
        messages, _ = run_draft_tool({"to": "a@x.jp", "subject": "件名"})
        assert_variables_match_json(self, messages)
        self.assertEqual(variables_of(messages)["compose_url"], COMPOSE_URL)


if __name__ == "__main__":
    unittest.main(verbosity=2)
