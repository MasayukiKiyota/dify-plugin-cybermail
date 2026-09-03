"""Tool 実装から CybermailClient を組み立てるための小さなヘルパー。"""

from collections.abc import Generator
from typing import Any

from utils.client import CybermailClient

# Dify の Tool ノードは text / files / json を組み込みの出力として持つ。
# 同名の変数を出すと組み込み側を上書きしてしまうため、変数化から除外する。
RESERVED_OUTPUT_NAMES = frozenset({"text", "files", "json"})


def create_client(tool: Any) -> CybermailClient:
    """Tool のランタイム情報からクライアントを生成する。

    セッションキャッシュ用の KV ストアはランタイムによって存在しないことがあるため、
    取得できない場合は None（＝毎回ログイン）にフォールバックする。
    """
    storage = getattr(getattr(tool, "session", None), "storage", None)
    return CybermailClient(tool.runtime.credentials, storage=storage)


def emit_result(tool: Any, result: dict[str, Any]) -> Generator[Any, None, None]:
    """JSON メッセージと、output_schema に対応する変数メッセージをまとめて出す。

    Dify の Tool ノードは output_schema 由来の出力変数を VARIABLE メッセージからのみ
    埋めるため、JSON と同じ内容を変数としても送る必要がある。
    """
    yield tool.create_json_message(result)
    for name, value in result.items():
        if name.startswith("_") or name in RESERVED_OUTPUT_NAMES:
            continue
        yield tool.create_variable_message(name, value)


def get_str(parameters: dict[str, Any], name: str, default: str = "") -> str:
    value = parameters.get(name)
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def get_int(parameters: dict[str, Any], name: str) -> int | None:
    value = parameters.get(name)
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} には数値を指定してください: {value!r}") from None


def get_bool(parameters: dict[str, Any], name: str) -> bool:
    value = parameters.get(name)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "on")
    return bool(value)
