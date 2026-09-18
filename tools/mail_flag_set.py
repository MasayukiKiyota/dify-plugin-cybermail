from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from utils.client import CybermailError
from utils.flags import FLAG_IMPORTANT, FLAG_UNREAD, decode_flag
from utils.plugin import create_client, emit_result, get_str

# 操作名 -> (flag ビット, unset)。
# Mail.MailFlagModify の unset は 0=付与 / 1=削除 と直感と逆なうえ、
# ビットが「既読」ではなく「未読」であるため、対応表を Tool 内に閉じ込める。
ACTIONS: dict[str, tuple[int, int]] = {
    "mark_read": (FLAG_UNREAD, 1),
    "mark_unread": (FLAG_UNREAD, 0),
    "add_important": (FLAG_IMPORTANT, 0),
    "remove_important": (FLAG_IMPORTANT, 1),
}

# flag / unset をそのまま送る診断用の操作。
# 変更前後の状態確認（Mail.MailInfoGet）はこのモードでのみ行う。
ACTION_CUSTOM = "custom"

# 助詞まで含めて持つ（「メール〇〇<ラベル>。」の形で使う）。
ACTION_LABELS: dict[str, str] = {
    "mark_read": "を既読にしました",
    "mark_unread": "を未読にしました",
    "add_important": "に重要フラグを付けました",
    "remove_important": "の重要フラグを外しました",
    ACTION_CUSTOM: "のフラグを変更しました（診断モード）",
}

# 状態を読まない通常操作で、その操作が意図した結果として返す状態。
# 操作していない方のフラグは読んでいないため None（未取得）のままにする。
INTENDED_STATE: dict[str, dict[str, bool]] = {
    "mark_read": {"unread": False},
    "mark_unread": {"unread": True},
    "add_important": {"important": True},
    "remove_important": {"important": False},
}


class MailFlagSetTool(Tool):
    def _invoke(
        self, tool_parameters: dict[str, Any]
    ) -> Generator[ToolInvokeMessage, None, None]:
        mail_id = get_str(tool_parameters, "mail_id")
        if not mail_id:
            raise ValueError("mail_id は必須です。「メール一覧取得」の結果から指定してください。")

        action = get_str(tool_parameters, "action")
        if action not in ACTIONS and action != ACTION_CUSTOM:
            raise ValueError(
                f"action の値が不正です: {action}"
                f"（{' / '.join(ACTIONS)} / {ACTION_CUSTOM} のいずれかを指定してください）"
            )

        folder_id = get_str(tool_parameters, "folder_id", "@")
        is_custom = action == ACTION_CUSTOM

        client = create_client(self)
        # Mail.MailFlagModify は API_SESSION 専用で、API_KEY 方式の代替指定が無い。
        if client.is_api_key_auth:
            raise ValueError(
                "フラグ操作は API_KEY 方式では利用できません。"
                "認証方式を「ユーザID/パスワード」に変更してください。"
            )

        # 状態の確認は診断モードのみ。通常操作では API 呼び出しを 1 回に抑える。
        # decode_flag が展開しない未文書ビットも追えるよう、生の flag 値を持つ。
        before = self._read_state(client, folder_id, mail_id)[0] if is_custom else None

        params: dict[str, Any] = {"folder_id": folder_id, "mail_id": mail_id}
        if is_custom:
            # 診断用のため入力値は一切加工せずに送る（"16" も "0x00000010" もそのまま）。
            # 空欄の場合は client._post が落とすので、パラメータ自体が送られない。
            params["flag"] = get_str(tool_parameters, "flag")
            params["unset"] = get_str(tool_parameters, "unset")
        else:
            flag, unset = ACTIONS[action]
            # unset は int で渡す。client._post は None と "" のみ除外するため 0 は落ちない。
            params["flag"] = flag
            params["unset"] = unset

        client.call("Mail.MailFlagModify", params)

        result: dict[str, Any] = {
            "mail_id": mail_id,
            "folder_id": folder_id,
            "action": action,
            "success": True,
            "verified": False,
            # 読み取っていない項目は None（未取得）で返す。False と区別できるようにする。
            "unread": None,
            "important": None,
            "subject": "",
            "flag_before": before["flag"] if before else None,
            "flag_after": None,
            "flag_before_hex": self._to_hex(before["flag"] if before else None),
            "flag_after_hex": "",
        }

        warning: str | None = None
        if is_custom:
            # Mail.MailFlagModify は data が常に null のため、状態は別途取得して確認する。
            after, error = self._read_state(client, folder_id, mail_id)
            if after is None:
                # フラグ変更自体は成功しているため、確認の失敗で Tool を落とさない。
                warning = f"フラグは変更しましたが、変更後の状態を確認できませんでした: {error}"
            else:
                decoded = decode_flag(after["flag"])
                result["verified"] = True
                result["unread"] = decoded["unread"]
                result["important"] = decoded["important"]
                result["subject"] = after["subject"]
                result["flag_after"] = after["flag"]
                result["flag_after_hex"] = self._to_hex(after["flag"])
        else:
            # 状態は読まないが、成功した操作が意図した結果は確実に分かる。
            result.update(INTENDED_STATE[action])

        yield from emit_result(self, result)
        if warning:
            yield self.create_text_message(warning)
        yield self.create_text_message(self._render(result))

    @staticmethod
    def _read_state(
        client: Any, folder_id: str, mail_id: str
    ) -> tuple[dict[str, Any] | None, str]:
        """Mail.MailInfoGet で現在の状態を読む。失敗したら (None, エラー文言) を返す。"""
        try:
            info = client.call(
                "Mail.MailInfoGet", {"folder_id": folder_id, "mail_id": mail_id}
            )
            if not isinstance(info, dict):
                raise CybermailError(
                    f"Mail.MailInfoGet が想定外の応答を返しました: {str(info)[:200]!r}"
                )
        except CybermailError as exc:
            return None, str(exc)

        try:
            flag = int(info.get("flag"))
        except (TypeError, ValueError):
            flag = 0
        return {"flag": flag, "subject": info.get("subject") or ""}, ""

    @staticmethod
    def _to_hex(flag: int | None) -> str:
        return "" if flag is None else f"0x{flag:08x}"

    @staticmethod
    def _render(result: dict[str, Any]) -> str:
        # 件名は診断モードでしか取得しないため、無ければ mail_id で示す。
        name = f"「{result['subject']}」" if result["subject"] else f" {result['mail_id']} "
        lines = [f"メール{name}{ACTION_LABELS[result['action']]}。"]

        if result["verified"]:
            lines.append(
                f"未読: {'はい' if result['unread'] else 'いいえ'} / "
                f"重要: {'はい' if result['important'] else 'いいえ'}"
            )
        # 他のフラグが巻き添えで変化していないかを見るため、生の値も出す（診断モードのみ）。
        if result["flag_before_hex"] or result["flag_after_hex"]:
            lines.append(
                f"flag: {result['flag_before_hex'] or '(取得できず)'}"
                f" → {result['flag_after_hex'] or '(取得できず)'}"
            )
        return "\n".join(lines)
