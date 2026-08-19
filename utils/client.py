"""CYBERMAILΣ Web API クライアント。

全 Tool はこのモジュール経由で API を呼ぶ（Tool 側に HTTP を書かない）。

API の癖として押さえている点:

* エンドポイントは 2 つ。JSON 応答は ``/cgi-bin/cgi_api``、添付バイナリは
  ``/cgi-bin/cgi_api_binary``。いずれも POST(form-urlencoded) で ``API_NAME`` を指定する。
* 応答は常に ``{"status": {"code": N, "message": "..."}, "data": ...}``。``code != 0`` は失敗。
* 認証パラメータ名が API ごとに揺れている（``user_id`` / ``API_USERID``、
  ``Core.KeyCheck`` と ``Core.SessionCheck`` だけは小文字の ``api_key`` / ``api_session``）。
  この吸収は本モジュールの責務とし、呼び出し側は意識しない。
"""

import hashlib
import json
from typing import Any

import requests

DEFAULT_TIMEOUT = 30

AUTH_API_KEY = "api_key"
AUTH_PASSWORD = "password"

# API_KEY 方式で対象ユーザを指定する際のパラメータ名。API ごとに異なるため表で持つ。
# ここに無い API は「ユーザ指定不要」とみなす。
_USER_PARAM_BY_API: dict[str, str] = {
    "Mail.SystemMailListGet": "user_id",
    "Mail.SystemMailBoxListGet": "user_id",
    "Mail.MailAdvanceGet": "API_USERID",
    "Mail.AttachmentGet": "API_USERID",
    "Mail.AttachmentPack": "API_USERID",
    "Mail.MailReadReceiptSend": "API_USERID",
}


class CybermailError(Exception):
    """設定不備やネットワーク障害など、API 応答以前の失敗。"""


class CybermailAPIError(CybermailError):
    """``status.code != 0`` で返ってきた API エラー。"""

    def __init__(self, code: int, message: str, api_name: str = "") -> None:
        self.code = code
        self.message = message
        self.api_name = api_name
        prefix = f"{api_name}: " if api_name else ""
        super().__init__(f"{prefix}CYBERMAIL API error (code={code}) {message}".strip())


def normalize_base_url(raw: str) -> str:
    """入力された Base URL を ``https://host`` 形式に正規化する。

    末尾スラッシュや ``/cgi-bin``、``/cgi-bin/cgi_api`` まで貼られていても受け付ける。
    """
    url = (raw or "").strip()
    if not url:
        raise CybermailError("Base URL が設定されていません。")
    if "://" not in url:
        url = "https://" + url
    url = url.rstrip("/")
    for suffix in ("/cgi-bin/cgi_api_binary", "/cgi-bin/cgi_api", "/cgi-bin"):
        if url.endswith(suffix):
            url = url[: -len(suffix)]
            break
    return url.rstrip("/")


class CybermailClient:
    """認証方式の差異とセッション管理を隠蔽した API クライアント。"""

    def __init__(
        self,
        credentials: dict[str, Any],
        storage: Any = None,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        self.base_url = normalize_base_url(credentials.get("base_url", ""))
        self.auth_method = (credentials.get("auth_method") or AUTH_PASSWORD).strip()
        self.user_id = (credentials.get("user_id") or "").strip()
        self.api_key = (credentials.get("api_key") or "").strip()
        self.password = credentials.get("password") or ""
        self.timeout = timeout
        self._storage = storage
        self._http = requests.Session()
        self._session_token: str | None = None
        self._session_from_cache = False

        if not self.user_id:
            raise CybermailError("ユーザID が設定されていません。")
        if self.auth_method == AUTH_API_KEY:
            if not self.api_key:
                raise CybermailError("認証方式が API_KEY ですが API_KEY が設定されていません。")
        elif self.auth_method == AUTH_PASSWORD:
            if not self.password:
                raise CybermailError(
                    "認証方式がユーザID/パスワードですが パスワード が設定されていません。"
                )
        else:
            raise CybermailError(f"未知の認証方式です: {self.auth_method}")

    # ------------------------------------------------------------------ URL / HTTP

    @property
    def is_api_key_auth(self) -> bool:
        return self.auth_method == AUTH_API_KEY

    @property
    def _json_endpoint(self) -> str:
        return f"{self.base_url}/cgi-bin/cgi_api"

    @property
    def _binary_endpoint(self) -> str:
        return f"{self.base_url}/cgi-bin/cgi_api_binary"

    def _post(self, url: str, api_name: str, params: dict[str, Any]) -> requests.Response:
        payload = {"API_NAME": api_name}
        for key, value in params.items():
            if value is None or value == "":
                continue
            payload[key] = value
        try:
            return self._http.post(url, data=payload, timeout=self.timeout)
        except requests.RequestException as exc:
            raise CybermailError(f"{api_name}: CYBERMAIL への接続に失敗しました: {exc}") from exc

    @staticmethod
    def _unwrap(response: requests.Response, api_name: str) -> Any:
        """``{"status": ..., "data": ...}`` を検証して data を返す。"""
        if response.status_code >= 400:
            raise CybermailError(
                f"{api_name}: HTTP {response.status_code} が返りました。Base URL を確認してください。"
            )
        try:
            body = response.json()
        except ValueError:
            snippet = response.text[:200]
            raise CybermailError(
                f"{api_name}: JSON 以外の応答が返りました。Base URL を確認してください: {snippet!r}"
            ) from None
        return CybermailClient._unwrap_body(body, api_name)

    @staticmethod
    def _unwrap_body(body: Any, api_name: str) -> Any:
        if not isinstance(body, dict) or "status" not in body:
            raise CybermailError(f"{api_name}: 想定外の応答形式です: {str(body)[:200]!r}")
        status = body.get("status") or {}
        code = status.get("code", -1)
        if code != 0:
            raise CybermailAPIError(code, status.get("message", ""), api_name)
        return body.get("data")

    # ------------------------------------------------------------------ セッション

    def _session_cache_key(self) -> str:
        digest = hashlib.sha256(f"{self.base_url}|{self.user_id}".encode()).hexdigest()
        return f"cm_sess_{digest[:32]}"

    def _load_cached_session(self) -> str | None:
        if self._storage is None:
            return None
        try:
            raw = self._storage.get(self._session_cache_key())
        except Exception:
            # 未保存の場合に例外を投げる実装があるため、キャッシュ無しとして扱う。
            return None
        if not raw:
            return None
        return raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)

    def _store_session(self, token: str) -> None:
        if self._storage is None:
            return
        try:
            self._storage.set(self._session_cache_key(), token.encode("utf-8"))
        except Exception:
            # キャッシュできなくても毎回ログインすれば動作するため、失敗は無視する。
            pass

    def login(self) -> str:
        """``Core.Login`` でセッションを取得する（キャッシュを使わない）。"""
        response = self._post(
            self._json_endpoint,
            "Core.Login",
            {"user_id": self.user_id, "password": self.password},
        )
        token = self._unwrap(response, "Core.Login")
        if not isinstance(token, str) or not token:
            raise CybermailError("Core.Login が API_SESSION を返しませんでした。")
        self._session_token = token
        self._session_from_cache = False
        self._store_session(token)
        return token

    def _get_session(self) -> str:
        if self._session_token:
            return self._session_token
        cached = self._load_cached_session()
        if cached:
            self._session_token = cached
            self._session_from_cache = True
            return cached
        return self.login()

    def _session_is_valid(self, token: str) -> bool:
        """``Core.SessionCheck`` でセッションの生死だけを確認する。"""
        try:
            response = self._post(
                self._json_endpoint, "Core.SessionCheck", {"api_session": token}
            )
            return self._unwrap(response, "Core.SessionCheck") == 1
        except CybermailError:
            # 判定できないときは「無効かもしれない」として再ログインを試させる。
            return False

    def check_api_key(self) -> bool:
        """``Core.KeyCheck`` で API_KEY の有効性を確認する（パラメータ名は小文字）。"""
        response = self._post(self._json_endpoint, "Core.KeyCheck", {"api_key": self.api_key})
        return self._unwrap(response, "Core.KeyCheck") == 1

    # ------------------------------------------------------------------ 認証パラメータ

    def _auth_params(self, api_name: str, user_scoped: str | None) -> dict[str, Any]:
        if self.is_api_key_auth:
            params: dict[str, Any] = {"API_KEY": self.api_key}
            user_param = user_scoped or _USER_PARAM_BY_API.get(api_name)
            if user_param:
                params[user_param] = self.user_id
            return params
        return {"API_SESSION": self._get_session()}

    # ------------------------------------------------------------------ 公開 API

    def call(
        self, api_name: str, params: dict[str, Any] | None = None, user_scoped: str | None = None
    ) -> Any:
        """JSON API を呼び出して ``data`` を返す。

        ``data`` は None・スカラ・配列・オブジェクトのいずれもあり得るため、
        呼び出し側で型を確認すること。
        """
        return self._call(api_name, params or {}, user_scoped, binary=False)

    def call_binary(
        self, api_name: str, params: dict[str, Any] | None = None, user_scoped: str | None = None
    ) -> tuple[bytes, str]:
        """バイナリ API を呼び出して ``(本体, Content-Type)`` を返す。"""
        return self._call(api_name, params or {}, user_scoped, binary=True)

    def _call(
        self, api_name: str, params: dict[str, Any], user_scoped: str | None, binary: bool
    ) -> Any:
        url = self._binary_endpoint if binary else self._json_endpoint
        request_params = {**params, **self._auth_params(api_name, user_scoped)}
        response = self._post(url, api_name, request_params)

        try:
            return self._handle(response, api_name, binary)
        except CybermailError:
            # パスワード方式でキャッシュ済みセッションを使っていた場合のみ、
            # セッション失効の可能性を確認して 1 度だけ再ログイン・再試行する。
            if not self._should_retry_with_new_session():
                raise
            self.login()
            retry_params = {**params, **self._auth_params(api_name, user_scoped)}
            retry_response = self._post(url, api_name, retry_params)
            return self._handle(retry_response, api_name, binary)

    def _should_retry_with_new_session(self) -> bool:
        if self.is_api_key_auth or not self._session_from_cache or not self._session_token:
            return False
        return not self._session_is_valid(self._session_token)

    def _handle(self, response: requests.Response, api_name: str, binary: bool) -> Any:
        if not binary:
            return self._unwrap(response, api_name)

        if response.status_code >= 400:
            raise CybermailError(
                f"{api_name}: HTTP {response.status_code} が返りました。Base URL を確認してください。"
            )
        content = response.content or b""
        # バイナリ用エンドポイントでもエラー時は JSON が返るため、ファイルとして
        # 返す前に判別する。Content-Type が誤っていても本文の形で拾えるようにする。
        content_type = (response.headers.get("Content-Type") or "").lower()
        looks_like_status = content[:64].lstrip().startswith(b'{"status"')
        if "json" in content_type or looks_like_status:
            try:
                body = json.loads(content.decode("utf-8", errors="replace"))
            except ValueError:
                pass
            else:
                if isinstance(body, dict) and "status" in body:
                    # code=0 の JSON がここに来ることは想定していないが、
                    # 来た場合はエラー判定だけ行い本体はそのまま返す。
                    self._unwrap_body(body, api_name)
        if not content:
            raise CybermailError(f"{api_name}: 空のファイルが返りました。")
        return content, content_type or "application/octet-stream"
