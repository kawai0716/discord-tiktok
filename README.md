# TikTok 複数ハッシュタグ → Discord

Python + Playwright + GitHub Actions で公開タグページを定期確認し、設定条件に一致した動画を Discord Webhook で通知します。初期設定は **`#lovely7` のみ**です。

## 最初に知っておいてほしいこと

**条件判定・重複排除・通知キューは実装済みですが、TikTokから常に取得できることや、新着を漏れなく検出できることは保証できません。** タグページは新着順の一覧ではなく、地域やアクセス元、ログイン状態、TikTokの変更によって表示が変わります。GitHubの実行環境からアクセスが制限される場合もあります。まず後述の「通知なしテスト」で、その環境で取得できるか確認してください。

- 有料サービス・有料プロキシ・TikTokのログインCookieは不要です。CAPTCHAやアクセス制限の回避処理はありません。
- 公開リポジトリの標準GitHubホストランナーは無料です。非公開リポジトリにはプランごとの無料枠があり、30分ごとのブラウザ起動では超過する可能性があります。無料優先なら公開リポジトリを使ってください。[GitHub公式の課金説明](https://docs.github.com/en/actions/concepts/billing-and-usage)
- 公開リポジトリではタグ設定・通知済みID・送信待ち投稿の本文も公開されます。Webhook URLはGitHub Secretにだけ保存します。
- GitHubの予約実行には遅延・取りこぼしがあり、公開リポジトリは60日間活動がないと予約実行が無効化されます。Actions画面をときどき確認してください。[GitHub公式のschedule説明](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)
- 公開ページへのアクセスでも、利用時点のTikTokの利用条件に従ってください。

## 1. GitHubに配置する

1. GitHubで新しいリポジトリを作成します。無料運用を優先する場合はPublicを選びます。
2. このフォルダのファイルをアップロードします。**`.github/workflows/` も必要**です。GitHub Desktopでこのフォルダをリポジトリ化してPublishすると、隠しフォルダの取りこぼしを避けられます。
3. `config.json` と `.github/workflows/monitor.yml` がデフォルトブランチ（通常 `main`）にあることを確認します。
4. リポジトリの **Settings → Actions → General → Workflow permissions** で書き込みを許可します。組織の設定で禁止されている場合は管理者による変更が必要です。`monitor-state` ブランチへの作成・更新を保護ルールで禁止しないでください。

コードを置いただけでは、こちらからGitHubへの公開やDiscordへの送信は行われません。

## 2. DiscordのWebhookを登録する

1. 通知先チャンネルの **チャンネルの編集 → 連携サービス → ウェブフック** でWebhookを作成します（管理権限が必要です）。
2. Webhook URLをコピーします。
3. GitHubの **Settings → Secrets and variables → Actions → New repository secret** を開きます。
4. Nameに `DISCORD_WEBHOOK_URL`、SecretにコピーしたURLを設定します。

URLはパスワードと同じように扱い、`config.json` やREADMEには貼り付けないでください。漏えいした場合はDiscord側でWebhookを作り直します。

## 3. 通知なしテストと初期化

初回配置時は **Actions → TikTok connection check** も自動実行されます。GitHub上でTikTok取得を試すだけのテストなので、Webhookや状態ブランチの準備は不要です。失敗した場合は取得ログを確認してください。手動の再実行も可能です。

1. **Actions → TikTok monitor → Run workflow** を開きます。ブランチはデフォルトブランチを選びます。
2. まず `dry_run` だけをONにして実行します。これはDiscord送信も履歴保存もしません。
3. 実行ログの `fetched` と `deduplicated` を確認します。取得エラーなら「困ったとき」を確認してください。0件のまま無理に初期化しないでください。
4. 取得できたら `dry_run` をOFF、`initialize` をONにして、もう一度実行します。
5. `baseline_saved` が出て、`monitor-state` ブランチに `state.json` が作成されれば初期化完了です。**この回は通知されません。**
6. 初期化に成功したら **Settings → Secrets and variables → Actions → Variables → New repository variable** で `MONITOR_ENABLED` を `true` にします。以降は毎時17分・47分（UTC基準、日本でも毎時17分・47分）に実行されます。手動実行では両方OFFにします。取得エラーが続く間はこの変数を設定せず、定期実行を停止したまま診断してください。手動実行は変数なしでも可能です。

初期化前の定期実行は「状態がありません」で停止します。`initialize` は既存履歴をリセットする操作ではありません。初回取得に失敗した場合は、取得可能になってから初期化を再実行してください。

Discordへの実配送は、初期化後に作成され、条件に一致し、取得できた動画で確認します。投稿がない間は通知がないのが正常です。

## 4. 条件を変更する

`config.json` の `rules` を編集して保存（コミット）するだけです。各ルールはORでつながり、**どれか1つが成立すれば動画ごとに1回通知**します。

### 単一タグ

```json
{"name": "lovely7", "allOf": ["lovely7"]}
```

### AND

```json
{"name": "誕生日", "allOf": ["lovely7", "birthday"]}
```

### OR

```json
{"name": "表記ゆれ", "anyOf": ["lovely7", "lovelyseven"]}
```

### OR + AND

```json
{
  "name": "表記ゆれ + birthday",
  "allOf": ["birthday"],
  "anyOf": ["lovely7", "lovelyseven"]
}
```

### 3つ中2つ以上

```json
{
  "name": "3タグ中2つ",
  "tags": ["event", "idol", "birthday"],
  "minMatches": 2
}
```

例えば設定全体を次に置き換えると、上記の複合条件と最低一致数を同時監視できます。

```json
{
  "rules": [
    {
      "name": "表記ゆれ + birthday",
      "allOf": ["birthday"],
      "anyOf": ["lovely7", "lovelyseven"]
    },
    {
      "name": "3タグ中2つ",
      "tags": ["event", "idol", "birthday"],
      "minMatches": 2
    }
  ],
  "maxNotificationsPerRun": 20,
  "collector": {"scrolls": 3, "waitSeconds": 5}
}
```

全種類を並べたサンプルは [examples/config.multiple.json](examples/config.multiple.json) にあります。ただし `lovely7` 単体ルールを残すと、`birthday` がなくても単体ルールによって通知されます。

| 項目 | 意味 |
| --- | --- |
| `name` | 一意なルール名。Discordにも表示 |
| `allOf` | すべて必要 |
| `anyOf` | 1つ以上必要 |
| `tags` + `minMatches` | 重複を除いたタグのうち指定数以上が必要 |
| `maxNotificationsPerRun` | 1回の通知上限。1〜100、標準20。残りは保留 |
| `collector.scrolls` | タグページのスクロール回数。0〜20、標準3 |
| `collector.waitSeconds` | 初回・スクロール後の待機秒数。1〜30、標準5 |

同一ルールに複数種類の条件を書くと、条件間はANDです。タグは先頭の `#` を除去し、Unicode NFKC正規化・大小文字の同一視を行います。日本語タグも使えます。部分一致ではなく完全一致です。空ルール、キーのタイプミス、不正な最低一致数は実行前にエラーになります。JSONにはコメントを書けません。

監視タグは全ルールのタグの和集合から自動計算します。広いタグ（`idol` など）を増やすと取得時間と取りこぼしが増えます。まず必要なタグだけで始めてください。

**条件の追加・削除・変更後、最初に全タグの取得に成功した回は、新しい基準を保存して通知を抑止します。** 過去動画の大量通知を避ける設計です。その回までに投稿された動画も通知対象外になる点に注意してください。ルール名変更・並べ替え・通知上限変更だけでは基準を作り直しません。送信待ちは現在のルールにまだ一致する分だけ残します。

## 判定・履歴の仕組み

1. 全監視タグの公開ページをPlaywrightで開き、ページが取得した動画一覧JSON・埋め込み動画データを読みます。
2. 動画IDで重複排除します。タグページの名前から動画のタグを推測せず、動画自身のcaptionとタグメタデータを使います。
3. 全タグで有効な動画が取れた場合だけ、ルール判定と履歴更新に進みます。
4. 初回は現在の全候補IDと基準時刻を保存し、通知しません。
5. 以後、基準時刻より後に作成された未通知の一致動画を送信待ちに保存します。古い動画が後日初めて表示されても通知しません。
6. Discordがメッセージの保存を確認したら、動画IDを既知にして直ちに保存します。

履歴はキャッシュや期限付きArtifactsではなく、`monitor-state` ブランチのJSONに保存します。状態が変わらない回はコミットしません。並行実行はGitHub Actionsのconcurrencyで直列化し、状態更新はSHAによる競合検出を使います。履歴の自動削除はしません。

送信失敗・上限超過の動画は本文ごと送信待ちに残ります。次回、TikTokの全タグ取得が正常に終了した後に再試行します。新着一覧から消えても再試行できますが、削除済み投稿の再確認は行いません。Discordが429を返した場合は指定時間を待ち、最大3回まで試します。その他の送信エラーではその回の配送を止め、失敗をActionsに表示します。

**完全な「絶対1回だけ」の保証はありません。** Discordで送信が成功して応答が失われた場合や、送信成功直後にGitHubへの状態保存が失敗した場合は、次回に重複する可能性があります。Discord WebhookとGitHubの保存を1つのトランザクションにはできないためです。通常時の複数タグ・複数ルールによる重複は防ぎます。[Discord Webhookの公式仕様](https://docs.discord.com/developers/resources/webhook#execute-webhook)

## 失敗時の扱い・限界

- HTTP 200でも動画0件なら正常な空一覧とはみなしません。真の0件とアクセス制限を確実に区別できないため、安全側に倒して状態変更も通知も止めます。そのため、まだ投稿がないタグを設定すると監視全体が停止します。
- 初回の一時エラー画面に限り、同じタグページを最大2回リロードして再試行します。スライダーやパズルなどの人間確認を検出した場合は、それ以上試行せず停止します。
- 一部のタグだけ取得失敗しても、その回は全体を止めます。初回に不完全な基準を保存することを防ぎます。
- 0件でなくてもTikTokが一部の動画しか返さないケースは検出しきれません。スクロール回数を増やしても全件・新着順は保証されません。
- 基準時刻以前の投稿、実行間隔の間に削除された投稿、ページに出ない投稿、非公開動画は通知できません。
- GitHub Actions以外から同じ状態を同時に操作しないでください。ローカルJSONにも同時に複数プロセスを起動しないでください。
- 状態ファイルが壊れていたりアクセスが拒否されたりした場合、自動リセットしません。ブランチ履歴から復旧してください。ブランチの削除は履歴消失になります。
- 大量運用ではJSONとGitの履歴が増えるため、DBへの移行が必要です。GitHub Contents APIのサイズ上限も考慮し、JSONが1MBに近づいたら保存先の変更を検討してください。

## ログと困ったとき

GitHubの **Actions → 実行履歴 → monitor → Collect and notify** を開きます。

| ログ | 意味 / 対応 |
| --- | --- |
| `watch_tags` / `fetched` | 監視タグ数 / 各タグから得た動画数 |
| `deduplicated` / `matching` / `matched` | 重複排除後の件数 / 一致件数 / 動画別の一致ルール |
| `new_videos` / `pending` | 基準時刻より後の未処理候補数 / 送信待ち数 |
| `baseline_saved` | 初回または条件変更後の基準保存。通知なし |
| `discord_success` / `discord_failure` | 送信成功 / 失敗件数 |
| 有効な動画0件 / ブラウザ取得失敗 | アクセス制限、空タグ、地域差、仕様変更など。状態は更新しません |
| HTTP 401 / 403 / 404 | Discord送信ならWebhookを確認。GitHub状態保存なら権限やブランチを確認 |
| HTTP 409 / 422 | 状態更新の競合やブランチ保護を確認。並行した別プロセスがないか確認 |
| HTTP 0 | タイムアウト・通信異常・不正なJSON応答。送信済みか不明な場合があります |

TikTok取得が失敗する場合は、通常ブラウザでタグページが開けるか確認し、ローカルの `--headed --dry-run` で表示を確認します。アクセス制限が続く場合は実行頻度を落とすか停止してください。自宅PCの定期実行に変更するとアクセス元が変わりますが、取得成功を保証するものではありません。取得方式の修正は `monitor/collector.py` にまとめてあります。

Actionsの実行失敗通知をGitHubの通知設定で有効にすると停止を把握しやすくなります。TikTok取得に失敗したことをDiscordの新着動画として通知する処理はありません。

## ローカル実行（任意）

Python 3.12以上を使います。PowerShellでは `python3` を `python` に置き換えてください。

```bash
python3 -m venv .venv
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

macOS / Linux:

```bash
source .venv/bin/activate
```

続いて:

```bash
python -m pip install -r requirements.txt
python -m playwright install chromium
python -m monitor --validate-config
python -m monitor --dry-run
```

Linuxで共有ライブラリが不足する場合は `python -m playwright install --with-deps chromium` を使います。

Discord通知を有効にする場合は環境変数に設定します（実際のURLを共有・コミットしないこと）。

```powershell
$env:DISCORD_WEBHOOK_URL = "DiscordでコピーしたURL"
python -m monitor --initialize
python -m monitor
```

macOS / Linuxでは `export DISCORD_WEBHOOK_URL='DiscordでコピーしたURL'` です。ローカルでは `state.json` に保存し、GitHub上の履歴とは独立しています。`--state パス` で変更できます。`.env` ファイルの自動読み込みはありません。

## 開発・検証

```bash
python -m unittest discover -s tests -v
```

テストは外部通信もDiscord送信もしません。AND/OR/最低一致数、日本語・全角タグ、初回抑止、複数ルールの重複排除、失敗後の再送、取得失敗時の履歴維持、設定変更、通知上限、状態破損、Discordの保存確認などを検証します。

| ファイル | 役割 |
| --- | --- |
| `config.json` | 利用者が編集する設定 |
| `monitor/collector.py` | TikTok公開ページの取得・解析 |
| `monitor/rules.py` | 正規化・設定検証・ルール判定 |
| `monitor/engine.py` | 初回処理・新規判定・送信待ち管理 |
| `monitor/discord.py` | Discord通知 |
| `monitor/state.py` | ローカルJSON / GitHubへの永続保存 |
| `monitor/models.py` | 共通データと交換用インターフェース |
| `.github/workflows/monitor.yml` | 定期・手動実行 |
| `.github/workflows/test.yml` | コード・設定変更の検証 |
| `.github/workflows/check-tiktok.yml` | 初回配置時・手動の実サイト取得テスト（送信・保存なし） |

取得アダプターは `collect(tags) -> {tag: [Post, ...]}`、通知アダプターは `send(post, rules)`、保存アダプターは `load()/save(state)` です。将来のSlack・LINE・DB連携はこの境界で追加できます。

実際の環境での検証結果は [VERIFICATION.md](VERIFICATION.md) を参照してください。
