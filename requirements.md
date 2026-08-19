# dify-plugin-cybermail

CYBERMAILΣ の Web API と Dify を接続する Tool プラグインです。

| ディレクトリ | 内容 |
|---|---|
| [cybermail/](cybermail/) | プラグイン本体。使い方は [cybermail/README.md](cybermail/README.md) を参照 |
| [docs/](docs/) | CYBERMAILΣ WebAPI 仕様書（Core / Mail モジュール） |
| [tests/](tests/) | 単体・結合テスト |

## テスト

HTTP 層をモックしているため、CYBERMAILΣ サーバーは不要です。

```bash
# SDK 不要（client / flags / mail のロジック）
python tests/test_client_logic.py

# dify_plugin SDK が必要（Tool の _invoke を実際に実行）
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r cybermail/requirements.txt
.venv/Scripts/python.exe tests/test_tools.py
```

## 実機での確認

```bash
cd cybermail
cp .env.example .env      # REMOTE_INSTALL_URL / REMOTE_INSTALL_KEY を設定
python -m main
```

Dify の「プラグイン」画面にデバッグ中として表示されたら、クレデンシャルを登録して
`mail_list` → `mail_get` → `attachment_get` の順に実行して動作を確認します。
