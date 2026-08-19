# CyberMail (CYBERMAILΣ) Dify プラグイン

CYBERMAILΣ の Web API 経由で、メール一覧・本文・添付ファイルを Dify のワークフロー／エージェントから取得するための Tool プラグインです。**読み取り専用**で、メールの送信・削除・移動・フラグ変更は行いません。

## 認証

Provider 設定で次のいずれかの方式を選びます。どちらの場合も操作対象のメールボックスは **クレデンシャルの「ユーザID」で固定**されます。

| 項目 | 説明 |
|---|---|
| Base URL | `https://example.cybermail.jp` のようにホストまで。`/cgi-bin/cgi_api` は自動付与されます |
| 認証方式 | 「ユーザID/パスワード」または「API_KEY」 |
| ユーザID | 操作対象のメールボックス（例 `user@example.co.jp`）。両方式で必須 |
| パスワード | 「ユーザID/パスワード」方式で必須 |
| API_KEY | 「API_KEY」方式で必須 |

- **ユーザID/パスワード方式** — `Core.Login` でログインし、取得した `API_SESSION` をプラグインの KV ストアにキャッシュします。セッションが失効した場合は `Core.SessionCheck` で確認したうえで自動的に再ログインします。
- **API_KEY 方式** — システム発行の `API_KEY` とユーザIDを組み合わせて呼び出します。この方式では `Mail.MailListGet` が使えないため、内部で `Mail.SystemMailListGet` に切り替えます。

認証情報の保存時に、API_KEY 方式では `Core.KeyCheck` と `Mail.SystemMailBoxListGet`、パスワード方式では `Core.Login` を実行して疎通を確認します。

## Tool

### メール一覧取得 (`mail_list`)

指定フォルダーのメール一覧を取得します。

- 主なパラメータ: `folder_id`（既定 `@`）、`max_entry`（既定 20）、`bgn_idx`、`sort_by`、`unread_only`、`flag_filter`、`label_filter`
- フォルダーID: `@` 受信BOX / `@.sent` 送信BOX / `@.draft` 下書き / `@.trash` ゴミ箱 / `@.01` などのサブフォルダー
- API 仕様では `max_entry` 省略時に全件返るため、本プラグインでは既定 20 件で歯止めをかけています
- 出力の `mails[].mail_id` を後続の Tool に渡します。`flag` はデコードされ `unread` / `important` / `has_attachment` などの真偽値になります

### メール本文取得 (`mail_get`)

`Mail.MailAdvanceGet` を使い、件名・差出人・宛先・日時・本文・添付ファイル一覧を取得します。

- パラメータ: `mail_id`（必須）、`folder_id`（既定 `@`）、`body_format`（`text` / `html` / `both`、既定 `text`）
- HTML 本文は非常に大きくなる場合があるため、既定ではテキスト本文のみを返します
- 出力の `attachments[].hash` を添付ファイル取得に渡します

### 添付ファイル取得 (`attachment_get`)

添付ファイルを **個別のファイル**として返します（ZIP にまとめません）。そのまま後続の文書抽出ノードに渡せます。

- パラメータ: `mail_id`（必須）、`folder_id`（既定 `@`）、`hash`（任意・単一取得）、`include_inline`（既定 false）
- `hash` を省略するとそのメールの添付を全件取得します
- 1 件の取得に失敗しても処理は止まらず、警告メッセージを出して残りを続行します

## 典型的なワークフロー

```
メール一覧取得 (folder_id=@, unread_only=true)
  → mails[].mail_id
    → メール本文取得 (mail_id)      → LLM で要約・分類
    → 添付ファイル取得 (mail_id)    → ドキュメント抽出ノード
```

## 対応 API と未対応 API

対応: `Core.Login` / `Core.SessionCheck` / `Core.KeyCheck` / `Mail.MailListGet` / `Mail.SystemMailListGet` / `Mail.SystemMailBoxListGet` / `Mail.MailAdvanceGet` / `Mail.AttachmentGet`

未対応（今後の拡張余地）:

- メール送信 — Mail モジュールに送信 API が存在しないため（別モジュールの仕様が必要）
- `Mail.MailFlagModify` / `Mail.MailMove` — 書き込み系のため対象外
- `Mail.VirtualFolder*`（分類表示BOX）、`Mail.MailReadReceiptSend`（開封通知）、`Mail.AttachmentPack`（ZIP 一括）

`utils/client.py` の `call()` / `call_binary()` は汎用のため、Tool を追加するだけで拡張できます。
