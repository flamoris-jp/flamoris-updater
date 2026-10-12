# Updater自身の初回インストール手順

この文書は、AIと利用者が**Updater本体を初めて導入する**ための手順です。
既にUpdaterがある場合は、この手順を再実行せず[自己更新手順](SELF_UPDATE.md)へ進みます。
アプリのインストールはUpdater導入後の別工程です。

## 0. 初回導入か自己更新かを決める

| 現在の状態 | 選ぶ手順 |
| --- | --- |
| Updaterのサービス・設定・実行履歴がない | 本書の初回導入 |
| Updaterが導入済みで管理画面を開ける | [自己更新](SELF_UPDATE.md) |
| 導入途中・更新失敗・管理画面を開けない | [調査・手動復旧](DIAGNOSTICS.md)。既存状態を確認して再開する |
| 設定済み1.0.3で新しいカタログを登録できない | [1.0.3専用のカタログ切替](UPGRADE_103.md)後、自己更新 |

実機の状態が必要なAIはServer Managerの観測を使います。会話履歴やREADMEの版を稼働版の代わりにしません。
この文書のコマンド例はLinuxで利用者が実行するもので、読んだだけで実機操作が許可されるものではありません。

## 1. 必要な環境と選定版

- Linux/systemd、管理者権限。
- **/usr/bin/python3.12**。Native bundleはPython依存ライブラリを含みますが、Python本体は含みません。
- 対応CPUはx86_64（linux-amd64）またはaarch64（linux-arm64）。配布物の参照環境はUbuntu 24.04です。
- GitHubのHTTPS配布物を取得できること。公開Updaterの取得にGitHubログインは不要です。
- 後でDockerアプリを導入する場合はDocker、Agent／Studioを導入する場合は到達可能なPostgreSQLを別途用意します。Updaterだけのbootstrapに、それらのアプリ設定は不要です。

まず[公開Release](https://github.com/flamoris-jp/flamoris-updater/releases)で導入する版と対応CPUのNative archiveを確認します。
以下は**公開済み1.0.10を固定して導入する例**です。将来の版では、そのReleaseの配布物・手順を確認して選定版を変更します。
wheelやソースを本番でビルドする手順ではありません。

1.0.10 Release添付の `INSTALL-v1.0.10.md` には旧1.0.8の固定例が残っています。1.0.10の初回導入には、本書の `release=1.0.10` と1.0.10 Releaseの対応CPU archiveを使います。導入済み環境は自己更新手順へ進みます。

事前に作業ディレクトリ、未使用の本体配置先、アプリ配置先、公開URLが必要かを確認します。
以下の /opt/flamoris-updater/1.0.10 は検証済み配布物の展開先です。ソースリポジトリを/optへcloneしません。

## 2. 配布物を取得・検証する

通常ユーザーの作業ディレクトリで実行します。

```bash
set -euo pipefail
release=1.0.10
case "$(uname -m)" in
  x86_64) platform=linux-amd64 ;;
  aarch64) platform=linux-arm64 ;;
  *) echo "Unsupported CPU architecture" >&2; exit 1 ;;
esac

workdir="$HOME/tmp/flamoris-updater-$release-$platform"
mkdir -p "$workdir"
cd "$workdir"
archive="flamoris-updater-$release-$platform.tar.gz"
release_url="https://github.com/flamoris-jp/flamoris-updater/releases/download/v$release"

curl --fail --location --output "$archive" "$release_url/$archive"
curl --fail --location --output SHA256SUMS "$release_url/SHA256SUMS"
test -s "$archive"
sha256sum --check SHA256SUMS --ignore-missing
```

選んだarchiveが存在し、そのファイル名について **OK** と表示されたことを確認してから進みます。
ignore-missingで省略されるのは他のRelease assetであり、手元にないarchiveの検証成功を意味しません。
SHA-256は公開Releaseとの内容一致の確認です。

## 3. 未使用の配置先へ展開する

同じシェルで、手順2の検証が成功した後に実行します。

```bash
install_dir="/opt/flamoris-updater/$release"
test ! -e "$install_dir"
sudo install -d -o root -g root -m 0755 "$install_dir"
sudo tar --extract --gzip --file "$archive" --directory "$install_dir" --no-same-owner
sudo chmod -R a-w "$install_dir"
```

配置先が存在する場合は上書きせず、既存導入／途中状態を確認します。
アーカイブにはbin/flamoris-updaterとbin/flamoris-updater-serviceが含まれます。
配布物の内部ファイル・indexを変更したり、後からpipで依存を足したりしません。

## 4. bootstrapを一度だけ実行する

ローカルloopbackで利用する初回導入例です。

```bash
sudo "$install_dir/bin/flamoris-updater" bootstrap --root /srv/flamoris/apps
```

bootstrapは既存の状態・サービスを上書きせず、専用OSアカウントと次のサービスを作成し、URLをJSONで返します。

| 作成するもの | デフォルト |
| --- | --- |
| Web | flamoris-updater.service |
| ローカル管理処理 | flamoris-updater-manager.service |
| 自己更新を制御するsupervisor | flamoris-updater-supervisor.service |
| 設定 | /var/lib/flamoris-updater/setup.json |
| 状態・履歴 | /var/lib/flamoris-updater/web と /var/lib/flamoris-updater/helper |
| アプリ配置先 | /srv/flamoris/apps |
| 管理画面 | http://127.0.0.1:8764 |

別の値を選ぶ場合はbootstrapの --directory、--root、--portを使います。
既存proxy等で https://updater.example.invalid/updater/ を公開する場合の初回例は次です。
**上のbootstrapを実行した後に、もう一度実行するコマンドではありません。**

```bash
sudo "$install_dir/bin/flamoris-updater" bootstrap \
  --root /srv/flamoris/apps \
  --public-origin https://updater.example.invalid \
  --base-path /updater
```

public-originはパスを含まないorigin、base-pathはパスです。選定したURLとproxy側のHost・パスを一致させます。
127.0.0.1はUpdaterを導入したマシン自身です。別端末から開く接続は[通信仕様](TRANSPORT.md)に沿って外部proxy／トンネルで用意します。
Updater自身はproxy・証明書・トンネルを設定しません。

## 5. 管理画面とカタログを確認する

1. bootstrapが返したURLを開く。Updater独自のログイン・セットアップコード・MCPキーは不要です。
2. Updater自身のカタログを登録する:
   https://github.com/flamoris-jp/flamoris-updater/releases/latest/download/catalog.json
3. 必要なアプリの配布元カタログを[カタログ一覧](../catalogs/README.md)から登録する。
4. 画面の更新ボタンで配布元を確認し、表示された現在版・利用可能な版を確認する。

**1.0.10ではカタログの自動登録・初回表示時の外部再取得は未実装です。**
登録URLは保存されますが、初回表示は保存済み情報で、更新ボタンが登録済みURLを再取得します。
自動確認・表示は[#37](https://github.com/flamoris-jp/flamoris-updater/issues/37)で追跡します。

Updater導入とアプリ導入は分けます。アプリは選択→設定→インストール→アプリ自身の初回設定→動作確認の順です。
ControllerはGeneration MCPに同居するlibraryで、追加daemonとして重複導入しません。

## 6. 完了判断と次の更新

画面の稼働版、選定した配置、接続、カタログ表示を確認してUpdater初回導入の完了とします。
これだけでアプリ間通信・GPU・生成providerの利用まで完了したとはしません。

以後は[自己更新手順](SELF_UPDATE.md)を使い、bootstrapを繰り返しません。
最初の本体配置はsupervisorが使い続けるため、自己更新後も削除しません。
詳細なCLI・通常アプリ操作は[実行手順](RUNNING.md)、問題時は[診断](DIAGNOSTICS.md)を参照してください。

## HTTPS below a public path

Bootstrap with `--public-origin https://updater.example.invalid --base-path /updater`
when the chosen public URL is `https://updater.example.invalid/updater/`. Configure
the external proxy to preserve both the original path and public Host. For nginx
on the same host, the location inside an already secured HTTPS server is:

```nginx
location /updater/ {
    proxy_pass http://127.0.0.1:8764;
    proxy_set_header Host $host;
    proxy_buffering off;
    proxy_read_timeout 300s;
}
location = /updater {
    proxy_pass http://127.0.0.1:8764;
    proxy_set_header Host $host;
}
```

The absence of a trailing slash on `proxy_pass` is intentional: do not strip
`/updater`. Updater supplies the canonical `/updater/` redirect. Forward browser Origin without substituting a loopback Origin. Updater does not trust forwarded-prefix headers. Its listener
remains loopback-only; a proxy on another host needs an independently secured
on-host relay, not direct LAN access to that listener. Certificates, proxy ACLs,
relay authentication and reachability are external prerequisites.
