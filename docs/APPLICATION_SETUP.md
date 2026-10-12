# Updaterで各アプリを導入する：入力値と導入後の設定

このガイドは、利用者がAIに相談しながら初回導入を進める入口です。
対象は公開のGPU Node Manager 1.2.2、Agent／Generation MCP／Intelligence MCP／Hub 1.0.2、Studio 1.0.3です。
各アプリのインストール定義と導入後契約を確認した2026-10-12の案内です。
別の版・private統合版では、その配布元のカタログと手順を確認します。

Updater自身は[初回導入](DISTRIBUTION.md)と[自己更新](SELF_UPDATE.md)の別手順を使います。

## 最初に読むアプリ別ガイド

| アプリ | 初回入力で主に必要なもの | 導入後に設定するもの | 詳細 |
| --- | --- | --- | --- |
| GPU Node Manager | 未使用のWebポート | 既存runtimeのsystemd／health／process対応を表すYAML、共通lock、外部接続 | [入力値・手順](https://github.com/flamoris-jp/flamoris-gpu-node-manager/blob/main/docs/FIRST_SETUP.md) |
| AI Agent | DB管理者接続、DB到達先、llama.cpp URL。接続tokenと新規DBパスワードは生成可能 | Human／Agent／Project、人格、モデル、delegation・利用／編集権限、Studio対応 | [入力値・手順](https://github.com/flamoris-jp/flamoris-ai-agent/blob/main/docs/FIRST_SETUP.md) |
| Generation MCP | ComfyUI URL、既存model folder。Controller tokenは生成可能 | provider・model／input領域、Studio Controller接続、任意の外部MCP／追加provider | [入力値・手順](https://github.com/flamoris-jp/flamoris-generation-mcp/blob/main/docs/FIRST_SETUP.md) |
| Intelligence MCP | llama.cpp URL、公開IDと実served IDの対応JSON | provider model接続、任意のHub／外部MCP | [入力値・手順](https://github.com/flamoris-jp/flamoris-intelligence-mcp/blob/main/docs/FIRST_SETUP.md) |
| MCP Hub | 未使用ポート、外部入口Host。Hub tokenは生成可能 | upstream YAMLと接続先、外部clientの認証、proxy／トンネル | [入力値・手順](https://github.com/flamoris-jp/flamoris-mcp-hub/blob/main/docs/FIRST_SETUP.md) |
| Studio | DB管理者接続、DB到達先。使う連携のURLと相手のtoken | Studio account、Agent側権限と正確なaccount対応、生成／推論の対象設定、公開URL | [入力値・手順](https://github.com/flamoris-jp/flamoris-studio/blob/main/docs/FIRST_SETUP.md) |

ControllerはGeneration MCPに同居する固定libraryです。別のController daemonを追加しません。
Hubは外部MCP入口です。Studio→Controller、Studio→Agent、内部推論のためにHub経由へ接続しません。

## 入力値を四つに分ける

| 種類 | 値の用意 | 例 |
| --- | --- | --- |
| 自分で決める値 | 用途と現在の環境を確認して選ぶ | 未使用ポート、新規DB名、公開モデルID、委譲者名 |
| 既存サービスから取得する値 | 実際のservice設定／管理者／モデル一覧で確認する | PostgreSQL管理者DSN、DBホスト、ComfyUI／llama.cpp URL、served model ID、model folder |
| 空欄で自動生成する値 | カタログのgenerate=trueに限ってUpdaterが生成する | 新規DBのOWNER_PASSWORD／RUNTIME_PASSWORD、GenerationのCONTROLLER_TOKEN、AgentのAGENT_TOKEN、HUB_TOKEN |
| 相手側と同じ値を使うもの | 生成元の保存済み設定から取得して接続先へ設定する | StudioのGENERATION_TOKEN、StudioのAGENT_TOKEN、Hubに接続する外部clientのtoken |

**既定値は入力欄に最初に入る値です。** ポート・URL・JSON等は必要な内容に置き換えるか、そのまま使います。
欄を空にすることで必ず既定値へ戻るわけではありません。
空欄の自動生成はgenerate=trueの項目だけです。任意欄でも、その連携を使うには値が必要な場合があります。
画面での詳細な用途・取得元表示は[#39](https://github.com/flamoris-jp/flamoris-updater/issues/39)の後続開発です。

## トークンとパスワードは何者か

FLAMORISのservice tokenは、接続する二つのサービスが同じ秘密値を使って相手を認証するものです。
外部サイトから払い出してもらうAPI keyとは違います。StudioのログインパスワードやDB接続パスワードとも違います。

| 生成／設定する側 | 保存先の現行環境変数 | 同じ値を使う側 | 目的 |
| --- | --- | --- | --- |
| GenerationのCONTROLLER_TOKEN | FLAMORIS_CONTROLLER_TOKEN | StudioのGENERATION_TOKEN → STUDIO_GENERATION_TOKEN | Studio backend→Controller内部HTTP |
| AgentのAGENT_TOKEN | AGENT_MCP_TOKEN | StudioのAGENT_TOKEN → STUDIO_AGENT_TOKEN | Studio backend→Agent内部HTTP |
| HubのHUB_TOKEN | FLAMORIS_MCP_HUB_CLIENT_TOKEN | 外部MCP clientのBearer認証設定 | 外部client→Hub。upstreamへそのまま転送する値ではない |
| 各DBアプリのOWNER_PASSWORD | 初期化／migration用のrole credential | そのアプリ所有者role | 新規DBのschema管理 |
| 各DBアプリのRUNTIME_PASSWORD | そのアプリのDB接続設定 | そのアプリruntime role | 通常のDB読書き |
| DB管理者が持つ既存credential | ADMIN_DSNに含める | Updaterからの新規DB／role作成 | 既存PostgreSQLに新規アプリ用DBを作る |
| 外部providerのAPI key | 選定providerのbackend設定 | 許可した外部API adapter | 任意の外部推論。FLAMORIS tokenとは別 |

GenerationとStudio、AgentとStudioで**それぞれ別のtokenを生成しない**でください。
生成元が先に作った値を、利用する側へ設定します。
自動生成のservice tokenを使う場合、Updaterは32byteの乱数からURL-safeな文字列を作ります。
手動指定はカタログの形式とアプリ側の条件を両方満たす必要があります。生成された値の利用が簡単です。

## 自動生成された値はどこにあるか

現在のUpdaterは、入力した値と自動生成した値をmanager側の管理者専用settingsへ保存します。
場所はmanagerの状態directory配下の **settings/{application_id}/values.json** です。
通常bootstrapの既定例では **/var/lib/flamoris-updater/helper/settings/{application_id}/values.json** ですが、
実際のbootstrap設定・配置情報から場所を確認します。private統合版へこのpathを無条件に流用しません。

アプリの現行recipeは、service token等をアプリroot配下の **config/runtime.env** にも反映します。
アプリrootはUpdaterの配置情報から取得します。上の対応表の環境変数名を確認してください。

現在の一般画面・通常APIは秘密値を表示しません。
接続を設定する権限のある管理者が、生成元の設定から**必要な項目だけ**をローカルで取り出し、
接続先のpassword欄／保護された設定へ入れます。AIには設定名・所在・同一値の対応を示せばよく、
secretそのものやvalues.json／runtime.env全文を会話・ログへ貼る必要はありません。
コピー手順を作るAIは、実際の権限・配置と相手側契約を確認し、値を画面へprintしない方法を使います。

## PostgreSQLの入力は何を指すか

ADMIN_DSNは、**既に存在するPostgreSQLの管理者接続**です。Updaterがこれを新規生成することはありません。
DB管理者へ確認します。形式例は次です。これは実値ではありません。

```text
postgresql://DB_ADMIN:URL_ENCODED_PASSWORD@DB_HOST:5432/postgres
```

接続先DB、管理者名、password、Host、Portは既存環境の値を使います。
passwordにURL予約文字がある場合は接続文字列の形式に合わせてencodeします。
新規DB・roleを作成できる権限と、その接続先への到達性を確認します。

PGHOST／PGPORTは作成されたアプリがDBへ接続する値です。
初期化は導入host、runtimeはhost／containerのネットワークで実行されるため、必要な両方から到達できる名前を使います。
Studioの公開recipeはbridge containerです。そこからの127.0.0.1はDB hostではなくcontainer自身です。

DATABASEは**新しく作るアプリ専用DB名**です。既存DBやroleを再初期化する値ではありません。
OWNER_PASSWORD／RUNTIME_PASSWORDはその新規roleのpasswordで、ADMIN_DSNに含まれる既存管理者passwordとは別です。
Updaterはアプリ所有のschema／migrationを実行します。初回導入後のguideから同じ初期schemaを重複実行しません。

## URLとモデルIDをどう用意するか

- ComfyUI／llama.cpp URLは既存serviceの待受設定から取得し、アプリの実行環境から到達できるか確認する。
- StudioのController URLは正確な/api/v1/generationのbaseを含める。
- StudioのAgent URLはoriginのみ。/api/v1や/mcpを付けない。
- raw推論URLはモデルproviderのbase。Hub／Intelligence MCPの/mcpとは別。
- provider_modelは実際のモデル一覧のserved IDを使う。公開モデルIDやモデルファイルpathをそのまま代用しない。
- model folderはインストール先hostの既存directory。モデルdownload・GPU runtimeの導入は別工程。

## インストールと制作準備の順番

1. **用途を選ぶ**：画像、会話、外部MCP、Speech／Musicなど、今回使う機能を決める。
2. **値を用意する**：上の四分類で入力値と取得元を確認する。空欄の意味を確認して入力する。
3. **Updaterで導入する**：インストールjobを追い、awaiting_setupまで進める。失敗／途中状態では同じ初期処理をまとめて再実行しない。
4. **アプリを起動し初回設定する**：Updaterの起動ボタンとアプリ所有のguideを使い、account・identity・profile・モデル・連携を設定する。
5. **Updaterの動作確認を完了する**：アプリの起動・healthを確認してsucceededにする。
6. **選定した機能を確認する**：ログイン、会話、対象生成・preview／download、外部client接続を必要な範囲で確認する。

アプリは独立に導入できます。Studio連携の接続値を最初から入力したい場合は、生成元のAgent／Generationを先に設定するとtokenの取得元が分かります。
すべてのserviceを同時に導入・有効化する必要はありません。

## AIに渡す確認項目

> 選定したReleaseのインストール定義とFIRST_SETUP.mdを読んでください。
> 対象アプリ／版、実際の配置、今回使う機能を確認してください。
> 入力値を「自分で決める／既存から取得／自動生成／相手と同じ値」に分類し、
> 導入時にUpdaterが実行済みの処理と、残るapp設定を分けて進めてください。
> 秘密値はローカルの必要項目だけを扱い、会話へ出さないでください。
> 実機状態が必要ならServer Managerで確認し、成功済みの初期設定やjobを再実行しないでください。

公開の手順には実環境のhostname・account・private topologyを固定しません。
