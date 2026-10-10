# FLAMORIS Updater

各リポジトリが管理するアプリを、一つの画面からインストール・更新する独立したWeb・CLI・MCPサービスです。

1. Updaterを導入して管理画面を開く。
2. 各リポジトリのカタログURLを登録する。複数登録できる。
3. 必要なアプリを選び、その配布元から現在のCPU向けの成果物を取得する。
4. 更新時は新版を横置きし、既存設定・データを引き継いで切り替える。

アプリのソース、ビルド、リリース、配布物は各アプリのリポジトリが管理します。Updaterは他のアプリをビルドしたり、一つの配布セットに集め直したりしません。カタログは配布URL・ハッシュ・対応CPU・設定・互換性を記載した案内です。Updater本体の配布物だけは、このリポジトリで管理します。

**Updater独自の管理者アカウント、セットアップコード、ログイン、セッション、CLI/MCPトークン、連携キーはありません。** 初回から同じ画面で操作できます。サービス用OSアカウントとローカル実行権限の分離はインストール処理のために維持します。アプリ自身の認証やGitHub側のリポジトリアクセス権限は別です。

## Install and update

Linux/systemd、Python 3.12とレビュー済みのUpdaterパッケージが必要です。

```bash
sudo /absolute/installation/bin/flamoris-updater bootstrap
```

表示されたURLを開いてカタログを登録します。[実行手順](docs/RUNNING.md)と[カタログ仕様](docs/INSTALL.md)を参照してください。Webはloopbackで待ち受け、トンネル・プロキシの設定は外部で行います。アクセスできる人は同じ更新操作を実行できます。[接続仕様](docs/TRANSPORT.md)に境界を記載しています。

新規インストール後はアプリ自身の初回設定と動作確認を行います。更新には対応する旧版との互換性が必要です。成功後は現行と旧版1世代を保持し、設定・DB・データ・外部ランタイム・モデルは削除しません。失敗・中断した処理は記録を残して停止します。

カタログは配布元を集めるだけなので、各アプリは独立してリリースできます。一つの配布元が取得できなくても、他のカタログの更新確認は継続します。登録解除はアプリのアンインストールではありません。既存の単一カタログ登録とインストール記録は引き継ぎます。

DB・システムバックアップ、未管理アプリの取り込み、任意シェルの実行は提供しません。アプリ固有のDB移行は各アプリが所有します。既存の高度なCore/Owner移行・署名付き協調処理は内部統合用で、通常のWeb/CLI/MCPには公開しません。

**Source status:** この構成のソース実装とテスト結果は[PROGRESS.md](PROGRESS.md)に記載しています。v1.0.4の配布物と1.0.3からの自己更新カタログを準備しています。公開・実機反映の確認は別です。各アプリのカタログ・配布物の公開も各リポジトリ側で行います。

## Development

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --constraint requirements-runtime.lock -e '.[dev]'
ruff check src tests scripts
ruff format --check src tests scripts
pytest -q
python -m build
python scripts/export_schemas.py --output dist/schemas
python scripts/check_docs.py
```

CoreとFLAMORISラッパは同じリポジトリ内です。Dedicated WebはStudioに依存しません。詳しい現在の契約は[仕様一覧](docs/CONTRACTS.md)、[Web](docs/WEB_UI.md)、[API](docs/MCP_API.md)、[自己更新](docs/SELF_UPDATE.md)を参照してください。

## License

Apache License 2.0. External applications, models and media retain their own licenses.
