# CyberMail (CYBERMAILΣ) Dify プラグイン

CYBERMAILΣ の Web API 経由で、メール一覧・本文・添付ファイルを Dify のワークフロー／エージェントから取得し、未読／重要フラグの変更とメール下書き（作成画面 URL）の発行を行うための Tool プラグインです。書き込みは**フラグ変更と下書き作成のみ**で、メールの送信・削除・移動は行いません。

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

各 Tool は結果を JSON として返すのに加えて、同じ内容を Tool ノードの出力変数としてもセットします。ワークフローでは `{{#ノード.count#}}` `{{#ノード.mails#}}` のように直接参照できます。

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
- ファイル本体は Dify 標準の `files` 出力に入ります。ファイル名・サイズ・成否などの明細は `attachments` 出力変数から参照してください

### メールフラグ変更 (`mail_flag_set`)

`Mail.MailFlagModify` を使い、指定メールの未読フラグ・重要フラグを変更します。
実機で検証済みで、**操作対象のフラグ以外は変化しません**（詳細は `requirements.md` の制約 9）。

- パラメータ: `mail_id`（必須）、`action`（必須）、`folder_id`（既定 `@`）
- `action` は次の 4 つ。API の `unset`（0＝付与 / 1＝削除）の反転は Tool 内で吸収しているため、意識する必要はありません

  | action | 内容 |
  |---|---|
  | `mark_read` | 既読にする（未読フラグを削除） |
  | `mark_unread` | 未読にする（未読フラグを付与） |
  | `add_important` | 重要フラグを付ける |
  | `remove_important` | 重要フラグを外す |

- **「ユーザID/パスワード」方式でのみ利用できます。** `Mail.MailFlagModify` は API_SESSION 専用で API_KEY を受け付けないため、API_KEY 方式では実行時にエラーになります
- 1 回の呼び出しで **1 通のみ**変更します。複数通に適用する場合は Dify のイテレーションノードで回してください
- **通常の操作では状態の読み取りを行いません**（API 呼び出しは `Mail.MailFlagModify` の 1 回だけ）。
  出力の `unread` / `important` にはその操作が意図した結果だけが入り（例: `mark_read` なら `unread: false`）、
  操作していない方のフラグ・`subject`・`flag_before` / `flag_after` は `null`、`verified` は `false` になります
- 変更後の実際の状態が必要な場合は、後続で「メール一覧取得」を呼ぶか、下の診断モードを使ってください

#### 診断モード（`action` ＝「任意指定（診断用）」）

未読・重要以外のフラグ（ToDo、アーカイブなど）を操作したいときや、挙動を調べたいときの逃げ道です。
`flag` と `unset` を**加工せずそのまま** API に送り、**変更の前後に `Mail.MailInfoGet` を呼んで**状態を
確認します（`unread` / `important` / `subject` と、生のフラグ値 `flag_before` / `flag_after`、
16 進表記の `flag_before_hex` / `flag_after_hex` が埋まります）。生の値を返すのは、デコード対象の
12 ビット以外（`0x04000000` など仕様書に無いビット）の変化も追えるようにするためです。
フラグ値は仕様書の 10 進表記（`16`＝重要、`256`＝未読 など）で指定します。`0x00000010` のような
16 進表記も受け付けられることを実機で確認しています。

- `flag`（文字列）— 「16」「0x00000010」「10」など入力どおりに送信。**空欄にすると `flag` パラメータ自体を送りません**
- `unset` — 0（付与）／1（削除）。空欄にすると `unset` パラメータ自体を送りません
- どちらもツール設定画面でのみ指定でき、LLM からは選ばれません（`form: form`）

### メール下書き作成 (`mail_draft_create`)

`Compose.ComposeInvoke` を使い、宛先・件名・本文を埋めた**メール作成画面の URL** を発行します。
**メールは送信されません。** 返った URL を開いて内容を確認し、人が送信ボタンを押す運用を想定しています。

- パラメータ: `to` / `cc` / `bcc`（いずれか 1 つ必須）、`exclude`（除外アドレス）、`subject`、`content`（本文）、`signature`
- 複数アドレスはカンマ区切り。`;` や改行で区切られていてもカンマ区切りに揃えて送ります
- 本文は**テキスト形式のみ**（API の仕様）。添付ファイルは付けられません
- `signature` は署名設定画面での表示順（先頭なら `1`）。ツール設定画面でのみ指定でき、LLM からは選ばれません（`form: form`）
- URL は `compose_url` 出力変数と、Dify の LINK メッセージの両方で返します。本文は入力そのものなので出力には含めません
- **「ユーザID/パスワード」方式でのみ利用できます。** `Compose.ComposeInvoke` は API_SESSION 専用のため、API_KEY 方式では実行時にエラーになります
- **URL にはログインセッション（API_SESSION）が含まれます。** URL を知っていればそのメールボックスを操作できてしまうため、チャットのログや第三者に共有しないでください

## 典型的なワークフロー

```
メール一覧取得 (folder_id=@, unread_only=true)
  → mails[].mail_id
    → メール本文取得 (mail_id)      → LLM で要約・分類
    → 添付ファイル取得 (mail_id)    → ドキュメント抽出ノード
    → メールフラグ変更 (mail_id, action=mark_read)  ※処理済みのメールを既読にする

メール本文取得 (mail_id)
  → LLM で返信案を作成
    → メール下書き作成 (to=差出人, subject="Re: ...", content=返信案)
      → compose_url を開いて人が確認・送信
```

## 対応 API と未対応 API

対応: `Core.Login` / `Core.SessionCheck` / `Core.KeyCheck` / `Mail.MailListGet` / `Mail.SystemMailListGet` / `Mail.SystemMailBoxListGet` / `Mail.MailAdvanceGet` / `Mail.AttachmentGet` / `Mail.MailFlagModify` / `Mail.MailInfoGet` / `Compose.ComposeInvoke`

未対応（今後の拡張余地）:

- `Compose.MailSend`（メール送信）— LLM による誤送信を避けるため対象外。送信は下書き作成の URL から人が行います
- `Mail.MailMove` — メールの移動・削除は誤削除リスクを避けるため対象外
- `Mail.VirtualFolder*`（分類表示BOX）、`Mail.MailReadReceiptSend`（開封通知）、`Mail.AttachmentPack`（ZIP 一括）

`utils/client.py` の `call()` / `call_binary()` は汎用のため、Tool を追加するだけで拡張できます。
