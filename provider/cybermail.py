from typing import Any

from dify_plugin import ToolProvider
from dify_plugin.errors.tool import ToolProviderCredentialValidationError

from utils.client import (
    AUTH_API_KEY,
    AUTH_PASSWORD,
    CybermailClient,
    CybermailError,
)


class CybermailProvider(ToolProvider):
    def _validate_credentials(self, credentials: dict[str, Any]) -> None:
        """設定値で実際に CYBERMAILΣ へ疎通し、認証が通ることを確認する。

        Dify のクレデンシャル定義では「認証方式によって必須が変わる」ことを表現できないため、
        password / api_key の必須チェックもここで行う（CybermailClient の初期化が担当）。
        """
        auth_method = (credentials.get("auth_method") or AUTH_PASSWORD).strip()

        try:
            # ここでは storage を渡さず、キャッシュを使わない素の状態で検証する。
            client = CybermailClient(credentials)

            if auth_method == AUTH_API_KEY:
                if not client.check_api_key():
                    raise ToolProviderCredentialValidationError(
                        "API_KEY が無効です（Core.KeyCheck）。"
                    )
                # KeyCheck は API_KEY の有効性しか見ないため、ユーザIDの実在も確認する。
                client.call("Mail.SystemMailBoxListGet")
            else:
                client.login()
        except ToolProviderCredentialValidationError:
            raise
        except CybermailError as exc:
            raise ToolProviderCredentialValidationError(str(exc)) from exc
        except Exception as exc:
            raise ToolProviderCredentialValidationError(
                f"認証情報の検証に失敗しました: {exc}"
            ) from exc
