"""CYBERMAILΣ のフラグ・ラベル・日時を人間/LLM が読める形に変換するユーティリティ。

ビットマスクの値は Mail モジュール仕様書の Mail.MailFlagModify および
flag_filter の説明に記載された値に基づく。
"""

from datetime import datetime, timedelta, timezone
from typing import Any

# CYBERMAILΣ は日本国内向け製品のため、表示用タイムゾーンは JST 固定。
JST = timezone(timedelta(hours=9))

# --- メールフラグのビットマスク -------------------------------------------------
FLAG_ATTACHMENT = 0x00000001  # 添付ファイル
FLAG_IMPORTANT = 0x00000010  # 重要
FLAG_TOP = 0x00000080  # トップに配置
FLAG_UNREAD = 0x00000100  # 未読
FLAG_TODO = 0x00000200  # ToDo
FLAG_REPLIED = 0x00000400  # 返信済
FLAG_IMAP_DELETED = 0x00002000  # IMAP クライアントで削除済みとしてマーク
FLAG_POP3_1 = 0x00080000  # 外部メール(POP3 1)
FLAG_POP3_2 = 0x00040000  # 外部メール(POP3 2)
FLAG_POP3_3 = 0x00020000  # 外部メール(POP3 3)
FLAG_POP3_4 = 0x00010000  # 外部メール(POP3 4)
FLAG_NOTIFIED = 0x00100000  # 通知済
FLAG_ARCHIVED = 0x00200000  # アーカイブ
FLAG_FLAGGED = 0x00400000  # フラグ
FLAG_VIRUS = 0x01000000  # ウィルス
FLAG_FORWARDED = 0x02000000  # 転送済

# デコード結果のキーと対応ビット。順序はそのまま JSON 出力の順序になる。
_FLAG_MAP: list[tuple[str, int]] = [
    ("unread", FLAG_UNREAD),
    ("important", FLAG_IMPORTANT),
    ("has_attachment", FLAG_ATTACHMENT),
    ("replied", FLAG_REPLIED),
    ("forwarded", FLAG_FORWARDED),
    ("todo", FLAG_TODO),
    ("flagged", FLAG_FLAGGED),
    ("pinned", FLAG_TOP),
    ("archived", FLAG_ARCHIVED),
    ("notified", FLAG_NOTIFIED),
    ("virus", FLAG_VIRUS),
    ("imap_deleted", FLAG_IMAP_DELETED),
]

LABEL_NAMES: dict[int, str] = {
    0: "なし",
    1: "茶色",
    2: "緑色",
    3: "赤色",
    4: "黄色",
    5: "青色",
}


def decode_flag(flag: Any) -> dict[str, bool]:
    """flag 値（integer）を bool の辞書に展開する。不正値は全て False として返す。"""
    try:
        value = int(flag)
    except (TypeError, ValueError):
        value = 0
    return {name: bool(value & mask) for name, mask in _FLAG_MAP}


def decode_label(label: Any) -> str:
    """label 値（0〜5）を名称に変換する。未知の値はそのまま文字列化する。"""
    try:
        return LABEL_NAMES[int(label)]
    except (TypeError, ValueError, KeyError):
        return str(label)


def to_jst_iso(epoch: Any) -> str | None:
    """epoch 秒を JST の ISO8601 文字列に変換する。変換できない場合は None。"""
    try:
        return datetime.fromtimestamp(int(epoch), tz=JST).isoformat()
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def parse_flag_filter(raw: Any) -> str | None:
    """flag_filter の入力値を API に渡す形式に正規化する。

    ``0x00000100`` のような16進表記、``256`` のような10進表記のどちらも受け付け、
    API の使用例に合わせた ``0x`` 付き8桁16進文字列にそろえる。
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        value = int(text, 16) if text.lower().startswith("0x") else int(text)
    except ValueError:
        raise ValueError(
            f"flag_filter の値を解釈できません: {text!r}（例: 0x00000100 または 256）"
        ) from None
    return f"0x{value:08x}"
