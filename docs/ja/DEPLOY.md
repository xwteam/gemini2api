# デプロイガイド

Gemini2API を本番環境にデプロイするための完全なガイドです。

## 環境要件

| 要件 | 最小値 | 推奨値 | 説明 |
|------|--------|--------|------|
| Docker | 20.10+ | 最新版 | コンテナ化デプロイ用 |
| メモリ | 512MB | 2GB+ | 複数アカウント運用時は 2GB 以上推奨 |
| ディスク | 100MB | 500MB+ | ログ・Cookie 保存用 |
| OS | Linux/Mac/Windows | Linux | Docker Desktop で Windows/Mac 対応 |
| Python | 3.12+ | 3.12+ | Docker 使用時は不要 |
| ネットワーク | — | — | gemini.google.com への直接アクセス必須 |

## Cookie 取得手順

Gemini2API を動作させるには、Google アカウントの Cookie が必要です。以下の手順で取得してください。

### ステップ 1: ブラウザで Gemini にアクセス

1. Chrome または Edge ブラウザを開く
2. [gemini.google.com](https://gemini.google.com) にアクセス
3. Google アカウントでログイン
4. Gemini が正常に使用できることを確認

### ステップ 2: 開発者ツールを開く

1. キーボードで `F12` を押す（または右クリック → 検査）
2. 上部のタブから **Application**（アプリケーション）を選択

### ステップ 3: Cookie を取得

1. 左側のサイドバーから **Cookies** を展開
2. `https://gemini.google.com` をクリック
3. Cookie リストから以下の 2 つを探す：

| Cookie 名 | 説明 | 例 |
|-----------|------|-----|
| `__Secure-1PSID` | `g.` で始まる長い文字列 | `g.a000xxx...` |
| `__Secure-1PSIDTS` | 短い文字列 | `sidts-xxx...` |

4. 各 Cookie の **Value** 列をダブルクリックして完全な値をコピー

> **ヒント**: 検索ボックスに `__Secure-1P` と入力すると、該当する Cookie をすぐに見つけられます。

> **注意**: 無痕モード（シークレットモード）での操作を推奨します。ページをリロードすると Cookie が変更される可能性があります。

## Docker デプロイ

### ステップ 1: リポジトリをクローン

```bash
git clone https://github.com/xwteam/gemini2api.git
cd gemini2api
```

### ステップ 2: 環境変数ファイルを作成

```bash
cp .env.example .env
```

### ステップ 3: .env ファイルを編集

テキストエディタで `.env` を開き、取得した Cookie を設定します：

```env
GEMINI_PSID=g.a000xxx...
GEMINI_PSIDTS=sidts-xxx...
API_KEY=
PORT=5918
REFRESH_INTERVAL=5
MAX_RETRIES=3
LOG_LEVEL=info
RATE_LIMIT_ENABLED=false
HEALTH_CHECK_ENABLED=true
ROTATION_STRATEGY=round-robin
MAX_CONCURRENT_PER_ACCOUNT=8
```

**重要な設定項目：**

| 変数 | 説明 | デフォルト |
|------|------|-----------|
| `GEMINI_PSID` | `__Secure-1PSID` Cookie | 必須 |
| `GEMINI_PSIDTS` | `__Secure-1PSIDTS` Cookie | 必須 |
| `API_KEY` | API アクセスキー（空白で自動生成） | 自動生成 |
| `ADMIN_API_KEY` | 管理パネル/`/admin` 専用認証キー（空白で `API_KEY` にフォールバック） | — |
| `PORT` | サービスポート | 5918 |
| `REFRESH_INTERVAL` | Cookie 更新間隔（分） | 5 |
| `MAX_RETRIES` | 失敗時の再試行回数 | 3 |
| `ACCOUNTS_FILE` | マルチアカウント設定ファイルのパス（存在しなければ単一アカウントモード） | accounts.json |
| `ROTATION_STRATEGY` | 負荷分散戦略（round-robin/failover） | round-robin |
| `MAX_CONCURRENT_PER_ACCOUNT` | アカウント当たりの最大並行数 | 8 |
| `ACQUIRE_TIMEOUT` | 並行満載時に空きスロットを待つ上限（秒） | 60.0 |
| `SAME_ACCOUNT_5XX_RETRIES` | 5xx 時の同一アカウント高速リトライ回数（なお失敗すれば failover） | 1 |
| `FAILOVER_COOLDOWN` | 5xx で制限されたアカウントのクールダウン時間（秒） | 30.0 |
| `FINGERPRINT_CONFIG_PATH` | フィンガープリント設定ファイルのパス | data/fingerprint.json |
| `VERSION_SYNC_ENABLED` | Chrome バージョン自動同期を有効化 | true |
| `VERSION_SYNC_INTERVAL` | バージョン同期間隔（時間） | 24 |
| `JITTER_ENABLED` | リクエスト時間ジッターを有効化 | true |
| `USAGE_STATS_ENABLED` | 使用統計を有効化（時系列スナップショット + 永続化） | true |
| `USAGE_STATS_INTERVAL` | スナップショット採集間隔（秒） | 300 |
| `USAGE_STATS_RETENTION_DAYS` | 履歴データの保持日数 | 30 |
| `MODEL_WHITELIST` | モデルホワイトリスト（カンマ区切り、空でフィルタなし；非空時は各 `/models` 一覧をフィルタ） | — |
| `CHAT_CLEANUP_ENABLED` | Gemini ウェブ側セッションの自動クリーンアップを有効化 | true |
| `CHAT_CLEANUP_KEEP_HOURS` | ウェブセッションの保持時間（時間） | 24.0 |
| `CHAT_CLEANUP_INTERVAL_HOURS` | 自動クリーンアップタスクの実行間隔（時間） | 6.0 |
| `CHAT_CLEANUP_SKIP_PINNED` | クリーンアップ時にピン留めセッションをスキップ | true |
| `CORS_ALLOW_ORIGINS` | CORS 許可オリジン（カンマ区切り、`*` ですべて許可） | * |
| `CORS_ALLOW_CREDENTIALS` | CORS で資格情報の送信を許可するか | true |
| `IMAGE_DOWNLOAD_SIZE_SUFFIX` | 生図代理ダウンロードのサイズサフィックス（`=s0` でフル解像度） | =s2048 |
| `IMAGE_DOWNLOAD_TIMEOUT` | 画像ダウンロード 1 回あたりの HTTP タイムアウト（秒） | 25.0 |

> **注意**: 値に引用符は不要です。余分なスペースや改行がないことを確認してください。

### ステップ 4: サービスを起動

```bash
docker compose up -d
```

### ステップ 5: ログを確認

```bash
docker compose logs -f
```

起動成功の確認：

```
Account pool ready: 1/1 active
```

Cookie が無効な場合：

```
SNlM0e not found
```

この場合は、Cookie を再度取得して `.env` を更新し、`docker compose restart` を実行してください。

## マルチアカウント設定

複数の Google アカウントを使用して負荷分散を実現できます。

### accounts.json の作成

プロジェクトルートに `accounts.json` を作成します：

```json
{
  "accounts": [
    {
      "id": "account-0",
      "psid": "g.a000xxx...",
      "psidts": "sidts-xxx...",
      "label": "メインアカウント"
    },
    {
      "id": "account-1",
      "psid": "g.a000yyy...",
      "psidts": "sidts-yyy...",
      "label": "バックアップアカウント"
    },
    {
      "id": "account-2",
      "psid": "g.a000zzz...",
      "psidts": "sidts-zzz...",
      "label": "予備アカウント"
    }
  ]
}
```

### 設定項目

| フィールド | 説明 | 必須 |
|-----------|------|------|
| `id` | アカウント識別子（ユニーク） | ✅ |
| `psid` | `__Secure-1PSID` Cookie | ✅ |
| `psidts` | `__Secure-1PSIDTS` Cookie | ✅ |
| `label` | 表示用ラベル | ❌ |

### 起動

```bash
docker compose up -d
```

サービスは自動的に `accounts.json` を読み込み、複数アカウントで負荷分散を開始します。

> **ヒント**: `accounts.json` が存在しない場合、`.env` の単一アカウント設定が使用されます。

## 検証

### ヘルスチェック

```bash
curl http://localhost:5918/health
```

期待される応答：

```json
{"status":"ok","service":"gemini2api"}
```

### モデル一覧の確認

```bash
curl http://localhost:5918/openai/v1/models \
  -H "Authorization: Bearer sk-あなたのキー"
```

### テストリクエスト

```bash
curl -X POST http://localhost:5918/openai/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-あなたのキー" \
  -d '{
    "model": "gemini-2.5-pro",
    "messages": [{"role": "user", "content": "こんにちは"}]
  }'
```

AI からの応答が返ってくれば、デプロイは成功です。

## トラブルシューティング

### Cookie が 2 時間で期限切れになる

**症状**: 数時間後に `SNlM0e not found` エラーが発生

**原因**: Google の Cookie は定期的に期限切れになります

**解決方法**:

1. Web パネルのアカウント管理から Cookie を更新
2. または API で更新：

```bash
curl -X PUT http://localhost:5918/admin/accounts/account-0/cookies \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-あなたのキー" \
  -d '{
    "psid": "g.新しい値",
    "psidts": "sidts-新しい値"
  }'
```

3. または `.env` を更新して再起動：

```bash
# .env を編集
nano .env

# 再起動
docker compose restart
```

### ポート競合エラー

**症状**: `Error response from daemon: Ports are not available`

**原因**: ポート 5918 が既に使用されている

**解決方法**:

`.env` でポートを変更：

```env
PORT=5919
```

`docker-compose.yml` も更新：

```yaml
ports:
  - "5919:5918"
```

再起動：

```bash
docker compose up -d
```

### メモリ不足エラー

**症状**: コンテナが頻繁に再起動される

**原因**: メモリが不足している

**解決方法**:

1. **SWAP を追加**（Linux）:

```bash
# 2GB の SWAP ファイルを作成
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile

# 永続化
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

2. **並行数を削減**:

`.env` で `MAX_CONCURRENT_PER_ACCOUNT` を減らす：

```env
MAX_CONCURRENT_PER_ACCOUNT=1
```

3. **アカウント数を削減**:

`accounts.json` のアカウント数を減らす

### 認証エラー（401）

**症状**: `{"error": "Unauthorized"}`

**原因**: API Key が正しくない、または認証ヘッダーが不正

**解決方法**:

1. API Key を確認：

```bash
docker compose logs | grep "API_KEY"
```

2. 正しいヘッダーを使用：

```bash
# 正しい方法
curl -H "Authorization: Bearer sk-xxx"

# または
curl -H "x-api-key: sk-xxx"
```

### Cookie 無効エラー

**症状**: `SNlM0e not found` または `Invalid session`

**原因**: Cookie が期限切れ、または無効

**解決方法**:

1. Cookie を再度取得（上記の「Cookie 取得手順」を参照）
2. `.env` を更新
3. サービスを再起動：

```bash
docker compose restart
```

## 本番環境での推奨設定

```env
# セキュリティ
API_KEY=sk-生成されたキーを使用

# パフォーマンス
REFRESH_INTERVAL=10
MAX_RETRIES=5
MAX_CONCURRENT_PER_ACCOUNT=5
ROTATION_STRATEGY=failover

# 監視
LOG_LEVEL=info
HEALTH_CHECK_ENABLED=true
HEALTH_CHECK_INTERVAL=10

# 限流
RATE_LIMIT_ENABLED=true
RATE_LIMIT_WINDOW=60
RATE_LIMIT_MAX=100
```

## Docker Compose の詳細設定

`docker-compose.yml` の主要な設定：

```yaml
services:
  gemini2api:
    build: .
    container_name: gemini2api
    env_file:
      - .env
    environment:
      - TZ=Asia/Shanghai
    ports:
      - "5918:5918"
    volumes:
      - ./data:/app/data           # ログ・Cookie 保存
      - ./api:/app/api             # 二次元コード設定
      - /etc/localtime:/etc/localtime:ro
    healthcheck:
      test: ["CMD", "wget", "-q", "-O", "/dev/null", "http://localhost:5918/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 30s
    restart: unless-stopped
```

## ログの確認

### リアルタイムログ

```bash
docker compose logs -f
```

### 特定のコンテナのログ

```bash
docker compose logs gemini2api
```

### ログファイルの確認

```bash
# ホストマシンのログディレクトリ
ls -la ./data/logs.json
```

## アップデート

新しいバージョンに更新する場合：

```bash
# リポジトリを更新
git pull origin main

# イメージを再構築
docker compose build --no-cache

# サービスを再起動
docker compose up -d
```

## 停止・削除

### サービスを停止

```bash
docker compose stop
```

### サービスを削除

```bash
docker compose down
```

### データを保持したまま削除

```bash
docker compose down -v
```

> **注意**: `-v` フラグはボリュームも削除します。データを保持したい場合は使用しないでください。
