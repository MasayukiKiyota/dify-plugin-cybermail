"""dify_plugin SDK に依存しない層（client / flags / mail）の単体テスト。

実行: python tests/test_client_logic.py
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.client import (  # noqa: E402
    CybermailAPIError,
    CybermailClient,
    CybermailError,
    normalize_base_url,
)
from utils.flags import decode_flag, decode_label, parse_flag_filter, to_jst_iso  # noqa: E402
from utils.mail import format_address, format_address_list, normalize_mail  # noqa: E402


class FakeResponse:
    def __init__(self, payload, status_code=200, content_type="application/json"):
        self.status_code = status_code
        self.headers = {"Content-Type": content_type}
        if isinstance(payload, bytes):
            self.content = payload
            self._json = None
        else:
            self.content = json.dumps(payload).encode("utf-8")
            self._json = payload

    @property
    def text(self):
        return self.content.decode("utf-8", errors="replace")

    def json(self):
        if self._json is None:
            return json.loads(self.text)
        return self._json


class FakeHttp:
    """requests.Session の差し替え。呼び出し履歴を記録し、応答を順に返す。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, data=None, timeout=None):
        self.calls.append((url, dict(data or {})))
        return self.responses.pop(0)


def ok(data):
    return FakeResponse({"status": {"code": 0, "message": ""}, "data": data})


def err(code=1, message="error"):
    return FakeResponse({"status": {"code": code, "message": message}, "data": None})


API_KEY_CREDS = {
    "base_url": "https://example.cybermail.jp",
    "auth_method": "api_key",
    "user_id": "adm@example.co.jp",
    "api_key": "KEY123",
}

PASSWORD_CREDS = {
    "base_url": "https://example.cybermail.jp",
    "auth_method": "password",
    "user_id": "adm@example.co.jp",
    "password": "p@ssw0rd",
}


class MemoryStorage:
    def __init__(self, initial=None):
        self.data = dict(initial or {})

    def get(self, key):
        if key not in self.data:
            raise KeyError(key)
        return self.data[key]

    def set(self, key, value):
        self.data[key] = value


class BaseUrlTest(unittest.TestCase):
    def test_normalizes_variants(self):
        for raw in (
            "https://example.cybermail.jp",
            "https://example.cybermail.jp/",
            "https://example.cybermail.jp/cgi-bin",
            "https://example.cybermail.jp/cgi-bin/cgi_api",
            "https://example.cybermail.jp/cgi-bin/cgi_api_binary",
            "example.cybermail.jp",
        ):
            self.assertEqual(normalize_base_url(raw), "https://example.cybermail.jp", raw)

    def test_rejects_empty(self):
        with self.assertRaises(CybermailError):
            normalize_base_url("")


class CredentialValidationTest(unittest.TestCase):
    def test_api_key_method_requires_api_key(self):
        with self.assertRaises(CybermailError):
            CybermailClient({**API_KEY_CREDS, "api_key": ""})

    def test_password_method_requires_password(self):
        with self.assertRaises(CybermailError):
            CybermailClient({**PASSWORD_CREDS, "password": ""})

    def test_user_id_always_required(self):
        with self.assertRaises(CybermailError):
            CybermailClient({**API_KEY_CREDS, "user_id": ""})

    def test_unknown_auth_method(self):
        with self.assertRaises(CybermailError):
            CybermailClient({**API_KEY_CREDS, "auth_method": "oauth"})


class AuthParamTest(unittest.TestCase):
    """API ごとに揺れるユーザ指定パラメータ名が正しく付くこと。"""

    def _call(self, creds, api_name, responses=None):
        client = CybermailClient(creds)
        client._http = FakeHttp(responses or [ok([])])
        client.call(api_name, {"folder_id": "@"})
        return client._http.calls

    def test_system_mail_list_uses_lowercase_user_id(self):
        calls = self._call(API_KEY_CREDS, "Mail.SystemMailListGet")
        _, payload = calls[0]
        self.assertEqual(payload["API_KEY"], "KEY123")
        self.assertEqual(payload["user_id"], "adm@example.co.jp")
        self.assertNotIn("API_USERID", payload)

    def test_mail_advance_get_uses_api_userid(self):
        calls = self._call(API_KEY_CREDS, "Mail.MailAdvanceGet")
        _, payload = calls[0]
        self.assertEqual(payload["API_USERID"], "adm@example.co.jp")
        self.assertNotIn("user_id", payload)

    def test_session_auth_sends_no_user_param(self):
        client = CybermailClient(PASSWORD_CREDS)
        client._http = FakeHttp([ok("$SESSION"), ok([])])
        client.call("Mail.MailAdvanceGet", {"folder_id": "@"})
        login_payload = client._http.calls[0][1]
        self.assertEqual(login_payload["API_NAME"], "Core.Login")
        api_payload = client._http.calls[1][1]
        self.assertEqual(api_payload["API_SESSION"], "$SESSION")
        self.assertNotIn("user_id", api_payload)
        self.assertNotIn("API_USERID", api_payload)

    def test_key_check_uses_lowercase_param(self):
        client = CybermailClient(API_KEY_CREDS)
        client._http = FakeHttp([ok(1)])
        self.assertTrue(client.check_api_key())
        _, payload = client._http.calls[0]
        self.assertEqual(payload["api_key"], "KEY123")

    def test_empty_values_are_dropped(self):
        client = CybermailClient(API_KEY_CREDS)
        client._http = FakeHttp([ok([])])
        client.call("Mail.SystemMailListGet", {"folder_id": "@", "flag_filter": None, "sort_by": ""})
        _, payload = client._http.calls[0]
        self.assertNotIn("flag_filter", payload)
        self.assertNotIn("sort_by", payload)


class ErrorHandlingTest(unittest.TestCase):
    def test_non_zero_status_raises(self):
        client = CybermailClient(API_KEY_CREDS)
        client._http = FakeHttp([err(101, "invalid mail id")])
        with self.assertRaises(CybermailAPIError) as ctx:
            client.call("Mail.MailAdvanceGet", {"mail_id": "X"})
        self.assertEqual(ctx.exception.code, 101)
        self.assertIn("invalid mail id", str(ctx.exception))

    def test_html_response_raises_readable_error(self):
        client = CybermailClient(API_KEY_CREDS)
        client._http = FakeHttp([FakeResponse(b"<html>404</html>", content_type="text/html")])
        with self.assertRaises(CybermailError) as ctx:
            client.call("Mail.MailAdvanceGet", {})
        self.assertIn("Base URL", str(ctx.exception))

    def test_http_error_status(self):
        client = CybermailClient(API_KEY_CREDS)
        client._http = FakeHttp([FakeResponse({}, status_code=500)])
        with self.assertRaises(CybermailError):
            client.call("Mail.MailAdvanceGet", {})


class BinaryTest(unittest.TestCase):
    def test_binary_returns_content(self):
        client = CybermailClient(API_KEY_CREDS)
        client._http = FakeHttp(
            [FakeResponse(b"PK\x03\x04data", content_type="application/zip")]
        )
        content, content_type = client.call_binary("Mail.AttachmentGet", {"hash": "abc"})
        self.assertEqual(content, b"PK\x03\x04data")
        self.assertEqual(content_type, "application/zip")
        url, _ = client._http.calls[0]
        self.assertTrue(url.endswith("/cgi-bin/cgi_api_binary"))

    def test_binary_endpoint_json_error_is_raised_not_returned(self):
        """バイナリ用エンドポイントがエラー JSON を返した場合、ファイルとして返さない。"""
        client = CybermailClient(API_KEY_CREDS)
        client._http = FakeHttp([err(102, "attachment not found")])
        with self.assertRaises(CybermailAPIError):
            client.call_binary("Mail.AttachmentGet", {"hash": "abc"})

    def test_binary_error_json_with_wrong_content_type(self):
        """Content-Type が octet-stream でも本文が status JSON ならエラーにする。"""
        body = json.dumps({"status": {"code": 5, "message": "ng"}, "data": None}).encode()
        client = CybermailClient(API_KEY_CREDS)
        client._http = FakeHttp([FakeResponse(body, content_type="application/octet-stream")])
        with self.assertRaises(CybermailAPIError):
            client.call_binary("Mail.AttachmentGet", {"hash": "abc"})


class SessionTest(unittest.TestCase):
    def test_cached_session_is_reused_without_login(self):
        storage = MemoryStorage()
        client = CybermailClient(PASSWORD_CREDS, storage=storage)
        client._http = FakeHttp([ok("$SESSION"), ok([])])
        client.call("Mail.MailListGet", {"folder_id": "@"})
        # 2 回目は別インスタンスでもキャッシュから復元され、ログインが走らない。
        client2 = CybermailClient(PASSWORD_CREDS, storage=storage)
        client2._http = FakeHttp([ok([])])
        client2.call("Mail.MailListGet", {"folder_id": "@"})
        self.assertEqual(client2._http.calls[0][1]["API_NAME"], "Mail.MailListGet")
        self.assertEqual(client2._http.calls[0][1]["API_SESSION"], "$SESSION")

    def test_expired_cached_session_triggers_relogin_and_retry(self):
        storage = MemoryStorage()
        client = CybermailClient(PASSWORD_CREDS, storage=storage)
        client._session_cache_key()
        storage.data[client._session_cache_key()] = b"$STALE"
        client._http = FakeHttp(
            [
                err(9, "session expired"),  # 1 回目の API 呼び出し
                ok(0),  # Core.SessionCheck -> 無効
                ok("$FRESH"),  # Core.Login
                ok([{"id": "M1"}]),  # 再試行
            ]
        )
        data = client.call("Mail.MailListGet", {"folder_id": "@"})
        self.assertEqual(data, [{"id": "M1"}])
        names = [payload["API_NAME"] for _, payload in client._http.calls]
        self.assertEqual(
            names,
            ["Mail.MailListGet", "Core.SessionCheck", "Core.Login", "Mail.MailListGet"],
        )
        self.assertEqual(storage.data[client._session_cache_key()], b"$FRESH")

    def test_valid_session_does_not_retry_business_error(self):
        """セッションが生きているなら、業務エラーは再ログインせずそのまま返す。"""
        storage = MemoryStorage()
        client = CybermailClient(PASSWORD_CREDS, storage=storage)
        storage.data[client._session_cache_key()] = b"$LIVE"
        client._http = FakeHttp([err(101, "no such mail"), ok(1)])
        with self.assertRaises(CybermailAPIError):
            client.call("Mail.MailAdvanceGet", {"mail_id": "X"})
        names = [payload["API_NAME"] for _, payload in client._http.calls]
        self.assertEqual(names, ["Mail.MailAdvanceGet", "Core.SessionCheck"])

    def test_fresh_login_failure_is_not_retried(self):
        client = CybermailClient(PASSWORD_CREDS, storage=MemoryStorage())
        client._http = FakeHttp([ok("$SESSION"), err(101, "no such mail")])
        with self.assertRaises(CybermailAPIError):
            client.call("Mail.MailAdvanceGet", {"mail_id": "X"})
        self.assertEqual(len(client._http.calls), 2)

    def test_api_key_auth_never_logs_in(self):
        client = CybermailClient(API_KEY_CREDS, storage=MemoryStorage())
        client._http = FakeHttp([err(101, "no such mail")])
        with self.assertRaises(CybermailAPIError):
            client.call("Mail.MailAdvanceGet", {"mail_id": "X"})
        self.assertEqual(len(client._http.calls), 1)

    def test_password_is_not_part_of_cache_key(self):
        a = CybermailClient(PASSWORD_CREDS)
        b = CybermailClient({**PASSWORD_CREDS, "password": "different"})
        self.assertEqual(a._session_cache_key(), b._session_cache_key())
        self.assertLessEqual(len(a._session_cache_key()), 64)


class FlagTest(unittest.TestCase):
    def test_decode_flag_from_spec_example(self):
        # 仕様書 Mail.MailListGet の例にある flag 値 67109120 = 0x04000100。
        # 0x00000100(未読) が立つ。0x04000000 は仕様書のフラグ表に無い内部ビットで、
        # デコード対象外として無視されることを確認する。
        flags = decode_flag(67109120)
        self.assertTrue(flags["unread"])
        self.assertFalse(flags["pinned"])
        self.assertFalse(flags["important"])
        self.assertFalse(flags["has_attachment"])
        # 仕様書 Mail.MailInfoGet の例の 67108864 = 0x04000000 は全て False。
        self.assertFalse(any(decode_flag(67108864).values()))
        # 重要(0x10)+添付(0x1) の組み合わせ。
        combined = decode_flag(0x11)
        self.assertTrue(combined["important"])
        self.assertTrue(combined["has_attachment"])
        self.assertFalse(combined["unread"])

    def test_decode_flag_invalid_value(self):
        self.assertFalse(any(decode_flag(None).values()))
        self.assertFalse(any(decode_flag("abc").values()))

    def test_decode_label(self):
        self.assertEqual(decode_label(0), "なし")
        self.assertEqual(decode_label(3), "赤色")
        self.assertEqual(decode_label(99), "99")

    def test_parse_flag_filter(self):
        self.assertEqual(parse_flag_filter("0x00000100"), "0x00000100")
        self.assertEqual(parse_flag_filter(256), "0x00000100")
        self.assertEqual(parse_flag_filter("17"), "0x00000011")
        self.assertIsNone(parse_flag_filter(""))
        self.assertIsNone(parse_flag_filter(None))
        with self.assertRaises(ValueError):
            parse_flag_filter("unread")

    def test_to_jst_iso(self):
        # 1626073885 は UTC 2021-07-12T07:11:25 なので JST では 16:11:25。
        self.assertEqual(to_jst_iso(1626073885), "2021-07-12T16:11:25+09:00")
        self.assertIsNone(to_jst_iso(None))
        self.assertIsNone(to_jst_iso("not-a-number"))


class MailNormalizeTest(unittest.TestCase):
    SAMPLE = {
        "reply_to": '"adm" <adm@example.co.jp>',
        "attachments": [
            {
                "filename": "test.pptx",
                "hash": "967587fc5769d2fd660a0cefb14c0698",
                "size": 79479,
                "contentType": "application/vnd.openxmlformats-officedocument."
                "presentationml.presentation",
            }
        ],
        "bcc": [],
        "subject": "テストメール",
        "from": {"addr": "adm@example.co.jp", "nick": "adm"},
        "inlineAttachments": [
            {"filename": "image.png", "hash": "aab5", "size": 3175, "contentType": "image/png"}
        ],
        "cc": [],
        "to": [{"addr": "adm@example.co.jp", "nick": "adm"}],
        "date": 1626064602,
        "content": {"html": "<html>body</html>", "text": "aaaaaa\n\n"},
    }

    def test_normalize_mail_matches_spec_sample(self):
        mail = normalize_mail(self.SAMPLE, "O_TMENEG7K8B", "@")
        self.assertEqual(mail["subject"], "テストメール")
        self.assertEqual(mail["from"], '"adm" <adm@example.co.jp>')
        self.assertEqual(mail["to"], ['"adm" <adm@example.co.jp>'])
        self.assertEqual(mail["cc"], [])
        self.assertEqual(mail["date"], "2021-07-12T13:36:42+09:00")
        self.assertEqual(mail["timestamp"], 1626064602)
        self.assertEqual(mail["body_text"], "aaaaaa\n\n")
        self.assertEqual(mail["body_html"], "<html>body</html>")
        self.assertEqual(mail["attachment_count"], 1)
        self.assertEqual(mail["inline_attachment_count"], 1)
        self.assertEqual(mail["attachments"][0]["hash"], "967587fc5769d2fd660a0cefb14c0698")
        self.assertFalse(mail["attachments"][0]["inline"])

    def test_plain_text_content(self):
        mail = normalize_mail({**self.SAMPLE, "content": "just text"}, "M", "@")
        self.assertEqual(mail["body_text"], "just text")
        self.assertEqual(mail["body_html"], "")

    def test_address_helpers_accept_strings(self):
        self.assertEqual(format_address("adm@example.co.jp"), "adm@example.co.jp")
        self.assertEqual(format_address({"addr": "a@b.jp", "nick": ""}), "a@b.jp")
        self.assertEqual(format_address_list(""), [])
        self.assertEqual(format_address_list("a@b.jp"), ["a@b.jp"])

    def test_missing_fields_do_not_crash(self):
        mail = normalize_mail({}, "M", "@")
        self.assertEqual(mail["subject"], "")
        self.assertEqual(mail["attachments"], [])
        self.assertIsNone(mail["date"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
