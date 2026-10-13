# Updater自身のアップデート手順

既に導入されたUpdaterのWeb／managerを、独立したsupervisorで更新します。
初回導入は[配布物の導入手順](DISTRIBUTION.md)へ進みます。自己更新でbootstrapを再実行しません。

## 1. 現在版・配置・実行中ジョブを確認する

管理画面のヘッダーと自己更新欄で稼働版を確認します。CLIなら、実際に導入されたlauncherと接続URLを使います。

```bash
updater_bin=/opt/flamoris-updater/1.0.8/bin/flamoris-updater
updater_url=http://127.0.0.1:8764
"$updater_bin" self-status --url "$updater_url"
```

これは1.0.8をそのパスへ初回導入した例です。既存環境では実際のlauncher配置とURLに置き換えます。
公開パスが /updater ならURLにも含めます。loopback経由で公開originを指定する設定ではCLIの --public-originを使います。

現在のself release、supported、installation、利用可能なreleasesを読み、
現在の操作を妨げる未完了／recovery_requiredのジョブがある場合は[診断](DIAGNOSTICS.md)から再開します。
同じ版が既に稼働していれば、それを再適用しません。

## 2. 自己更新カタログを登録・再取得する

管理画面で次の公式URLを登録します。既に登録済みなら追加せず、更新ボタンで再取得します。

https://github.com/flamoris-jp/flamoris-updater/releases/latest/download/catalog.json

CLIで新規登録する例:

```bash
printf '%s\n' '{"url":"https://github.com/flamoris-jp/flamoris-updater/releases/latest/download/catalog.json"}' |
  "$updater_bin" call --url "$updater_url" --tool updater_catalog_add --arguments -
"$updater_bin" apps --url "$updater_url"
"$updater_bin" self-status --url "$updater_url"
```

appsは登録済み配布元をrefreshし、self-statusはその結果から自己更新候補を返します。
登録解除はインストール済みアプリの削除ではありません。新しい配布元へ切り替えるときは、新URLを登録・確認してから不要な旧URLを解除します。

1.0.12までの初回表示は保存済み情報です。公開済み1.0.13では画面を開く・再読み込みする際に、Updaterと導入済みアプリの記録された配布元を自動確認します。定期的な進捗確認では外部取得しません。詳細は[画面仕様](WEB_UI.md)を参照してください。

## 3. 互換性のある公開済み版を選ぶ

現行CPUと現在版に対応し、compatible_fromに現在版を含む候補を選びます。
選定版の[Release](https://github.com/flamoris-jp/flamoris-updater/releases)とrelease notesも確認します。
候補がない場合は「更新なし」であり、別の版を推測して実行しません。

公開済み1.0.13のカタログは1.0.3〜1.0.12を互換元に含みます。
固定した1.0.13のカタログは
https://github.com/flamoris-jp/flamoris-updater/releases/download/v1.0.13/catalog.json
です。1.0.13導入済み環境で、この版を再度選ぶ手順ではありません。

## 4. 更新を一度だけ開始し、返されたjob_idを記録する

Webでは自己更新欄の版を選び「Updaterを更新」を押します。
CLIの次の例は、カタログで1.0.13への互換更新が確認できた旧版環境だけで使います。

```bash
request_key="$(python3.12 -c 'import uuid; print(uuid.uuid4())')"
"$updater_bin" self-update --url "$updater_url" \
  --release 1.0.13 --request-key "$request_key"
```

開始前にrequest_key、開始後に返されたjob_idを記録します。
応答が失われたときは新しいrequest_keyでやり直さず、同じキー・引数で既存ジョブを照会／再取得します。
通常の進捗確認には次を使います。job-REPLACEは実際のIDに置き換えます。

```bash
"$updater_bin" job --url "$updater_url" --job-id job-REPLACE
```

自己更新中はWeb／API／MCPが一時的に切れます。接続回復後も同じジョブを確認します。
読み取りの再接続と、更新操作の再実行を混同しません。自動rollback・失敗ジョブの自動再送はありません。

## 5. 成功と保持を確認する

ジョブがsucceededになり、ヘッダー／self-statusの稼働版が選定版と一致したことを確認します。
設定・カタログ登録・履歴・アプリの導入記録は引き継ぎます。
GPU切替やprovider推論を自己更新確認へ追加しません。

supervisorは最初の本体配置に固定されており、自己更新でWeb／managerと一緒に置き換えません。
**元の配置を削除しないでください。** 自己更新版はbootstrapの状態ディレクトリ内のreleasesへ配置されます。
supervisor自身の交換は別の管理者メンテナンスです。

## 古い版・途中状態の例外

- 設定済み1.0.3で登録URLを変更できない場合は、[1.0.3専用のカタログ切替](UPGRADE_103.md)を使ってから既存画面で自己更新します。
- 1.0.1の元supervisorにはGitHub Release redirect対応がありません。Web／managerだけの更新では解決せず、元の設定・ジョブ・配置を確認した管理者メンテナンスが必要です。
- 管理画面が起動しない／更新が中断した場合は[診断・手動復旧](DIAGNOSTICS.md)へ進みます。既存の状態を消して初回bootstrapを通すことはしません。

以下は実装契約と検証の詳細です。通常の手順は上記1〜5で完結します。

## Self-update contract

New bootstrap starts three services: unprivileged Web, local root manager and
independent root supervisor. The supervisor stays in its original installation
so stopping/replacing the first two does not stop the update controller. Never
delete that installation. Updating the pinned supervisor itself remains explicit
bootstrap maintenance; this is not a claim to replace every privileged component.

Distribution 1.0.3 applies the checked public-release redirect policy described in
[installation](INSTALL.md) to supervisor bundle downloads as well as manager
catalog/app downloads. The published 1.0.1 supervisor does not contain that
correction. Replacing Web/manager alone cannot enable GitHub Release downloads
for it; install a corrected distribution through explicit administrator bootstrap
maintenance with current Job/journal/binding inspection. This source work does
not modify a live pinned unit or discard the original installation.

The catalog's `updater_releases` bind release, platform, explicit compatible
predecessors, HTTPS Native archive digest/index/budget and supervisor protocol 1.
Maintainers can include a bundle with:

```bash
python scripts/build_install_catalog.py --updater-bundle dist/native/bundle-digests.json https://releases.example.invalid/updater/1.1.0 --compatible-from 1.0.0 --output dist/catalog.json
```

The recipe can coexist with repeated `--candidate` application recipes. A
withdrawn release cannot be republished with different contents. API callers
choose an available version and request key; they cannot choose paths/commands.

Only one local Job may be active. The supervisor records stage → stop →
control-check → switch → start → verify intents/outcomes with timestamps.
Staging verifies archive/index/files, release metadata, imports and runtime
identity. After stopping Web/manager, both existing journal stores must pass the
candidate's read-only v1 schema/content probe. No data migration occurs. Drifted
bootstrap configuration or managed units are rejected rather than overwritten.
Final checks require the actual Web and manager versions/runtime paths, not just
HTTP 200 or an active unit. Settings and history stay in place. Historical account records may remain in existing journals but are no longer used by the endpoint.

Current and immediately previous Updater records are retained; staged self
bundles and the original supervisor installation are not automatically deleted.
Application current-plus-one cleanup remains independent. Failed/interrupted
self Jobs retain their candidate, completed steps and last intent, stop at
`recovery_required`, block subsequent local work, and are not replayed or rolled
back automatically. Detailed exception output is not included in public Jobs.

## Continuing MCP operation

Streamable HTTP needs no Updater credential. Self-update causes a temporary outage; clients reconnect at the same URL and read the same durable Job. A lost response is reconciled with the same request key. Client reconnection and external proxy/tunnel access remain deployment responsibilities. Scheduled checking/updating is not added.

## Diagnostic evidence and manual recovery

Ordinary app install/update, setup verification, cleanup and self-update now record
structured intent/completion/failure timelines. Read-only scoped MCP tools
`updater_managed_log_get` and `updater_managed_layout_get` expose those records and
recorded current/candidate/previous placement. Command failures include fixed
classification and exit/errno context without raw output, credentials or SQL.
This supersedes the earlier investigation finding that latest Job state alone
was insufficient. Earlier Jobs do not receive invented retrospective logs.

If Updater Web/manager itself is unavailable, its MCP endpoint is unavailable.
Manual recovery through an independent administrator channel is required;
Server Manager can support AI investigation only if independently available.
See [AI-readable evidence and manual recovery](DIAGNOSTICS.md) for record fields,
limits, offline private exports, uncertainty and the human investigation procedure.

## Validation boundary

Tests exercise real indexed archive staging, protected journals, candidate
read-only probes of both SQLite stores, credential-free Web/CLI/MCP continuity and supervised Job failure/interruption. Only
systemd and running service identity commands are controlled in the self Job
tests. Native-bundle CI separately imports the actual packaged dependencies and
checks its runtime identity on amd64/arm64. This does not certify real host
service replacement, external clients, tunnels or application domain behavior.

