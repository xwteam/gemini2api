# API リファレンス

Gemini2API の完全な API ドキュメントです。

## 認証

すべての API リクエストには認証が必要です。以下の 2 つの方法をサポートしています。

### 方法 1: Authorization ヘッダー（推奨）

```bash
curl -H "Authorization: Bearer sk-あなたのキー" \
  http://localhost:5918/openai/v1/models
```

### 方法 2: x-api-key ヘッダー

```bash
curl -H "x-api-key: sk-あなたのキー" \
  http://localhost:5918/openai/v1/models
```

> **ヒント**: API Key は `.env` ファイルまたはログから確認できます。

## 標準ベアパス

v1.6.4 以降、各 API は 2 種類のパスに対応しています。

### プレフィックス付きパス

プロバイダーごとに明示的なパスを使用します（以下のエンドポイント文書はこちらを使用）：

- OpenAI: `/openai/v1/chat/completions`、`/openai/v1/models`
- Claude: `/claude/v1/messages`、`/claude/v1/messages/count_tokens`
- Gemini: `/gemini/v1beta/models/{model}:generateContent`、`:streamGenerateContent`

### 標準ベアパス（v1.6.4 新規）

主要 SDK が `base_url` にサフィックス不要でそのまま動作します：

- **OpenAI**: `/v1/chat/completions`、`/v1/models`
- **Claude**: `/v1/messages`、`/v1/messages/count_tokens`
- **Gemini**: `/v1beta/models/{model}:generateContent`、`:streamGenerateContent`、`/v1beta/models`

> **重要**: ベアパス `/v1/models` は OpenAI 形式を返します（1 つのパスで 2 つの形式は返せません）。Claude 形式のモデル一覧が必要な場合は `/claude/v1/models` を使用してください。

## OpenAI 互換 API

OpenAI SDK と互換性のあるエンドポイントです。

### GET /openai/v1/models

利用可能なモデル一覧を取得します。

**リクエスト:**

```bash
curl http://localhost:5918/openai/v1/models \
  -H "Authorization: Bearer sk-あなたのキー"
```

**レスポンス:**

```json
{
  "object": "list",
  "data": [
    {
      "id": "gemini-pro",
      "object": "model",
      "created": 1715970000,
      "owned_by": "gemini"
    },
    {
      "id": "gemini-flash",
      "object": "model",
      "created": 1715970000,
      "owned_by": "gemini"
    },
    {
      "id": "gemini-flash-thinking",
      "object": "model",
      "created": 1715970000,
      "owned_by": "gemini"
    }
  ]
}
```

> 💡 **モデル選択ガイド**：3つのモデルは異なる速度/品質のトレードオフを提供します。
> - `gemini-flash`：最速(応答約4-5秒)、**agent / 高頻度 / 高並行**シナリオに最適、デフォルト推奨。
> - `gemini-flash-thinking`：思考プロセス付き、速度はflashに近く、推論が必要なタスクに適しています。
> - `gemini-pro`：最高品質だが遅い(応答約9-17秒、長いコンテキストではさらに遅い)、品質重視でレイテンシを気にしないシナリオに適しています。
>
> agentクライアント(多数の並行リクエストを発行)は `gemini-flash` を優先すべきです。本サービスのストリーミングインターフェースは真の増分ストリーミングで、最初の文字が生成されるとすぐにプッシュを開始します。

### POST /openai/v1/chat/completions

チャット補完リクエストを送信します。

**リクエスト:**

```bash
curl -X POST http://localhost:5918/openai/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-あなたのキー" \
  -d '{
    "model": "gemini-2.5-pro",
    "messages": [
      {"role": "user", "content": "こんにちは"}
    ],
    "stream": false,
    "temperature": 0.7,
    "max_tokens": 2048
  }'
```

**リクエストパラメータ:**

| パラメータ | 型 | 必須 | 説明 |
|-----------|-----|------|------|
| `model` | string | ✅ | モデル名（例: `gemini-flash`） |
| `messages` | array | ✅ | メッセージ配列。`content` は文字列またはオブジェクト配列（マルチモーダル対応） |
| `stream` | boolean | ❌ | ストリーミング有効（デフォルト: false） |
| `temperature` | number | ❌ | 創造性（0.0-2.0、デフォルト: 1.0） |
| `max_tokens` | integer | ❌ | 最大トークン数 |
| `top_p` | number | ❌ | Nucleus sampling（0.0-1.0） |
| `conversation_id` | string | ❌ | 会話 ID（コンテキスト保持用） |
| `tools` | array | ❌ | 関数定義配列 |
| `tool_choice` | string | ❌ | 関数選択戦略 |

**マルチモーダル content 形式:**

`content` は文字列（テキストのみ）またはオブジェクト配列（テキストと画像対応）：

```json
{
  "role": "user",
  "content": [
    {"type": "text", "text": "これは何ですか"},
    {
      "type": "image_url",
      "image_url": {
        "url": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
      }
    }
  ]
}
```

対応する content タイプ：
- `text`：プレーンテキストコンテンツ
- `image_url`：画像、Base64 Data URI（`data:image/...;base64,...`）とリモート HTTP URL をサポート

**メッセージ形式:**

```json
{
  "role": "user|assistant|system",
  "content": "テキスト内容"
}
```

**レスポンス（非ストリーミング）:**

```json
{
  "id": "chatcmpl-xxx",
  "object": "chat.completion",
  "created": 1715970000,
  "model": "gemini-2.5-pro",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "こんにちは。何かお手伝いできることはありますか？"
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 10,
    "completion_tokens": 20,
    "total_tokens": 30
  },
  "conversation_id": "conv-xxx"
}
```

**レスポンス（ストリーミング）:**

```
data: {"choices":[{"delta":{"content":"こんにちは"}}]}
data: {"choices":[{"delta":{"content":"。"}}]}
data: [DONE]
```

### POST /openai/v1/images/generations

AI 画像生成リクエストを送信します。`prompt` をトリガーとして画像を生成し、`b64_json` 形式で返却します。

> **注**: 標準ベアパス `/v1/images/generations` でもアクセスできます。

**リクエスト:**

```bash
curl -X POST http://localhost:5918/openai/v1/images/generations \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-あなたのキー" \
  -d '{
    "model": "gemini-pro",
    "prompt": "a cute cat",
    "n": 1
  }'
```

**リクエストパラメータ:**

| パラメータ | 型 | 必須 | 説明 |
|-----------|-----|------|------|
| `model` | string | ✅ | モデル名（例: `gemini-pro`） |
| `prompt` | string | ✅ | 画像生成用のプロンプト |
| `n` | integer | ❌ | 生成する画像の枚数（デフォルト: 1） |

**レスポンス:**

```json
{
  "created": 1715970000,
  "data": [
    {
      "b64_json": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    }
  ]
}
```

> **ヒント**: 3 つのチャット API（OpenAI / Claude / Gemini）も応答内に生成された画像を検出すると、自動的に画像を埋め込みます（markdown / image block / inlineData）。

## Claude 互換 API

Anthropic Claude SDK と互換性のあるエンドポイントです。

### GET /claude/v1/models

モデル一覧を取得します。

**リクエスト:**

```bash
curl http://localhost:5918/claude/v1/models \
  -H "Authorization: Bearer sk-あなたのキー"
```

**レスポンス:**

```json
{
  "data": [
    {
      "id": "gemini-2.5-pro",
      "type": "model",
      "display_name": "Gemini 2.5 Pro"
    }
  ]
}
```

### POST /claude/v1/messages

メッセージを送信します。

**リクエスト:**

```bash
curl -X POST http://localhost:5918/claude/v1/messages \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-あなたのキー" \
  -d '{
    "model": "gemini-2.5-pro",
    "max_tokens": 1024,
    "messages": [
      {"role": "user", "content": "こんにちは"}
    ]
  }'
```

**リクエストパラメータ:**

| パラメータ | 型 | 必須 | 説明 |
|-----------|-----|------|------|
| `model` | string | ✅ | モデル名 |
| `max_tokens` | integer | ✅ | 最大トークン数 |
| `messages` | array | ✅ | メッセージ配列 |
| `system` | string | ❌ | システムプロンプト |
| `temperature` | number | ❌ | 創造性 |
| `stream` | boolean | ❌ | ストリーミング有効 |

**レスポンス:**

```json
{
  "id": "msg-xxx",
  "type": "message",
  "role": "assistant",
  "content": [
    {
      "type": "text",
      "text": "こんにちは。何かお手伝いできることはありますか？"
    }
  ],
  "model": "gemini-2.5-pro",
  "stop_reason": "end_turn",
  "stop_sequence": null,
  "usage": {
    "input_tokens": 10,
    "output_tokens": 20
  }
}
```

### POST /claude/v1/messages/count_tokens

トークン数を推定します。

**リクエスト:**

```bash
curl -X POST http://localhost:5918/claude/v1/messages/count_tokens \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-あなたのキー" \
  -d '{
    "model": "gemini-2.5-pro",
    "messages": [
      {"role": "user", "content": "こんにちは"}
    ]
  }'
```

**レスポンス:**

```json
{
  "input_tokens": 10
}
```

## Gemini 原生 API

Google Gemini API と互換性のあるエンドポイントです。

### GET /gemini/v1beta/models

モデル一覧を取得します。

**リクエスト:**

```bash
curl http://localhost:5918/gemini/v1beta/models \
  -H "Authorization: Bearer sk-あなたのキー"
```

**レスポンス:**

```json
{
  "models": [
    {
      "name": "models/gemini-2.5-pro",
      "displayName": "Gemini 2.5 Pro",
      "description": "Most capable model",
      "inputTokenLimit": 1000000,
      "outputTokenLimit": 4096
    }
  ]
}
```

### POST /gemini/v1beta/models/{model}:generateContent

コンテンツを生成します。

**リクエスト:**

```bash
curl -X POST http://localhost:5918/gemini/v1beta/models/gemini-2.5-pro:generateContent \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-あなたのキー" \
  -d '{
    "contents": [
      {
        "role": "user",
        "parts": [
          {"text": "こんにちは"}
        ]
      }
    ],
    "generationConfig": {
      "temperature": 0.7,
      "maxOutputTokens": 2048
    }
  }'
```

**レスポンス:**

```json
{
  "candidates": [
    {
      "content": {
        "role": "model",
        "parts": [
          {
            "text": "こんにちは。何かお手伝いできることはありますか？"
          }
        ]
      },
      "finishReason": "STOP"
    }
  ],
  "usageMetadata": {
    "promptTokenCount": 10,
    "candidatesTokenCount": 20,
    "totalTokenCount": 30
  }
}
```

### POST /gemini/v1beta/models/{model}:streamGenerateContent

ストリーミングでコンテンツを生成します。

**リクエスト:**

```bash
curl -X POST http://localhost:5918/gemini/v1beta/models/gemini-2.5-pro:streamGenerateContent \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-あなたのキー" \
  -d '{
    "contents": [
      {
        "role": "user",
        "parts": [{"text": "詩を書いてください"}]
      }
    ]
  }'
```

**レスポンス（Chunked JSON）:**

```
[{"candidates":[{"content":{"parts":[{"text":"春の"}]}}]}]
[{"candidates":[{"content":{"parts":[{"text":"夜"}]}}]}]
```

## 管理 API

サービス管理用のエンドポイントです。すべて認証が必須です。

### GET /admin/status

サービスステータスを取得します。

**リクエスト:**

```bash
curl http://localhost:5918/admin/status \
  -H "Authorization: Bearer sk-あなたのキー"
```

**レスポンス:**

```json
{
  "status": "ok",
  "accounts": [
    {
      "id": "account-0",
      "label": "メインアカウント",
      "status": "healthy",
      "last_used": "2025-05-17T10:30:00Z",
      "request_count": 150
    }
  ],
  "rotation_strategy": "round-robin",
  "total_requests": 150,
  "error_count": 2
}
```

### GET /admin/system-info

システム情報を取得します。

**リクエスト:**

```bash
curl http://localhost:5918/admin/system-info \
  -H "Authorization: Bearer sk-あなたのキー"
```

**レスポンス:**

```json
{
  "version": "1.1.0",
  "python_version": "3.12.0",
  "server_time": "2025/05/17 10:30:00",
  "os": "Linux 6.17.0",
  "memory_usage": 256,
  "memory_total": 2048,
  "cpu_percent": 15.5,
  "pid": 12345,
  "run_mode": "Docker",
  "uptime_seconds": 86400
}
```

### GET /admin/accounts

すべてのアカウントを取得します。

**リクエスト:**

```bash
curl http://localhost:5918/admin/accounts \
  -H "Authorization: Bearer sk-あなたのキー"
```

**レスポンス:**

```json
{
  "accounts": [
    {
      "id": "account-0",
      "label": "メインアカウント",
      "status": "healthy",
      "last_used": "2025-05-17T10:30:00Z"
    }
  ]
}
```

### POST /admin/accounts

新しいアカウントを追加します。

**リクエスト:**

```bash
curl -X POST http://localhost:5918/admin/accounts \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-あなたのキー" \
  -d '{
    "psid": "g.新しい値",
    "psidts": "sidts-新しい値",
    "label": "新規アカウント"
  }'
```

**レスポンス:**

```json
{
  "status": "ok",
  "account": {
    "id": "account-1",
    "label": "新規アカウント",
    "status": "healthy"
  }
}
```

### DELETE /admin/accounts/{id}

アカウントを削除します。

**リクエスト:**

```bash
curl -X DELETE http://localhost:5918/admin/accounts/account-1 \
  -H "Authorization: Bearer sk-あなたのキー"
```

**レスポンス:**

```json
{
  "status": "ok",
  "message": "Account account-1 removed"
}
```

### GET /admin/accounts/{id}/check

単一アカウントの状態をチェックします。

**リクエスト:**

```bash
curl http://localhost:5918/admin/accounts/account-0/check \
  -H "Authorization: Bearer sk-あなたのキー"
```

**レスポンス:**

```json
{
  "id": "account-0",
  "status": "healthy",
  "checked_at": "2025-05-17T10:30:00Z",
  "message": "Account is healthy"
}
```

### POST /admin/reload-cookies

Cookie を更新します。

**リクエスト（新しい Cookie を指定）:**

```bash
curl -X POST http://localhost:5918/admin/reload-cookies \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-あなたのキー" \
  -d '{
    "psid": "g.新しい値",
    "psidts": "sidts-新しい値"
  }'
```

**リクエスト（.env から読み込み）:**

```bash
curl -X POST http://localhost:5918/admin/reload-cookies \
  -H "Authorization: Bearer sk-あなたのキー"
```

**レスポンス:**

```json
{
  "status": "ok",
  "message": "Cookies reloaded successfully",
  "healthy": true
}
```

### PUT /admin/accounts/{id}/cookies

特定アカウントの Cookie を更新します。

**リクエスト:**

```bash
curl -X PUT http://localhost:5918/admin/accounts/account-0/cookies \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-あなたのキー" \
  -d '{
    "psid": "g.新しい値",
    "psidts": "sidts-新しい値"
  }'
```

**レスポンス:**

```json
{
  "status": "ok",
  "message": "Cookies updated successfully"
}
```

### GET /admin/health-history

健全性チェック履歴を取得します。

**リクエスト:**

```bash
curl http://localhost:5918/admin/health-history \
  -H "Authorization: Bearer sk-あなたのキー"
```

**レスポンス:**

```json
{
  "total": 50,
  "records": [
    {
      "account_id": "account-0",
      "status": "healthy",
      "checked_at": "2025-05-17T10:30:00Z",
      "message": "OK"
    }
  ]
}
```

### GET /admin/usage-stats/summary

使用統計の概要を取得します。

**リクエスト:**

```bash
curl http://localhost:5918/admin/usage-stats/summary \
  -H "Authorization: Bearer sk-あなたのキー"
```

**レスポンス:**

```json
{
  "total_requests": 1000,
  "error_count": 5,
  "error_rate": 0.5,
  "avg_latency_ms": 1250,
  "cookie_rotation_success_rate": 99.5
}
```

### GET /admin/usage-stats/history

使用統計の履歴を取得します。

**クエリパラメータ:**

| パラメータ | 型 | 説明 |
|-----------|-----|------|
| `granularity` | string | 粒度（1h/6h/24h） |
| `hours` | integer | 過去 N 時間 |

**リクエスト:**

```bash
curl "http://localhost:5918/admin/usage-stats/history?granularity=1h&hours=24" \
  -H "Authorization: Bearer sk-あなたのキー"
```

**レスポンス:**

```json
{
  "data": [
    {
      "timestamp": "2025-05-17T09:00:00Z",
      "requests": 100,
      "errors": 1,
      "avg_latency_ms": 1200
    }
  ]
}
```

### GET /admin/settings

現在の設定を取得します。

**リクエスト:**

```bash
curl http://localhost:5918/admin/settings \
  -H "Authorization: Bearer sk-あなたのキー"
```

**レスポンス:**

```json
{
  "performance": {
    "max_concurrent_per_account": 3,
    "max_retries": 3,
    "refresh_interval": 5
  },
  "rate_limit": {
    "enabled": false,
    "window": 60,
    "max": 10
  }
}
```

### POST /admin/settings

設定を更新します。

**リクエスト:**

```bash
curl -X POST http://localhost:5918/admin/settings \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-あなたのキー" \
  -d '{
    "max_concurrent_per_account": 5,
    "rotation_strategy": "failover"
  }'
```

**レスポンス:**

```json
{
  "status": "ok",
  "message": "Settings updated successfully"
}
```

### POST /admin/restart

サービスを再起動します（パネル右上のワンクリック再起動。再起動後は自動ポーリングで復帰します）。

**リクエスト:**

```bash
curl -X POST http://localhost:5918/admin/restart \
  -H "Authorization: Bearer sk-あなたのキー"
```

**レスポンス:**

```json
{
  "status": "ok",
  "message": "Service restarting"
}
```

### GET /admin/check-update

新しいバージョンの有無を確認します。

**リクエスト:**

```bash
curl http://localhost:5918/admin/check-update \
  -H "Authorization: Bearer sk-あなたのキー"
```

**レスポンス:**

```json
{
  "current_version": "1.6.19",
  "latest_version": "1.6.19",
  "has_update": false
}
```

### POST /admin/update

最新バージョンへの更新をトリガーします。

**リクエスト:**

```bash
curl -X POST http://localhost:5918/admin/update \
  -H "Authorization: Bearer sk-あなたのキー"
```

**レスポンス:**

```json
{
  "status": "ok",
  "message": "Update started"
}
```

### GET /admin/logs

ログを取得します。

**クエリパラメータ:**

| パラメータ | 型 | 説明 |
|-----------|-----|------|
| `direction` | string | フィルタ（request/response） |
| `search` | string | テキスト検索 |
| `limit` | integer | 取得件数（デフォルト: 15） |
| `offset` | integer | オフセット |

**リクエスト:**

```bash
curl "http://localhost:5918/admin/logs?limit=10&offset=0" \
  -H "Authorization: Bearer sk-あなたのキー"
```

**レスポンス:**

```json
{
  "total": 1000,
  "logs": [
    {
      "id": "log-xxx",
      "timestamp": "2025-05-17T10:30:00Z",
      "level": "info",
      "message": "Request processed",
      "details": {}
    }
  ]
}
```

### POST /admin/logs/clear

ログをクリアします。

**リクエスト:**

```bash
curl -X POST http://localhost:5918/admin/logs/clear \
  -H "Authorization: Bearer sk-あなたのキー"
```

**レスポンス:**

```json
{
  "status": "ok",
  "message": "Logs cleared"
}
```

### GET /health

ヘルスチェック（認証不要）

**リクエスト:**

```bash
curl http://localhost:5918/health
```

**レスポンス:**

```json
{
  "status": "ok",
  "service": "gemini2api"
}
```

### GET /admin/web-chats

アカウントの Gemini ウェブセッション一覧を取得します（読み取り専用）。

**リクエスト:**

```bash
curl http://localhost:5918/admin/web-chats \
  -H "Authorization: Bearer sk-あなたのキー"
```

**レスポンス:**

```json
{
  "chats": [
    {
      "id": "chat-xxx",
      "title": "会話のタイトル",
      "created_at": "2025-05-17T10:30:00Z",
      "updated_at": "2025-05-17T12:00:00Z",
      "is_pinned": false
    }
  ],
  "total": 10
}
```

### POST /admin/cleanup-web-chats

`keep_hours` より古いウェブセッションのクリーンアップを手動でトリガーします。バックグラウンドで非同期実行され、即座にステータスを返します。

**リクエスト:**

```bash
curl -X POST http://localhost:5918/admin/cleanup-web-chats \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-あなたのキー" \
  -d '{
    "keep_hours": 24,
    "skip_pinned": true
  }'
```

**リクエストパラメータ:**

| パラメータ | 型 | 必須 | 説明 |
|-----------|-----|------|------|
| `keep_hours` | integer | ❌ | 保持時間（時間単位、デフォルト: 24） |
| `skip_pinned` | boolean | ❌ | ピン留めセッションをスキップ（デフォルト: true） |

**レスポンス:**

```json
{
  "status": "started",
  "message": "Cleanup task started in background"
}
```

## エラーコード

API エラーは以下のコードで返されます。

| コード | 説明 | 対応 |
|--------|------|------|
| 400 | パラメータエラー | リクエストパラメータを確認 |
| 401 | 未認証 | API Key を確認 |
| 403 | 禁止 | 権限がない |
| 429 | レート制限 | しばらく待機 |
| 500 | サーバーエラー | ログを確認 |
| 503 | 利用不可 | アカウントが利用不可 |

**エラーレスポンス例:**

```json
{
  "error": {
    "message": "Invalid API key",
    "type": "authentication_error",
    "code": 401
  }
}
```

## レート制限

レート制限が有効な場合、以下のヘッダーが返されます。

```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 95
X-RateLimit-Reset: 1715970060
```

## タイムアウト

デフォルトのタイムアウトは 30 秒です。長時間の処理にはストリーミングを使用してください。
