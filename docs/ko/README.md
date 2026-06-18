<div align="center">

<h1>Gemini2API</h1>
<h3>경량 Gemini Web 리버스 프록시</h3>
<p>단일 코드베이스로 OpenAI / Claude / Gemini 3대 주류 AI SDK 호환, 순수 비동기 아키텍처, 공식 키 불필요, Docker 빠른 배포.</p>

<p>
  <img src="https://img.shields.io/badge/Python-3.12+-blue?style=flat-square&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/FastAPI-0.115-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/curl__cffi-Chrome%20TLS-ff6b35?style=flat-square&logo=google-chrome&logoColor=white" alt="curl_cffi">
  <img src="https://img.shields.io/badge/Docker-20.10+-2496ED?style=flat-square&logo=docker&logoColor=white" alt="Docker">
  <img src="https://img.shields.io/badge/Chrome%20%7C%20Edge-Latest-4285F4?style=flat-square&logo=googlechrome&logoColor=white" alt="Browser">
  <img src="https://img.shields.io/badge/License-Non--Commercial-red?style=flat-square" alt="License">
</p>

<p>
  <a href="#-최근-업데이트">최근 업데이트</a> &bull;
  <a href="#-핵심-기능">핵심 기능</a> &bull;
  <a href="#-시스템-요구사항">시스템 요구사항</a> &bull;
  <a href="#-빠른-배포">빠른 배포</a> &bull;
  <a href="#-통합-예제">통합 예제</a> &bull;
  <a href="#-api-엔드포인트">API 엔드포인트</a> &bull;
  <a href="#-설정">설정</a> &bull;
  <a href="#-주의사항">주의사항</a> &bull;
  <a href="#-로드맵">로드맵</a>
</p>

<p>
  📖 문서 언어: <a href="../zh-CN/README.md">简体中文</a> | <a href="../zh-TW/README.md">繁體中文</a> | <a href="../en/README.md">English</a> | <a href="../ja/README.md">日本語</a> | 한국어
</p>

<br>

<a href="https://github.com/xwteam/gemini2api/issues"><img src="https://img.shields.io/github/issues/xwteam/gemini2api?style=flat-square" alt="Issues"></a>
<a href="https://github.com/xwteam/gemini2api/stargazers"><img src="https://img.shields.io/github/stars/xwteam/gemini2api?style=flat-square" alt="Stars"></a>

</div>

---

> [!NOTE]
> 이 프로젝트는 연구 및 학습 목적으로만 사용됩니다. 책임감 있게 사용하고 상업적 목적으로 사용하지 마십시오.

> [!WARNING]
> 이 프로젝트는 Google과 무관합니다. 리버스 엔지니어링된 브라우저 쿠키를 사용하여 Gemini Web에 액세스하며, Google 서비스 약관을 위반할 수 있습니다. 사용에 따른 위험은 본인이 부담합니다. 작성자는 계정 제재 또는 데이터 손실에 대해 책임지지 않습니다.

> [!TIP]
> 완전한 모델 액세스 및 안정적인 경험을 위해 Gemini Pro 이상 구독을 사용하는 것이 좋습니다.

> [!IMPORTANT]
> Google의 보안 정책 제한으로 인해 쿠키 세션은 현재 약 2시간 후 강제로 만료됩니다. 완벽한 장기 유지 솔루션을 아직 찾지 못했습니다. 이 분야에 경험이나 아이디어가 있으시면 [Issue](https://github.com/xwteam/gemini2api/issues) 또는 PR을 통해 공유해 주시기 바랍니다.

---

## 📝 최근 업데이트

> 전체 변경 로그는 [CHANGELOG.md](../../CHANGELOG.md)를 참조하세요.

| 날짜 | 업데이트 내용 |
|------|----------|
| 2026-06-19 03:01:44 | v1.6.16 - 🔧 안정성·보안 강화: 딥리서치 동기 엔드포인트 항상 500, 서드파티 스트리밍 전달 실패, 계정 슬롯 누수 교착, 다중 계정 모델 해석 혼선, 간헐적 "Client not ready", 작동하지 않던 레이트리밋 수정; 🔒 보안: 관리/업무 키 분리(선택 `ADMIN_API_KEY`), API 키 로그 마스킹, 이중 SSRF 방어, 키 내보내기/PSID 마스킹, 자격증명 파일 원자적 쓰기, CORS 구성 가능, 상수 시간 비교; 🧪 자동화 테스트 + CI 게이트 및 패널 접근성/다국어 개선 추가. 무회귀(58 테스트 통과)|
| 2026-06-06 19:29:01 | v1.6.15 - 🧹 Gemini 웹 측 누적 세션 자동 정리: API 대화마다 웹 측에 기록이 남아 장기적으로 누적됨. 이제 백그라운드에서 주기적으로(기본 6시간마다) 보존 기간(기본 24시간)을 초과한 오래된 세션을 삭제; 고정 세션은 삭제 안 함; 루프 정리로 대량 누적 계정도 처리; 보존 기간이 프록시 컨텍스트 기간(6h)보다 훨씬 길어 진행 중인 멀티턴 대화는 잘못 삭제되지 않음; 설정에 "웹 세션 정리" 그룹 추가 |
| 2026-06-02 20:16:19 | v1.6.14 - 🖼️ 이미지 생성 의도 인식에 의지 동사 추가：「〜 이미지를 원해요」「이미지가 필요해요」「포스터를 원해」등 원하다/필요하다로 표현되는 이미지 생성 요청을 정확하게 인식하고 이미지를 앞에 배치(이전에는 이미지가 텍스트 뒤에 배치되거나 http 조각이 나타남)；오탐을 방지하기 위해 이미지 명사+동사 공기는 여전히 필요 |
| 2026-06-02 18:51:41 | v1.6.13 - 🖼️ 이미지 생성 응답을 이미지 우선+컴팩트 레이아웃으로 변경(더 이상 긴 텍스트+빈 줄+이미지가 아님)；이미지 생성 의도 인식 대폭 향상(그려/생성/디자인/만들어/〜 이미지…, 포스터/logo/poster 등 구어체 요청도 정확하게 이미지를 생성하고 이미지가 앞에 표시됨)；image_retrieval/image_collection 검색 플레이스홀더 URL 필터링, 유효한 이미지가 없을 때 빈 콘텐츠 대신 친절한 안내 메시지 표시 |
| 2026-06-02 16:37:57 | v1.6.12 - 🛠️ agent(예: Hermes)가 tools를 가질 때 이미지 생성 억제 및 도구 호출 기형 JSON 투과 수정：이미지 생성 의도 감지 시 도구 시뮬레이션을 건너뛰고 직접 생성；도구 호출 다층 내결함성 파싱(markdown 제거/JSON 추출/기형 허용), 기형이 더 이상 투과되지 않음；Gemini 네이티브 API 도구 호출이 functionCall을 올바르게 반환 |
| 2026-06-02 13:04:39 | v1.6.11 - 🔁 503 지능형 failover：Google이 데이터센터 IP에 간헐적으로 503 속도 제한을 걸 때, 다중 계정 구성에서는 다음 사용 가능한 계정으로 자동 전환하여 재시도(하나가 제한되면 즉시 전환), 제한된 계정은 30s 쿨다운에 진입하지만 무효로 표시되지 않음; 단일 계정 5xx는 빠른 재시도만 하고 긴 backoff 시간 낭비 없음 |
| 2026-06-01 20:21:43 | v1.6.10 - ⚡ 진정한 스트리밍 출력：세 API 모두 진정한 증분 스트리밍으로 변경(첫 문자가 생성되면 즉시 푸시, 전체 청크가 생성될 때까지 기다렸다가 문자별로 가짜 출력하는 방식 폐지), 채팅 경험이 크게 향상; 🚀 동시성 대폭 향상：단일 계정 동시 처리 3→8, 만재 시 대기열에 추가하고 즉시 "No available accounts" 오류를 반환하지 않음, agent가 동시 요청에서 더 이상 실패하지 않음 |
| 2026-06-01 00:32:16 | v1.6.9 - 🖼️ 생성 이미지를 전체 해상도 원본으로 반환: 이전에는 압축 썸네일(512px)을 다운로드했으나, 이제 `=s0`를 붙여 원본 크기(예: 1408×768)를 가져옴 |
| 2026-06-01 00:18:01 | v1.6.8 - 🖼️ 이미지 생성 시 googleusercontent 플레이스홀더 URL을 반환하지 않음: 의미 없는 플레이스홀더를 응답에서 제거하여 이미지 자체만 반환 |
| 2026-06-01 00:02:09 | v1.6.7 - 🖼️ 컨트롤 패널 모델 테스트에서 이미지가 표시되지 않는 문제 수정: 생성된 이미지를 이제 직접 렌더링하여 표시, markdown 텍스트/URL로 표시되지 않음 |
| 2026-05-31 23:41:15 | v1.6.6 - 🖼️ 생성 이미지 로컬 호스팅: 대화 엔드포인트의 이미지 생성 결과를 접근 가능한 로컬 URL(/images/{id}) 반환 방식으로 변경하여 CLI/agent 클라이언트에서도 정상적으로 렌더링 표시(base64는 이런 클라이언트에서 표시 불가); 이미지는 주기적으로 자동 정리 |
| 2026-05-31 22:36:53 | v1.6.5 - 🎨 AI 이미지 생성: OpenAI 호환 /v1/images/generations 엔드포인트 신규 추가(b64_json 반환); 3대 대화 엔드포인트에서 생성된 이미지를 감지하면 자동으로 응답에 삽입(markdown / image block / inlineData) |
| 2026-05-31 17:00:00 | v1.6.4 - 세 가지 API 모두 표준 베어 경로(/v1/chat/completions, /v1/messages, /v1beta/...) 노출, 주요 SDK 즉시 사용 가능; 배포 메커니즘 수정(docker-compose를 build에서 image로 변경하여 docker compose pull이 실제로 작동) |
| 2026-05-31 14:10:00 | v1.6.3 - 이미지/파일 업로드 지원(OpenAI/Claude/Gemini 멀티모달); 모델을 웹 버전 실제 데이터로 변경 + 고정 안정 이름(gemini-pro/flash/flash-thinking); 재시작 시 Cookie 손실 없음 |
| 2026-05-19 20:00:00 | v1.6.2 - 5분간 작업이 없으면 세션 자동 만료 및 로그아웃 |
| 2025-05-18 16:30:00 | v1.6.1 - 다크 테마 전면 수정, 업데이트 확인 대화상자 미화, GitHub Actions 자동 이미지 빌드, failover 장애 조치 전략 |
| 2025-05-17 23:20:00 | 모델 목록을 사용자 친화적 이름으로 통일, 사고 모드(gemini-2.5-flash-thinking) 및 Pro 모드 추가, Playground 대화 컨텍스트 수정 |
| 2025-05-17 22:30:00 | 컨테이너 시간대를 Asia/Shanghai로 수정, 로그에 베이징 시간 표시 |

---

## 🌟 핵심 기능

> 📖 자세한 사용 문서: [USAGE.md](USAGE.md)

### 🔌 3-in-1 프로토콜 호환

- 하나의 서비스로 OpenAI, Claude, Gemini 세 가지 SDK 형식 동시 제공
- SSE 스트리밍 출력(OpenAI / Claude) + Chunked JSON(Gemini)
- 함수 호출(Function Calling) 세 가지 형식 모두 지원
- Deep Research 다단계 심층 연구

### 🔐 보안 및 인증

- API Key 자동 생성(`sk-` 접두사 + 32자 무작위 문자열)
- `Authorization: Bearer` 및 `x-api-key` 두 가지 인증 방식 지원
- 첫 배포 시 자동으로 키 생성, 사용자 정의 수정 가능

### 🔄 다중 계정 로테이션 및 쿠키 자가 치유

- **다중 계정 로드 밸런싱**: round-robin(순환) 및 failover(장애 조치) 두 가지 전략 지원
- 계정별 독립적인 동시성 제어로 단일 계정 과부하 방지
- 연속 실패 시 자동으로 비정상 표시, 장애 계정 자동 건너뛰기
- 백그라운드 자동 쿠키 로테이션, 무감각 갱신
- 쿠키 핫 업데이트 API, 컨테이너 재시작 불필요
- API를 통한 계정 동적 추가/제거 지원
- 건강 검사 기록, 웹 패널에 데이터 제공

### 🛡 탐지 방지 및 프로토콜 위장

- **TLS 지문 일관성**: UA, Sec-Ch-Ua, curl_cffi impersonate 세 가지 버전 항상 동기화(현재 Chrome 124)
- **동적 요청 헤더**: Chrome 실제 순서로 정렬, 요청 유형(탐색 GET / API POST)에 따라 Sec-Fetch-* 값 동적 조정
- **완전한 쿠키 지속성**: 모든 응답 쿠키 자동 캡처 및 디스크에 지속, 재시작 후에도 유지
- **쿠키 도메인 격리**: 각 요청 전 세션 내부 쿠키 지우기, 도메인 간 누적 충돌 방지
- **Chrome 버전 자동 동기화**: 24시간마다 Google 버전 API 폴링, 새 버전 감지 시 자동으로 지문 구성 업데이트
- **요청 시간 지터**: 인간 작업 간격 시뮬레이션(탐색 200-800ms / API 50-300ms / 쿠키 로테이션 1-3s)
- **버전 다운그레이드 전략**: curl_cffi가 최신 Chrome 버전을 지원하지 않을 때 자동으로 가장 가까운 사용 가능한 버전 사용

### 🖥 웹 관리 패널

- 한국어 시각화 관리 인터페이스, API Key 로그인 인증
- 우측 상단 제어 바: 테마 전환, 서비스 재시작, 로그아웃
- 대시보드: 실시간 가동 시간 카운터, QR 코드 카드(이미지 확대 지원), 시스템 정보(버전/Python/OS/메모리/CPU/PID/실행 모드), 구성 관리(로테이션 전략/동시성 제한), 계정 상태 개요, 사용 가능한 모델 목록
- **핫 업데이트 리소스**: `api/` 디렉토리 볼륨 마운트, QR 코드 이미지 및 텍스트 구성 수정 후 페이지 새로고침만으로 적용, 컨테이너 재빌드 불필요
- 계정 관리: 계정 추가/삭제, 개별 쿠키 업데이트, 건강 검사
- **설정 페이지**: 런타임 구성 시각화 관리(성능, 속도 제한, 건강 검사, 계정 관리 등), 수정 즉시 적용 및 런타임에 전파
- **모델 매핑**: 요청의 모델 이름을 실제 사용 모델로 매핑(예: gpt-4o → gemini-2.5-pro)
- **API Key 관리**: 타사 대형 모델 API Key 중앙 관리(OpenAI/Anthropic/Gemini/OpenRouter/사용자 정의), 가져오기/내보내기 지원
- Playground: 온라인 API 요청 테스트
- 실시간 로그: 구조화된 테이블 표시, 방향 필터링, 텍스트 검색, 페이지네이션(페이지당 15개), JSON 세부 정보 패널, 디스크에 로그 지속(재시작 후에도 유지)
- 다크/라이트 테마 전환, 반응형 모바일 적응

### 🔀 통합 전달 엔진

- 요청 모델이 Gemini Web 사용 가능 목록에 없을 때 API Key 풀에서 자동 매칭 및 해당 Provider로 전달
- OpenAI 호환 형식 직접 전달(스트리밍 포함), Anthropic 형식 양방향 변환
- `/openai/v1/models`는 Gemini Web 모델 + API Key 풀의 타사 모델 자동 집계
- 하나의 인터페이스, 하나의 Key로 모든 대형 모델 호출

### ⚡ 고성능 아키텍처

- Python asyncio + curl_cffi 기반, 전체 체인 논블로킹
- Chrome TLS 지문 위장 + 버전 자동 추적, 세션 생존 시간 대폭 연장
- Pydantic 강력한 타입 검증, 요청 매개변수 자동 검증
- 모듈식 설계, 각 API 형식 독립 라우팅 파일
- 실패 자동 재시도, 지수 백오프 전략

---

## 📋 시스템 요구사항

| 종속성 | 버전 | 설명 |
|------|------|------|
| Python | 3.12+ | 3.12 권장, 낮은 버전 미테스트 |
| Docker | 20.10+ | 선택 사항, Docker 배포 권장 |
| Google 계정 | — | [gemini.google.com](https://gemini.google.com)에 정상적으로 액세스 가능해야 함 |
| 브라우저 | Chrome / Edge | 쿠키 획득용(배포 시에만 필요) |

> [!TIP]
> Docker 배포를 사용하면 로컬에 Python 환경을 설치할 필요가 없으며, Docker와 유효한 쿠키만 있으면 됩니다.

---

## ⚡ 빠른 배포

> 📖 자세한 배포 문서: [DEPLOY.md](DEPLOY.md)

> **전제 조건**: Gemini를 정상적으로 사용할 수 있는 Google 계정이 필요합니다.

### 1. 쿠키 획득

1. Chrome 또는 Edge 브라우저로 [gemini.google.com](https://gemini.google.com) 방문
2. Google 계정으로 로그인하고 Gemini 대화를 정상적으로 사용할 수 있는지 확인
3. `F12`를 눌러 개발자 도구 열기
4. 상단의 **Application**(애플리케이션) 탭 클릭
5. 왼쪽 사이드바에서 **Cookies** -> `https://gemini.google.com` 클릭
6. 쿠키 목록에서 다음 두 값 찾기:

| 쿠키 이름 | 설명 |
|-------------|------|
| `__Secure-1PSID` | `g.`로 시작하는 긴 문자열, 일반적으로 수십 자 |
| `__Secure-1PSIDTS` | 짧은 문자열 |

7. 시크릿 모드에서 작업하는 것이 좋으며, 필요한 값을 얻은 후 즉시 창을 닫아 페이지 새로고침으로 인한 쿠키 로테이션 실패 방지

> [!TIP]
> 검색 상자에 `__Secure-1P`를 입력하여 빠르게 필터링할 수 있습니다. Value 열을 더블 클릭하면 전체 값을 복사할 수 있습니다.

> [!WARNING]
> 쿠키에는 유효 기간이 있으며, 만료되면 다시 획득해야 합니다. 서비스가 갑자기 사용할 수 없게 되면 먼저 쿠키가 만료되었는지 확인하십시오.

### 2. Docker 배포

```bash
# 저장소 복제
git clone https://github.com/xwteam/gemini2api.git
cd gemini2api

# 환경 변수 파일 생성
cp .env.example .env
```

`.env` 파일을 편집하여 쿠키 입력:

```env
GEMINI_PSID=g.a000xxx...(전체 __Secure-1PSID 값 붙여넣기)
GEMINI_PSIDTS=sidts-xxx...(전체 __Secure-1PSIDTS 값 붙여넣기)
```

> [!IMPORTANT]
> 주의사항:
> - 값에 따옴표가 필요하지 않음
> - 추가 공백이나 줄 바꿈이 없어야 함
> - 전체 값을 복사했는지 확인하고 끝 문자를 누락하지 않도록 함

서비스 시작:

```bash
docker compose up -d
```

로그를 확인하여 시작 성공 확인:

```bash
docker compose logs -f
# "Account pool ready: 1/1 active"가 표시되면 계정 풀 준비 완료
# "SNlM0e not found"가 표시되면 쿠키가 유효하지 않으므로 다시 획득해야 함
```

### 3. 검증

```bash
# 건강 검사
curl http://localhost:5918/health
# {"status":"ok","service":"gemini2api"}

# 사용 가능한 모델 보기(API Key 필요, 첫 시작 시 로그에서 확인)
curl http://localhost:5918/openai/v1/models \
  -H "Authorization: Bearer sk-당신의API키"

# 테스트 요청 보내기
curl -X POST http://localhost:5918/openai/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-당신의API키" \
  -d '{"model":"gemini-2.0-flash","messages":[{"role":"user","content":"hi"}]}'
```

AI 응답 텍스트가 표시되면 배포 성공입니다. 401이 반환되면 API Key가 올바른지 확인하십시오.

---

## 🧪 통합 예제

> [!NOTE]
> 모든 API 요청에는 API Key가 필요합니다. 두 가지 방식 지원:
> - `Authorization: Bearer sk-xxx`(권장, OpenAI/Claude SDK 호환)
> - `x-api-key: sk-xxx`
>
> API Key는 첫 시작 시 자동으로 생성되어 `.env` 파일에 기록되며, 로그에서 확인하거나 수동으로 수정할 수 있습니다.

<details>
<summary><b>OpenAI SDK (Python)</b></summary>

```python
from openai import OpenAI

client = OpenAI(
    api_key="sk-당신의API키",
    base_url="http://localhost:5918/openai/v1"
)

for chunk in client.chat.completions.create(
    model="gemini-2.0-flash",
    messages=[{"role": "user", "content": "상대성 이론을 세 문장으로 설명해주세요"}],
    stream=True
):
    print(chunk.choices[0].delta.content or "", end="")
```

</details>

<details>
<summary><b>Claude SDK (Python)</b></summary>

```python
import anthropic

client = anthropic.Anthropic(
    api_key="sk-당신의API키",
    base_url="http://localhost:5918/claude"
)

msg = client.messages.create(
    model="gemini-2.0-flash",
    max_tokens=4096,
    messages=[{"role": "user", "content": "퀵 정렬의 Python 구현을 작성해주세요"}]
)
print(msg.content[0].text)
```

</details>

---

## 📡 API 엔드포인트

> 📖 자세한 API 문서: [API.md](API.md)

### OpenAI 호환 (`/openai/v1`)

| 메서드 | 엔드포인트 | 기능 |
|------|------|------|
| GET | `/models` | 사용 가능한 모델 목록 |
| POST | `/chat/completions` | 대화 완성(스트리밍 + 도구 호출 지원) |

### Claude 호환 (`/claude/v1`)

| 메서드 | 엔드포인트 | 기능 |
|------|------|------|
| GET | `/models` | 모델 목록 |
| GET | `/models/{id}` | 모델 세부 정보 |
| POST | `/messages` | 메시지 생성(스트리밍 + 도구 호출 지원) |
| POST | `/messages/count_tokens` | 토큰 수 추정 |

### Gemini 네이티브 (`/gemini/v1beta`)

| 메서드 | 엔드포인트 | 기능 |
|------|------|------|
| GET | `/models` | 모델 목록 |
| POST | `/models/{m}:generateContent` | 콘텐츠 생성 |
| POST | `/models/{m}:streamGenerateContent` | 스트리밍 생성(Chunked JSON) |

### 관리 인터페이스 (`/admin`)

전체 관리 인터페이스 목록은 메인 README 또는 [API.md](API.md)를 참조하십시오.

---

## ⚙ 설정

| 변수 | 필수 | 기본값 | 설명 |
|------|------|--------|------|
| `GEMINI_PSID` | ✅ | — | 브라우저 `__Secure-1PSID` |
| `GEMINI_PSIDTS` | ✅ | — | 브라우저 `__Secure-1PSIDTS` |
| `API_KEY` | ❌ | 자동 생성 | API 액세스 키(`sk-`로 시작, 비워두면 첫 시작 시 자동 생성) |
| `REFRESH_INTERVAL` | ❌ | `5` | 쿠키 새로고침 주기(분) |
| `MAX_RETRIES` | ❌ | `3` | 실패 재시도 횟수(지수 백오프) |
| `PORT` | ❌ | `5918` | 서비스 포트 |
| `LOG_LEVEL` | ❌ | `info` | 로그 레벨(debug/info/warning/error) |
| `ROTATION_STRATEGY` | ❌ | `round-robin` | 로테이션 전략: `round-robin`(순환) / `failover`(장애 조치) |
| `MAX_CONCURRENT_PER_ACCOUNT` | ❌ | `3` | 계정당 최대 동시 요청 수 |

전체 구성 목록은 메인 README를 참조하십시오.

---

## ⚠ 주의사항

1. **쿠키 유효 기간**: Google 쿠키는 정기적으로 만료됩니다(일반적으로 수 시간에서 수 일). 서비스에 자동 새로고침 메커니즘이 내장되어 있지만, 계정이 로그아웃되거나 비밀번호가 변경되면 쿠키를 다시 획득해야 합니다.

2. **스트리밍 출력**: 모든 API 엔드포인트는 기본적으로 스트리밍 방식으로 반환됩니다. `stream: false`로 설정하면 서비스 내부에서 여전히 스트리밍 방식으로 데이터를 수신하고, 수집 완료 후 전체 JSON을 한 번에 반환합니다.

3. **모델 가용성**: 사용 가능한 모델 목록은 Google 계정 권한에 따라 다릅니다. 무료 계정과 Gemini Advanced 계정이 보는 모델이 다르며, 서비스 시작 시 자동으로 감지됩니다.

4. **요청 빈도**: 내장 속도 제한을 끄더라도(`RATE_LIMIT_ENABLED=false`) Google 측에는 여전히 빈도 제한이 있습니다. 고빈도 요청은 CAPTCHA 또는 임시 차단을 유발할 수 있으므로 호출 빈도를 합리적으로 제어하는 것이 좋습니다.

5. **네트워크 환경**: 배포 서버는 `gemini.google.com`에 직접 액세스할 수 있어야 하며, 일부 지역에서는 프록시 구성이 필요할 수 있습니다.

---

## 🗺 로드맵

- [x] OpenAI / Claude / Gemini 3가지 형식 호환
- [x] 스트리밍 응답 + 함수 호출
- [x] Deep Research 심층 연구
- [x] Docker 배포
- [x] API Key 인증
- [x] 쿠키 핫 업데이트 API
- [x] 계정 상태 정기 검사
- [x] 다중 계정 로테이션(로드 밸런싱)
- [x] 웹 관리 패널
- [x] 탐지 방지 및 프로토콜 위장(TLS 지문 일관성, 쿠키 지속성, 버전 자동 동기화)
- [x] 설정 페이지(시각화 구성 관리)
- [x] API Key 관리(타사 대형 모델 Key 중앙 관리)
- [x] 통합 전달 엔진(하나의 인터페이스로 모든 대형 모델 호출)
- [x] 모델 매핑(별칭→실제 모델 이름, 예: gpt-4o → gemini-2.5-pro)
- [x] 로테이션 전략 런타임 핫 업데이트(설정 수정 즉시 적용)
- [x] 대시보드 시스템 정보 패널(버전/Python/OS/메모리/CPU/PID/실행 모드)
- [x] 대화 컨텍스트 지속성
- [ ] 이미지/파일 업로드 지원
- [x] 웹 측 누적 세션 자동 정리(오래된 세션 정기 삭제, 고정 세션 보존)

---

## ☕ 후원 & 기여

도움이 되셨나요? 작성자에게 커피를 사주거나 WeChat 그룹에 가입하여 지원을 받으세요. 자세한 내용은 [SPONSORS.md](SPONSORS.md)를 참조하세요.

PR과 Issue를 환영합니다.

1. 이 저장소를 포크하기
2. 브랜치 생성 `git checkout -b feature/your-feature`
3. 코드 커밋 `git commit -m "feat: add something"`
4. 푸시 및 풀 리퀘스트 생성

---

## 🙏 감사의 말

[Issues](https://github.com/xwteam/gemini2api/issues)에서 버그 재현, 로그, 호환성 피드백, 기능 제안을 제출해 주신 모든 사용자에게 감사드립니다. 이러한 피드백이 Cookie 유지, 다중 계정 순환, 모델 선택, 다국어 지원, Web 패널 등 핵심 기능의 발전을 직접적으로 이끌었습니다.

---

## 📄 라이선스

이 프로젝트는 [비상업적 라이선스 (Non-Commercial)](../../LICENSE)를 채택합니다:

- **허용**: 개인 학습, 연구, 자체 배포
- **금지**: 판매, 재판매, 유료 프록시, 상업 제품 통합을 포함한 모든 형태의 상업적 사용

이 프로젝트는 Google과 무관합니다. 사용자는 스스로 위험을 부담하고 Google의 서비스 약관을 준수해야 합니다.

---

<div align="center">
  <sub>Built with Python + FastAPI + curl_cffi | Powered by Gemini Web</sub>
</div>
