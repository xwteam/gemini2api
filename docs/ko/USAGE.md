# 사용 가이드

Gemini2API의 Web 패널, API 클라이언트 연동, 그리고 고급 기능 사용법을 설명합니다.

## Web 패널 기능

### 접속 방법

브라우저에서 `http://서버IP:5918`로 접속하면 로그인 페이지가 나타납니다.

**로그인**:
- API Key 입력 (`.env` 파일의 `API_KEY` 값 또는 로그에서 확인)
- "로그인" 버튼 클릭

### 대시보드

메인 페이지에서 서비스 상태를 한눈에 확인:

- **운행 시간**: 서비스 시작 이후 경과 시간 실시간 표시
- **이차원 코드 카드**: 문자/이미지 설정 (api/ 디렉토리에서 동적 로드, 수정 후 새로고침으로 반영)
- **시스템 정보**: 버전, Python, OS, 메모리, CPU, PID, 실행 모드
- **설정 관리**: 회전 전략, 동시 실행 제한 조정
- **계정 상태**: 활성 계정 수 및 상태 개요
- **사용 가능 모델**: 현재 사용 가능한 모델 목록

### 계정 관리

"계정 관리" 탭에서:

**계정 추가**:
1. "계정 추가" 버튼 클릭
2. PSID, PSIDTS, 레이블 입력
3. "추가" 클릭

**Cookie 업데이트**:
1. 계정 목록에서 대상 계정 선택
2. "Cookie 업데이트" 클릭
3. 새로운 PSID, PSIDTS 입력
4. "저장" 클릭

**계정 삭제**:
1. 계정 목록에서 대상 계정 선택
2. "삭제" 버튼 클릭
3. 확인

**상태 확인**:
- 각 계정의 마지막 확인 시간 및 상태 표시
- "확인" 버튼으로 즉시 상태 검사 가능

### 모델 테스트 Playground

"Playground" 탭에서 API 요청 실시간 테스트:

**기본 사용법**:
1. 모델 선택 (드롭다운)
2. 메시지 입력
3. "전송" 버튼 클릭
4. 실시간 응답 확인

**고급 옵션**:
- **Stream**: 스트리밍 응답 활성화/비활성화
- **Temperature**: 응답 창의성 조절 (0.0-2.0)
- **Max Tokens**: 최대 응답 길이 설정
- **Conversation ID**: 대화 컨텍스트 유지 (선택사항)

**대화 컨텍스트**:
- 클라이언트가 자동으로 messages 히스토리 관리
- 또는 `conversation_id` 필드로 명시적 관리
- 같은 conversation_id로 여러 요청 시 컨텍스트 유지

### 실시간 로그

"로그" 탭에서 구조화된 로그 확인:

**기능**:
- 방향 필터 (요청/응답/오류)
- 텍스트 검색
- 페이지 분할 (페이지당 15개)
- JSON 상세 패널
- 로그 디스크 지속화 (재시작 후에도 유지)

**로그 관리**:
- "일시 중지" 버튼으로 로그 기록 중단
- "재개" 버튼으로 다시 시작
- "초기화" 버튼으로 모든 로그 삭제

### 사용 통계

"통계" 탭에서 서비스 사용 현황 분석:

**개요**:
- 누적 요청 수
- 오류율
- 평균 응답 시간
- Cookie 갱신 성공률

**히스토리**:
- 시간별 추이 그래프
- 세분화 옵션 (시간/일/주)
- 기간 선택 가능

### API Key 관리

"API Key" 탭에서 제3자 대형 모델 API Key 중앙 관리:

**Key 추가**:
1. "Key 추가" 버튼 클릭
2. Provider 선택 (OpenAI/Anthropic/Gemini/OpenRouter/Custom)
3. API Key 입력
4. 모델 선택 (Provider별 사용 가능 모델)
5. "추가" 클릭

**Key 관리**:
- 각 Key의 상태 표시 (활성/비활성)
- "활성화/비활성화" 토글로 상태 변경
- "삭제" 버튼으로 제거

**일괄 작업**:
- "내보내기": 모든 Key 다운로드 (완전한 키 포함)
- "가져오기": 파일에서 Key 일괄 추가
- "일괄 삭제": 여러 Key 한 번에 제거

### 설정

"설정" 탭에서 실행 중 설정 관리:

**성능**:
- 회전 전략: round-robin (순차) / failover (장애 조치)
- 계정당 최대 동시 요청: 1-10

**속도 제한**:
- 활성화/비활성화
- 시간 창 (초)
- 최대 요청 수

**헬스 체크**:
- 활성화/비활성화
- 검사 간격 (분)

**기타**:
- 로그 레벨 변경
- 모델 화이트리스트 설정

모든 변경사항은 즉시 적용되며 `.env` 파일에 저장됩니다.

### 우측 상단 제어 표시줄

- **테마 전환**: 밝은 테마/어두운 테마 전환
- **다국어**: 지구본 아이콘으로 언어 변경
- **서비스 재시작**: 서비스 재시작 버튼
- **로그아웃**: 계정 로그아웃

## 이미지 업로드

Gemini2API는 이미지 및 파일 업로드를 포함한 멀티모달 콘텐츠를 지원합니다. 3가지 API 형식의 이미지 전송을 지원합니다.

### OpenAI 형식

`messages` 배열에서 `image_url` 타입을 사용합니다. Base64 Data URI와 원격 HTTP URL을 모두 지원합니다.

**Base64 이미지 예시**:

```bash
curl -X POST http://localhost:5918/openai/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-당신의API키" \
  -d '{
    "model": "gemini-flash",
    "messages": [
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
    ]
  }'
```

**원격 URL 이미지 예시**:

```bash
curl -X POST http://localhost:5918/openai/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-당신의API키" \
  -d '{
    "model": "gemini-flash",
    "messages": [
      {
        "role": "user",
        "content": [
          {"type": "text", "text": "이 이미지를 분석하세요"},
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

### Claude 형식

`content` 배열에서 `image` 타입을 사용합니다.

```bash
curl -X POST http://localhost:5918/claude/v1/messages \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-당신의API키" \
  -d '{
    "model": "gemini-flash",
    "max_tokens": 1024,
    "messages": [
      {
        "role": "user",
        "content": [
          {"type": "text", "text": "이것은 무엇입니까"},
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

### Gemini 네이티브 형식

`parts` 배열에서 `inlineData`를 사용합니다.

```bash
curl -X POST http://localhost:5918/gemini/v1beta/models/gemini-flash:generateContent \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-당신의API키" \
  -d '{
    "contents": [
      {
        "parts": [
          {"text": "이것은 무엇입니까"},
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

### Web 패널 업로드

Playground 테스트 페이지에서 "이미지 추가" 버튼을 클릭하여 로컬 이미지를 직접 업로드하고 테스트할 수 있습니다.

## AI 이미지 생성

Gemini2API는 이미지 생성을 지원하며, prompt로 트리거됩니다. 대화 중에 "이미지를 그려줘" 또는 영어로 "generate an image of ..."라고 말하면 됩니다. 3가지 대화 API 형식(OpenAI `/v1/chat/completions`, Claude `/v1/messages`, Gemini `/v1beta/...:generateContent`)이 모두 이미지 생성을 지원하며, 별도로 OpenAI 호환 전용 엔드포인트 `/v1/images/generations`도 제공합니다.

### 대화 중 이미지 생성

대화 메시지에서 이미지 생성을 요청하면 됩니다.

```bash
curl -X POST http://localhost:5918/openai/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-당신의API키" \
  -d '{
    "model": "gemini-pro",
    "messages": [
      {"role": "user", "content": "generate an image of a cute cat"}
    ]
  }'
```

### 전용 이미지 생성 엔드포인트

OpenAI 호환 `/v1/images/generations` 엔드포인트를 사용합니다.

```bash
curl -X POST http://localhost:5918/v1/images/generations \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-당신의API키" \
  -d '{
    "model": "gemini-pro",
    "prompt": "a cute cat",
    "n": 1
  }'
```

대화 API는 생성된 이미지의 로컬 URL(`http://당신의주소/images/xxx.png`)을 반환하며, 이 URL은 브라우저에서 직접 열거나 렌더링할 수 있습니다. `/v1/images/generations` 엔드포인트는 `b64_json` 형식으로 반환합니다. 어느 방식이든 이미지는 전체 해상도 원본(예: 1408×768)으로 제공됩니다.

## 지원 모델

Gemini2API는 3개의 고정된 안정적인 모델 이름을 외부에 제공하며, 이들은 변경되지 않습니다. 이러한 모델 이름은 API 계약으로 작동하여 클라이언트가 장기간 사용할 수 있습니다.

| 모델 ID | 설명 |
|--------|------|
| `gemini-pro` | Pro 모델, 최고 성능, 복잡한 작업에 적합 |
| `gemini-flash` | 빠른 모델, 낮은 지연시간, 실시간 애플리케이션에 적합 |
| `gemini-flash-thinking` | 사고 모델, 깊은 추론 및 분석 지원 |

**내부 자동 매핑**: 서비스는 Google 계정의 구독 수준(Advanced/Plus/Basic)에 따라 이러한 고정 이름을 현재 사용 가능한 실제 모델 버전으로 자동 매핑합니다. 계정 수준 변경, Google 롤아웃, 서비스 재시작 등 어떤 상황에서도 클라이언트는 항상 이 3개의 고정 이름을 사용할 수 있으며 수정이 필요하지 않습니다.

**레거시 별칭 호환성**: 하위 호환성을 위해 다음 이전 모델 이름도 지원됩니다:
- `gemini-2.5-pro`, `gemini-2.0-flash`, `gemini-2.0-flash-thinking` 등

### 서드파티 모델

API Key 풀을 통해 지원:
- **OpenAI**: gpt-4o, gpt-4-turbo, gpt-3.5-turbo 등
- **Anthropic**: claude-3-opus, claude-3-sonnet, claude-3-haiku 등
- **Google Gemini**: 공식 API Key를 통해
- **OpenRouter**: OpenRouter 플랫폼의 모든 모델

## 서드파티 클라이언트 연동

### ChatGPT-Next-Web

1. 설정 열기
2. "API 설정" 섹션에서:
   - **API URL**: `http://서버IP:5918/openai/v1`
   - **API Key**: `sk-당신의API키`
3. 모델 선택: `gemini-2.0-flash` 등
4. 대화 시작

### LobeChat

1. 설정 열기
2. "모델 제공자" 섹션에서:
   - **제공자**: Custom
   - **API URL**: `http://서버IP:5918/openai/v1`
   - **API Key**: `sk-당신의API키`
3. 모델 선택
4. 대화 시작

### OpenCat

1. 설정 열기
2. "API 설정"에서:
   - **API Endpoint**: `http://서버IP:5918/openai/v1`
   - **API Key**: `sk-당신의API키`
3. 모델 선택
4. 대화 시작

### 일반 OpenAI 호환 클라이언트

모든 OpenAI 호환 클라이언트에서:

```
API URL: http://서버IP:5918/openai/v1
API Key: sk-당신의API키
```

## Cookie 갱신

### 자동 갱신

서비스는 5분마다 자동으로 Cookie 갱신:
- Google RotateCookies API 호출
- batchexecute 하트비트 전송
- 세션 수명 연장

### 수동 갱신

**Web 패널 사용**:
1. "계정 관리" 탭 열기
2. 대상 계정 선택
3. "Cookie 업데이트" 클릭
4. 새로운 PSID, PSIDTS 입력
5. "저장" 클릭

**API 사용**:
```bash
curl -X PUT http://localhost:5918/admin/accounts/account-0/cookies \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-당신의API키" \
  -d '{"psid":"g.새로운값...","psidts":"sidts-새로운값..."}'
```

## 다국어 전환

우측 상단 지구본 아이콘 클릭하여 언어 선택:

- 简体中文 (중국어 간체)
- 繁體中文 (중국어 번체)
- English (영어)
- 日本語 (일본어)
- 한국어 (한국어)

모든 페이지가 선택한 언어로 즉시 전환됩니다.

## 대화 컨텍스트 관리

### 자동 관리 (권장)

클라이언트가 messages 배열 히스토리 자동 관리:

```python
from openai import OpenAI

client = OpenAI(
    api_key="sk-당신의API키",
    base_url="http://localhost:5918/openai/v1"
)

messages = []

# 첫 번째 메시지
messages.append({"role": "user", "content": "안녕하세요"})
response = client.chat.completions.create(
    model="gemini-2.0-flash",
    messages=messages
)
messages.append({"role": "assistant", "content": response.choices[0].message.content})

# 두 번째 메시지 (컨텍스트 유지)
messages.append({"role": "user", "content": "이전 대화 기억하세요?"})
response = client.chat.completions.create(
    model="gemini-2.0-flash",
    messages=messages
)
```

### 명시적 관리 (conversation_id)

`conversation_id` 필드로 서버 측 컨텍스트 유지:

```python
import json

# 첫 번째 요청
response = client.chat.completions.create(
    model="gemini-2.0-flash",
    messages=[{"role": "user", "content": "안녕하세요"}],
    conversation_id="my-conv-123"
)
conv_id = response.get("conversation_id")

# 두 번째 요청 (같은 conversation_id 사용)
response = client.chat.completions.create(
    model="gemini-2.0-flash",
    messages=[{"role": "user", "content": "이전 대화 기억하세요?"}],
    conversation_id=conv_id
)
```

## 성능 최적화

### 회전 전략 선택

**Round-Robin** (기본):
- 모든 계정을 순차적으로 사용
- 부하 균등 분산
- 단일 계정 과부하 방지

**Least-Used**:
- 가장 적게 사용된 계정 우선
- 특정 계정 집중 사용 방지
- 불균형 부하 분산 시 유용

### 동시 실행 제한

계정당 최대 동시 요청 수 조정:
- 기본값: 3
- 높을수록: 처리량 증가, 오류 위험 증가
- 낮을수록: 안정성 증가, 처리량 감소

권장값: 3-5

### 속도 제한

고빈도 요청 방지:
- 활성화 권장 (기본값: 비활성화)
- 시간 창: 60초
- 최대 요청: 10개/분

## 문제 해결

### 401 Unauthorized

**원인**: API Key 오류 또는 누락

**해결책**:
1. API Key 확인 (로그 또는 `.env` 파일)
2. 요청 헤더에 `Authorization: Bearer sk-...` 포함 확인
3. 또는 `x-api-key` 헤더 사용

### 503 Service Unavailable

**원인**: 사용 가능한 계정 없음

**해결책**:
1. Web 패널에서 계정 상태 확인
2. Cookie 만료 여부 확인
3. 필요시 Cookie 갱신
4. 새 계정 추가

### 응답 시간 초과

**원인**: 네트워크 지연 또는 Google 서버 응답 지연

**해결책**:
1. 네트워크 연결 확인
2. 요청 타임아웃 값 증가
3. 동시 실행 제한 감소
4. 속도 제한 활성화

### 모델 사용 불가

**원인**: 계정 권한 부족 또는 모델 비활성화

**해결책**:
1. 다른 모델 시도
2. 계정 권한 확인 (Gemini Advanced 필요 여부)
3. 새 계정 추가
4. Web 패널에서 사용 가능 모델 확인
