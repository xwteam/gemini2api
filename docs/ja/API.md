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

### 2 種類のキー

| 種類 | 入手元 | 到達範囲 | カウント |
|------|------|--------|------|
| `API_KEY`（`.env`） | 初回起動時に自動生成、または自分で設定 | 業務 API + `/admin/*`（`ADMIN_API_KEY` を別途設定していない場合） | されない |
| アクセスキー | 管理者がパネルの「アクセスキー」ページまたは `POST /admin/access-keys` で発行 | **業務 API のみ**。`/admin/*` には到達できません | リクエストごとに +1 |

アクセスキーは**追加**の層です：`API_KEY` は常に全権限を保持し、アクセスキーを 1 本も発行していない場合、認証の挙動は従来版と完全に同一です。アクセスキーはそれぞれ有効期限・リクエスト上限・バインドするアカウント・許可するモデルを持てます（詳細は `POST /admin/access-keys`）。

アクセスキーが拒否されたとき（無効／期限切れ／上限到達）のステータスは 401 で、本文の `message` に理由が入ります。

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

## 🧠 モデルと思考レベル

| 公開モデル名 | 自動でマッピングされる Web 版のモデル（現時点の実測） | 説明 |
|------|------|------|
| `gemini-pro` | 3.1 Pro | 最高品質、やや遅い |
| `gemini-flash` | 3.8 Flash | 高速。既定としておすすめ |
| `gemini-flash-lite` | 3.5 Flash-Lite | 最軽量・最速。Pro/Flash がレート制限されたときの代替 |
| `gemini-argon` | 4 Argon | 複雑なタスク向け。**アカウントが実際に Argon を持つ場合のみ一覧に出ます** |

- **マッピングは自動です**：各アカウントのハートビートが、そのアカウントで今実際に使える Web 版モデルを報告します。公開名は変わらず、内部では Web 版の現行世代に自動で追従します（Google が世代交代してもクライアントの変更は不要）。
- **`gemini-flash-thinking` は廃止しました**：これは「flash + 思考モード」という見せかけのモデルにすぎず、思考は今やすべてのモデルが持つレベルになりました（下記）。旧クライアント互換のため、`gemini-flash-thinking`・`gemini-2.5-flash-thinking`・`gemini-2.0-flash-thinking` と内部名 `gemini-3-flash-thinking*` は**引き続き呼び出せます**（`gemini-flash` の隠しエイリアス）。ただしどのモデル一覧にも出ません。思考内容が必要な場合はレベルパラメータを指定してください。 例外：アクセスキーの「許可モデル」に `gemini-flash-thinking` が含まれている場合、そのキーのモデル一覧には引き続き表示されます（それだけを許可した古いキーで一覧が空にならないように）。新しく発行するキーでは `gemini-flash` を選んでください。⚠️ 挙動の変更：旧クライアントがレベルを指定せずに `gemini-flash-thinking` を呼ぶと v1.6.42 では思考内容が返っていましたが、現在は返りません（要求されていない思考は返しません）。
- **思考は 3 段階**：`low` / `medium` / `high`。Web 版の低 / 中 / 高に対応します（実測では `high` が最も深く最も遅い。`low` と `medium` の差は実測では見分けられませんでした）。
- **既定は `low`**：クライアントが**レベルを指定しない**場合（思考パラメータをまったく送らない場合と、思考は要求したがレベルを示さない場合）は「既定の思考レベル」（環境変数 `DEFAULT_THINKING_LEVEL`、またはパネルの「設定 → 思考」。保存すると即時反映、再起動不要）を使います。出荷時は `low`。
  - ⚠️ **速度のコスト**：実測では既定の `low` は思考なしより**1 リクエストあたり平均約 5 秒遅く**なります（flash の簡単な質問：6.5 / 8.8 秒 → 8.6 / 16.6 秒）。速度を最優先するなら既定を **`off`** にしてください（思考なし・最速。旧版でパラメータを付けなかったときと上流へのリクエストが完全に同じ）。前段プロキシに初回バイトのタイムアウトがある場合（EdgeOne 無料版の 15 秒など）は非ストリーミングリクエストに特に注意してください。ストリーミングにもコストがあります：思考を要求していないリクエストでは既定値で有効にした思考を返さないため、**本文は思考が終わってから始まります**（その間はキープアライブを送るのでプロキシに切断されません）。推論が必要な質問では `gemini-pro` の `low` は実測で合計 36～47 秒でした。最初のトークンまでの時間が重要なら `off` を使ってください。⚠️ `off`（および既定レベルそのもの）が対象とするのは**レベルが指定されていない**リクエストです：思考パラメータを送らないものと、思考は要求したがレベルを示さないもの（Claude Code の初期設定のリクエストがこれに当たるため、Claude Code も既定レベルに従います）。クライアントが**明示的にレベルを指定した**場合（Codex / Cursor が low/medium/high を選んだ場合、Anthropic が `budget_tokens` を送った場合、Claude Code の `/effort max` など）、既定レベルは効きません。すべての思考を止める（本当に最速にする）には下のマスタースイッチ（`EXTENDED_THINKING_ENABLED=false`）をオフにしてください。
  - クライアントが**思考を一切要求していない**場合、既定レベルで有効にした思考は**生成にのみ使い、決して返しません**：`reasoning_content` / `thinking` ブロック / 思考 part は追加されず、思考なしのレスポンスとフィールド単位で同一です（厳格なクライアントもエラーになりません）。思考内容を返すのは、クライアントが**思考を要求した**場合（レベルを指定したかどうかを問いません）だけです（ネイティブ Gemini は引き続き `includeThoughts` だけを見ます）。既定レベルが `off` のときは、思考は要求したがレベルを示さないリクエストも思考しないため、返すべき思考はありません。
- **Claude Code**（最新版）：すべてのリクエストに `adaptive` + `effort: high`（high は Claude Code の出荷時設定で、変更しない限り毎回これ）が付くため、追加の設定なしでここの既定レベル（出荷時 `low`、速度優先）に従います。あるセッションでより深く考えさせたいときは、Claude Code で `/effort max`（または `xhigh`）を実行します → high。`/effort low` / `medium` もそのレベルで扱われます。
- **マスタースイッチ** `EXTENDED_THINKING_ENABLED=false`：クライアントが明示的に要求しても常に思考しません。これが**本当に最速**のモードです。パネルの「設定 → 思考 →「思考を許可（マスタースイッチ）」」に常に表示され、保存すると即座に反映されます。既定の思考レベルとの役割分担：既定レベルはレベルを指定しないリクエスト（Claude Code の初期設定のリクエストを含む）が対象、マスタースイッチはレベルを明示したクライアントも対象です。
- パネルの「モデルテスト」ページは、従来の「思考」チェックボックスの代わりに**レベル選択**（低 / 中 / 高、既定は低）になりました。選んだレベルは `reasoning_effort` として送られ、思考過程は回答の上に表示されます。 「既定レベル（パラメータなし）」も選べます：`reasoning_effort` を送らず通常のクライアントと同じ経路を通るので、設定の既定の思考レベル（`off` を含む）の実際の速度を測れます（思考内容は規定どおり返されません）。

プロトコルごとのレベル指定（**レベルを指定しなければ既定レベルを使います**。思考を一切要求しないリクエストには思考を返しません）：

| プロトコル | パラメータ | 値 → レベル |
|------|------|------|
| OpenAI `/v1/chat/completions` | `reasoning_effort` | `low` / `medium` / `high`。`minimal` → low、`xhigh` → high。`none` → 思考なし。認識できない値 → 既定レベルに従う（エラーにしません） |
| OpenAI `/v1/responses` | `reasoning.effort`（またはトップレベルの `reasoning_effort`） | 同上 |
| Anthropic `/v1/messages` | `thinking` | `{"type":"enabled","budget_tokens":N}`：`N<2048` → low、`2048–4095` → medium、`≥4096` → high。`{"type":"adaptive"}` または無効な budget → `output_config.effort` を見る：`low` / `medium` はそのレベル、`xhigh` / `max` → high、`high`（Claude Code の出荷時設定で、明示的な選択なしとみなす）または未指定 → 既定レベルに従う。`{"type":"disabled"}` → 思考なし。認識できない `type` は未指定と同じ扱い |
| Gemini ネイティブ `generateContent` / `streamGenerateContent` | `generationConfig.thinkingConfig` | `thinkingLevel`：`LOW` / `MEDIUM` / `HIGH`（`MINIMAL` → low、未指定 → 既定レベルに従う）。`thinkingBudget`：`0` → 思考なし、`-1`（自動）→ 既定レベルに従う、`>0` は 2048 / 4096 を境に段階分け。両方指定した場合は `thinkingLevel` を優先。`includeThoughts: true` だけを指定した場合 → 既定レベルに従う。`includeThoughts: true` のときだけ思考をレスポンスで返します（`"thought": true` の part） |

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
      "id": "gemini-flash-lite",
      "object": "model",
      "created": 1715970000,
      "owned_by": "gemini"
    },
    {
      "id": "gemini-argon",
      "object": "model",
      "created": 1715970000,
      "owned_by": "gemini"
    }
  ]
}
```

> 💡 **モデル選択ガイド**：4つのモデルは異なる速度/品質のトレードオフを提供します。
> - `gemini-flash`：最速(応答約4-5秒)、**agent / 高頻度 / 高並行**シナリオに最適、デフォルト推奨。
> - `gemini-argon`：4 Argon。複雑なタスク向けで、アカウントが実際に Argon を持つ場合のみ一覧に出ます。
> - `gemini-flash-lite`：最軽量・最速のティア（3.5 Flash-Lite）。Pro/Flash がレート制限に達したときの利用可能なフォールバック。
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
| `conversation_id` | string | ❌ | 会話 ID（マルチターン続行用。ルールは下の「マルチターン続行」を参照） |
| `tools` | array | ❌ | 関数定義配列 |
| `tool_choice` | string | ❌ | 関数選択戦略 |

**マルチターン続行（`conversation_id`）:** 同じ `conversation_id` の後続ターンは上流 Gemini の同じ会話を続けます。送るのは最新のユーザーメッセージだけで、前のターンで記録した続行メタデータ（`[cid, rid, rcid]`）を付けます。Gemini Web の会話は特定のアカウントに属するため、後続ターンは**前のターンに応答したアカウントに固定**されます。ストリーミングリクエストも同じように続行しますが、ストリーミングのレスポンスには `conversation_id` が含まれないため、クライアント自身が付けてください（非ストリーミングで付けなかった場合はサーバーが生成し、レスポンスの `conversation_id` フィールドで返します）。次のいずれかに当たる場合は**自動で全履歴を送り直し、新しい会話を始めます**（成功したら新しい会話とアカウントを記録し、次のターンは通常どおり続行）。最後の一文だけを送って黙ってコンテキストを失うことはありません：

- そのアカウントが使えない：期限切れ、削除済み、このアクセスキーのバインドするアカウント外、または（プールに複数アカウントがある場合）満杯；
- 記録した続行メタデータが使えない（アップグレード前に保存され、アカウントが記録されていない古い会話を含む：最初のターンは全履歴を送り、以降は続行に戻る）；
- 前のターンを第三者フォールバックが回答した、または上流がそのターンの続行ポイントを返さなかった；
- 新しいターンがユーザーメッセージ 1 件だけではない：ツール結果（`role: "tool"`、またはユーザーメッセージ内の `tool_result` ブロック）を含む、または前の回答のあとに複数のメッセージが続いている；
- Gem モデルを使っていて、Gem にバインドされたアカウントが会話のアカウントと異なる（Gem を優先）。

Google 側で会話が本当に期限切れになり続行リクエストが失敗した場合は、引き続き全履歴で 1 回再試行します（タイムアウトを除く。[タイムアウト](#タイムアウト) を参照）。固定したアカウントが実際の送信時になって使えなくなった場合（ちょうど満杯になったなど）も同様に全履歴を送り直し、このターンの思考レベルはそのまま保ちます。

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

### POST /openai/v1/responses

OpenAI Responses API。Chat Completions ではなく新しい Responses プロトコルを必要とするクライアント（例: **Codex CLI**。2026 年 2 月に Chat Completions のサポートを終了したため、Codex CLI を gemini2api に接続するにはこのエンドポイントが必要）向けに追加されました。テキスト、ストリーミング、関数/ツール呼び出しに対応し、Gemini モデルと API 管理で設定したサードパーティモデルの両方で利用できます。

**リクエスト:**

```bash
curl -X POST http://localhost:5918/openai/v1/responses \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-api-key" \
  -d '{
    "model": "gemini-flash",
    "input": "What is 2+2?",
    "stream": false
  }'
```

**リクエストパラメータ:**

| パラメータ | 型 | 必須 | 説明 |
|-----------|-----|------|------|
| `model` | string | ✅ | モデル ID（例: `gemini-flash`）、または API 管理で設定したサードパーティモデル |
| `input` | string または array | ✅ | プレーンな文字列（単一のユーザーメッセージの省略形）、または入力アイテムの配列（下記参照） |
| `instructions` | string | ❌ | 会話の先頭に付加されるシステム/開発者プリアンブル |
| `stream` | boolean | ❌ | ストリーミングを有効化（デフォルト: false） |
| `tools` | array | ❌ | ツール呼び出し用の関数定義、**フラット形式**: `{"type":"function","name","description","parameters"}`（注: Chat Completions のネストされた `{"type":"function","function":{...}}` 形式とは異なります） |
| `tool_choice` | string または object | ❌ | `auto`、`none`、`required`、または特定のツールを強制する `{"type":"function","name":"..."}` |
| `temperature` | number | ❌ | ランダム性（サードパーティモデルには転送されますが、Gemini 経路では反映されません） |
| `max_output_tokens` | number | ❌ | 最大レスポンス長（サードパーティモデルには転送されますが、Gemini 経路では反映されません） |

**`input` 配列アイテムの種類:**

- `{"type":"message","role":"user"|"assistant"|"system","content":[...]}` — content のパーツ: `{"type":"input_text","text":...}`、`{"type":"input_image","image_url":"..."}`、`{"type":"output_text","text":...}`
- `{"type":"function_call","call_id","name","arguments"}` — 直前のアシスタントによるツール呼び出しターン（複数ターンの履歴として自身で再送する場合に使用）
- `{"type":"function_call_output","call_id","output"}`（または `"tool_result"`）— 送り返すツールの実行結果

**サポートされていません（暗黙の無視ではなく明示的エラー）:** `previous_response_id` — 本サーバーはサーバー側で会話状態を保持しません。指定した場合、黙って無視するのではなく 400 の `invalid_request_error` を返します。毎回のリクエストで会話全体を `input` に含めて送信してください（Codex CLI は既にこの方式で動作しています）。

**レスポンス（非ストリーミング）:**

```json
{
  "id": "resp_xxx",
  "object": "response",
  "created_at": 1715970000,
  "status": "completed",
  "model": "gemini-flash",
  "output": [
    {
      "id": "msg_xxx",
      "type": "message",
      "role": "assistant",
      "status": "completed",
      "content": [
        {"type": "output_text", "text": "2 + 2 = 4", "annotations": []}
      ]
    }
  ],
  "usage": {
    "input_tokens": 10,
    "input_tokens_details": {"cached_tokens": 0},
    "output_tokens": 5,
    "output_tokens_details": {"reasoning_tokens": 0},
    "total_tokens": 15
  },
  "previous_response_id": null,
  "instructions": null,
  "error": null
}
```

**レスポンス（ストリーミング）:** 仕様に準拠した名前付き SSE イベントの並びで、各イベントは単調増加する `sequence_number` を持ちます。`data: [DONE]` のような終端マーカーは**ありません**（これは Chat Completions の慣習です）— 完了は `response.completed`（または `response.failed`）によって通知されます。

```
event: response.created
data: {"type":"response.created","sequence_number":0,"response":{...}}

event: response.in_progress
data: {"type":"response.in_progress","sequence_number":1,...}

event: response.output_item.added
data: {"type":"response.output_item.added","sequence_number":2,...}

event: response.content_part.added
data: {"type":"response.content_part.added","sequence_number":3,...}

event: response.output_text.delta
data: {"type":"response.output_text.delta","sequence_number":4,"delta":"2"}

event: response.output_text.done
data: {"type":"response.output_text.done","sequence_number":5,"text":"2 + 2 = 4"}

event: response.content_part.done
data: {"type":"response.content_part.done","sequence_number":6,...}

event: response.output_item.done
data: {"type":"response.output_item.done","sequence_number":7,...}

event: response.completed
data: {"type":"response.completed","sequence_number":8,"response":{...}}
```

ツール呼び出しの場合、`response.output_item.added`（type が `function_call`）の後には、上記のテキストイベントの代わりに `response.function_call_arguments.delta` / `response.function_call_arguments.done` / `response.output_item.done` が続きます。

**関数呼び出しの例:**

```bash
curl -X POST http://localhost:5918/openai/v1/responses \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-api-key" \
  -d '{
    "model": "gemini-flash",
    "input": "What is the weather in Paris?",
    "tools": [
      {
        "type": "function",
        "name": "get_weather",
        "description": "Get weather for a city",
        "parameters": {
          "type": "object",
          "properties": {
            "city": {"type": "string"}
          },
          "required": ["city"]
        }
      }
    ]
  }'
```
レスポンスの `output` には `function_call` アイテムが含まれます:
```json
{"id": "fc_xxx", "type": "function_call", "status": "completed", "call_id": "call_xxx", "name": "get_weather", "arguments": "{\"city\": \"Paris\"}"}
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

#### 拡張思考（`thinking`）

| パラメータ | 型 | 必須 | 説明 |
|-----------|-----|------|------|
| `thinking` | object | ❌ | 思考レベルを指定します。**送らない場合、上流は「既定の思考レベル」（出荷時 `low`）で思考しますが、レスポンスに `thinking` ブロックは決して含めず、従来と完全に同一です** |
| `output_config` | object | ❌ | その中の `effort` だけを読み、`thinking` と組み合わせてレベルを決めます（使い方は下の `adaptive` の行）。`thinking` なしで `output_config.effort` だけを送っても効果はありません（思考パラメータを送らなかったものとして扱います）。形が正しくない場合（オブジェクトでない、`effort` を認識できない）は指定なしと同じ扱いで、エラーにはしません |

- `{"type":"enabled","budget_tokens":N}`：有効。`N` は `<2048` / `2048–4095` / `>=4096` で低／中／高の 3 段階に対応します。有効な `budget_tokens` があればそれでレベルが決まり、`output_config.effort` より優先されます。
- `{"type":"adaptive"}`：有効。レベルは `output_config.effort` を見て決めます：`low` / `medium` はそのレベル、`xhigh` / `max` → high、`high`（Claude Code の出荷時設定で、明示的な選択なしとみなす）または未指定 → 既定の思考レベルに従います。`budget_tokens` がない／無効な場合も同様。
- `{"type":"disabled"}` / `{"type":"between_tools"}`：思考しません（明示的なオフ。既定レベルは適用されず、`output_config.effort` が何であっても無視されます）。

思考内容は Anthropic 仕様の `thinking` コンテンツブロックとして、`text` / `tool_use` ブロックの**前に**返します。ストリーミングでは `content_block_start(thinking)` → `thinking_delta` → `content_block_stop` です。

⚠️ **`signature` は付きません**（有効な署名を生成できないため。空文字や自作の署名を付けるのはより危険で、クライアントが本物の API に送り返すと 400 になります）。段階は Web 版の低 / 中 / 高に対応します（実機計測で high が最も深い。low と medium は見分けられませんでした）。 `EXTENDED_THINKING_ENABLED=false` の場合、`thinking` を送っても思考パスは使われません。

⚠️ **本文が始まった後に届いた思考の増分は破棄されます**（ストリーミング）：Anthropic のブロック順序では `text` ブロックの後に `thinking` ブロックを開く／続けることができません（失われた文字数は WARNING に記録されます）。完全な思考チェーンが必要な場合は、ブロック順序の制約がない OpenAI プロトコルの `reasoning_content` を使ってください。本文は常に完全です。`thinking` がオブジェクト以外の場合は**未指定**として扱い、200 を返します。

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
  "total": 2,
  "active": 1,
  "strategy": "round-robin",
  "max_concurrent_per_account": 8,
  "accounts": [
    {
      "id": "account-0",
      "label": "メインアカウント",
      "psid": "g.a0****x0yz",
      "status": "active",
      "request_count": 152,
      "error_count": 1,
      "active_requests": 0,
      "last_used": "2026-10-26T03:58:10.512014+00:00",
      "cooling_down": false,
      "is_healthy": true,
      "consecutive_failures": 0,
      "consecutive_empty": 0,
      "empty_count": 0,
      "last_success_at": "2026-10-26T03:58:12.104233+00:00",
      "last_error": "",
      "last_error_at": null,
      "models": ["gemini-pro", "gemini-flash", "gemini-flash-lite", "gemini-argon"],
      "models_count": 4,
      "keepalive_mode": "browser"
    },
    {
      "id": "account-1",
      "label": "予備アカウント",
      "psid": "g.a0****k9qr",
      "status": "expired",
      "request_count": 87,
      "error_count": 0,
      "active_requests": 0,
      "last_used": "2026-10-24T14:40:02.338190+00:00",
      "cooling_down": false,
      "is_healthy": false,
      "consecutive_failures": 0,
      "consecutive_empty": 0,
      "empty_count": 0,
      "last_success_at": "2026-10-24T14:40:05.901123+00:00",
      "last_error": "Google session expired (login redirect)",
      "last_error_at": null,
      "models": ["gemini-pro", "gemini-flash", "gemini-flash-lite", "gemini-argon"],
      "models_count": 4,
      "keepalive_mode": "server"
    }
  ],
  "model_breakers": {
    "flash": {
      "state": "open",
      "enabled": true,
      "consecutive_failures": 2,
      "open_remaining_seconds": 41.2,
      "retry_at": "2026-10-26T09:01:03.402771+00:00",
      "cooldown_seconds": 60.0,
      "probe_in_flight": false,
      "last_reason": "GeminiFailureReply (HTTP 502)",
      "last_failure_at": "2026-10-26T09:00:03.402771+00:00"
    }
  }
}
```

| フィールド | 説明 |
|------|------|
| `active` | 対外 `status` が `active` のアカウント数 |
| `accounts[].status` | `active`：利用可能。`expired`：セッション失効で Cookie の差し替えが必要 —— 連続 3 回の失敗、上流の 401/403、そして **Google セッションのログインページへのリダイレクト**（このとき `is_healthy` は `false`、`last_error` が空なら `Google session expired (login redirect)` が入ります）。新しい Cookie が入ると自動的に `active` に戻ります。`disabled`：無効 |
| `accounts[].is_healthy` | クライアントのセッションが現在利用可能か。`active` なのに `false` の場合は一時的な不調（ネットワークの揺らぎなど）で、セッション失効とはまだ判定されていません |
| `accounts[].last_error` / `last_error_at` | 直近の失敗の秘匿化された要約と発生時刻 |
| `accounts[].keepalive_mode` | Cookie を誰が保持するか：`server`（デフォルト。サーバーが定期的にローテーション）/ `browser`（ブラウザ保持拡張機能が送信。サーバーはローテーションしない —— `PUT /admin/accounts/{id}/cookies` を参照） |
| `model_breakers` | モデル障害ブレーカーのファミリーごとの状態（`GET /admin/accounts` にも含まれます）。状態を持ったことのあるファミリーだけを列挙。[Google 側の障害](#google-側の障害) を参照 |
| `model_breakers.*.state` | `closed`：通常どおり Google を呼ぶ；`open`：Google 側で障害中、フォールバックのある `/v1/chat/completions` リクエストは直接フォールバックへ；`half_open`：開放期間が終わり、次のリクエストで Google を試す |
| `model_breakers.*.enabled` | `MODEL_BREAKER_ENABLED`。`false` でも状態は記録しますが、Google を迂回することはありません |
| `model_breakers.*.consecutive_failures` | 現在のウィンドウで障害の疑いがある失敗をした異なるリクエストの数 |
| `model_breakers.*.open_remaining_seconds` / `retry_at` | `open` のとき残り秒数 / 終わる絶対時刻（UTC）。それ以外は `0` / `null` |
| `model_breakers.*.cooldown_seconds` | 今回（または次回）の開放期間の秒数（試行が失敗すると倍、上限 `MODEL_BREAKER_MAX_COOLDOWN`） |
| `model_breakers.*.probe_in_flight` | `half_open` のとき、すでに 1 件のリクエストが Google を試しているか |
| `model_breakers.*.last_reason` / `last_failure_at` | ブレーカーが数えた直近の失敗（例外の型 + ステータスコードの安全な要約）とその時刻（UTC） |

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

> レスポンスは `GET /admin/status` と同じです（`model_breakers` も含みます。パネルのアカウントページ上部のブレーカー表示はこのエンドポイントを読みます）。

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

新しく追加したアカウントも送信元から `keepalive_mode` を記録します（ルールは `PUT /admin/accounts/{id}/cookies` と同じ。パネルの「アカウント追加」やスクリプトで追加したものは `server`）。アカウントを削除してもその PSID の記録は消えませんが、同じ Cookie で追加し直すと今回の送信元で記録し直します。

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

成功時は送信元から保持方式を記録し、アカウントはただちに `active` に戻ります（ルールは `PUT /admin/accounts/{id}/cookies` と同じ）。

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

**保持方式：** リロードに成功すると、リクエストの送信元からこのアカウントの保持方式を記録します（新しい PSID の名義で `data/keepalive-modes.json` に保存。PSID のハッシュのみを保存）：

| リクエスト | `keepalive_mode` | 効果 |
|------|------|------|
| `X-Gemini2API-Keepalive` ヘッダー付き（ブラウザ保持拡張機能 v1.3.0 以降が送信。値は `gemini2api-plugin/1.3.0` の形式。リポジトリ付属の Playwright 更新サイドカーは `gemini2api-refresher` を送信） | `browser` | サーバーはこのアカウントの RotateCookies を呼ばなくなり、ブラウザがローテーションして拡張機能が送信します |
| `Origin` が `chrome-extension://` で始まる（このヘッダーを送らない旧版の拡張機能） | `browser` | 同上 |
| その他（パネルの「Cookie 更新」、スクリプト / curl） | `server` | サーバーの定期ローテーションに戻します |

成功するとアカウントはただちに `active` に戻り、連続失敗数もリセットされます（続けて `/check` を呼ぶ必要はありません）。リロードに失敗した場合（503）は何も変わりません。その Cookie には切り替わらず、保持方式もアカウント状態もそのままです。送信元がブラウザ保持拡張機能の場合は、このリロード自体でも RotateCookies を呼びません（トークン取得に失敗したときの予備のローテーションも行わないので、ブラウザが使用中のセッションをサーバーが差し替えることはありません）。

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
    "refresh_interval": 30
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

### GET /admin/access-keys

すべてのアクセスキーを一覧（平文のキー・状態・使用量・適用範囲を含む）。

**リクエスト:**
```bash
curl http://localhost:5918/admin/access-keys \
  -H "Authorization: Bearer sk-あなたのキー"
```

**レスポンス:**

```json
{
  "keys": [
    {
      "id": 1,
      "key": "sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
      "name": "山田",
      "display_name": "山田",
      "enabled": true,
      "created_at": "2026-10-20T03:00:00+00:00",
      "expires_at": null,
      "duration_days": 7,
      "activated_at": null,
      "request_limit": 500,
      "request_count": 0,
      "bound_account_ids": null,
      "allowed_models": ["gemini-flash"],
      "last_used_at": null,
      "state": "pending"
    }
  ]
}
```

`state` の値：`valid`（有効）／`disabled`（無効）／`pending`（未アクティブ。`duration_days` は設定済みだが未使用）／`expired`（期限切れ）／`quota_exceeded`（上限到達）。判定は `disabled` → `expired` → `quota_exceeded` → `pending` → `valid` の優先順位で短絡的に行われます。

### GET /admin/access-keys/options

パネル発行フォームの選択肢：アカウントプール内のアカウントと、外部に見えるモデル名（`GET /v1/models` と同じ範囲）。

**リクエスト:**
```bash
curl http://localhost:5918/admin/access-keys/options \
  -H "Authorization: Bearer sk-あなたのキー"
```

### POST /admin/access-keys

アクセスキーを発行します。

**パラメータ:**

| 項目 | 型 | 必須 | 説明 |
|------|------|------|------|
| `name` | string | ❌ | ラベル。`count > 1` のとき `name-1`、`name-2`… と自動連番 |
| `count` | integer | ❌ | 一度に発行する本数。デフォルト 1、**上限 50** |
| `expires_at` | string | ❌ | 絶対有効期限（ISO8601）。`duration_days` と排他 |
| `duration_days` | number | ❌ | 有効日数。**遅延アクティベーション**：保持者の初回利用から計時開始（上限 36500） |
| `request_limit` | integer | ❌ | リクエスト上限。空で無制限 |
| `bound_account_ids` | string[] | ❌ | バインドするアカウント。空で制限なし |
| `allowed_models` | string[] | ❌ | 許可するモデル。空で制限なし |
| `enabled` | boolean | ❌ | 即座に使用可能にするか。デフォルト `true` |

**リクエスト:**
```bash
curl -X POST http://localhost:5918/admin/access-keys \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-あなたのキー" \
  -d '{
    "name": "山田",
    "duration_days": 7,
    "request_limit": 500,
    "allowed_models": ["gemini-flash"]
  }'
```

レスポンスの `keys` は今回発行したすべてのキー、`key` はそのうちの 1 本目です（1 本だけ発行する場合にそのまま使えます）。

> `count` が 0 または 50 超なら 400、`expires_at` と `duration_days` を同時に指定しても 400、ディスクへの書き込み失敗は 500 を返します（保存できていないキーに 200 を返すことは絶対にありません —— 配ったキーが再起動後に無効になってしまいます）。

### PATCH /admin/access-keys/{id}

キーの設定を変更します。

**リクエスト:**
```bash
# 無効化
curl -X PATCH http://localhost:5918/admin/access-keys/1 \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-あなたのキー" \
  -d '{"enabled": false}'

# リクエスト上限とモデル制限を解除
curl -X PATCH http://localhost:5918/admin/access-keys/1 \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-あなたのキー" \
  -d '{"clear": ["request_limit", "allowed_models"]}'
```

> **JSON の `null` は「この項目を変更しない」という意味**で、「空にする」ではありません。`expires_at` / `duration_days` / `request_limit` / `bound_account_ids` / `allowed_models` を実際に空にするには、項目名を `clear` 配列に入れる必要があります。`clear` にそれ以外の項目名が入っていると 400 を返します。

### DELETE /admin/access-keys/{id}

キーを削除します。使用中のクライアントは直ちに接続できなくなります。

**リクエスト:**
```bash
curl -X DELETE http://localhost:5918/admin/access-keys/1 \
  -H "Authorization: Bearer sk-あなたのキー"
```

### POST /admin/access-keys/{id}/reset-usage

`request_count` をゼロに戻し、上限到達したキーを再び使えるようにします。

**リクエスト:**
```bash
curl -X POST http://localhost:5918/admin/access-keys/1/reset-usage \
  -H "Authorization: Bearer sk-あなたのキー"
```

> **カウントの考え方**：業務リクエストは認証入口でアトミックに加算され、単調増加で払い戻しはありません（上流がエラーでもカウントされます）。**`GET /v1/models` もカウント対象です** —— クライアントによっては対話のたびにモデル一覧を取得するため 1 ラウンドで 2 回消費します。`request_limit` を設定する際は余裕を持たせてください。

## エラーコード

API エラーは以下のコードで返されます。

| コード | 説明 | 対応 |
|--------|------|------|
| 400 | パラメータエラー | リクエストパラメータを確認 |
| 401 | 未認証 | API Key を確認 |
| 403 | 禁止 | 権限がない |
| 429 | レート制限 | しばらく待機 |
| 500 | サーバーエラー | ログを確認 |
| 502 | 上流エラー（`api_error`）。Google が回答の代わりに失敗の定型文を返した場合を含む | 少し待って再試行。[Google 側の障害](#google-側の障害) を参照 |
| 503 | 利用不可 | アカウントが利用不可 |
| 504 | 生成タイムアウト（`timeout_error`） | 少し待って再試行、またはストリーミングを使用。[タイムアウト](#タイムアウト) を参照 |

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

生成タイムアウトは**モデルファミリー単位で段階化**されており（非ストリーミングとストリーミングで同じ予算）、`GENERATE_TIMEOUTS` で上書きできます。

| モデルファミリー | デフォルトのタイムアウト |
|------|------|
| flash-lite | 60 秒 |
| flash | 120 秒 |
| pro | 300 秒 |
| argon | 300 秒 |
| 認識できないファミリー | 60 秒 |

画像生成と推定されるリクエストは、上記の値と `GENERATE_TIMEOUT_IMAGE`（デフォルト 180 秒）のうち**大きい方**を採用します。タイムアウトは 3 回リトライしなくなりました —— 失敗は失敗です。

**ストリーミングリクエスト**も同じ予算に従います：最初の進展（本文・思考・生成画像・Canvas の新しい内容）は予算内に届く必要があり、レスポンスヘッダーを待つ時間も含みます。以降、進展どうしの間隔も予算を超えられません。Google がキューで待たせている間 60 秒ごとに送ってくる内容のないハートビートフレーム `[{"37":[0]}]` は**進展に数えません**。重複したフレームや会話メタデータだけのフレームも同様です。ファミリーの予算より早く打ち切ることはありません：同じアカウントの pro が思考なしで難問に答えるとき、60 秒後にレスポンスヘッダー、89 秒後に本文が届くのは正常な回答です。添付ファイルのアップロード時間は数えません。予算を使い切ると、まず Google との転送を中止してから `timeout_error` イベントをクライアントに送ります。

タイムアウトは **504**、エラータイプ `timeout_error` で、各プロトコル独自のエラー本文で返ります：OpenAI / Gemini ネイティブ / Responses は `{"error": {..., "type": "timeout_error"}}`、Anthropic は `{"type": "error", "error": {"type": "timeout_error", ...}}`（以前はプレーンテキストの `500 Internal Server Error` で、SDK は解析できず、タイムアウトとして再試行もしませんでした）。ストリーミングリクエスト（ツール呼び出し用の擬似ストリーミングを含む）はすでに 200 を返しているため、タイムアウトはプロトコル内のエラーイベントになります：OpenAI の error フレームは `type` が `timeout_error`、`code` が `504`；Anthropic の `error` イベントと Gemini ネイティブ NDJSON のエラー行は `type` が `timeout_error`；Responses の `response.failed` は `error.code` が `timeout_error`。画像生成エンドポイント `/v1/images/generations` も同じく 504 + `timeout_error` を返します。ディープリサーチのエンドポイント（`/gemini/v1beta/deepresearch`、および `/gemini/v1beta/deepresearch/interact` への非ストリーミングリクエスト）は 504 を返し、エラー本文は `{"detail": "..."}` です。

- `FALLBACK_ENABLED` が有効なら、`/v1/chat/completions` はクライアントに本文を送る前であれば、まず第三者フォールバックを試みます。ほかの 3 プロトコルには第三者フォールバックがなく、上記のエラーをそのまま返します。
- タイムアウトは思考なしで再試行せず、完全なプロンプトでの再試行もしません：このターンの予算はすでに使い切っており、再試行してもクライアントをもう 1 ラウンド待たせるだけです。
- タイムアウトは Google 側の停滞で、Cookie の失効ではありません：アカウントの連続失敗には数えず、アカウントを `expired` にすることもありません（エラーを 1 回記録し、短いクールダウンに入るだけです）。
- 接続段階のタイムアウト（数秒で返ってきて、生成の予算を使い切っていないもの）は従来どおりまず同じアカウントで数回再試行します。再試行を使い切った場合もタイムアウトとして扱います：504 を返し、連続失敗には数えず、思考なしや完全なプロンプトでの再試行もしません。

> [!IMPORTANT]
> 非ストリーミング経路では生成が返るまで接続上の出力は**ゼロバイト**です。つまりこれはアイドルタイムアウトではなく**最初の 1 バイトまで**のタイムアウトです。
> **pro の非ストリーミングは最長 300 秒無音で待つことになり、一般的な前段プロキシの最初の 1 バイトの上限を超えます**（EdgeOne 無料版は 15 秒、多くのリバースプロキシはデフォルト 60 秒）。その場合クライアントが受け取るのは本サービスのエラー本文ではなくプロキシの 504 です。
> 本サービス自身のタイムアウトも 504 ですが、上記の JSON エラー本文（`timeout_error`）を伴うので、プロキシの 504 と区別できます。
> 前段プロキシがある構成では、この種のリクエストに `stream: true` を使うことを推奨します（ストリーミングは最初のフレームをすぐに送り、待機中はキープアライブフレームを送ります）。ストリーミングリクエストも上の表の予算に従います。ルールは上記のとおりです。

## Google 側の障害

Google 側で、あるモデルファミリー全体に問題が起きたとき（2026-10-26 の実測：gemini-flash が 2 回障害になり 3 アカウントすべてが影響を受け、同じアカウントの flash-lite と pro は正常）、現れ方は 2 通りです：キューで止まる（60 秒後にレスポンスヘッダー、以降 60 秒ごとに空のハートビートフレーム。上記の[タイムアウト](#タイムアウト)で処理）か、1 秒ほどで固定の失敗の定型文が返ってくるかです。

**失敗の定型文**：回答全体（前後の空白を除き、連続する空白を 1 つにまとめ、大文字小文字を区別しない）がちょうど `I seem to be encountering an error. Can I try something else for you?`（または `GEMINI_FAILURE_REPLIES` で追加した文）であれば、上流の失敗として扱います：次のアカウントで再試行し、すべて失敗した場合 `/v1/chat/completions` はまず第三者フォールバックを試み、それ以外は **502 `api_error`** を返します（OpenAI / Gemini ネイティブ / Responses は `{"error": {..., "type": "api_error"}}`、Anthropic は `{"type": "error", "error": {"type": "api_error", ...}}`。画像生成エンドポイントも 502）。ストリーミングリクエストではほかの上流エラーと同じくプロトコル内のエラーイベントになります：OpenAI の error フレームは `type` が `api_error`、`code` が `502`；Anthropic の `error` イベントと Gemini ネイティブ NDJSON のエラー行は `type` が `api_error`；Responses の `response.failed` は `error.code` が `internal_error`；ディープリサーチのエンドポイントは従来どおり 500 です。この文を含むだけ・この文で始まるだけ・生成画像付きの回答は対象外で、ユーザーがまさにこの文の復唱を頼んだ場合も対象外です。定型文が会話記録に保存されることはなく、アカウントは短いクールダウンに入るだけで連続失敗には数えません。ストリーミングでは、まだこの文になり得る冒頭（回答の最初の数語だけ）を保留し、違うと分かった時点ですぐに送り出します。

**モデル障害ブレーカー**（`/v1/chat/completions` のみ）：ウィンドウ（`MODEL_BREAKER_WINDOW`、デフォルト 300 秒）内で `MODEL_BREAKER_THRESHOLD`（デフォルト 2）件の**異なるリクエスト**が同じモデルファミリーで障害の疑いがある失敗 —— 失敗の定型文、ほとんどデータを受け取れなかった（< 1KB）非ストリーミングの生成タイムアウト、一度も進展のないストリーミングタイムアウト —— をすると、ブレーカーが `MODEL_BREAKER_COOLDOWN`（デフォルト 60）秒間開きます。その間、`FALLBACK_ENABLED` が有効でフォールバック候補がある `/v1/chat/completions` リクエストは、予算を丸ごと待たずに**第三者フォールバックが直接回答**します（ストリーミングは従来どおり最初のフレームをすぐ受け取り、フォールバックを待つ間もキープアライブフレームが届きます）。フォールバックが回答できなければ通常どおり Google を呼び、その後フォールバックを繰り返すことはありません。期間が終わると実際のリクエスト 1 件で Google を試します：成功すればすぐに復帰し、失敗すれば開放期間を倍にします（上限 `MODEL_BREAKER_MAX_COOLDOWN`）。フォールバックのないリクエスト、ほかのプロトコル、ディープリサーチ、画像生成は常に通常どおり Google を呼び、その結果もブレーカーの状態に反映されます。影響するのは障害中のファミリーだけです。ファミリーごとの状態は `GET /admin/status`（および `GET /admin/accounts`）の `model_breakers` で確認でき、プロセスを再起動するとクリアされます。
