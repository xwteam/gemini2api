<div align="center">

<img src="../logo.png" width="128" height="128" alt="Gemini2API">

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
  <a href="#-アクセスキー">アクセスキー</a> &bull;
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

> 直近 10 件のみ表示しています。完全な変更ログは [CHANGELOG.md](../../CHANGELOG.md) を参照してください。

| 日付 | 更新内容 |
|------|----------|
| 2026-10-26 21:14:00 | v1.6.47 - 🙅 **Gemini の「言語モデル」系の定型拒否文を回答として返さないように**：「17 は素数？」のような簡単な質問やモデル障害時にも、Google が「I'm just a language model, so I can't help you with that.」（中国語版も）の一文だけを返すことがあり、これまではそのまま回答として返していました。今後は定型の失敗文と同様に別アカウントで再試行し、フォールバックも使えますが、モデル単位のサーキットブレーカーには数えません |
| 2026-10-26 20:26:00 | v1.6.46 - 🩺 **Gemini のモデル障害時の待ち時間を短縮**：Google 側でモデルが止まると、ストリーミングは 60 秒ごとに届く空のハートビートで待たされ続けていました（実測で 4 分）。今後は非ストリーミングと同じ予算でタイムアウトし、その場で接続を切ってアカウントを解放します。Google が 1～2 秒で返す定型の失敗文（I seem to be encountering an error…）は回答として返さず、会話にも保存せず、別アカウントかフォールバックに切り替えます。モデル単位のサーキットブレーカーを追加：同じモデルが続けて失敗すると、フォールバックのあるリクエストは毎回待たずに直接フォールバックし、Google の復旧は自動で試します |
| 2026-10-26 16:41:00 | v1.6.45 - ⏱️ **生成タイムアウトでプレーンテキストの 500 を返さなくなりました**：Google が生成予算を超えて止まると、従来はプレーンテキストの 500 が返っていました（SDK が解析できず、フォールバックも働かない）。今後は全プロトコルで 504 + `timeout_error` を返し、`/v1/chat/completions` はフォールバック有効時にまず第三者フォールバックへ切り替え、タイムアウトは再試行せずアカウントの失敗にも数えません。💬 **マルチターン会話が本当に同じ会話を継続**：`conversation_id` 付きの会話は従来、毎ターン新しい会話を開いて最後の発言だけを送っており、長い会話で文脈が黙って失われていました。今後は `[cid, rid, rcid]` で同じアカウントに固定して継続し（ストリーミングも同様）、継続できない場合は自動で全履歴を送ります |
| 2026-10-26 14:01:00 | v1.6.44 - 🔄 **ブラウザ保活拡張機能が再び機能**：Google にログインページへ戻されたアカウントが従来も active と報告され（is_healthy だけ false）、拡張機能は expired にしか反応しないため救済されず、本番の 2 アカウントが約 37 時間ダウンしていました。今後は expired と正しく報告し、Cookie の差し替えに成功した時点で即復帰します。🔁 **ブラウザとの奪い合いを解消**：拡張機能が Cookie を送ったアカウントは自動で「ブラウザ保活」となり、サーバーはローテーションしません（両側が同じ PSIDTS を更新し、後から更新した側が締め出されていました）。パネルで手動更新したアカウントは従来どおりサーバーがローテーション。対応する拡張機能 v1.3.0 はブラウザの Cookie が変わるとすぐ送信 |
| 2026-10-21 15:29:00 | v1.6.43 - 🧠 **思考を Web 版と同じ低 / 中 / 高の 3 段階に**：4 つのプロトコルすべてで選べ、**既定は `low`**（パネル「設定 → 思考」で保存すると即反映。実測で 1 リクエストあたり平均約 5 秒遅くなるため、速度最優先なら「オフ」に）。思考を求めていないクライアントのために既定で有効にした思考は生成にのみ使い、返しません。⚡ **Claude Code が毎回最も深いレベルで動かなくなりました**（毎回 `adaptive` + `effort: high` を送り、前版はこれを high に固定していました）。今後は既定レベルに従い、`/effort low|medium|xhigh|max` も効くようになりました。`reasoning_effort: none` は思考なし。🤖 **公開モデルを 4 つに整理**：`gemini-pro` / `gemini-flash` / `gemini-flash-lite` / `gemini-argon` が Web 版の 3.1 Pro / 3.8 Flash / 3.5 Flash-Lite / 4 Argon に自動対応。`gemini-flash-thinking` は廃止（旧名は引き続き利用可）。🔌 「API 管理」のサードパーティ転送を修正（厳密な上流の deepseek / glm / kimi などがすべて 400 で、クォータ不足と誤表示されていました）。🧪 モデルテストはレベル選択に |
| 2026-10-21 04:30:00 | v1.6.42 - 🤖 **4 Argon に対応し、モデル探索をアカウント駆動に**：アカウントのハートビートは元々実際に利用可能なモデル一覧を返していましたが、ハードコード表にない項目はログすら残さず破棄していました（これが Argon を使えなかった理由）。今後は自動採用され、Google の世代交代のたびにコード修正を待つ必要がありません。公開モデル名の契約は不変、採用時は検証付きで不正な項目は引き続き破棄しつつログに記録します。💵 **アクセスキーごとのトークン使用量と USD 概算**（集計のみ・制限には使いません。UI に「概算」と明示：本サービスは Web 版経由で費用は発生せず、トークン数も文字数ベースの近似です）。📄 **Canvas の本文が丸ごと消える問題を修正**（従来は開けないプレースホルダ URL だけが返っていました）。🧼 `<ctrl94>thought` の思考漏れなど制御マーカーを除去。🧠 **Anthropic プロトコルに思考チェーンを配線**（Claude Code が送る thinking パラメータは従来黙って捨てられ、同プロトコルの利用者は常に「思考なし」でした） |
| 2026-10-21 00:58:00 | v1.6.41 - 🔑 **配布可能なアクセスキー**を追加：パネルから複数の key を発行し、個別に有効/無効・有効期限・**遅延アクティベーション**（渡した時点ではなく相手の初回使用から計時）・リクエスト上限・アカウント紐付け・モデル制限を設定可能。`.env` の API_KEY は引き続き全権限で、アクセスキーは `/admin` に到達できません。⚠️ `REFRESH_INTERVAL` の既定値 5→30 分（下限 10）：cookie ローテーションループは従来**起動に失敗した時しか動かず**、正常起動したゲートウェイは一度もローテーションせず数時間でアカウントが死んでいました（issue #11）。Gemini が **HTTP 200** で返す拒否ブロックを認識（セッション期限切れ／レート制限／コンテキスト超過／CAPTCHA が「空の返信」として飲み込まれ、不健全フラグも自動復旧も発火しなかった）。非ストリーミングのタイムアウトをモデル系統別に階層化し、タイムアウト時の 3 回リトライを廃止（従来は 60 秒で強制切断＋リトライ＝失敗まで 183 秒）。思考レベルが常に最高段ではなくなりました。添付ファイル付きでも本物のストリーミングに復帰 |
| 2026-09-12 10:15:00 | v1.6.40 - 🔍 モデルテストページが実際のエラーを「応答内容なし」と表示していた問題を修正（issue #11 追加分）：ストリーミング中の失敗はストリーム内 error フレームでしか表現できないが、フロントがそのキーを見ていなかったため 503/529/500/400 が全て同じ見た目に。実際の理由とステータスコードを表示し、既に出力済みの内容も消えません。アカウントカードに実際の健全性情報（`is_healthy`／連続失敗数／最終成功時刻／秘匿化した直近エラー）を追加 —— 緑の ACTIVE バッジはプールの status 列挙であってクライアントの健全フラグではないため、cookie が死んだアカウントも緑のままでした。空応答を成功として黙って飲み込まなくなりました（連続 3 回で初めてエラー計上、単発では降格しません）。起動時に cookie ローテーションループが起動したかをログに明記 |
| 2026-09-01 16:20:00 | v1.6.39 - ⚙️ `LOG_BODIES_ENABLED` を管理パネルの新しい「ログ」グループに追加。クリックで即時反映、設定変更も再起動も不要（既定はオフのまま）；⚠️ 動作変更：パネルで保存した設定は `data/settings-overrides.json` に永続化され、**環境変数より優先**されます（従来はパネルで変更しても再起動で元に戻っていました）；小数フィールドが `parseInt` で切り捨てられる問題を修正、NaN/±Infinity を拒否、書き込み失敗時は 3 層（メモリ／上書きファイル／.env）を一括ロールバック；生のフィールド名や中国語がそのまま出ていたラベルを整備し、ガードテストを追加 |
| 2026-09-01 13:10:00 | v1.6.38 - 🍪 同名 Cookie が複数ドメインに並存する問題（Google が .com.hk 等の国別ドメインへリダイレクトした場合）でセッショントークン取得が丸ごと失敗し、アカウントが誤って unhealthy とされる不具合を修正（issue #10 追加分。issue #11 のスタックの実際の誘因の一つでもあります）。ツール呼び出し JSON が不正な場合に自動で 1 回だけ再生成（再試行中もストリームのキープアライブあり）。リクエスト/レスポンス全文ログ `LOG_BODIES_ENABLED` を追加（既定オフ・メモリのみでディスク非保存・リクエストヘッダーは記録しない） |

---

## 🌟 主な機能

> 📖 詳細な使用ガイド：[USAGE.md](USAGE.md)

### 🔌 トリプルプロトコル互換性

- 単一サービスで OpenAI、Claude、Gemini SDK 形式を同時に提供
- SSE ストリーミング（OpenAI / Claude）+ Chunked JSON（Gemini）
- 関数呼び出しは 3 つの形式すべてでサポート
- Deep Research マルチステップ研究機能
- **思考レベル**：`low` / `medium` / `high` の 3 段階が Web 版の低 / 中 / 高に対応。クライアントがレベルを指定しない場合の既定は `low`（`off` にすると最速）、クライアントが思考を一切要求していない場合に既定レベルで有効にした思考は返しません。詳しくは [🧠 モデルと思考レベル](#-モデルと思考レベル)
- **添付ファイル付きでも本物のストリーミング**：画像やファイルを含むリクエストが、生成完了まで待たずに最初のトークンを返すようになりました（ツール呼び出しを含むリクエストは引き続き buffered —— ツール引数は完全な JSON でなければ解析できないため）

### 🧠 モデルと思考レベル

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

### 🔐 セキュリティと認証

- 自動生成 API キー（`sk-` プレフィックス + 32 ランダム文字）
- `Authorization: Bearer` と `x-api-key` の両方の認証方式をサポート
- 初回デプロイ時に自動生成、ユーザーがカスタマイズ可能
- **アクセスキー**：管理者が配布用の受信キーを任意の本数だけ発行できます。キーごとに有効期限（「初回利用から数え始める」遅延アクティベーション対応）、リクエスト上限、バインドするアカウント、許可するモデルを個別に設定でき、いつでも無効化・削除できます
- `.env` の `API_KEY` は常に全権限を保持し、アクセスキーは**追加**の層にすぎません。またアクセスキーは業務 API のみを呼び出せ、`/admin/*` には到達できません（詳細は下記 [🔑 アクセスキー](#-アクセスキー)）

### 🔄 マルチアカウント負荷分散と Cookie 自己修復

- **マルチアカウント負荷分散**：ラウンドロビンと最小使用の 2 つの戦略をサポート
- アカウントごとの独立した並行制御により、単一アカウントの過負荷を防止
- 連続失敗時に自動的に不健康とマーク、故障アカウントを自動スキップ
- バックグラウンド Cookie ローテーション、シームレスな更新
- ホットアップデート Cookie API、コンテナ再起動不要
- API 経由での動的なアカウント追加/削除
- Web パネル用のヘルスチェック履歴
- **Cookie ローテーションループが起動時から常駐**：以前は「起動時にトークンを取得できなかった」場合のみローテーションループが立ち上がっていたため、正常に起動したゲートウェイは一度もローテーションせず、Cookie は数時間で死んでいました（[issue #11](https://github.com/xwteam/gemini2api/issues/11)）。現在は無条件で常駐します
- **2 つの保持方式を自動で区別**：ブラウザ拡張機能が Cookie を送ってきたアカウントは自動的にブラウザ保持になり、サーバーはローテーションしません（双方がそれぞれローテーションすると互いにセッションを追い出し合うため）。Google セッションがログインページへリダイレクトされたアカウントは `expired` として報告され、拡張機能がすぐに救済できます
- **HTTP 200 内の拒否ブロックを認識**：Gemini は 200 レスポンスの本文に拒否ブロック（レート制限／セッション期限切れ／コンテキスト超過／CAPTCHA）を返すことがあります。従来はこれが「空の応答」として現れ、自己修復も一切作動しませんでしたが、現在は明示的なエラーに変換してクールダウン + アカウント切り替えのリトライに乗ります。`BARD_ERROR_CODES` で個別のコードに意味を割り当てられます
- **マルチターンの `conversation_id` は同じアカウントで続行**：`/v1/chat/completions` で `conversation_id` を付けた会話は、2 ターン目以降も前のターンに応答したアカウントに固定され、完全な続行メタデータ（`[cid, rid, rcid]`）を付けて上流 Gemini の同じ会話を続けます（送るのは最新のユーザーメッセージだけ）。以前は保存していた続行パラメータの形式が誤っていてアカウントも記録していなかったため、実際には毎ターン新しい会話になっていました。ストリーミングリクエストも、クライアントが自分で `conversation_id` を付ければ同じように続行します。そのアカウントが使えない（期限切れ／削除済み／アクセスキーのバインドするアカウント外／満杯）、保存したメタデータが使えない、前のターンを第三者フォールバックが回答した、または新しいターンがユーザーメッセージ 1 件だけではない（ツール結果を含むなど）場合は、自動で全履歴を送り直して新しい会話を始めます —— 最後の一文だけを送って黙ってコンテキストを失うことはありません。Gem モデルでは Gem にバインドされたアカウントが優先されます

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
- **アクセスキー**：配布用の受信キーを発行／編集／無効化／削除でき、状態・使用量・適用範囲が一覧にそのまま表示されます（下の「API キー管理」とは無関係です。あちらは第三者への**送信**キーを管理します）
- **API キー管理**：第三者モデル API キー集中管理（OpenAI/Anthropic/Gemini/OpenRouter/カスタム）、インポート/エクスポート対応
- Playground：オンライン API テスト
- リアルタイムログ：構造化テーブル表示、方向フィルター、テキスト検索、ページネーション（15 件/ページ）、JSON 詳細パネル、ディスク永続化（再起動後も保持）
- ダーク/ライトテーマ切り替え、レスポンシブモバイル対応

### 🔀 統一転送エンジン

- Gemini Web の利用可能リストにないモデルのリクエストを自動的に API キープールから対応 Provider に転送
- OpenAI 互換形式を直接転送（ストリーミング含む）、Anthropic 形式は双方向変換
- `/openai/v1/models` は Gemini Web モデル + API キープール内の第三者モデルを自動集約
- 単一インターフェース、単一キーですべての主要モデルを呼び出し
- 第三者自動フォールバック（`FALLBACK_ENABLED`、デフォルト無効）：任意の Gemini モデルがエラー（生成タイムアウトを含む）/ 空レスポンスを返した場合、API キープール内の第三者モデルに自動で切り替えてネイティブにリトライ、クライアントは無感知で引き続き単一のモデル名のみ使用；デフォルトではプール内のすべての「チャットに適した」第三者を自動選択（image/video など非チャットモデルを除外）してランダムにローテーション、失敗したら次へ切り替え、`FALLBACK_MODELS` で正確に指定することも可能

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

gemini2api には Cookie 自動ローテーション機能が組み込まれています：デフォルトで 30 分ごと（`REFRESH_INTERVAL`、下限は 10 分で固定）に Google RotateCookies API で `__Secure-1PSIDTS` を更新、batchexecute ハートビートでブラウザアクティビティをシミュレート、セッション寿命を延長。

> [!IMPORTANT]
> **`REFRESH_INTERVAL` のデフォルトは 5 分から 30 分に変更され、コード側で 10 分の下限が強制されます**（それより小さい値は 10 に引き上げられ、起動ログに該当項目が出ます）。
> 理由：従来、ローテーションループは**「起動時にトークンを取得できなかった」場合にのみ立ち上がっていました**。つまり正常に起動したゲートウェイは一度もローテーションせず、Cookie は数時間で死んでいました（[issue #11](https://github.com/xwteam/gemini2api/issues/11)）。常駐させた今、同じ間隔のままでは Google へのバックグラウンドリクエスト量が約 3.5 倍に増えるため、間隔もそれに応じて広げる必要があります —— 頻繁すぎるローテーションは Google から見れば自動化そのもので、リスク判定に引っかかってかえってセッションを殺します。

Cookie を手動更新するには、Web パネルの「アカウント管理」→「Cookie 更新」を使用、サービス再起動不要。

> [!NOTE]
> Cookie 寿命は Google のリスク管理ポリシーに影響されます。データセンター IP は通常数時間持続。Cookie が頻繁に失効する場合、住宅 IP の使用またはアカウント数を増やしてローテーションを検討してください。

#### 2 つの保持方式：サーバー側ローテーション / ブラウザ拡張機能からの送信

同じ Google セッションを**ローテーションできるのは一方だけ**です。ブラウザとサーバーがそれぞれ RotateCookies を呼ぶと、後から呼んだ側は相手がすでに差し替えた古い `__Secure-1PSIDTS` で更新しようとして 401 になり、セッションごとログアウトされます（「よく切断されて再ログインが必要」という症状）。そのため各アカウントは次のどちらか一方を使います：

- **サーバー側ローテーション**（デフォルト）：本サービスが `REFRESH_INTERVAL` ごとに RotateCookies を呼びます。新しく追加したアカウント、パネルの「Cookie 更新」、スクリプト / curl で送った Cookie はこの方式です。
- **ブラウザ保持**：付属のブラウザ拡張機能 [**gemini2api-plugin**](https://github.com/xwteam/gemini2api-plugin) をローカルのブラウザ（住宅 IP）に入れると、ブラウザがセッションを維持し、拡張機能が新しい Cookie を本サービスへ送ります。**拡張機能からの送信に成功したアカウントは自動的にブラウザ保持へ切り替わり、以後サーバーはローテーションしません**（リクエストヘッダー `X-Gemini2API-Keepalive` で識別。このヘッダーを送らない旧版の拡張機能は、リクエストに付く `Origin: chrome-extension://…` で識別）。

補足：

- パネルのアカウントカードでは、ブラウザ保持のアカウントに「ブラウザ保持」タグが表示されます。`GET /admin/status` の各アカウントには `keepalive_mode`（`server` / `browser`）が付きます。
- サーバー側ローテーションに戻したい場合（例：シークレットウィンドウで取得した Cookie に切り替えた —— ウィンドウを閉じると誰もローテーションしません）、パネルの「Cookie 更新」でもう一度送信してください。
- ブラウザ保持のアカウントはそのブラウザに依存します。ブラウザを長く開かないと Cookie が期限切れになり、アカウントは `expired` になります。
- 記録は `data/keepalive-modes.json` に保存されます。キーは PSID の SHA-256 の先頭 16 桁（`data/cookies/` のファイル名と同じ方式）で、Cookie の値は一切含みません。記録は PSID に紐づきます。再ログインで PSID が変わると古い記録は使われなくなり、新しい PSID は送ってきた側に応じて記録されます。拡張機能から送られた場合はブラウザ保持のまま、パネル / スクリプトから送られた場合や、パネルの「アカウント追加」で追加した場合（削除したアカウントを同じ Cookie で追加し直した場合を含む）はサーバー側ローテーションです。
- リポジトリ付属の Playwright 更新サイドカー（`docker compose --profile refresher`）もそれ自体がブラウザで、同じヘッダーを付けて送信するため、送信したアカウントは同様にブラウザ保持として記録されます。
- **拡張機能ではアカウント ID をバインドしてください**（サイドバー上部の「このブラウザが担当するアカウント ID」）。バインドしていないと、拡張機能 v1.2.3 は `/admin/status` に `expired` のアカウントが 1 つでもあれば、ポーリングのたびに（デフォルト 60 秒）まずブラウザの Gemini タブを再読み込みし、そのあとで PSID によるアカウントのマッチングを行います。このブラウザのものではないアカウントが失効している間は、使用中の Gemini ページが繰り返し再読み込みされ、入力中の内容が失われることがあります。「セッションがログインページへリダイレクトされた」場合も `expired` になったため、以前より起こりやすくなっています。ブラウザ自体がログアウトしている場合も同様に毎回再読み込みされるので、ブラウザで再ログインしてください。

> [!NOTE]
> アカウント状態 `expired` には「**Google セッションがログインページへリダイレクトされた**」（Cookie 失効）場合も含まれるようになりました。以前はこの状態でも `active` と表示され、`is_healthy` が `false` になるだけだったため、ブラウザ拡張機能は気付かず救済もしませんでした。セッションがログインページへリダイレクトされ、かつその Cookie の RotateCookies に Google が 401 を返した後は、サーバー（ローテーションループも自己修復も同じ）は同じ Cookie で無駄な RotateCookies を呼ばず、セッションの確認だけを続けます（一時的な障害なら自然に復旧します）。ログインページへリダイレクトされただけで Google にまだ拒否されていないセッションは、引き続きローテーションします（PSIDTS が期限切れのセッションは 1 回のローテーションで復旧することが多いため）。拡張機能またはパネルから新しい Cookie が届くと、アカウントはすぐに `active` に戻ります（「チェック」を押す必要はありません）。

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
| POST | `/responses` | OpenAI Responses API（テキスト／ストリーミング／ツール呼び出し。Codex CLI など新しいクライアントが使用） |

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

> 完全な管理エンドポイント（リクエスト/レスポンス例付き）は [API.md](API.md) を参照。下表は完全な一覧です。

| メソッド | エンドポイント | 機能 |
|---------|--------------|------|
| GET | `/status` | サービスステータス（アカウントプール概要 + ローテーション戦略） |
| GET | `/system-info` | システム情報（バージョン/Python/OS/メモリ/CPU/PID/実行モード） |
| GET | `/accounts` | すべてのアカウントリストとステータス |
| POST | `/accounts` | 新しいアカウントを動的追加 |
| DELETE | `/accounts/{id}` | アカウントを削除 |
| GET | `/accounts/{id}/check` | 単一アカウントステータスをチェック |
| GET | `/check-account` | すべてのアカウントステータスをチェック |
| POST | `/reload-cookies` | ホットアップデート Cookie（コンテナ再起動不要） |
| PUT | `/accounts/{id}/cookies` | 指定アカウントの Cookie を更新 |
| GET | `/health-history` | 直近のヘルスチェック記録 |
| GET | `/usage-stats/summary` | 使用統計の概要 |
| GET | `/usage-stats/history` | 履歴トレンドデータ |
| GET | `/settings` | 編集可能な現在の設定を取得（グループ別） |
| POST | `/settings` | 設定を一括更新（メモリのホットアップデート + `data/settings-overrides.json` へ書き込み、`.env` にも書き込み） |
| GET | `/api-keys` | API Key 一覧（キーはマスク表示） |
| GET | `/api-keys/catalog` | Provider カタログ（内蔵モデル一覧） |
| POST | `/api-keys` | API Key を追加 |
| DELETE | `/api-keys/{id}` | API Key を削除 |
| PATCH | `/api-keys/{id}/status` | Key の状態を切り替え（有効/無効） |
| PATCH | `/api-keys/{id}/label` | Key のラベルを変更 |
| POST | `/api-keys/import` | Key を一括インポート |
| GET | `/api-keys/export` | すべての Key をエクスポート（デフォルトはマスク、`?reveal=true` で平文取得） |
| POST | `/api-keys/batch-delete` | 一括削除 |
| POST | `/api-keys/models` | 指定 Provider/base_url で利用可能なモデル一覧を探索 |
| GET | `/verify` | API Key の有効性を検証（ログイン用） |
| POST | `/restart` | サービス再起動（パネル右上のワンクリック再起動） |
| GET | `/check-update` | 新バージョンの有無を確認 |
| POST | `/update` | 最新バージョンへの更新をトリガー |
| GET | `/logs` | 構造化ログのページング照会 |
| GET | `/logs/state` | ログ記録状態 |
| POST | `/logs/state` | ログ記録状態を更新 |
| POST | `/logs/clear` | ログをクリア |
| GET | `/logs/{id}` | 単一ログの詳細 |
| GET | `/model-mapping` | すべてのモデルマッピングを取得 |
| POST | `/model-mapping` | モデルマッピングを追加/更新 |
| DELETE | `/model-mapping/{alias}` | モデルマッピングを削除 |
| GET | `/web-chats` | アカウントが Gemini ウェブ側に蓄積したセッションを一覧（読み取り専用） |
| POST | `/cleanup-web-chats` | 期限超過のウェブセッションのクリーンアップを手動トリガー（バックグラウンドで非同期実行） |

> アクセスキーの 6 つの `/admin/access-keys` エンドポイントは下記 [🔑 アクセスキー](#-アクセスキー) に記載しています。

---

## 🔑 アクセスキー

`.env` にある全権限の `API_KEY` とは別に、管理者は**配布用**のアクセスキーを何本でも発行できます。キーごとに有効期限・リクエスト上限・使用できるアカウント・許可するモデルを個別に設定し、相手ごとに配り、いつでも個別に無効化・削除できます。パネルには管理用の「アクセスキー」ページが追加され、バックエンドは `/admin/access-keys` 系のエンドポイントに対応します。

キーは `data/access_keys.json`（`data/` は docker-compose の永続化 bind mount）に保存されるため、再起動しても失われません。

### キーごとに設定できる項目

| 項目 | 説明 |
|------|------|
| `name` | ラベル。誰に渡したキーかを覚えておくためのもの（空の場合は `key-{id}` と表示） |
| `enabled` | 有効／無効スイッチ。無効化すると保持者は即座に 401 になりますが、キーは一覧に残り、いつでも復帰できます |
| `expires_at` | 絶対有効期限（ISO8601）。その時刻で失効します |
| `duration_days` | 有効日数。**遅延アクティベーション**：配っただけでは計時が始まらず、保持者の最初のリクエストから N 日を数え始めます |
| `request_limit` | リクエスト上限。累計が到達した時点で失効します（「使用量をリセット」でゼロに戻せば再利用可能） |
| `bound_account_ids` | バインドするアカウント。指定した Gemini アカウントのみ使用可（空 = 制限なし） |
| `allowed_models` | 許可するモデル。指定したモデル名のみ呼び出し可（空 = 制限なし） |

`expires_at` と `duration_days` はどちらか一方のみ。両方空にすると無期限のキーになります。

### キーの状態

| 状態 | 意味 |
|------|------|
| 有効 | 通常どおり呼び出せます |
| 無効 | 管理者が `enabled` をオフにした状態 |
| 未アクティブ | `duration_days` は設定済みだが未使用で、まだ計時が始まっていない |
| 期限切れ | `expires_at` を過ぎた |
| 上限到達 | `request_count` が `request_limit` に到達した |

判定は「無効 → 期限切れ → 上限到達 → 未アクティブ → 有効」の優先順位で短絡的に行われます。

### エンドポイント

| メソッド | エンドポイント | 機能 |
|------|------|------|
| GET | `/admin/access-keys` | すべてのアクセスキーを一覧（状態・使用量・適用範囲を含む） |
| GET | `/admin/access-keys/options` | パネル発行フォームの選択肢（アカウントプール内のアカウント + 外部に見えるモデル名） |
| POST | `/admin/access-keys` | キーを発行。`count` で一括発行（上限 50） |
| PATCH | `/admin/access-keys/{id}` | 設定を変更（項目を空にするには `clear` 配列を使用、下記参照） |
| DELETE | `/admin/access-keys/{id}` | キーを削除 |
| POST | `/admin/access-keys/{id}/reset-usage` | リクエストカウントをリセット |

```bash
# 1 本発行：初回利用から 7 日間有効、最大 500 リクエスト、flash のみ許可
curl -X POST http://localhost:5918/admin/access-keys \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-あなたのAPIキー" \
  -d '{"name":"山田","duration_days":7,"request_limit":500,"allowed_models":["gemini-flash"]}'

# 同じ設定のキーを 20 本一括発行（名称は trial-1 … trial-20 と自動連番）
curl -X POST http://localhost:5918/admin/access-keys \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-あなたのAPIキー" \
  -d '{"name":"trial","count":20,"duration_days":3}'

# すべてのキーを一覧
curl http://localhost:5918/admin/access-keys \
  -H "Authorization: Bearer sk-あなたのAPIキー"

# 3 番目のキーを無効化
curl -X PATCH http://localhost:5918/admin/access-keys/3 \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-あなたのAPIキー" \
  -d '{"enabled":false}'

# 3 番目のキーのリクエスト上限とモデル制限を解除：JSON の null は「変更しない」を意味するため、
# 項目を空にするには項目名を clear 配列に入れる必要があります
curl -X PATCH http://localhost:5918/admin/access-keys/3 \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-あなたのAPIキー" \
  -d '{"clear":["request_limit","allowed_models"]}'

# 使用量カウントをリセット
curl -X POST http://localhost:5918/admin/access-keys/3/reset-usage \
  -H "Authorization: Bearer sk-あなたのAPIキー"
```

### ⚠ 押さえておくべき 3 つの境界

> [!IMPORTANT]
> **1. `.env` の `API_KEY` は引き続き全権限を持ちます。** アクセスキーは**追加**の層であり、置き換えではありません：`API_KEY` に一致したリクエストはその場で通過し、キーストアを参照せず、使用量も一切カウントしません。**アクセスキーを 1 本も発行していない場合、認証の挙動は従来版と完全に同一です。**
>
> **2. アクセスキーは業務 API のみを呼び出せ、`/admin/*` には絶対に到達できません。** 管理面は従来どおり `API_KEY` / `ADMIN_API_KEY` のみが守っています。だからこそ外部の人にアクセスキーを渡しても安全です —— アカウントの Cookie は読めず、設定も変更できず、他人のキーも見えません。
>
> **3. 業務リクエストは `GET /v1/models` も含めてすべて +1 されます。** カウントは認証入口でアトミックに加算され、単調増加で払い戻しはありません（上流がエラーでもカウントされます）。クライアントによっては対話のたびにモデル一覧を取得するため、**1 ラウンドで 2 回消費**します —— `request_limit` を設定する際は余裕を持たせてください。

---

## ⚙ 設定

> [!IMPORTANT]
> **パネルで変更した設定項目は環境変数より優先されます。** Web パネルの「設定」
> ページで保存した項目は `data/settings-overrides.json`（`data/` は docker-compose の
> 永続 bind mount）に書き込まれ、起動のたびに再適用されて下表の環境変数を**上書き**
> します。これは意図的な挙動です。パネルで `LOG_BODIES_ENABLED` をオフにしたあと、
> `docker compose restart` でオンに戻ってはいけないからです。
>
> つまり **`.env` を編集して再起動しても反映されない** 場合、その項目はパネルの設定に
> 上書きされている可能性が高いです。起動ログに
> `Applied N panel setting override(s) from data/settings-overrides.json: ...`
> という行が出て対象項目を示します。`data/settings-overrides.json` を削除すれば
> 環境変数に制御が戻ります。

| 変数 | 必須 | デフォルト | 説明 |
|------|------|----------|------|
| `GEMINI_PSID` | ✅ | — | ブラウザ `__Secure-1PSID` |
| `GEMINI_PSIDTS` | ✅ | — | ブラウザ `__Secure-1PSIDTS` |
| `API_KEY` | ❌ | 自動生成 | API アクセスキー（`sk-` プレフィックス、空の場合は初回起動時に自動生成） |
| `REFRESH_INTERVAL` | ❌ | `30` | Cookie 更新間隔（分、最小 10） |
| `MAX_RETRIES` | ❌ | `3` | 失敗時の再試行回数（指数バックオフ） |
| `PORT` | ❌ | `5918` | サービスポート |
| `LOG_LEVEL` | ❌ | `info` | ログレベル（debug/info/warning/error） |
| `RATE_LIMIT_ENABLED` | ❌ | `false` | レート制限を有効化 |
| `RATE_LIMIT_WINDOW` | ❌ | `60` | レート制限ウィンドウ（秒） |
| `RATE_LIMIT_MAX` | ❌ | `10` | ウィンドウ内の最大リクエスト数 |
| `HEALTH_CHECK_ENABLED` | ❌ | `true` | スケジュール済みアカウントヘルスチェックを有効化 |
| `HEALTH_CHECK_INTERVAL` | ❌ | `5` | チェック間隔（分） |
| `ACCOUNTS_FILE` | ❌ | `accounts.json` | マルチアカウント設定ファイルのパス（存在しない場合は環境変数の単一アカウントモードを使用） |
| `ROTATION_STRATEGY` | ❌ | `round-robin` | ローテーション戦略：`round-robin`（ラウンドロビン）/ `failover`（フェイルオーバー） |
| `MAX_CONCURRENT_PER_ACCOUNT` | ❌ | `8` | アカウントあたりの最大並行リクエスト数 |
| `ACQUIRE_TIMEOUT` | ❌ | `60.0` | 並行満載時に空きスロットを待つ上限（秒）。待ちきれない場合のみエラー |
| `SAME_ACCOUNT_5XX_RETRIES` | ❌ | `1` | 5xx 時の同一アカウント高速リトライ回数（長い backoff なし）、なお失敗すれば failover で別アカウントへ |
| `FAILOVER_COOLDOWN` | ❌ | `30.0` | 5xx で制限されたアカウントがクールダウンに入る時間（秒）、その間は優先選択しない |
| `FINGERPRINT_CONFIG_PATH` | ❌ | `data/fingerprint.json` | フィンガープリント設定ファイルのパス |
| `VERSION_SYNC_ENABLED` | ❌ | `true` | Chrome バージョン自動同期を有効化 |
| `VERSION_SYNC_INTERVAL` | ❌ | `24` | バージョン同期間隔（時間） |
| `JITTER_ENABLED` | ❌ | `true` | リクエスト時間ジッターを有効化（人間の挙動をシミュレート） |
| `USAGE_STATS_ENABLED` | ❌ | `true` | 使用統計を有効化（時系列スナップショット + 永続化） |
| `USAGE_STATS_INTERVAL` | ❌ | `300` | スナップショット採集間隔（秒） |
| `USAGE_STATS_RETENTION_DAYS` | ❌ | `30` | 履歴データの保持日数 |
| `MODEL_WHITELIST` | ❌ | — | モデルホワイトリスト（カンマ区切り、空の場合はフィルタしない；非空時は各 `/models` 一覧をフィルタ） |
| `CHAT_CLEANUP_ENABLED` | ❌ | `true` | Gemini ウェブ側セッションの自動クリーンアップを有効化 |
| `CHAT_CLEANUP_KEEP_HOURS` | ❌ | `24.0` | ウェブセッションの保持時間（時間）、超過分をクリーンアップ |
| `CHAT_CLEANUP_INTERVAL_HOURS` | ❌ | `6.0` | 自動クリーンアップタスクの実行間隔（時間） |
| `CHAT_CLEANUP_SKIP_PINNED` | ❌ | `true` | クリーンアップ時にピン留めセッションをスキップ |
| `ADMIN_API_KEY` | ❌ | — | 管理パネル/`/admin` 専用認証キー（空の場合は `API_KEY` にフォールバック） |
| `CORS_ALLOW_ORIGINS` | ❌ | `*` | CORS 許可オリジン（カンマ区切り、`*` ですべて許可） |
| `CORS_ALLOW_CREDENTIALS` | ❌ | `true` | CORS で資格情報の送信を許可するか |
| `IMAGE_DOWNLOAD_SIZE_SUFFIX` | ❌ | `=s2048` | 生図代理ダウンロードのサイズサフィックス（`=s0` でフル解像度の原画像） |
| `IMAGE_DOWNLOAD_TIMEOUT` | ❌ | `25.0` | 画像ダウンロード 1 回あたりの HTTP タイムアウト（秒） |
| `FALLBACK_ENABLED` | ❌ | `false` | Gemini → 第三者フォールバックを有効化：任意の Gemini モデル（flash/pro/thinking）がエラーまたは空レスポンスを返した場合、API キープール内の第三者モデルに自動で切り替えて「ネイティブにリトライ」 |
| `FALLBACK_MODELS` | ❌ | — | フォールバックモデル（カンマ区切り、順に試行）；空の場合はプール内のすべての「チャットに適した」第三者を自動選択（名前で image/video/audio/embedding などの非チャットモデルを除外）してランダムにローテーション、1 つが失敗（エラー/空）したら次へ切り替え |
| `DEFAULT_THINKING_LEVEL` | ❌ | `low` | クライアントがレベルを指定しないときのレベル：`off` / `low` / `medium` / `high`。`low` は実測で 1 リクエストあたり平均約 5 秒遅く、`off` が最速。パネルの「設定 → 思考」で即時切り替え可。クライアントが思考を一切要求していない場合、既定レベルで有効にした思考はクライアントに返しません |
| `EXTENDED_THINKING_ENABLED` | ❌ | `true` | 思考のマスタースイッチ（上級者向け・互換用）：`false` = 4 つのプロトコルすべてで思考しない。クライアントが明示的に要求しても無視 |
| `THIRDPARTY_FAILOVER_COOLDOWN` | ❌ | `180` | 同名の複数サードパーティ間フェイルオーバー時の、失敗した提供元のクールダウン秒数（0 で無効） |
| `BARD_ERROR_CODES` | ❌ | — | Gemini が **HTTP 200** の本文で返す拒否ブロックの code→意味の対照表。`1152=rate_limit,404=session_expired` の形式で、分類は `rate_limit` / `session_expired` / `context_too_long` / `captcha`。**空の場合はすべての拒否ブロックを不明として扱います（該当アカウントをクールダウン + 別アカウントでリトライ）。これは意図した安全なフォールバックです**。設定すると分類ごとの専用処理が有効になります（セッション期限切れは Cookie 自己修復をトリガー、コンテキスト超過は 400 を返してリトライしない、CAPTCHA は該当アカウントを解放） |
| `GEMINI_FAILURE_REPLIES` | ❌ | — | Google が回答の代わりに返す「失敗の定型文」を追加（`\|` 区切り。組み込みの `I seem to be encountering an error. Can I try something else for you?` は常に有効）。回答全体がちょうどそのいずれかなら上流の失敗として扱い（アカウント切り替え / フォールバック / 502）、通常の回答としては返しません。注意事項 8 を参照 |
| `GENERATE_TIMEOUTS` | ❌ | — | 生成タイムアウトをモデルファミリー単位で上書き。`pro=300,flash=120` の形式。空の場合は組み込みの段階設定（flash-lite 60 / flash 120 / pro 300 / argon 300、認識できないファミリーは 60 にフォールバック）。非ストリーミングはこの予算でリクエスト全体を打ち切り、ストリーミングは「最初の進展」と「次の進展までの間隔」をこの予算以内に制限します（Google のハートビートフレームは数えません） |
| `GENERATE_TIMEOUT_IMAGE` | ❌ | `180` | 画像生成と推定されるリクエストの生成タイムアウト（秒）。モデルファミリーの値と比べて**大きい方**を採用し、ストリーミングと非ストリーミングで共通です |
| `MODEL_BREAKER_ENABLED` | ❌ | `true` | モデル障害ブレーカーのマスタースイッチ（注意事項 7 を参照）。`false` でも状態は記録しますが、Google を迂回することはありません |
| `MODEL_BREAKER_THRESHOLD` | ❌ | `2` | ウィンドウ内でこの数の**異なるリクエスト**が同じモデルファミリーで障害の疑いがある失敗をしたらブレーカーを開きます（同じリクエストのアカウント切り替え・再試行・クライアントの再送は 1 件として数えます） |
| `MODEL_BREAKER_WINDOW` | ❌ | `300` | カウントのウィンドウ（秒）：失敗した試行の開始が、直近に数えた失敗からこれ以上離れていれば、カウントを 1 からやり直します |
| `MODEL_BREAKER_COOLDOWN` | ❌ | `60` | ブレーカーが開いている期間（秒）。その間、フォールバックのある `/v1/chat/completions` リクエストは直接フォールバックへ回します |
| `MODEL_BREAKER_MAX_COOLDOWN` | ❌ | `300` | Google の試行がまた失敗したときに開放期間を倍にする上限（秒）。`MODEL_BREAKER_COOLDOWN` 未満にはなりません |
| `TOKEN_PRICES` | ❌ | — | アクセスキー使用量の**概算 USD** 用の価格表。例：`gemini-pro=2.0/12.0,gemini-flash=0.75/3.75`（公開モデル名=入力価格/出力価格、単位 USD／100 万トークン）。空なら内蔵の既定値を使用。書式が不正な項目は黙って無視し、価格のないモデルはパネルで `—` と表示されます。**統計専用で制限判定には一切使われません**。また請求額ではありません（本サービスは Gemini Web を使うため、それ自体に費用は発生しません） |

---

## ⚠ 重要な注意事項

1. **Cookie 失効**：Google Cookie は定期的に失効します（通常数時間から数日）。サービスには自動更新機能がありますが、アカウントがログアウトされたりパスワードが変更された場合は、新しい Cookie が必要です。

2. **ストリーミング出力**：すべての API エンドポイントはデフォルトでストリーミングします。`stream: false` の場合、サービスは内部的にストリーミングデータを受け取り、収集後に完全な JSON を返します。

3. **モデル可用性**：利用可能なモデルはあなたの Google アカウント権限に依存します。無料アカウントと Gemini Advanced アカウントでは異なるモデルが表示されます。サービスは起動時に自動検出します。

4. **リクエスト頻度**：レート制限を無効化（`RATE_LIMIT_ENABLED=false`）しても、Google 側には独自の制限があります。高頻度リクエストは CAPTCHA またはテンポラリーバンをトリガーする可能性があります。リクエスト頻度を適切に制御してください。

5. **ネットワーク環境**：デプロイサーバーは `gemini.google.com` に直接アクセスできる必要があります。一部の地域ではプロキシ設定が必要な場合があります。

6. **非ストリーミングのタイムアウトと前段プロキシ**：非ストリーミング（`stream: false`）リクエストのタイムアウトはモデルファミリー単位で段階化されています —— flash-lite 60 秒、flash 120 秒、pro と argon 300 秒（`GENERATE_TIMEOUTS` で上書き可。画像生成と推定される場合は `GENERATE_TIMEOUT_IMAGE`、デフォルト 180 秒）。またタイムアウトは 3 回リトライしなくなりました。タイムアウトになると本サービスは **504**（エラータイプ `timeout_error`、各プロトコル独自の JSON エラー本文。ストリーミングではプロトコル内のエラーイベント）を返し、プレーンテキストの 500 にはなりません。`FALLBACK_ENABLED` が有効なら `/v1/chat/completions` はまず第三者フォールバックを試みます。タイムアウトは Google 側の停滞なので、アカウントの連続失敗には数えず、アカウントを `expired` にすることもありません（接続段階のタイムアウトは従来どおりまず数回再試行し、使い切った場合も同じくタイムアウトとして扱います）。この間、接続上の出力は**ゼロバイト**であることに注意してください。つまりこれはアイドルタイムアウトではなく**最初の 1 バイトまで**のタイムアウトです：**pro の非ストリーミングは最長 300 秒無音で待つことになり、一般的な前段プロキシの最初の 1 バイトの上限を超えます**（EdgeOne 無料版は 15 秒、多くのリバースプロキシはデフォルト 60 秒）。その場合クライアントが受け取るのは本サービスのエラー本文ではなくプロキシの 504 です。このようなシナリオではストリーミングリクエストを推奨します。 思考を有効にしたリクエストはさらに数秒かかります（既定の `low` は実測で 1 リクエストあたり平均約 5 秒増）。 flash-lite の 60 秒は「思考なしで数秒で返る」前提の値なので、既定レベルで思考すると長いプロンプトや難しい質問では足りない場合があります。`GENERATE_TIMEOUTS=flash-lite=120` で延ばせます（生成中のタイムアウトは思考なしで再試行されず、そのままタイムアウトとして返ります）。 **ストリーミングリクエストも同じファミリー予算に従います**：最初の進展（本文・思考・生成画像・Canvas の新しい内容）は予算内に届く必要があり（レスポンスヘッダーを待つ時間も含みます）、以降の進展どうしの間隔も予算を超えられません。Google がキューで待たせている間 60 秒ごとに送ってくる内容のないハートビートフレームは**進展に数えません**。予算を使い切るとプロトコル内の `timeout_error` イベントを返します（まだ本文を送っていなければ `/v1/chat/completions` はまず第三者フォールバックを試みます）。以前のストリーミングは「2 回のバイト受信の間」の 120 秒だけを見ていたため、Google のハートビートで毎回リセットされ、実測でクライアントが約 240 秒待たされていました。

7. **モデル障害ブレーカー**：Google 側で Gemini のあるモデルファミリー全体が障害になったとき（例：すべてのアカウントの gemini-flash がキューで止まる、または失敗の定型文を即答する）、ウィンドウ内で `MODEL_BREAKER_THRESHOLD`（デフォルト 2）件の異なるリクエストがそのファミリーで障害の疑いがある失敗（失敗の定型文、ほとんどデータを受け取れなかった生成タイムアウト、一度も進展のないストリーミングタイムアウト）をすると、ブレーカーが `MODEL_BREAKER_COOLDOWN`（デフォルト 60）秒間開きます。その間、**`FALLBACK_ENABLED` が有効でフォールバック候補がある** `/v1/chat/completions` リクエストは、予算を丸ごと待たずに直接第三者フォールバックへ回ります。期間が終わると実際のリクエスト 1 件で Google を試し、失敗すれば開放期間を倍にし（上限 `MODEL_BREAKER_MAX_COOLDOWN`）、どれか 1 件でも成功すればすぐに復帰します。フォールバックのないリクエストと Claude / Gemini ネイティブ / Responses は常に通常どおり Google を呼びます（その結果もブレーカーの状態に反映されます）。影響するのは障害中のファミリーだけで、同じアカウントのほかのファミリーは通常どおりです。状態はパネルのアカウントページ上部の表示と `/admin/status` の `model_breakers` で確認でき、プロセスを再起動するとクリアされます。

8. **Google の失敗の定型文**：障害中の Gemini は回答の代わりに、固定の `I seem to be encountering an error. Can I try something else for you?` を即答することがあります。回答全体がちょうどこの文（または `GEMINI_FAILURE_REPLIES` で追加した文）であれば上流の失敗として扱い（別のアカウントで再試行し、`/v1/chat/completions` はフォールバックを使える場合があり、それ以外は 502 `api_error`）、通常の回答として返したり会話記録に保存したりはしません。ストリーミングでは、まだこの文になり得る冒頭を一時的に保留し、違うと分かった時点ですぐに送り出します（回答の冒頭が数語ぶん遅れることがあります）。 v1.6.47 から、Gemini の「言語モデル」系の定型拒否文（例：`I'm just a language model, so I can't help you with that.`、中国語の `我只是一个语言模型，无法提供这方面的帮助。`）も組み込みで識別し、同じく別アカウント／フォールバック／502 で扱いますが、モデル単位のサーキットブレーカーには数えません（特定の質問で毎回出る本物の拒否である可能性があるため）。

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
- [x] ウェブ側蓄積セッションの自動クリーンアップ（古いセッションを定期削除、ピン留めは保持）
- [x] [issues #2](https://github.com/xwteam/gemini2api/issues/2) カスタム Gemini Gem 対応（パネルで一覧/作成/編集/削除 + モデル名として公開）
- [x] [issues #6](https://github.com/xwteam/gemini2api/issues/6) [#7](https://github.com/xwteam/gemini2api/issues/7) ネイティブ Gemini 拡張思考対応（`reasoning_effort` で有効化、思考はフレーム単位でストリーミングされ回答より先に表示 + モデルテストパネルの「思考」トグル + ワンクリックでオフ、通常チャットに影響なし）
- [x] API 管理ページの Gemini フォールバックトグル（即時オン/オフ・永続化、.env 編集・再起動不要）

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
