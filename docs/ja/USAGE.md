# 使用ガイド

Gemini2API の Web パネルとクライアント接続方法について説明します。

## Web 管理パネル

Gemini2API は、ブラウザベースの管理パネルを提供しています。

### アクセス方法

ブラウザで以下の URL にアクセス：

```
http://localhost:5918
```

または、リモートサーバーの場合：

```
http://サーバーIP:5918
```

### ログイン

初回アクセス時、API Key の入力を求められます。

1. `.env` ファイルまたはログから API Key を確認
2. パネルに入力してログイン

> **ヒント**: API Key は `sk-` で始まる 36 文字の文字列です。

## パネル機能

### ダッシュボード

メインページには以下の情報が表示されます：

| 項目 | 説明 |
|------|------|
| 運行時間 | サービス起動からの経過時間（リアルタイム更新） |
| 二次元コード | WeChat・スポンサーシップ QR コード（クリックで拡大） |
| システム情報 | バージョン、Python、OS、メモリ、CPU、PID、実行モード |
| 設定管理 | 轮換策略、並行数制限の変更 |
| アカウント状態 | 各アカウントの健全性、最後の使用時刻 |
| 利用可能モデル | 現在使用可能な全モデル一覧 |

### アカウント管理

複数の Google アカウントを管理します。

**機能:**

- **アカウント追加**: 新しい Google アカウントの Cookie を追加
- **アカウント削除**: 不要なアカウントを削除
- **Cookie 更新**: 期限切れの Cookie を更新
- **健全性チェック**: 各アカウントの状態を確認

**操作例:**

1. 左側メニューから「アカウント管理」を選択
2. 「新規追加」ボタンをクリック
3. Cookie（PSID と PSIDTS）を入力
4. 「追加」をクリック

### Playground（テスト環境）

API リクエストをブラウザから直接テストできます。

**使用方法:**

1. 「Playground」タブを開く
2. モデルを選択
3. メッセージを入力
4. 「送信」をクリック

**例:**

```json
{
  "model": "gemini-2.5-pro",
  "messages": [
    {
      "role": "user",
      "content": "Python で Fibonacci 数列を実装してください"
    }
  ],
  "stream": false
}
```

### リアルタイムログ

API リクエストのログをリアルタイムで表示します。

**機能:**

- **方向フィルタ**: リクエスト/レスポンスを個別に表示
- **テキスト検索**: ログ内容から検索
- **ページネーション**: 1 ページ 15 件表示
- **JSON 詳細**: 各ログの詳細情報をパネルで表示
- **ログ管理**: ログの記録開始/一時停止/クリア

### 使用統計

API 使用状況の統計情報を表示します。

**表示項目:**

| 項目 | 説明 |
|------|------|
| 累計リクエスト数 | 総リクエスト数 |
| エラー率 | エラーの割合 |
| 平均レイテンシ | 平均応答時間 |
| 轮換成功率 | Cookie 更新の成功率 |

**グラフ:**

- 時系列グラフで過去 24 時間のトレンドを表示
- 粒度（1 時間/6 時間/24 時間）を選択可能

### API Key 管理

第三方の大型言語モデル API Key を一元管理します。

**対応プロバイダ:**

- OpenAI
- Anthropic（Claude）
- Google Gemini
- OpenRouter
- カスタムプロバイダ

**操作:**

1. 「API Key 管理」を開く
2. 「新規追加」をクリック
3. プロバイダを選択
4. API Key を入力
5. 「保存」をクリック

**機能:**

- Key の有効/無効を切り替え
- 複数 Key の一括インポート/エクスポート
- Key の削除

### アクセスキー

配布用の受信アクセスキーを発行します。上の「API Key 管理」とは無関係です —— あちらは第三者への**送信**キーを管理し、こちらは「誰が本サービスを呼び出せるか」を管理します。

**キーの発行:**

1. 「キーを発行」をクリック
2. 「名称」を入力（相手の名前など。後から照合しやすくなります）
3. 「数量」で一度に複数発行できます（上限 50）。名称は `名称-1`、`名称-2`… と自動連番になります
4. 「有効日数（初回利用から）」と「絶対有効期限」はどちらか一方のみ。両方空なら無期限です
5. 「リクエスト上限」を空にすると無制限
6. 「バインドするアカウント」／「許可するモデル」は未選択 = 制限なし
7. 「発行」をクリックし、一覧の「キーをコピー」で平文を相手に渡します

**一覧と管理:**

各行に状態（有効／未アクティブ／無効／期限切れ／上限到達）、有効期限、使用量、適用範囲が表示され、以下の操作ができます。

- **編集**：名称・有効期限・上限・バインドするアカウント・許可するモデルを変更
- **有効化／無効化**：無効化すると保持者は即座に 401 になりますが、キーは一覧に残り、いつでも復帰できます
- **使用量をリセット**：リクエストカウントをゼロに戻すと、上限到達したキーも再利用できます
- **削除**：キーを削除します。使用中のクライアントは直ちに接続できなくなります

**知っておくべき 3 点:**

1. `.env` の `API_KEY` は引き続き全権限を持ち、アクセスキーは追加の層にすぎません。1 本も発行していない場合、挙動は従来版と完全に同一です。
2. アクセスキーは**業務 API のみ**を呼び出せ、`/admin/*` には到達できません。管理面は従来どおり `API_KEY` / `ADMIN_API_KEY` が守っているため、外部の人にキーを渡しても安全です。
3. 業務リクエストは `GET /v1/models` も含めてすべて +1 されます。クライアントによっては対話のたびにモデル一覧を取得するため、1 ラウンドで 2 回消費します。「リクエスト上限」を設定する際は余裕を持たせてください。

#### トークン使用量と概算コスト

一覧には「使用量」（リクエスト回数）に加えて **トークン（概算）** と **概算コスト (USD)**（数値の前に必ず `≈`）の 2 列があります。

⚠️ **これは請求額ではなく参考値です。** 本サービスは Gemini **Web** を使うため、**それ自体に費用は発生しません**。この列は「同じ内容を公式 API で実行した場合の概算額」です。トークン数は `len(テキスト) / 4` による概算で**実際のトークナイザではありません**（日本語・中国語は大幅に少なく出ます）。価格表は公表されている標準有料枠に平準化しており、長コンテキストの段階料金や将来の価格改定は考慮していません。思考トークンは出力に計上します。サードパーティのフォールバックで処理されたリクエストは計上されません。

**統計専用で、制限には一切使われません**：上限はリクエスト数のみです。「使用量をリセット」でリクエスト数とトークン／コストが一緒にゼロになります。価格表は環境変数 `TOKEN_PRICES` で設定します（公開モデル名=入力価格/出力価格、単位 USD／100 万トークン）。空なら内蔵の既定値を使い、価格が設定されていないモデルは `—` と表示されます。

### 設定

サービスの動作パラメータをリアルタイムで変更できます。

**設定カテゴリ:**

| カテゴリ | 設定項目 |
|---------|---------|
| パフォーマンス | 並行数、再試行回数、タイムアウト |
| 限流 | 有効/無効、ウィンドウ、最大リクエスト数 |
| 健全性チェック | 有効/無効、チェック間隔 |
| アカウント管理 | 轮換策略、Cookie 更新間隔 |
| ログ | ログレベル、保持期間 |
| ウェブセッションクリーンアップ | 有効化トグル、保持時間（hours）、クリーンアップ間隔（hours）、ピン留めスキップ（デフォルト: true）。API 呼び出しにより Gemini ウェブ側に蓄積されたセッション記録を定期的にクリーンアップします。ピン留めされたセッションは保持され、保持期間はプロキシのコンテキスト期間よりはるかに長く設定されているためアクティブな複数ターン会話には影響しません |

**変更は即座に反映されます。**

### 多言語切替

右上の地球アイコンから言語を切り替えられます。

**対応言語:**

- 简体中文（簡体中国語）
- 繁體中文（繁体中国語）
- English（英語）
- 日本語
- 한국어（韓国語）

### 右上コントロールバー

| アイコン | 機能 |
|---------|------|
| 🌙/☀️ | ダークモード/ライトモード切替 |
| 🔄 | サービス再起動 |
| 🚪 | ログアウト |

## 画像アップロード

Gemini2API はマルチモーダルコンテンツをサポートしており、画像やファイルのアップロードが可能です。3 つの API 形式での画像転送に対応しています。

### OpenAI 形式

`messages` 配列で `image_url` タイプを使用します。Base64 Data URI とリモート HTTP URL の両方をサポートしています。

**Base64 画像の例**：

```bash
curl -X POST http://localhost:5918/openai/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-あなたのキー" \
  -d '{
    "model": "gemini-flash",
    "messages": [
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
    ]
  }'
```

**リモート URL 画像の例**：

```bash
curl -X POST http://localhost:5918/openai/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-あなたのキー" \
  -d '{
    "model": "gemini-flash",
    "messages": [
      {
        "role": "user",
        "content": [
          {"type": "text", "text": "この画像を分析してください"},
          {
            "type": "image_url",
            "image_url": {
              "url": "https://example.com/image.jpg"
            }
          }
        ]
      }
    ]
  }'
```

### Claude 形式

`content` 配列で `image` タイプを使用します。

```bash
curl -X POST http://localhost:5918/claude/v1/messages \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-あなたのキー" \
  -d '{
    "model": "gemini-flash",
    "max_tokens": 1024,
    "messages": [
      {
        "role": "user",
        "content": [
          {"type": "text", "text": "これは何ですか"},
          {
            "type": "image",
            "source": {
              "type": "base64",
              "media_type": "image/png",
              "data": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
            }
          }
        ]
      }
    ]
  }'
```

### Gemini ネイティブ形式

`parts` 配列で `inlineData` を使用します。

```bash
curl -X POST http://localhost:5918/gemini/v1beta/models/gemini-flash:generateContent \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-あなたのキー" \
  -d '{
    "contents": [
      {
        "parts": [
          {"text": "これは何ですか"},
          {
            "inlineData": {
              "mimeType": "image/png",
              "data": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
            }
          }
        ]
      }
    ]
  }'
```

### Web パネルでのアップロード

Playground テストページで「画像を追加」ボタンをクリックすると、ローカル画像を直接アップロードしてテストできます。

## AI 画像生成

Gemini2API はプロンプトによる画像生成に対応しています。会話の中で「画像を生成して」や英語で "generate an image of ..." と伝えるだけで画像が生成されます。3 つの会話 API（OpenAI `/v1/chat/completions`、Claude `/v1/messages`、Gemini `/v1beta/...:generateContent`）すべてで利用できるほか、画像生成専用の OpenAI 互換エンドポイント `/v1/images/generations` も用意されています。

### 会話 API での画像生成

メッセージ内で画像生成を指示するだけです。

```bash
curl -X POST http://localhost:5918/openai/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-あなたのキー" \
  -d '{
    "model": "gemini-pro",
    "messages": [
      {"role": "user", "content": "generate an image of a cute cat"}
    ]
  }'
```

### 画像生成専用エンドポイント

OpenAI 互換の `/v1/images/generations` を使用します。

```bash
curl -X POST http://localhost:5918/v1/images/generations \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-あなたのキー" \
  -d '{
    "model": "gemini-pro",
    "prompt": "a cute cat",
    "n": 1
  }'
```

会話 API は生成された画像のローカル URL（`http://あなたのアドレス/images/xxx.png`）を返すため、ブラウザで直接開いたりレンダリングしたりできます。一方、`/v1/images/generations` は `b64_json` 形式で画像データを返します。いずれの場合も、画像は元の解像度（例: 1408×768）のまま返されます。

## 本文の復元（Canvas と制御マーカー）

Gemini Web には「本文が本文になっていない」ケースが 2 つあり、サービスは回答をクライアントに渡す前に両方を正規化します（ストリーミングと非ストリーミングで完全に同一の本文になります）。

**Canvas パネル**：やや長いコードや文書を書くとき、Web クライアントは内容を Canvas パネルに移し、本文には `http://googleusercontent.com/immersive_entry_chip/N` というプレースホルダーリンクだけを残します。サービスはレスポンスから Canvas の実際の内容を取り出して本文に復元します（コードは言語付きの Markdown コードフェンス、文書はそのままインライン）。実際の内容を取得できない場合は**デッドリンクを削除し、読める説明文を残します** —— 開けない URL を回答として渡すことはなく、本文が空になることもありません。

**制御マーカー**：本文には 3 種類の内部マーカーが混入しうるため、いずれも除去します。

| マーカー | 処理 |
|---------|------|
| `<ctrl94>thought…<ctrl95>` | 内容は破棄せず**思考チェーンに回します**（`reasoning_content` / Anthropic の `thinking` ブロック）。**対になっている**ものだけを処理し、閉じていないマーカーはそのまま残します |
| `?code_reference&code_event_index=N` / `?code_stdout&…` | コードフェンスの info string 内のマーカーのみを除去し、**フェンス本文は一字も変更しません** |
| `http://googleusercontent.com/card_content/N` | 削除（クライアントからアクセスできないデッドリンク） |

本文がこれらの文字列に単に「言及している」だけの場合は影響を受けません。

**既知の制約**：本文に実際に**対になった** `<ctrl94>…<ctrl95>` が現れた場合（両方のリテラルを含むログを貼ってそのまま出力させた場合など）、その間のテキストは思考内容として本文から取り除かれます。OpenAI プロトコルでは `reasoning_content`、Anthropic プロトコルで `thinking` を渡した場合は `thinking` ブロックから取得できますが、ネイティブ Gemini プロトコルと `thinking` を渡さない `/v1/messages` には思考を運ぶ経路がないため、そのテキストは復元できません。

## 対応モデル

Gemini2API は 3 つの固定された安定したモデル名を対外的に提供しており、これらは変更されません。これらのモデル名は API コントラクトとして機能し、クライアントは長期間使用できます。

| モデル名 | 説明 |
|---------|------|
| `gemini-pro` | Pro モデル、最高性能、複雑なタスクに適している |
| `gemini-flash` | 高速モデル、低遅延、リアルタイムアプリケーションに適している |
| `gemini-flash-lite` | 最軽量・最速のモデル（3.5 Flash-Lite）。Pro/Flash がレート制限されても利用可能 |
| `gemini-argon` | 4 Argon、複雑なタスク向け。少なくとも 1 つのアカウントが実際に保有している場合のみ一覧に出ます（別名：`gemini-4-argon`） |

> `gemini-flash-thinking` は廃止しました：引き続き呼び出せます（`gemini-flash` の隠しエイリアス）が、モデル一覧には出ません。思考はすべてのモデルが持つ `low` / `medium` / `high` の 3 段階になり、クライアントが指定しない場合の既定は `low` です（実測で 1 リクエストあたり平均約 5 秒増。パネルの「設定 → 思考」で `off` にすると最速）。詳しくは [README の「🧠 モデルと思考レベル」](README.md#-モデルと思考レベル)。

**アカウント駆動のモデル発見**：上記の固定名に加えて、サービスはアカウントのハートビートからモデル一覧を読み取ります。アカウントが実際に持っているのに組み込みテーブルが知らないモデル（4 Argon がまさにこれ）は自動的に採用されます。採用前に検証（16 桁の 16 進数 model id、正の model number、解析可能なラベル、既存の公開名を上書きしない名前）を行い、不合格の項目は破棄してログに残します。上記 3 つの契約名は発見経由では決して設定されないため、異常なハートビートがそれらを別のモデルに向け替えることはできません。

**発見されたモデルはアカウント単位です**：`gemini-argon` のような発見由来の名前は、実際にそれを発見したアカウントでのみルーティングできます。モデル一覧はプール全体で集約されるため、混在プール（一部のアカウントだけが Argon を持つ）ではそれを持たないアカウントにリクエストが割り当たることがあります。その場合、サービスは別のモデルにフォールバックせずエラーを返します（HTTP 400 `Model ... unavailable`）。これは意図的です：モデルの無言の差し替えは HTTP 200 で本文も正常に見えるため、クライアントは別モデルの回答だと気づけません。安定して使いたい場合は、プール内のすべてのアカウントがそのモデルを持つようにするか、3 つの契約名を使ってください。また、あるラウンドのハートビートが発見済みモデルを報告しなくなると、その名前は直ちに一覧から消えます（一覧にはあるのに呼べない名前は残りません）。


**内部自動マッピング**：サービスは Google アカウントのサブスクリプションレベル（Advanced/Plus/Basic）に基づいて、これらの固定名を現在利用可能な実際のモデルバージョンに自動的にマップします。アカウントレベルの変更、Google のロールアウト、サービスの再起動など、どのような状況でも、クライアントは常にこれら 3 つの固定名を使用でき、変更は不要です。

**レガシーエイリアスの互換性**：後方互換性のため、以下の古いモデル名もサポートされています：
- `gemini-2.5-pro`、`gemini-2.0-flash`、`gemini-2.0-flash-thinking` など

### サードパーティモデル

API Key プール経由でサポート：
- **OpenAI**：gpt-4o、gpt-4-turbo、gpt-3.5-turbo など
- **Anthropic**：claude-3-opus、claude-3-sonnet、claude-3-haiku など
- **Google Gemini**：公式 API Key 経由
- **OpenRouter**：OpenRouter プラットフォームのすべてのモデル

## サードパーティクライアント接続

Gemini2API は OpenAI 互換 API を提供しているため、多くのクライアントから直接接続できます。

### ChatGPT-Next-Web

1. ChatGPT-Next-Web を起動
2. 設定 → API 設定
3. API URL を入力：

```
http://サーバーIP:5918/openai/v1
```

4. API Key を入力：

```
sk-あなたのキー
```

5. 保存して使用開始

### LobeChat

1. LobeChat を起動
2. 設定 → 言語モデル
3. プロバイダを「OpenAI」に設定
4. API URL：

```
http://サーバーIP:5918/openai/v1
```

5. API Key を入力
6. モデルを選択して使用

### OpenCat

1. OpenCat を起動
2. 設定 → API 設定
3. API エンドポイント：

```
http://サーバーIP:5918/openai/v1
```

4. API Key を入力
5. 使用開始

### cURL コマンド

```bash
curl -X POST http://localhost:5918/openai/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-あなたのキー" \
  -d '{
    "model": "gemini-2.5-pro",
    "messages": [
      {"role": "user", "content": "こんにちは"}
    ]
  }'
```

### Python SDK

```python
from openai import OpenAI

client = OpenAI(
    api_key="sk-あなたのキー",
    base_url="http://localhost:5918/openai/v1"
)

response = client.chat.completions.create(
    model="gemini-2.5-pro",
    messages=[
        {"role": "user", "content": "Python で Hello World を出力してください"}
    ]
)

print(response.choices[0].message.content)
```

### Node.js SDK

```javascript
import OpenAI from "openai";

const client = new OpenAI({
  apiKey: "sk-あなたのキー",
  baseURL: "http://localhost:5918/openai/v1",
});

const message = await client.chat.completions.create({
  model: "gemini-2.5-pro",
  messages: [
    { role: "user", content: "JavaScript で Hello World を出力してください" },
  ],
});

console.log(message.choices[0].message.content);
```

## Cookie 管理

### Cookie の有効期限

Google の Cookie は定期的に期限切れになります。

- **通常**: 数時間～数日
- **データセンター IP**: 数時間
- **住宅 IP**: 数日～数週間

### Cookie の更新方法

#### 方法 1: Web パネルから更新

1. 「アカウント管理」を開く
2. 対象アカウントの「Cookie 更新」をクリック
3. 新しい PSID と PSIDTS を入力
4. 「更新」をクリック

#### 方法 2: API で更新

```bash
curl -X PUT http://localhost:5918/admin/accounts/account-0/cookies \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-あなたのキー" \
  -d '{
    "psid": "g.新しい値",
    "psidts": "sidts-新しい値"
  }'
```

#### 方法 3: 環境変数から再読み込み

```bash
curl -X POST http://localhost:5918/admin/reload-cookies \
  -H "Authorization: Bearer sk-あなたのキー"
```

### Cookie 取得の詳細

Cookie の取得方法については、[DEPLOY.md](DEPLOY.md#cookie-取得手順) を参照してください。

## 会話コンテキスト

Gemini2API は複数ターンの会話をサポートしています。

### 自動コンテキスト管理

クライアント側で `messages` 配列に会話履歴を含めると、自動的にコンテキストが保持されます。

```python
messages = [
    {"role": "user", "content": "Python とは何ですか？"},
    {"role": "assistant", "content": "Python は..."},
    {"role": "user", "content": "その特徴を教えてください"},
]

response = client.chat.completions.create(
    model="gemini-2.5-pro",
    messages=messages
)
```

### conversation_id を使用した永続化

`conversation_id` フィールドを使用すると、複数のリクエスト間でコンテキストが保持されます。

```python
# 最初のリクエスト
response1 = client.chat.completions.create(
    model="gemini-2.5-pro",
    messages=[{"role": "user", "content": "こんにちは"}],
    conversation_id="conv-123"  # 任意の ID
)

# 2 番目のリクエスト（同じ conversation_id）
response2 = client.chat.completions.create(
    model="gemini-2.5-pro",
    messages=[{"role": "user", "content": "さっきの話の続きを教えてください"}],
    conversation_id="conv-123"  # 同じ ID を使用
)
```

> **注意**: `conversation_id` は Gemini Web の内部 ID と同期されます。

## ストリーミング応答

リアルタイムで応答を受け取ることができます。

### Python での例

```python
response = client.chat.completions.create(
    model="gemini-2.5-pro",
    messages=[{"role": "user", "content": "長編小説を書いてください"}],
    stream=True
)

for chunk in response:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="", flush=True)
```

### cURL での例

```bash
curl -X POST http://localhost:5918/openai/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-あなたのキー" \
  -d '{
    "model": "gemini-2.5-pro",
    "messages": [{"role": "user", "content": "詩を書いてください"}],
    "stream": true
  }'
```

## 関数呼び出し（Function Calling）

モデルに特定のタスクを実行させることができます。

```python
response = client.chat.completions.create(
    model="gemini-2.5-pro",
    messages=[
        {"role": "user", "content": "東京の天気を調べてください"}
    ],
    tools=[
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "指定都市の天気を取得",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "city": {"type": "string", "description": "都市名"}
                    },
                    "required": ["city"]
                }
            }
        }
    ]
)

# モデルが関数呼び出しを提案
if response.choices[0].message.tool_calls:
    for tool_call in response.choices[0].message.tool_calls:
        print(f"関数: {tool_call.function.name}")
        print(f"引数: {tool_call.function.arguments}")
```

## トラブルシューティング

### 接続エラー

**症状**: `Connection refused`

**解決方法**:

1. サービスが起動しているか確認：

```bash
docker compose ps
```

2. ポートが正しいか確認：

```bash
curl http://localhost:5918/health
```

### 認証エラー

**症状**: `401 Unauthorized`

**解決方法**:

1. API Key が正しいか確認
2. ヘッダーが正しいか確認：

```bash
# 正しい
curl -H "Authorization: Bearer sk-xxx"

# 間違い
curl -H "Authorization: sk-xxx"
```

### モデルが見つからない

**症状**: `Model not found`

**解決方法**:

1. 利用可能なモデルを確認：

```bash
curl http://localhost:5918/openai/v1/models \
  -H "Authorization: Bearer sk-あなたのキー"
```

2. アカウントの権限を確認（Pro アカウントが必要な場合がある）

### Cookie 期限切れ

**症状**: `SNlM0e not found` または `Invalid session`

**解決方法**:

1. Cookie を更新（上記の「Cookie 管理」を参照）
2. または新しい Cookie を取得して `.env` を更新
