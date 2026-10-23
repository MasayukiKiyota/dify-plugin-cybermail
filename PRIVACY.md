# プライバシーポリシー / Privacy Policy

## 取り扱う情報

本プラグインは、利用者が設定した CYBERMAILΣ サーバーとのみ通信します。プラグインの開発者や第三者のサーバーにデータを送信することはありません。通信は HTTPS に限定しています（`http://` の Base URL は受け付けません）。

- **認証情報** — Base URL、ユーザID、パスワードまたは API_KEY。Dify のクレデンシャルストアに保存され、CYBERMAILΣ への認証にのみ使用されます。
- **セッション** — ユーザID/パスワード方式では `Core.Login` で取得した `API_SESSION` を、プラグインの KV ストアにそのままの形でキャッシュします。キャッシュキーには Base URL とユーザIDのハッシュのみを使用し、パスワードは含めません。キャッシュの保護は Dify のストレージに依存します。
- **メールデータ** — メールの件名・差出人・宛先・本文・添付ファイルを CYBERMAILΣ から取得し、Dify のワークフローに返します。プラグイン自身がメール内容を永続化することはありません。
- **下書き作成時の入力** — 宛先・件名・本文は CYBERMAILΣ に送られ、メール作成画面に反映されます。本文はツールの出力には含めません。

## 第三者提供

本プラグインは取得したデータを外部に送信しません。ただし、ワークフロー内で LLM ノードなどに渡した場合、その先の処理は Dify および当該モデルプロバイダーのポリシーに従います。メール本文には機微情報が含まれ得るため、ワークフローの設計時にご留意ください。

## 権限と書き込み操作

本プラグインはメールの読み取りに加え、次の書き込み操作を行います。メールの送信・削除・移動は行いません。

- **フラグ変更**（`mail_flag_set`）— 指定したメールの未読／重要フラグを変更します。
- **下書き作成**（`mail_draft_create`）— 宛先・件名・本文を埋めたメール作成画面の URL を発行します。メールは送信されず、人が URL を開いて確認・送信します。

## セキュリティ上の注意

- **作成画面の URL にはログインセッションが含まれます。** URL を知っていればそのメールボックスを操作できるため、URL はツールの出力（JSON・出力変数・LINK・TEXT）や Dify の実行ログに残ることを前提に、チャットの公開や第三者との共有を避けてください。
- **メール本文は信頼できない入力です。** 細工されたメールの内容によって LLM が誘導され、意図しない宛先（特に Bcc）を含む下書きを作成する可能性があります。下書きの送信前に宛先を必ず人が確認してください。
- 添付ファイルのファイル名と Content-Type は、送信者由来の値をそのまま使わず、パス要素・制御文字を取り除き、形式が不正な場合は `application/octet-stream` に置き換えたうえで返します。
- HTML 本文（`body_html`）は加工せずに返します。画面に表示する場合は表示側でサニタイズしてください。

---

This plugin communicates only with the CYBERMAILΣ server configured by the user, over HTTPS only. Credentials are stored in Dify's credential store and used solely to authenticate against that server. Session tokens are cached as-is in the plugin key-value store under a hash of the base URL and user ID; passwords are never included in the cache key. Mail content retrieved from the server is returned to the workflow and is not persisted by the plugin, nor sent to any third party.

Besides reading mail, the plugin changes the unread / important flags of a mail and creates mail drafts by returning the URL of the compose screen. It never sends, deletes or moves mail. The compose URL contains the login session, so treat it as a secret: it appears in the tool output and in Dify's execution logs. Mail content is untrusted input and may try to steer the LLM, for example into adding unintended recipients to a draft; a person must review the recipients before sending. Attachment file names and content types coming from the server are sanitized before being returned, and HTML bodies are returned unmodified.
