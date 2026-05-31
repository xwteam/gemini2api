<div align="center">

<h1>Gemini2API</h1>
<h3>軽量 Gemini Web リバースプロキシ</h3>
<p>単一コードベースで OpenAI / Claude / Gemini の 3 つの主流 AI SDK に対応、純非同期アーキテクチャ、公式キー不要、Docker で高速デプロイ。</p>

<p>
  <img src="https://img.shields.io/badge/Python-3.12+-blue?style=flat-square&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/FastAPI-0.115-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/curl__cffi-Chrome%20TLS-ff6b35?style=flat-square&logo=google-chrome&logoColor=white" alt="curl_cffi">
  <img src="https://img.shields.io/badge/Docker-20.10+-2496ED?style=flat-square&logo=docker&logoColor=white" alt="Docker">
  <img src="https://img.shields.io/badge/Chrome%20%7C%20Edge-Latest-4285F4?style=flat-square&logo=googlechrome&logoColor=white" alt="Browser">
  <img src="https://img.shields.io/badge/License-Non--Commercial-red?style=flat-square" alt="License">
</p>

<p>
  <a href="#-最近の更新">最近の更新</a> &bull;
  <a href="#-主な機能">主な機能</a> &bull;
  <a href="#-システム要件">システム要件</a> &bull;
  <a href="#-クイックデプロイ">クイックデプロイ</a> &bull;
  <a href="#-統合例">統合例</a> &bull;
  <a href="#-api-エンドポイント">API エンドポイント</a> &bull;
  <a href="#-設定">設定</a> &bull;
  <a href="#-重要な注意事項">重要な注意事項</a> &bull;
  <a href="#-ロードマップ">ロードマップ</a>
</p>

<p>
  📖 ドキュメント：<a href="../zh-CN/README.md">简体中文</a> | <a href="../zh-TW/README.md">繁體中文</a> | <a href="../en/README.md">English</a> | 日本語 | <a href="../ko/README.md">한국어</a>
</p>

<br>

<a href="https://github.com/xwteam/gemini2api/issues"><img src="https://img.shields.io/github/issues/xwteam/gemini2api?style=flat-square" alt="Issues"></a>
<a href="https://github.com/xwteam/gemini2api/stargazers"><img src="https://img.shields.io/github/stars/xwteam/gemini2api?style=flat-square" alt="Stars"></a>

</div>

---

> [!NOTE]
> このプロジェクトは研究と学習目的のみです。責任を持って使用し、商業目的での使用は禁止です。

> [!WARNING]
> このプロジェクトは Google と無関係です。リバースエンジニアリングされたブラウザ Cookie を使用して Gemini Web にアクセスしており、Google の利用規約に違反する可能性があります。自己責任で使用してください。作者はアカウント停止やデータ損失に対して責任を負いません。

> [!TIP]
> 完全なモデルアクセスと安定した体験のために、Gemini Pro 以上のサブスクリプションの使用をお勧めします。

> [!IMPORTANT]
> Google のリスク管理ポリシーにより、Cookie セッションは通常約 2 時間後に強制的に失効します。完璧な長期保持ソリューションはまだ見つかっていません。この方面で経験やアイデアがあれば、[Issue](https://github.com/xwteam/gemini2api/issues) または PR で共有してください。コミュニティの知恵を期待しています。

---

## 📝 最近の更新

> 完全な変更ログは [CHANGELOG.md](../../CHANGELOG.md) を参照してください。以下は CI により自動同期されます。

| 日付 | 更新内容 |
|------|----------|
| 2026-06-01 00:18:01 | v1.6.8 - 🖼️ 画像生成で googleusercontent のプレースホルダ URL を返さないように：無意味なプレースホルダを応答から除去し、画像本体のみを返却 |
| 2026-06-01 00:02:09 | v1.6.7 - 🖼️ コントロールパネルのモデルテストで画像が表示されない問題を修正：生成された画像を直接レンダリング表示するようにし、markdown テキスト / URL として表示されないように |
| 2026-05-31 23:41:15 | v1.6.6 - 🖼️ 生成画像のローカルホスティング：チャット API の画像生成結果をアクセス可能なローカル URL（/images/{id}）で返却するように変更し、CLI / エージェント系クライアントでも正常にレンダリング表示できるように（base64 はこれらのクライアントでは表示不可）；画像は定期的に自動クリーンアップ |
| 2026-05-31 22:36:53 | v1.6.5 - 🎨 AI 画像生成：OpenAI 互換の /v1/images/generations エンドポイントを新規追加（b64_json 形式で返却）；3 つのチャット API は生成された画像を検出すると自動的に応答へ埋め込み（markdown / image block / inlineData） |
| 2026-05-31 17:00:00 | v1.6.4 - 3 つの API すべてが標準ベアパス（/v1/chat/completions、/v1/messages、/v1beta/...）を公開、主要 SDK がそのまま利用可能；デプロイ機構を修正（docker-compose を build から image に変更し、docker compose pull が正しく機能） |
| 2026-05-31 14:10:00 | v1.6.3 - 画像/ファイルアップロード対応（OpenAI/Claude/Gemini マルチモーダル）；モデルを Web 版実データに変更 + 固定の安定名（gemini-pro/flash/flash-thinking）；再起動時に Cookie が失われない |
| 2026-05-19 20:00:00 | v1.6.2 - 5 分間操作がないとセッションが自動的に期限切れになりログアウト |
| 2025-05-18 16:30:00 | v1.6.1 - ダークテーマの全面修正、更新チェックダイアログの美化、GitHub Actions 自動イメージビルド、failover フェイルオーバー戦略 |
| 2025-05-17 23:20:00 | モデルリストをユーザーフレンドリー名に統一、思考モード（gemini-2.5-flash-thinking）と Pro モードを追加、Playground 会話コンテキスト修正 |
| 2025-05-17 22:30:00 | コンテナタイムゾーンを Asia/Shanghai に修正、ログは北京時間を表示 |

---

## 🌟 主な機能

> 📖 詳細な使用ガイド：[USAGE.md](USAGE.md)

### 🔌 トリプルプロトコル互換性

- 単一サービスで OpenAI、Claude、Gemini SDK 形式を同時に提供
- SSE ストリーミング（OpenAI / Claude）+ Chunked JSON（Gemini）
- 関数呼び出しは 3 つの形式すべてでサポート
- Deep Research マルチステップ研究機能

### 🔐 セキュリティと認証

- 自動生成 API キー（`sk-` プレフィックス + 32 ランダム文字）
- `Authorization: Bearer` と `x-api-key` の両方の認証方式をサポート
- 初回デプロイ時に自動生成、ユーザーがカスタマイズ可能

### 🔄 マルチアカウント負荷分散と Cookie 自己修復

- **マルチアカウント負荷分散**：ラウンドロビンと最小使用の 2 つの戦略をサポート
- アカウントごとの独立した並行制御により、単一アカウントの過負荷を防止
- 連続失敗時に自動的に不健康とマーク、故障アカウントを自動スキップ
- バックグラウンド Cookie ローテーション、シームレスな更新
- ホットアップデート Cookie API、コンテナ再起動不要
- API 経由での動的なアカウント追加/削除
- Web パネル用のヘルスチェック履歴

### 🛡 検出回避とプロトコルスプーフィング

- **TLS フィンガープリント一貫性**：UA、Sec-Ch-Ua、curl_cffi impersonate は常に同期（Chrome 124）
- **動的リクエストヘッダー**：Chrome の実際の順序で配列、リクエストタイプに基づいて Sec-Fetch-* を動的調整
- **完全な Cookie 永続化**：すべてのレスポンス Cookie を自動キャプチャしてディスクに永続化、再起動後も保持
- **Cookie ドメイン隔離**：各リクエスト前にセッション内部 Cookie をクリア、クロスドメイン競合を防止
- **Chrome バージョン自動同期**：24 時間ごとに Google バージョン API をポーリング、新バージョン検出時に自動更新
- **リクエスト時間ジッター**：人間の操作間隔をシミュレート（ナビゲーション 200-800ms / API 50-300ms / Cookie ローテーション 1-3s）
- **バージョンフォールバック戦略**：curl_cffi が最新 Chrome をサポートしない場合、最新の利用可能バージョンを自動使用

### 🖥 Web 管理パネル

- 中国語ビジュアル管理インターフェース、API キー認証
- 右上コントロールバー：テーマ切り替え、サービス再起動、ログアウト
- ダッシュボード：リアルタイム稼働時間カウンター、QR コードカード（画像ズーム対応）、システム情報（バージョン/Python/OS/メモリ/CPU/PID/モード）、設定管理、アカウント状態概要、利用可能モデルリスト
- **ホットアップデートリソース**：`api/` ディレクトリ volume マウント、QR コード画像とテキスト設定変更後、ページ更新で即座に反映、コンテナ再構築不要
- アカウント管理：アカウント追加/削除、個別 Cookie 更新、ヘルスチェック
- **設定ページ**：ビジュアル実行時設定管理（パフォーマンス、レート制限、ヘルスチェック、アカウント管理など）、変更は即座に反映
- **モデルマッピング**：リクエストモデル名を実際のモデルにマッピング（例：gpt-4o → gemini-2.5-pro）
- **API キー管理**：第三者モデル API キー集中管理（OpenAI/Anthropic/Gemini/OpenRouter/カスタム）、インポート/エクスポート対応
- Playground：オンライン API テスト
- リアルタイムログ：構造化テーブル表示、方向フィルター、テキスト検索、ページネーション（15 件/ページ）、JSON 詳細パネル、ディスク永続化（再起動後も保持）
- ダーク/ライトテーマ切り替え、レスポンシブモバイル対応

### 🔀 統一転送エンジン

- Gemini Web の利用可能リストにないモデルのリクエストを自動的に API キープールから対応 Provider に転送
- OpenAI 互換形式を直接転送（ストリーミング含む）、Anthropic 形式は双方向変換
- `/openai/v1/models` は Gemini Web モデル + API キープール内の第三者モデルを自動集約
- 単一インターフェース、単一キーですべての主要モデルを呼び出し

### ⚡ 高性能アーキテクチャ

- Python asyncio + curl_cffi、完全ノンブロッキングパイプライン
- Chrome TLS フィンガープリントスプーフィング + 自動バージョン追跡、セッション寿命大幅延長
- Pydantic 強型検証、自動リクエストパラメータ検証
- モジュール設計、各 API 形式の独立ルーティングファイル
- 自動リトライ、指数バックオフ戦略

---

## 📋 システム要件

| 依存関係 | バージョン | 説明 |
|---------|-----------|------|
| Python | 3.12+ | 3.12 推奨、古いバージョンはテスト未実施 |
| Docker | 20.10+ | オプション、Docker デプロイ推奨 |
| Google アカウント | — | [gemini.google.com](https://gemini.google.com) に正常にアクセス可能である必要があります |
| ブラウザ | Chrome / Edge | Cookie 抽出用（デプロイ時のみ） |

> [!TIP]
> Docker デプロイではローカル Python インストール不要、Docker と有効な Cookie があれば十分です。

---

## ⚡ クイックデプロイ

> 📖 詳細なデプロイガイド：[DEPLOY.md](DEPLOY.md)

> **前提条件**：Gemini に正常にアクセスできる Google アカウントが必要です。

### 1. Cookie を取得

1. Chrome または Edge ブラウザで [gemini.google.com](https://gemini.google.com) にアクセス
2. Google アカウントでログイン、Gemini が正常に動作することを確認
3. `F12` キーを押して開発者ツールを開く
4. 上部の **Application** タブをクリック
5. 左側バーで **Cookies** を見つけ、`https://gemini.google.com` をクリック
6. Cookie リストから以下の 2 つの値を見つけます：

| Cookie 名 | 説明 |
|-----------|------|
| `__Secure-1PSID` | `g.` で始まる長い文字列、通常数十文字 |
| `__Secure-1PSIDTS` | より短い文字列 |

7. シークレットモードでの操作をお勧めします。値を取得したら、すぐにウィンドウを閉じて Cookie ローテーション問題を避けてください

> [!TIP]
> 検索ボックスで `__Secure-1P` を検索して素早くフィルタリング。Value 列をダブルクリックして完全な値をコピー。

> [!WARNING]
> Cookie は時間とともに失効します。サービスが突然停止した場合、まず Cookie の失効を確認してください。

### 2. Docker デプロイ

```bash
# リポジトリをクローン
git clone https://github.com/xwteam/gemini2api.git
cd gemini2api

# 環境ファイルを作成
cp .env.example .env
```

`.env` ファイルを編集して Cookie を追加：

```env
GEMINI_PSID=g.a000xxx...(完全な __Secure-1PSID 値を貼り付け)
GEMINI_PSIDTS=sidts-xxx...(完全な __Secure-1PSIDTS 値を貼り付け)
```

> [!IMPORTANT]
> 重要な注意事項：
> - 値は引用符不要
> - 余分なスペースや改行なし
> - 完全な値をコピーしたことを確認、末尾文字を見落とさないこと

サービスを起動：

```bash
docker compose up -d
```

ログを確認して起動成功を確認：

```bash
docker compose logs -f
# "Account pool ready: 1/1 active" はアカウントプール準備完了
# "SNlM0e not found" は Cookie 無効、新しい Cookie が必要
```

### マルチアカウント設定（オプション）

複数の Google アカウントで負荷分散を使用するには、`accounts.json` を作成：

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
    }
  ]
}
```

> [!TIP]
> `accounts.json` がない場合、サービスは `.env` の単一アカウントモードを自動使用。実行時に `POST /admin/accounts` API でアカウントを動的追加することも可能。

### Cookie 自動保持

gemini2api には Cookie 自動ローテーション機能が組み込まれています：Google RotateCookies API で 5 分ごとに `__Secure-1PSIDTS` を更新、batchexecute ハートビートでブラウザアクティビティをシミュレート、セッション寿命を延長。

Cookie を手動更新するには、Web パネルの「アカウント管理」→「Cookie 更新」を使用、サービス再起動不要。

> [!NOTE]
> Cookie 寿命は Google のリスク管理ポリシーに影響されます。データセンター IP は通常数時間持続。Cookie が頻繁に失効する場合、住宅 IP の使用またはアカウント数を増やしてローテーションを検討してください。

### 3. 検証

```bash
# ヘルスチェック
curl http://localhost:5918/health
# {"status":"ok","service":"gemini2api"}

# 利用可能なモデルを表示（API キー必要、初回起動時はログで確認）
curl http://localhost:5918/openai/v1/models \
  -H "Authorization: Bearer sk-your-api-key"

# テストリクエストを送信
curl -X POST http://localhost:5918/openai/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-api-key" \
  -d '{"model":"gemini-2.0-flash","messages":[{"role":"user","content":"hi"}]}'
```

AI の応答テキストが表示されればデプロイ成功。401 が返された場合、API キーを確認してください。

---

## 🧪 統合例

> [!NOTE]
> すべての API リクエストには API キーが必要です。2 つの認証方法をサポート：
> - `Authorization: Bearer sk-xxx`（推奨、OpenAI/Claude SDK 互換）
> - `x-api-key: sk-xxx`
>
> API キーは初回起動時に自動生成され `.env` に書き込まれ、ログで確認または手動編集可能。

<details>
<summary><b>OpenAI SDK（Python）</b></summary>

```python
from openai import OpenAI

client = OpenAI(
    api_key="sk-your-api-key",
    base_url="http://localhost:5918/openai/v1"
)

for chunk in client.chat.completions.create(
    model="gemini-2.0-flash",
    messages=[{"role": "user", "content": "相対性理論を 3 文で説明してください"}],
    stream=True
):
    print(chunk.choices[0].delta.content or "", end="")
```

</details>

<details>
<summary><b>Claude SDK（Python）</b></summary>

```python
import anthropic

client = anthropic.Anthropic(
    api_key="sk-your-api-key",
    base_url="http://localhost:5918/claude"
)

msg = client.messages.create(
    model="gemini-2.0-flash",
    max_tokens=4096,
    messages=[{"role": "user", "content": "Python クイックソート実装を書いてください"}]
)
print(msg.content[0].text)
```

</details>

<details>
<summary><b>cURL</b></summary>

```bash
# ストリーミングなしリクエスト
curl -X POST http://localhost:5918/openai/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-api-key" \
  -d '{"model":"gemini-2.0-flash","messages":[{"role":"user","content":"Hi"}]}'

# ストリーミングリクエスト
curl -X POST http://localhost:5918/openai/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-api-key" \
  -d '{"model":"gemini-2.0-flash","messages":[{"role":"user","content":"Hi"}],"stream":true}'
```

</details>

<details>
<summary><b>関数呼び出し</b></summary>

```python
response = client.chat.completions.create(
    model="gemini-2.0-flash",
    messages=[{"role": "user", "content": "北京の今日の天気は"}],
    tools=[{
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "都市の天気を取得",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"]
            }
        }
    }]
)
```

</details>

---

## 📡 API エンドポイント

> 📖 詳細 API ドキュメント：[API.md](API.md)

### OpenAI 互換（`/openai/v1`）

| メソッド | エンドポイント | 機能 |
|---------|--------------|------|
| GET | `/models` | 利用可能モデルリスト |
| POST | `/chat/completions` | チャット補完（ストリーミング + ツール呼び出し） |

### Claude 互換（`/claude/v1`）

| メソッド | エンドポイント | 機能 |
|---------|--------------|------|
| GET | `/models` | モデルリスト |
| GET | `/models/{id}` | モデル詳細 |
| POST | `/messages` | メッセージ生成（ストリーミング + ツール呼び出し） |
| POST | `/messages/count_tokens` | トークン数推定 |

### Gemini ネイティブ（`/gemini/v1beta`）

| メソッド | エンドポイント | 機能 |
|---------|--------------|------|
| GET | `/models` | モデルリスト |
| POST | `/models/{m}:generateContent` | コンテンツ生成 |
| POST | `/models/{m}:streamGenerateContent` | ストリーミング生成（Chunked JSON） |

### 管理インターフェース（`/admin`）

| メソッド | エンドポイント | 機能 |
|---------|--------------|------|
| GET | `/status` | サービスステータス（アカウントプール概要 + ローテーション戦略） |
| GET | `/accounts` | すべてのアカウントリストとステータス |
| POST | `/accounts` | 新しいアカウントを動的追加 |
| DELETE | `/accounts/{id}` | アカウントを削除 |
| GET | `/accounts/{id}/check` | 単一アカウントステータスをチェック |
| POST | `/reload-cookies` | ホットアップデート Cookie（コンテナ再起動不要） |

---

## ⚙ 設定

| 変数 | 必須 | デフォルト | 説明 |
|------|------|----------|------|
| `GEMINI_PSID` | ✅ | — | ブラウザ `__Secure-1PSID` |
| `GEMINI_PSIDTS` | ✅ | — | ブラウザ `__Secure-1PSIDTS` |
| `API_KEY` | ❌ | 自動生成 | API アクセスキー（`sk-` プレフィックス、空の場合は初回起動時に自動生成） |
| `REFRESH_INTERVAL` | ❌ | `5` | Cookie 更新間隔（分） |
| `MAX_RETRIES` | ❌ | `3` | 失敗時の再試行回数（指数バックオフ） |
| `PORT` | ❌ | `5918` | サービスポート |
| `LOG_LEVEL` | ❌ | `info` | ログレベル（debug/info/warning/error） |
| `RATE_LIMIT_ENABLED` | ❌ | `false` | レート制限を有効化 |
| `RATE_LIMIT_WINDOW` | ❌ | `60` | レート制限ウィンドウ（秒） |
| `RATE_LIMIT_MAX` | ❌ | `10` | ウィンドウ内の最大リクエスト数 |
| `HEALTH_CHECK_ENABLED` | ❌ | `true` | スケジュール済みアカウントヘルスチェックを有効化 |
| `HEALTH_CHECK_INTERVAL` | ❌ | `5` | チェック間隔（分） |
| `ROTATION_STRATEGY` | ❌ | `round-robin` | ローテーション戦略：`round-robin` / `failover` |
| `MAX_CONCURRENT_PER_ACCOUNT` | ❌ | `3` | アカウントあたりの最大並行リクエスト数 |

---

## ⚠ 重要な注意事項

1. **Cookie 失効**：Google Cookie は定期的に失効します（通常数時間から数日）。サービスには自動更新機能がありますが、アカウントがログアウトされたりパスワードが変更された場合は、新しい Cookie が必要です。

2. **ストリーミング出力**：すべての API エンドポイントはデフォルトでストリーミングします。`stream: false` の場合、サービスは内部的にストリーミングデータを受け取り、収集後に完全な JSON を返します。

3. **モデル可用性**：利用可能なモデルはあなたの Google アカウント権限に依存します。無料アカウントと Gemini Advanced アカウントでは異なるモデルが表示されます。サービスは起動時に自動検出します。

4. **リクエスト頻度**：レート制限を無効化（`RATE_LIMIT_ENABLED=false`）しても、Google 側には独自の制限があります。高頻度リクエストは CAPTCHA またはテンポラリーバンをトリガーする可能性があります。リクエスト頻度を適切に制御してください。

5. **ネットワーク環境**：デプロイサーバーは `gemini.google.com` に直接アクセスできる必要があります。一部の地域ではプロキシ設定が必要な場合があります。

---

## 🗺 ロードマップ

- [x] OpenAI / Claude / Gemini トリプル形式互換性
- [x] ストリーミング応答 + 関数呼び出し
- [x] Deep Research マルチステップ研究
- [x] Docker デプロイ
- [x] API キー認証
- [x] Cookie ホットアップデート API
- [x] スケジュール済みアカウントヘルスチェック
- [x] マルチアカウントローテーション（負荷分散）
- [x] Web 管理パネル
- [x] 検出回避とプロトコルスプーフィング
- [x] 設定ページ（ビジュアル設定管理）
- [x] API キー管理（第三者モデルキー）
- [x] 統一転送エンジン（単一インターフェースですべてのモデル）
- [x] モデルマッピング（エイリアス → 実際のモデル）
- [ ] 画像/ファイルアップロード対応

---

## ☕ サポート & 貢献

役に立ちましたか？作者にコーヒーをおごるか、WeChatグループに参加してサポートを受けてください。詳細は [SPONSORS.md](SPONSORS.md) をご覧ください。

PR と Issue を歓迎します。

1. このリポジトリをフォーク
2. ブランチを作成 `git checkout -b feature/your-feature`
3. コードをコミット `git commit -m "feat: add something"`
4. プッシュして Pull Request を作成

---

## 🙏 謝辞

[Issues](https://github.com/xwteam/gemini2api/issues) でバグ報告、ログ、互換性フィードバック、機能提案を提出してくださったすべてのユーザーに感謝します。これらのフィードバックが Cookie 保持、マルチアカウントローテーション、モデル選択、多言語サポート、Web パネルなどのコア機能の改善を直接推進しました。

---

## 📄 ライセンス

このプロジェクトは [非商用ライセンス](../../LICENSE) を使用しています：

- **許可**：個人学習、研究、自己ホスト型デプロイ
- **禁止**：販売、転売、有料プロキシ、商用製品統合を含むあらゆる商用利用

このプロジェクトは Google と無関係です。ユーザーはすべてのリスクを負い、Google の利用規約に準拠する必要があります。

---

<div align="center">
  <sub>Built with Python + FastAPI + curl_cffi | Powered by Gemini Web</sub>
</div>
