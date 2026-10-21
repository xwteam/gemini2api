# API 레퍼런스

Gemini2API의 모든 API 엔드포인트 상세 정보입니다.

## 인증

모든 API 요청에 인증 필수입니다. 다음 두 가지 방식 지원:

### Bearer Token (권장)

```bash
curl -H "Authorization: Bearer sk-당신의키"
```

### API Key 헤더

```bash
curl -H "x-api-key: sk-당신의키"
```

> API Key는 `.env` 파일의 `API_KEY` 값 또는 서비스 시작 로그에서 확인 가능합니다.

### 사용할 수 있는 두 가지 키

| 종류 | 출처 | 접근 범위 | 집계 |
|------|------|--------|------|
| `API_KEY`(`.env`) | 첫 시작 시 자동 생성 또는 직접 설정 | 업무 API + `/admin/*`(`ADMIN_API_KEY`를 따로 설정하지 않은 경우) | 안 함 |
| 액세스 키 | 관리자가 패널 "액세스 키" 페이지 또는 `POST /admin/access-keys`로 발급 | **업무 API만**. `/admin/*`에는 접근 불가 | 요청마다 +1 |

액세스 키는 **추가** 계층입니다: `API_KEY`는 항상 모든 권한을 가지며, 액세스 키를 하나도 발급하지 않으면 인증 동작은 이전 버전과 완전히 동일합니다. 액세스 키는 각각 유효 기간, 요청 한도, 바인딩 계정, 허용 모델을 가질 수 있습니다(자세한 내용은 `POST /admin/access-keys`).

액세스 키가 거부될 때(비활성 / 만료 / 한도 초과)의 상태 코드는 401이며, 본문의 `message`에 구체적인 사유가 담깁니다.

## 표준 베어 경로

v1.6.4부터 각 API는 두 가지 경로 형식을 지원합니다:

### 접두사 경로 (제공자별 명시)

아래 엔드포인트 문서에서 사용하는 형식입니다:

- OpenAI: `/openai/v1/chat/completions`, `/openai/v1/models`
- Claude: `/claude/v1/messages`, `/claude/v1/messages/count_tokens`
- Gemini: `/gemini/v1beta/models/{model}:generateContent`, `:streamGenerateContent`

### 표준 베어 경로 (v1.6.4 신규)

주요 SDK가 `base_url`에 접미사 없이 즉시 작동하도록 표준 경로를 노출합니다:

**OpenAI 형식**:
- `/v1/chat/completions`
- `/v1/models`

**Claude 형식**:
- `/v1/messages`
- `/v1/messages/count_tokens`

**Gemini 형식**:
- `/v1beta/models/{model}:generateContent`
- `/v1beta/models/{model}:streamGenerateContent`
- `/v1beta/models`

> [!IMPORTANT]
> 베어 `/v1/models`는 OpenAI 형식을 반환합니다(하나의 경로로 두 형식을 반환할 수 없음). Claude 형식 모델 목록이 필요하면 `/claude/v1/models`를 사용하세요.

## 🧠 모델과 사고 수준

| 공개 모델명 | 자동으로 매핑되는 웹 모델(현재 실측) | 설명 |
|------|------|------|
| `gemini-pro` | 3.1 Pro | 품질 최고, 다소 느림 |
| `gemini-flash` | 3.8 Flash | 빠름, 기본값으로 권장 |
| `gemini-flash-lite` | 3.5 Flash-Lite | 가장 가볍고 빠름. Pro/Flash가 사용량 제한에 걸렸을 때의 대안 |
| `gemini-argon` | 4 Argon | 복잡한 작업용. **계정이 실제로 Argon을 가진 경우에만 목록에 표시** |

- **매핑은 자동입니다**: 각 계정의 하트비트가 그 계정에서 지금 실제로 쓸 수 있는 웹 모델을 알려 줍니다. 공개 이름은 바뀌지 않고, 내부적으로 웹의 현재 세대에 자동으로 맞춰집니다(Google이 세대를 바꿔도 클라이언트를 고칠 필요 없음).
- **`gemini-flash-thinking`은 폐지되었습니다**: "flash + 사고 모드"라는 가짜 모델이었을 뿐이며, 이제 사고는 모든 모델이 가진 수준입니다(아래 참고). 기존 클라이언트 호환을 위해 `gemini-flash-thinking`, `gemini-2.5-flash-thinking`, `gemini-2.0-flash-thinking`과 내부 이름 `gemini-3-flash-thinking*`은 **계속 호출할 수 있습니다**(`gemini-flash`의 숨은 별칭). 다만 어떤 모델 목록에도 나타나지 않습니다. 사고 내용이 필요하면 수준 파라미터를 지정하세요. 예외: 액세스 키의 "허용 모델"에 `gemini-flash-thinking`이 포함된 경우 그 키의 모델 목록에는 계속 표시됩니다(그것만 허용한 예전 키가 빈 목록을 받지 않도록). 새로 발급하는 키에는 `gemini-flash`를 선택하세요. ⚠️ 동작 변경: 예전 클라이언트가 수준 없이 `gemini-flash-thinking`을 호출하면 v1.6.42에서는 사고 내용이 반환되었지만 이제는 반환되지 않습니다(요청하지 않은 사고는 반환하지 않음).
- **사고는 3단계**: `low` / `medium` / `high`, 웹의 낮음 / 중간 / 높음에 대응합니다(실측상 `high`가 가장 깊고 가장 느림. `low`와 `medium`의 차이는 실측에서 구분되지 않았습니다).
- **기본값 `low`**: 클라이언트가 **수준을 지정하지 않으면**(사고 파라미터를 전혀 보내지 않은 경우와, 사고는 요청했지만 몇 단계인지 밝히지 않은 경우) "기본 사고 수준"(환경 변수 `DEFAULT_THINKING_LEVEL` 또는 패널의 "설정 → 사고", 저장 즉시 적용·재시작 불필요)을 사용합니다. 출고 기본값은 `low`.
  - ⚠️ **속도 비용**: 실측상 기본 `low`는 사고하지 않을 때보다 **요청당 평균 약 5초 더 걸립니다**(flash 간단한 질문: 6.5 / 8.8초 → 8.6 / 16.6초). 속도가 가장 중요하면 기본값을 **`off`**로 설정하세요(사고 안 함·가장 빠름. 이전 버전에서 파라미터 없이 보낼 때와 업스트림 요청이 완전히 같음). 앞단 프록시에 첫 바이트 타임아웃이 있는 경우(EdgeOne 무료 15초 등) 비스트리밍 요청에 특히 주의하세요.스트리밍에도 비용이 있습니다: 사고를 요청하지 않은 요청은 기본값으로 켠 사고를 반환하지 않으므로 **본문은 사고가 끝난 뒤에 시작됩니다**(그동안 keep-alive 프레임을 보내므로 프록시가 연결을 끊지 않습니다). 추론이 필요한 질문에서 `gemini-pro`의 `low`는 실측 총 36~47초였습니다. 첫 토큰까지의 시간이 중요하면 `off`를 쓰세요. ⚠️ `off`(그리고 기본 수준 자체)는 **수준을 지정하지 않은** 요청에 적용됩니다: 사고 파라미터를 보내지 않은 요청과, 사고는 요청했지만 몇 단계인지 밝히지 않은 요청(Claude Code의 기본 설정 요청이 바로 이런 경우이므로 Claude Code도 기본 수준을 따릅니다). 클라이언트가 **수준을 명시적으로 지정한** 경우(Codex / Cursor가 low/medium/high를 고른 경우, Anthropic이 `budget_tokens`를 보낸 경우, Claude Code의 `/effort max` 등)에는 기본 수준이 적용되지 않습니다. 모든 사고를 끄려면(진짜 가장 빠름) 아래 마스터 스위치(`EXTENDED_THINKING_ENABLED=false`)를 끄세요.
  - 클라이언트가 **사고를 전혀 요청하지 않은** 경우, 기본 수준으로 켠 사고는 **생성에만 쓰이고 절대 반환되지 않습니다**: `reasoning_content` / `thinking` 블록 / 사고 part가 추가되지 않으며 사고하지 않은 응답과 필드 단위로 동일합니다(엄격한 클라이언트도 오류가 나지 않음). 사고 내용은 클라이언트가 **사고를 요청한** 경우(수준 지정 여부와 무관)에만 반환합니다(네이티브 Gemini는 여전히 `includeThoughts`만 봅니다). 기본 수준이 `off`이면 사고는 요청했지만 수준을 밝히지 않은 요청도 사고하지 않으므로 반환할 사고가 없습니다.
- **Claude Code**(최신 버전): 모든 요청에 `adaptive` + `effort: high`(high는 Claude Code의 출고 설정으로, 바꾸지 않으면 매 요청이 이 값)가 붙으므로 별도 설정 없이 여기의 기본 수준(출고 `low`, 속도 우선)을 따릅니다. 특정 세션에서 더 깊이 생각하게 하려면 Claude Code에서 `/effort max`(또는 `xhigh`)를 실행하세요 → high. `/effort low` / `medium`도 해당 수준으로 처리됩니다.
- **마스터 스위치** `EXTENDED_THINKING_ENABLED=false`: 클라이언트가 명시적으로 요청해도 항상 사고하지 않습니다. 이것이 **진짜 가장 빠른** 모드입니다. 패널의 "설정 → 사고 → '사고 허용(마스터 스위치)'"에 항상 표시되며 저장하면 즉시 적용됩니다. 기본 사고 수준과의 역할 분담: 기본 수준은 수준을 지정하지 않은 요청(Claude Code의 기본 설정 요청 포함)만, 마스터 스위치는 수준을 명시한 클라이언트까지 적용됩니다.
- 패널의 "모델 테스트" 페이지는 기존 "사고" 체크박스 대신 **수준 선택**(낮음 / 중간 / 높음, 기본 낮음)을 사용합니다. 선택한 수준은 `reasoning_effort`로 전송되고 사고 과정은 답변 위에 표시됩니다. "기본 수준(파라미터 없음)" 항목도 있습니다: `reasoning_effort`를 보내지 않아 일반 클라이언트와 같은 경로를 타므로 설정의 기본 사고 수준(`off` 포함)의 실제 속도를 측정할 수 있습니다(사고 내용은 규정대로 반환되지 않음).

프로토콜별 수준 지정(**수준을 지정하지 않으면 기본 수준을 사용**하며, 사고를 전혀 요청하지 않은 요청에는 사고를 반환하지 않음):

| 프로토콜 | 파라미터 | 값 → 수준 |
|------|------|------|
| OpenAI `/v1/chat/completions` | `reasoning_effort` | `low` / `medium` / `high`. `minimal` → low, `xhigh` → high. `none` → 사고 안 함. 인식할 수 없는 값 → 기본 수준을 따름(오류 없음) |
| OpenAI `/v1/responses` | `reasoning.effort`(또는 최상위 `reasoning_effort`) | 위와 같음 |
| Anthropic `/v1/messages` | `thinking` | `{"type":"enabled","budget_tokens":N}`: `N<2048` → low, `2048–4095` → medium, `≥4096` → high. `{"type":"adaptive"}` 또는 잘못된 budget → `output_config.effort`를 봄: `low` / `medium`은 해당 수준, `xhigh` / `max` → high, `high`(Claude Code의 출고 설정, 명시적 선택이 없는 것으로 간주) 또는 없음 → 기본 수준을 따름. `{"type":"disabled"}` → 사고 안 함. 인식할 수 없는 `type`은 보내지 않은 것으로 처리 |
| Gemini 네이티브 `generateContent` / `streamGenerateContent` | `generationConfig.thinkingConfig` | `thinkingLevel`: `LOW` / `MEDIUM` / `HIGH`(`MINIMAL` → low, 미지정 → 기본 수준을 따름). `thinkingBudget`: `0` → 사고 안 함, `-1`(자동) → 기본 수준을 따름, `>0`은 2048 / 4096 기준으로 구분. 둘 다 주면 `thinkingLevel` 우선. `includeThoughts: true`만 주면 → 기본 수준을 따름. `includeThoughts: true`일 때만 응답에서 사고를 반환(`"thought": true` part) |

## OpenAI 호환 API

### POST /openai/v1/chat/completions

OpenAI 형식의 대화 완성 API입니다.

**요청**:

```bash
curl -X POST http://localhost:5918/openai/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-당신의키" \
  -d '{
    "model": "gemini-2.0-flash",
    "messages": [
      {"role": "user", "content": "안녕하세요"}
    ],
    "stream": false,
    "temperature": 0.7,
    "max_tokens": 1000,
    "conversation_id": "optional-conv-id"
  }'
```

**요청 파라미터**:

| 파라미터 | 타입 | 필수 | 설명 |
|---------|------|------|------|
| `model` | string | ✅ | 모델 ID (예: gemini-flash) |
| `messages` | array | ✅ | 메시지 배열. `content`는 문자열 또는 객체 배열 (멀티모달 지원) |
| `stream` | boolean | ❌ | 스트리밍 응답 (기본값: false) |
| `temperature` | number | ❌ | 응답 창의성 (0.0-2.0, 기본값: 0.7) |
| `max_tokens` | integer | ❌ | 최대 응답 길이 (기본값: 4096) |
| `top_p` | number | ❌ | 누적 확률 샘플링 (0.0-1.0) |
| `conversation_id` | string | ❌ | 대화 컨텍스트 ID |
| `tools` | array | ❌ | 함수 호출 도구 정의 |

**멀티모달 content 형식**:

`content`는 문자열 (텍스트만) 또는 객체 배열 (텍스트와 이미지 지원):

```json
{
  "role": "user",
  "content": [
    {"type": "text", "text": "이것은 무엇입니까"},
    {
      "type": "image_url",
      "image_url": {
        "url": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
      }
    }
  ]
}
```

지원되는 content 타입:
- `text`: 순수 텍스트 콘텐츠
- `image_url`: 이미지, Base64 Data URI (`data:image/...;base64,...`) 및 원격 HTTP URL 지원

**메시지 형식**:

```json
{
  "role": "user|assistant|system",
  "content": "텍스트 또는 배열"
}
```

**응답 (비스트리밍)**:

```json
{
  "id": "chatcmpl-xxx",
  "object": "chat.completion",
  "created": 1234567890,
  "model": "gemini-2.0-flash",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "응답 텍스트"
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 10,
    "completion_tokens": 50,
    "total_tokens": 60
  },
  "conversation_id": "conv-xxx"
}
```

**응답 (스트리밍)**:

```
data: {"choices":[{"delta":{"content":"응답"}}]}
data: {"choices":[{"delta":{"content":" 텍스트"}}]}
data: [DONE]
```

**에러 응답**:

```json
{
  "error": {
    "message": "오류 설명",
    "type": "invalid_request_error",
    "code": "invalid_model"
  }
}
```

### GET /openai/v1/models

사용 가능한 모델 목록 조회

**요청**:

```bash
curl http://localhost:5918/openai/v1/models \
  -H "Authorization: Bearer sk-당신의키"
```

**응답**:

```json
{
  "object": "list",
  "data": [
    {
      "id": "gemini-pro",
      "object": "model",
      "created": 1234567890,
      "owned_by": "google"
    },
    {
      "id": "gemini-flash",
      "object": "model",
      "created": 1234567890,
      "owned_by": "google"
    },
    {
      "id": "gemini-flash-lite",
      "object": "model",
      "created": 1234567890,
      "owned_by": "google"
    },
    {
      "id": "gemini-argon",
      "object": "model",
      "created": 1234567890,
      "owned_by": "google"
    }
  ]
}
```

> 💡 **모델 선택 가이드**: 네 가지 모델은 서로 다른 속도/품질 트레이드오프를 제공합니다.
> - `gemini-flash`: 가장 빠름(응답 약 4-5초), **agent / 고빈도 / 고동시성** 시나리오에 적합, 기본 선택으로 권장.
> - `gemini-argon`: 4 Argon, 복잡한 작업용. 계정이 실제로 Argon을 가진 경우에만 목록에 표시됩니다.
> - `gemini-flash-lite`: 가장 가볍고 빠른 등급(3.5 Flash-Lite), Pro/Flash가 사용량 제한에 걸렸을 때 사용 가능한 대체 옵션.
> - `gemini-pro`: 최고 품질이지만 느림(응답 약 9-17초, 긴 컨텍스트에서 더 느림), 품질 중시하고 지연 시간을 신경 쓰지 않는 시나리오에 적합.
>
> agent 클라이언트(많은 동시 요청 발행)는 `gemini-flash`를 우선 사용하는 것이 좋습니다. 본 서비스의 스트리밍 인터페이스는 진정한 증분 스트리밍으로, 첫 글자가 생성되는 즉시 푸시를 시작합니다.


### POST /openai/v1/responses

OpenAI Responses API입니다. Chat Completions 대신 최신 Responses 프로토콜을 요구하는 클라이언트(예: 2026년 2월부로 Chat Completions 지원을 중단한 **Codex CLI** — Codex CLI를 gemini2api에 연결하려면 이 엔드포인트가 필요합니다)를 위해 추가되었습니다. 텍스트, 스트리밍, 함수/도구 호출을 지원하며, Gemini 모델과 API 관리에서 구성한 타사 모델 모두에서 사용할 수 있습니다.

**요청**:

```bash
curl -X POST http://localhost:5918/openai/v1/responses \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-api-key" \
  -d '{
    "model": "gemini-flash",
    "input": "2+2는 얼마인가요?",
    "stream": false
  }'
```

**요청 본문**:

| 파라미터 | 타입 | 필수 | 설명 |
|---------|------|------|------|
| `model` | string | ✅ | 모델 ID (예: `gemini-flash`), 또는 API 관리에서 구성한 타사 모델 |
| `input` | string 또는 array | ✅ | 단일 문자열(사용자 메시지 하나를 축약한 형태), 또는 입력 항목 배열(아래 참고) |
| `instructions` | string | ❌ | 대화 앞에 붙는 시스템/개발자 사전 지시문 |
| `stream` | boolean | ❌ | 스트리밍 활성화 여부 (기본값: false) |
| `tools` | array | ❌ | 도구 호출용 함수 정의, **평면(flat) 구조**: `{"type":"function","name","description","parameters"}` (참고: Chat Completions의 중첩 구조 `{"type":"function","function":{...}}`와 다름) |
| `tool_choice` | string 또는 object | ❌ | `auto`, `none`, `required`, 또는 특정 도구 호출을 강제하는 `{"type":"function","name":"..."}` |
| `temperature` | number | ❌ | 무작위성 (타사 모델에는 전달됨; Gemini 경로에서는 적용되지 않음) |
| `max_output_tokens` | number | ❌ | 최대 응답 길이 (타사 모델에는 전달됨; Gemini 경로에서는 적용되지 않음) |

**`input` 배열 항목 유형**:
- `{"type":"message","role":"user"|"assistant"|"system","content":[...]}` — 콘텐츠 파트: `{"type":"input_text","text":...}`, `{"type":"input_image","image_url":"..."}`, `{"type":"output_text","text":...}`
- `{"type":"function_call","call_id","name","arguments"}` — 이전 어시스턴트의 도구 호출 턴 (멀티턴 히스토리는 직접 다시 전송)
- `{"type":"function_call_output","call_id","output"}` (또는 `"tool_result"`) — 다시 전달하는 도구 실행 결과

**지원하지 않음(조용히 무시하지 않고 명시적으로 오류 반환)**: `previous_response_id` — 이 서버는 서버 측 대화 상태를 유지하지 않습니다. 이 필드를 보내면 조용히 무시하는 대신 400 `invalid_request_error`를 반환합니다. 매 요청마다 전체 대화 내용을 `input`에 담아 다시 보내세요 (Codex CLI는 이미 이렇게 동작합니다).

**응답 (비스트리밍)**:

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

**응답 (스트리밍)**: 각 이벤트마다 단조 증가하는 `sequence_number`를 포함하는, 공식 프로토콜 순서를 그대로 따르는 명명된 SSE 이벤트 시퀀스입니다. `data: [DONE]` 같은 종료 표시는 **없으며** (이는 Chat Completions 방식의 관례입니다) — 완료는 `response.completed`(실패 시 `response.failed`)로 알립니다:

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

도구 호출의 경우, `response.output_item.added`(타입 `function_call`) 다음에는 위의 텍스트 이벤트 대신 `response.function_call_arguments.delta` / `response.function_call_arguments.done` / `response.output_item.done`이 이어집니다.

**함수 호출 예시**:

```bash
curl -X POST http://localhost:5918/openai/v1/responses \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-api-key" \
  -d '{
    "model": "gemini-flash",
    "input": "파리 날씨가 어때요?",
    "tools": [
      {
        "type": "function",
        "name": "get_weather",
        "description": "도시의 날씨를 조회합니다",
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
응답 `output`에는 `function_call` 항목이 포함됩니다:
```json
{"id": "fc_xxx", "type": "function_call", "status": "completed", "call_id": "call_xxx", "name": "get_weather", "arguments": "{\"city\": \"파리\"}"}
```

### POST /openai/v1/images/generations

OpenAI 호환 AI 이미지 생성 API입니다. `prompt`로 이미지 생성을 트리거하며, Base64로 인코딩된 이미지를 `b64_json` 형식으로 반환합니다.

> 표준 베어 경로 `/v1/images/generations`로도 호출할 수 있습니다.

**요청**:

```bash
curl -X POST http://localhost:5918/openai/v1/images/generations \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-당신의키" \
  -d '{
    "model": "gemini-pro",
    "prompt": "a cute cat",
    "n": 1
  }'
```

**요청 파라미터**:

| 파라미터 | 타입 | 필수 | 설명 |
|---------|------|------|------|
| `model` | string | ✅ | 모델 ID (예: gemini-pro) |
| `prompt` | string | ✅ | 생성할 이미지를 설명하는 프롬프트 |
| `n` | integer | ❌ | 생성할 이미지 개수 (기본값: 1) |

**응답**:

```json
{
  "created": 1234567890,
  "data": [
    {
      "b64_json": "iVBORw0KGgoAAAANSUhEUgAA..."
    }
  ]
}
```

> [!TIP]
> 대화 엔드포인트(`/chat/completions`, `/messages`, `:generateContent`)에서 모델이 이미지를 생성하면, 생성된 이미지가 자동으로 응답에 삽입됩니다(markdown 이미지 / Claude image block / Gemini inlineData).

## Claude 호환 API

### POST /claude/v1/messages

Claude 형식의 메시지 생성 API입니다.

**요청**:

```bash
curl -X POST http://localhost:5918/claude/v1/messages \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-당신의키" \
  -d '{
    "model": "gemini-2.0-flash",
    "max_tokens": 1024,
    "messages": [
      {"role": "user", "content": "안녕하세요"}
    ],
    "stream": false
  }'
```

**요청 파라미터**:

| 파라미터 | 타입 | 필수 | 설명 |
|---------|------|------|------|
| `model` | string | ✅ | 모델 ID |
| `max_tokens` | integer | ✅ | 최대 응답 길이 |
| `messages` | array | ✅ | 메시지 배열 |
| `stream` | boolean | ❌ | 스트리밍 응답 |
| `temperature` | number | ❌ | 응답 창의성 |
| `system` | string | ❌ | 시스템 프롬프트 |

**응답**:

```json
{
  "id": "msg-xxx",
  "type": "message",
  "role": "assistant",
  "content": [
    {
      "type": "text",
      "text": "응답 텍스트"
    }
  ],
  "model": "gemini-2.0-flash",
  "stop_reason": "end_turn",
  "stop_sequence": null,
  "usage": {
    "input_tokens": 10,
    "output_tokens": 50
  }
}
```

#### 확장 사고(`thinking`)

| 파라미터 | 타입 | 필수 | 설명 |
|---------|------|------|------|
| `thinking` | object | ❌ | 사고 수준을 지정합니다. **보내지 않으면 업스트림은 "기본 사고 수준"(출고 기본값 `low`)으로 사고하지만, 응답에는 `thinking` 블록을 절대 넣지 않으며 이전과 완전히 동일합니다** |
| `output_config` | object | ❌ | 그 안의 `effort`만 읽으며, `thinking`과 함께 수준을 정합니다(사용법은 아래 `adaptive` 줄 참고). `thinking` 없이 `output_config.effort`만 보내면 효과가 없습니다(사고 파라미터를 보내지 않은 것으로 처리). 형태가 올바르지 않으면(객체가 아니거나 `effort`를 인식할 수 없음) 지정하지 않은 것으로 보며 오류를 내지 않습니다 |

- `{"type":"enabled","budget_tokens":N}`: 켜기. `N`은 `<2048` / `2048–4095` / `>=4096` 기준으로 낮음／중간／높음 3단계에 대응합니다. 유효한 `budget_tokens`가 있으면 그것으로 수준이 정해지며 `output_config.effort`보다 우선합니다.
- `{"type":"adaptive"}`: 켜기. 수준은 `output_config.effort`를 보고 정합니다: `low` / `medium`은 해당 수준, `xhigh` / `max` → high, `high`(Claude Code의 출고 설정, 명시적 선택이 없는 것으로 간주) 또는 없음 → 기본 사고 수준을 따릅니다. `budget_tokens`가 없거나 잘못된 경우도 같음.
- `{"type":"disabled"}` / `{"type":"between_tools"}`: 사고하지 않음(명시적 끄기. 기본 수준이 적용되지 않으며 `output_config.effort`가 무엇이든 무시됨).

사고 내용은 Anthropic 규격의 `thinking` 콘텐츠 블록으로, `text` / `tool_use` 블록**앞에** 반환됩니다. 스트리밍에서는 `content_block_start(thinking)` → `thinking_delta` → `content_block_stop` 순서입니다.

⚠️ **`signature`는 포함하지 않습니다**(유효한 서명을 만들 수 없기 때문입니다. 빈 문자열이나 임의의 서명을 넣는 것이 더 위험합니다 — 클라이언트가 실제 API로 되돌려 보내면 400). 단계는 웹의 낮음 / 중간 / 높음에 대응합니다(실제 계정 측정에서 high가 가장 깊음. low와 medium은 구분되지 않았습니다). `EXTENDED_THINKING_ENABLED=false`이면 `thinking`을 보내도 사고 경로를 사용하지 않습니다.

⚠️ **본문이 시작된 뒤에 도착한 사고 증분은 버려집니다**(스트리밍): Anthropic 블록 순서상 `text` 블록 뒤에 `thinking` 블록을 열거나 이어 붙일 수 없습니다(잃어버린 문자 수는 WARNING으로 기록됩니다). 완전한 사고 체인이 필요하면 블록 순서 제약이 없는 OpenAI 프로토콜의 `reasoning_content`를 사용하세요. 본문은 항상 완전합니다. `thinking`이 객체가 아니면 **보내지 않은 것**으로 처리하고 200을 반환합니다.

### GET /claude/v1/models

Claude 호환 모델 목록

**요청**:

```bash
curl http://localhost:5918/claude/v1/models \
  -H "Authorization: Bearer sk-당신의키"
```

### POST /claude/v1/messages/count_tokens

Token 개수 추정

**요청**:

```bash
curl -X POST http://localhost:5918/claude/v1/messages/count_tokens \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-당신의키" \
  -d '{
    "model": "gemini-2.0-flash",
    "messages": [
      {"role": "user", "content": "안녕하세요"}
    ]
  }'
```

**응답**:

```json
{
  "input_tokens": 10
}
```

## Gemini 원생 API

### GET /gemini/v1beta/models

Gemini 모델 목록

**요청**:

```bash
curl http://localhost:5918/gemini/v1beta/models \
  -H "Authorization: Bearer sk-당신의키"
```

### POST /gemini/v1beta/models/{model}:generateContent

Gemini 형식의 콘텐츠 생성

**요청**:

```bash
curl -X POST http://localhost:5918/gemini/v1beta/models/gemini-2.0-flash:generateContent \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-당신의키" \
  -d '{
    "contents": [
      {
        "role": "user",
        "parts": [
          {"text": "안녕하세요"}
        ]
      }
    ],
    "generationConfig": {
      "temperature": 0.7,
      "maxOutputTokens": 1000
    }
  }'
```

### POST /gemini/v1beta/models/{model}:streamGenerateContent

스트리밍 콘텐츠 생성 (Chunked JSON)

**요청**:

```bash
curl -X POST http://localhost:5918/gemini/v1beta/models/gemini-2.0-flash:streamGenerateContent \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-당신의키" \
  -d '{
    "contents": [
      {
        "role": "user",
        "parts": [{"text": "안녕하세요"}]
      }
    ]
  }'
```

## Deep Research API

### POST /gemini/v1beta/deepresearch/

동기식 심화 연구 (계획 → 조사 → 종합 보고서)

**요청**:

```bash
curl -X POST http://localhost:5918/gemini/v1beta/deepresearch/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-당신의키" \
  -d '{
    "query": "한국의 AI 산업 현황",
    "max_steps": 5
  }'
```

**응답**:

```json
{
  "status": "completed",
  "query": "한국의 AI 산업 현황",
  "report": "종합 보고서 텍스트",
  "steps": [
    {"type": "planning", "content": "..."},
    {"type": "research", "content": "..."},
    {"type": "synthesis", "content": "..."}
  ]
}
```

### POST /gemini/v1beta/deepresearch/stream

스트리밍 연구 (실시간 진행 상황 푸시)

**요청**:

```bash
curl -X POST http://localhost:5918/gemini/v1beta/deepresearch/stream \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-당신의키" \
  -d '{"query": "한국의 AI 산업 현황"}'
```

**응답** (스트리밍):

```
data: {"step": "planning", "content": "..."}
data: {"step": "research", "content": "..."}
data: {"step": "synthesis", "content": "..."}
data: [DONE]
```

### POST /gemini/v1beta/deepresearch/interact

비동기 작업 모드 (생성 → 폴링 결과)

**요청 (생성)**:

```bash
curl -X POST http://localhost:5918/gemini/v1beta/deepresearch/interact \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-당신의키" \
  -d '{"query": "한국의 AI 산업 현황", "action": "create"}'
```

**응답**:

```json
{
  "task_id": "task-xxx",
  "status": "running"
}
```

**요청 (결과 폴링)**:

```bash
curl http://localhost:5918/gemini/v1beta/deepresearch/interact?task_id=task-xxx \
  -H "Authorization: Bearer sk-당신의키"
```

## 관리 API

### GET /admin/status

서비스 상태 (계정 풀 개요 + 회전 전략)

**요청**:

```bash
curl http://localhost:5918/admin/status \
  -H "Authorization: Bearer sk-당신의키"
```

**응답**:

```json
{
  "status": "ok",
  "accounts_total": 2,
  "accounts_active": 2,
  "rotation_strategy": "round-robin",
  "uptime_seconds": 3600
}
```

### GET /admin/system-info

시스템 정보 (버전/Python/OS/메모리/CPU/PID/실행 모드)

**요청**:

```bash
curl http://localhost:5918/admin/system-info \
  -H "Authorization: Bearer sk-당신의키"
```

**응답**:

```json
{
  "version": "1.0.0",
  "python_version": "3.12.0",
  "os": "Linux",
  "memory_mb": 512,
  "cpu_count": 4,
  "pid": 12345,
  "run_mode": "docker"
}
```

### GET /admin/accounts

모든 계정 목록 및 상태

**요청**:

```bash
curl http://localhost:5918/admin/accounts \
  -H "Authorization: Bearer sk-당신의키"
```

**응답**:

```json
{
  "accounts": [
    {
      "id": "account-0",
      "label": "주 계정",
      "status": "active",
      "last_check": "2025-05-17T10:30:00Z",
      "requests_count": 150
    }
  ]
}
```

### POST /admin/accounts

새 계정 추가

**요청**:

```bash
curl -X POST http://localhost:5918/admin/accounts \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-당신의키" \
  -d '{
    "psid": "g.a000xxx...",
    "psidts": "sidts-xxx...",
    "label": "새 계정"
  }'
```

**응답**:

```json
{
  "id": "account-1",
  "label": "새 계정",
  "status": "active"
}
```

### DELETE /admin/accounts/{id}

계정 삭제

**요청**:

```bash
curl -X DELETE http://localhost:5918/admin/accounts/account-1 \
  -H "Authorization: Bearer sk-당신의키"
```

**응답**:

```json
{"message": "Account deleted"}
```

### GET /admin/accounts/{id}/check

단일 계정 상태 확인

**요청**:

```bash
curl http://localhost:5918/admin/accounts/account-0/check \
  -H "Authorization: Bearer sk-당신의키"
```

**응답**:

```json
{
  "id": "account-0",
  "status": "active",
  "last_check": "2025-05-17T10:35:00Z"
}
```

### PUT /admin/accounts/{id}/cookies

계정 Cookie 업데이트

**요청**:

```bash
curl -X PUT http://localhost:5918/admin/accounts/account-0/cookies \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-당신의키" \
  -d '{
    "psid": "g.새로운값...",
    "psidts": "sidts-새로운값..."
  }'
```

**응답**:

```json
{"message": "Cookies updated"}
```

### POST /admin/reload-cookies

전체 Cookie 갱신

**요청**:

```bash
curl -X POST http://localhost:5918/admin/reload-cookies \
  -H "Authorization: Bearer sk-당신의키"
```

**응답**:

```json
{"message": "Cookies reloaded"}
```

### GET /admin/health-history

최근 헬스 체크 기록

**요청**:

```bash
curl http://localhost:5918/admin/health-history \
  -H "Authorization: Bearer sk-당신의키"
```

### GET /admin/usage-stats/summary

사용 통계 개요 (누적 요청, 오류율, 지연, 갱신 성공률)

**요청**:

```bash
curl http://localhost:5918/admin/usage-stats/summary \
  -H "Authorization: Bearer sk-당신의키"
```

**응답**:

```json
{
  "total_requests": 1000,
  "error_rate": 0.02,
  "avg_latency_ms": 1500,
  "cookie_refresh_success_rate": 0.98
}
```

### GET /admin/usage-stats/history

히스토리 추이 데이터 (세분화 및 기간 선택 가능)

**요청**:

```bash
curl "http://localhost:5918/admin/usage-stats/history?granularity=hour&hours=24" \
  -H "Authorization: Bearer sk-당신의키"
```

### GET /admin/settings

현재 편집 가능 설정 (그룹별 반환)

**요청**:

```bash
curl http://localhost:5918/admin/settings \
  -H "Authorization: Bearer sk-당신의키"
```

**응답**:

```json
{
  "performance": {
    "rotation_strategy": "round-robin",
    "max_concurrent_per_account": 3
  },
  "rate_limit": {
    "enabled": false,
    "window": 60,
    "max": 10
  }
}
```

### POST /admin/settings

설정 일괄 업데이트 (.env 쓰기 + 메모리 핫 업데이트)

**요청**:

```bash
curl -X POST http://localhost:5918/admin/settings \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-당신의키" \
  -d '{
    "rotation_strategy": "failover",
    "max_concurrent_per_account": 5
  }'
```

### GET /admin/api-keys

API Key 목록 (키 마스킹)

**요청**:

```bash
curl http://localhost:5918/admin/api-keys \
  -H "Authorization: Bearer sk-당신의키"
```

### POST /admin/api-keys

API Key 추가

**요청**:

```bash
curl -X POST http://localhost:5918/admin/api-keys \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-당신의키" \
  -d '{
    "provider": "openai",
    "api_key": "sk-...",
    "model": "gpt-4o"
  }'
```

### DELETE /admin/api-keys/{id}

API Key 삭제

**요청**:

```bash
curl -X DELETE http://localhost:5918/admin/api-keys/key-1 \
  -H "Authorization: Bearer sk-당신의키"
```

### PATCH /admin/api-keys/{id}/label

Key 레이블 수정

**요청**:

```bash
curl -X PATCH http://localhost:5918/admin/api-keys/key-1/label \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-당신의키" \
  -d '{"label": "내 OpenAI Key"}'
```

### POST /admin/api-keys/models

특정 Provider / base_url에서 사용 가능한 모델 목록 탐지 (Key 추가 시 모델 드롭다운 채우기에 사용)

**요청**:

```bash
curl -X POST http://localhost:5918/admin/api-keys/models \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-당신의키" \
  -d '{
    "provider": "openai",
    "api_key": "sk-xxx",
    "base_url": "https://api.openai.com/v1"
  }'
```

### GET /admin/logs

구조화된 로그 페이지 조회 (방향/검색/제한/오프셋 지원)

**요청**:

```bash
curl "http://localhost:5918/admin/logs?direction=desc&search=error&limit=15&offset=0" \
  -H "Authorization: Bearer sk-당신의키"
```

**응답**:

```json
{
  "logs": [
    {
      "id": "log-1",
      "timestamp": "2025-05-17T10:30:00Z",
      "level": "error",
      "message": "Cookie expired",
      "details": {}
    }
  ],
  "total": 100
}
```

### POST /admin/logs/clear

모든 로그 삭제

**요청**:

```bash
curl -X POST http://localhost:5918/admin/logs/clear \
  -H "Authorization: Bearer sk-당신의키"
```

### GET /admin/web-chats

계정의 Gemini 웹 측 세션 목록 조회 (읽기 전용)

**요청**:

```bash
curl http://localhost:5918/admin/web-chats \
  -H "Authorization: Bearer sk-당신의키"
```

**응답**:

```json
{
  "chats": [
    {
      "id": "chat-xxx",
      "title": "세션 제목",
      "created": "2026-06-06T10:00:00Z",
      "pinned": false
    }
  ],
  "total": 50
}
```

### POST /admin/cleanup-web-chats

보존 기간보다 오래된 웹 측 세션 정리 수동 트리거 (백그라운드 비동기 실행)

**요청**:

```bash
curl -X POST http://localhost:5918/admin/cleanup-web-chats \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-당신의키" \
  -d '{
    "keep_hours": 24,
    "skip_pinned": true
  }'
```

**요청 파라미터**:

| 파라미터 | 타입 | 필수 | 설명 |
|---------|------|------|------|
| `keep_hours` | integer | ❌ | 보존 기간(시간), 이보다 오래된 세션 삭제 (기본값: 24) |
| `skip_pinned` | boolean | ❌ | 고정 세션 건너뛰기 (기본값: true) |

**응답**:

```json
{
  "status": "started",
  "message": "Web chat cleanup started in background"
}
```

### POST /admin/restart

서비스 재시작 (패널 우측 상단 원클릭 재시작, 재시작 후 자동 폴링으로 복구)

**요청**:

```bash
curl -X POST http://localhost:5918/admin/restart \
  -H "Authorization: Bearer sk-당신의키"
```

### GET /admin/check-update

새 버전이 있는지 확인

**요청**:

```bash
curl http://localhost:5918/admin/check-update \
  -H "Authorization: Bearer sk-당신의키"
```

### POST /admin/update

최신 버전으로 업데이트 트리거

**요청**:

```bash
curl -X POST http://localhost:5918/admin/update \
  -H "Authorization: Bearer sk-당신의키"
```

### GET /admin/access-keys

모든 액세스 키 목록 (평문 키, 상태, 사용량, 적용 범위 포함)

**요청**:

```bash
curl http://localhost:5918/admin/access-keys \
  -H "Authorization: Bearer sk-당신의키"
```

**응답**:

```json
{
  "keys": [
    {
      "id": 1,
      "key": "sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
      "name": "홍길동",
      "display_name": "홍길동",
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

`state` 값: `valid`(유효) / `disabled`(비활성) / `pending`(미활성. `duration_days`는 설정됐지만 아직 사용된 적 없음) / `expired`(만료됨) / `quota_exceeded`(한도 초과). 판정은 `disabled` → `expired` → `quota_exceeded` → `pending` → `valid` 우선순위로 단축 평가됩니다.

### GET /admin/access-keys/options

패널 발급 폼의 선택 항목: 계정 풀의 계정과 외부에 노출되는 모델 이름(`GET /v1/models`와 동일한 범위)

**요청**:

```bash
curl http://localhost:5918/admin/access-keys/options \
  -H "Authorization: Bearer sk-당신의키"
```

### POST /admin/access-keys

액세스 키 발급

**파라미터**:

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `name` | string | ❌ | 라벨. `count > 1`이면 `name-1`, `name-2` … 로 자동 번호 부여 |
| `count` | integer | ❌ | 한 번에 발급할 개수. 기본 1, **최대 50** |
| `expires_at` | string | ❌ | 절대 만료 시각(ISO8601). `duration_days`와 상호 배타 |
| `duration_days` | number | ❌ | 유효 일수. **지연 활성화**: 소지자의 최초 사용부터 계산 시작 (최대 36500) |
| `request_limit` | integer | ❌ | 요청 한도. 비우면 무제한 |
| `bound_account_ids` | string[] | ❌ | 바인딩 계정. 비우면 제한 없음 |
| `allowed_models` | string[] | ❌ | 허용 모델. 비우면 제한 없음 |
| `enabled` | boolean | ❌ | 즉시 사용 가능 여부. 기본 `true` |

**요청**:

```bash
curl -X POST http://localhost:5918/admin/access-keys \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-당신의키" \
  -d '{
    "name": "홍길동",
    "duration_days": 7,
    "request_limit": 500,
    "allowed_models": ["gemini-flash"]
  }'
```

응답의 `keys`는 이번에 발급한 모든 키이고, `key`는 그중 첫 번째입니다 (한 개만 발급할 때 바로 쓸 수 있습니다).

> `count`가 0 또는 50 초과면 400, `expires_at`과 `duration_days`를 함께 주면 400, 디스크 기록 실패는 500을 반환합니다 (저장되지 않은 키에 200을 반환하는 일은 절대 없습니다 —— 이미 나눠준 키가 재시작 후 무효가 되기 때문입니다).

### PATCH /admin/access-keys/{id}

키 설정 변경

**요청**:

```bash
# 비활성화
curl -X PATCH http://localhost:5918/admin/access-keys/1 \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-당신의키" \
  -d '{"enabled": false}'

# 요청 한도와 모델 제한 해제
curl -X PATCH http://localhost:5918/admin/access-keys/1 \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-당신의키" \
  -d '{"clear": ["request_limit", "allowed_models"]}'
```

> **JSON의 `null`은 "이 필드를 변경하지 않음"**을 뜻하며 "비우기"가 아닙니다. `expires_at` / `duration_days` / `request_limit` / `bound_account_ids` / `allowed_models`를 실제로 비우려면 필드 이름을 `clear` 배열에 넣어야 합니다. `clear`에 그 밖의 필드 이름이 들어가면 400을 반환합니다.

### DELETE /admin/access-keys/{id}

키 삭제. 사용 중인 클라이언트는 즉시 연결이 끊깁니다.

**요청**:

```bash
curl -X DELETE http://localhost:5918/admin/access-keys/1 \
  -H "Authorization: Bearer sk-당신의키"
```

### POST /admin/access-keys/{id}/reset-usage

`request_count`를 0으로 되돌려 한도를 초과한 키를 다시 쓸 수 있게 합니다.

**요청**:

```bash
curl -X POST http://localhost:5918/admin/access-keys/1/reset-usage \
  -H "Authorization: Bearer sk-당신의키"
```

> **집계 방식**: 모든 업무 요청은 인증 입구에서 원자적으로 증가하며, 단조 증가하고 환불되지 않습니다 (업스트림 오류도 집계됨). **`GET /v1/models`도 집계 대상입니다** —— 일부 클라이언트는 대화마다 모델 목록을 조회하므로 한 번의 대화에 2회 소비합니다. `request_limit`을 설정할 때 여유를 두세요.

### GET /health

헬스 체크 (Docker 프로브 호환)

**요청**:

```bash
curl http://localhost:5918/health
```

**응답**:

```json
{"status":"ok","service":"gemini2api"}
```

## 에러 코드

| 코드 | 설명 |
|------|------|
| 400 | 파라미터 오류 (필수 필드 누락, 잘못된 형식) |
| 401 | 미인증 (API Key 누락 또는 무효) |
| 403 | 금지 (권한 부족) |
| 404 | 찾을 수 없음 (엔드포인트 또는 리소스 없음) |
| 429 | 너무 많은 요청 (속도 제한 초과) |
| 500 | 서버 오류 (내부 오류) |
| 503 | 서비스 사용 불가 (사용 가능한 계정 없음) |

## 에러 응답 형식

```json
{
  "error": {
    "message": "오류 설명",
    "type": "error_type",
    "code": "error_code"
  }
}
```

## 요청 예제

### Python (OpenAI SDK)

```python
from openai import OpenAI

client = OpenAI(
    api_key="sk-당신의키",
    base_url="http://localhost:5918/openai/v1"
)

response = client.chat.completions.create(
    model="gemini-2.0-flash",
    messages=[{"role": "user", "content": "안녕하세요"}],
    stream=True
)

for chunk in response:
    print(chunk.choices[0].delta.content or "", end="")
```

### Python (Anthropic SDK)

```python
import anthropic

client = anthropic.Anthropic(
    api_key="sk-당신의키",
    base_url="http://localhost:5918/claude"
)

message = client.messages.create(
    model="gemini-2.0-flash",
    max_tokens=1024,
    messages=[{"role": "user", "content": "안녕하세요"}]
)

print(message.content[0].text)
```

### cURL (스트리밍)

```bash
curl -X POST http://localhost:5918/openai/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-당신의키" \
  -d '{
    "model": "gemini-2.0-flash",
    "messages": [{"role": "user", "content": "안녕하세요"}],
    "stream": true
  }'
```

### JavaScript (fetch)

```javascript
const response = await fetch('http://localhost:5918/openai/v1/chat/completions', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'Authorization': 'Bearer sk-당신의키'
  },
  body: JSON.stringify({
    model: 'gemini-2.0-flash',
    messages: [{ role: 'user', content: '안녕하세요' }],
    stream: false
  })
});

const data = await response.json();
console.log(data.choices[0].message.content);
```

## 타임아웃

비스트리밍(`stream: false`) 요청의 생성 타임아웃은 **모델 패밀리 단위로 구분**되며 `GENERATE_TIMEOUTS`로 재정의할 수 있습니다:

| 모델 패밀리 | 기본 타임아웃 |
|------|------|
| flash-lite | 60초 |
| flash | 120초 |
| pro | 300초 |
| argon | 300초 |
| 인식되지 않는 패밀리 | 60초 |

이미지 생성으로 추정되는 요청은 위 값과 `GENERATE_TIMEOUT_IMAGE`(기본 180초) 중 **더 큰 쪽**을 채택합니다. 타임아웃은 더 이상 3번 재시도하지 않습니다 —— 실패는 실패입니다.

> [!IMPORTANT]
> 비스트리밍 경로에서는 생성이 반환되기 전까지 연결에 **0바이트**가 흐릅니다. 즉 유휴 타임아웃이 아니라 **첫 바이트까지**의 타임아웃입니다.
> **pro 비스트리밍은 최대 300초를 무응답으로 기다리게 되어 흔한 앞단 프록시의 첫 바이트 한도를 넘깁니다**(EdgeOne 무료 버전 15초, 많은 리버스 프록시의 기본값 60초). 그러면 클라이언트가 받는 것은 이 서비스의 오류 본문이 아니라 프록시의 504입니다.
> 앞단 프록시가 있는 구성에서는 이런 요청에 `stream: true`를 권장합니다. 스트리밍 경로는 자체 한도(청크당 120초 / 전체 180초)를 따르며 위 표의 영향을 받지 않습니다.
