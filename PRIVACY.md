# プライバシーポリシー / Privacy Policy

## 取り扱う情報

本プラグインは、利用者が設定した CYBERMAILΣ サーバーとのみ通信します。プラグインの開発者や第三者のサーバーにデータを送信することはありません。

- **認証情報** — Base URL、ユーザID、パスワードまたは API_KEY。Dify のクレデンシャルストアに保存され、CYBERMAILΣ への認証にのみ使用されます。
- **セッション** — ユーザID/パスワード方式では `Core.Login` で取得した `API_SESSION` を、プラグインの KV ストアにキャッシュします。キャッシュキーには Base URL とユーザIDのハッシュのみを使用し、パスワードは含めません。
- **メールデータ** — メールの件名・差出人・宛先・本文・添付ファイルを CYBERMAILΣ から取得し、Dify のワークフローに返します。プラグイン自身がメール内容を永続化することはありません。

## 第三者提供

本プラグインは取得したデータを外部に送信しません。ただし、ワークフロー内で LLM ノードなどに渡した場合、その先の処理は Dify および当該モデルプロバイダーのポリシーに従います。メール本文には機微情報が含まれ得るため、ワークフローの設計時にご留意ください。

## 権限

本プラグインは読み取り専用です。メールの送信・削除・移動・フラグ変更は行いません。

---

This plugin communicates only with the CYBERMAILΣ server configured by the user. Credentials are stored in Dify's credential store and used solely to authenticate against that server. Session tokens are cached in the plugin key-value store under a hash of the base URL and user ID; passwords are never included in the cache key. Mail content retrieved from the server is returned to the workflow and is not persisted by the plugin, nor sent to any third party. The plugin is read-only.
