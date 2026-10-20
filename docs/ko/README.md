<div align="center">

<img src="../logo.png" width="128" height="128" alt="Gemini2API">

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
  <a href="#-액세스-키">액세스 키</a> &bull;
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

> 최근 10개 업데이트만 표시합니다. 전체 변경 로그는 [CHANGELOG.md](../../CHANGELOG.md)를 참조하세요.

| 날짜 | 업데이트 내용 |
|------|----------|
| 2026-09-12 10:15:00 | v1.6.40 - 🔍 모델 테스트 페이지가 실제 오류를 "응답 내용 없음"으로 표시하던 문제 수정(issue #11 후속): 스트리밍 중 실패는 스트림 내 error 프레임으로만 표현되는데 프런트가 그 키를 읽지 않아 503/529/500/400이 모두 똑같이 보였습니다. 이제 실제 원인과 상태 코드를 표시하며 이미 출력된 내용도 지워지지 않습니다. 계정 카드에 실제 상태 정보(`is_healthy`/연속 실패 수/마지막 성공 시각/비식별화된 최근 오류) 추가 —— 녹색 ACTIVE 배지는 풀의 status 열거형이지 클라이언트 헬스 플래그가 아니라서, 쿠키가 죽은 계정도 녹색으로 보였습니다. 빈 응답을 성공으로 조용히 삼키지 않습니다(연속 3회부터 오류 집계, 1회로는 절대 강등 안 함). 시작 시 쿠키 로테이션 루프가 실제로 시작됐는지 로그에 명시 |
| 2026-09-01 16:20:00 | v1.6.39 - ⚙️ `LOG_BODIES_ENABLED`를 관리 패널의 새 「로그」 그룹에서 바로 켜고 끌 수 있습니다. 즉시 적용되며 설정 수정이나 재시작이 필요 없습니다(기본값은 여전히 꺼짐); ⚠️ 동작 변경: 패널에서 저장한 설정은 이제 `data/settings-overrides.json`에 저장되어 **환경 변수보다 우선**합니다(이전에는 패널에서 바꿔도 재시작하면 되돌아갔습니다); 소수점 필드가 `parseInt`로 잘리는 문제 수정, NaN/±Infinity 거부, 쓰기 실패 시 세 계층(메모리/오버라이드 파일/.env) 전부 아니면 전무 롤백; 원시 필드명이나 중국어로 표시되던 라벨 정비 및 가드 테스트 추가 |
| 2026-09-01 13:10:00 | v1.6.38 - 🍪 동일 이름 쿠키가 여러 도메인에 공존할 때(Google이 .com.hk 등 국가 도메인으로 리디렉션하는 경우) 세션 토큰 획득이 통째로 실패하고 계정이 잘못 unhealthy로 표시되던 문제 수정(issue #10 후속, issue #11 멈춤의 실제 유발 원인 중 하나). 도구 호출 JSON이 잘못된 경우 자동으로 1회 재생성(재시도 중에도 스트림 keepalive 유지). 요청/응답 전문 로깅 `LOG_BODIES_ENABLED` 추가(기본 꺼짐, 메모리 전용·디스크 미저장·요청 헤더 미기록) |
| 2026-08-30 18:20:00 | v1.6.37 - 🩺 계정 풀이 영구적으로 멈추고 "All accounts busy"를 잘못 보고하던 문제 수정(issue #11): 세션이 만료된 계정 때문에 모든 요청이 60초를 기다린 뒤 잘못된 529를 반환했으나, 이제 정확한 503으로 즉시 실패하며 **쿠키 재로드로 자동 복구를 시도**합니다. 클라이언트 연결 해제는 더 이상 계정 실패로 집계되지 않으며(‘중지’ 3회로 단일 계정 풀이 마비될 수 있었음), 쿠키 재로드 실패가 정상 계정을 영구히 비활성화하지 않습니다 |
| 2026-08-28 19:40:00 | v1.6.36 - 🚨 OpenAI 스트리밍에서 업스트림 오류가 정상 답변으로 위장되지 않습니다(표준 `error` 프레임 전송으로 SDK 클라이언트가 예외를 발생시키고 재시도 가능); 업스트림 4xx 오류 타입 세분화; Anthropic `citations` 필드를 스트리밍/비스트리밍 간 일치; 문자열이 아닌 `content`로 인한 500 해소 |
| 2026-08-28 17:30:00 | v1.6.35 - 🛠️ 프로토콜 정합성·견고성 대규모 수정: 이미지 의도 오탐으로 **클라이언트 도구가 조용히 삭제**되던 문제(4개 프로토콜 공용), 업스트림 오류가 정상 답변으로 위장되던 문제, `HTTPStatusError`가 맨 500으로 새던 문제(풀 고갈은 529+Retry-After), `/v1/responses`·네이티브 Gemini buffered 분기의 keepalive 누락, 네이티브 Gemini가 공식 SDK camelCase를 거부하던 문제, OpenAI `tool_calls` 유실, 서드파티 Anthropic 전달의 도구 루프 2라운드 실패, Anthropic 응답 구조 정합성 수정 |
| 2026-08-28 15:10:00 | v1.6.34 - 🧹 Anthropic 프로토콜 세부 정리: 응답에 규격상의 `stop_sequence` 필드 추가 및 5개 언어 API 문서 동기화; 도구 호출 블록의 `name`이 null일 때 Python 리터럴 None으로 렌더링되지 않음; 연결 해제 keepalive 가드에서 예외 회수; 도구 렌더링 형식·연결 해제 취소 테스트 강화 |
| 2026-08-28 14:20:00 | v1.6.33 - 🔌 Claude Code 연결 오류 수정(issue #10): `system`이 텍스트 블록 배열 형식을 지원하여 422 해소; `tool_use`/`tool_result` 블록이 더 이상 삭제되지 않아 도구 루프 정상 동작; Anthropic 스트리밍을 표준 `event:`+`data:` 2줄 형식으로 변경; Claude buffered 스트림에 keepalive 추가 및 연결 해제 시 계정 슬롯 즉시 반환 |
| 2026-08-14 22:50:00 | v1.6.32 - 🧠 사고를 프레임 단위로 스트리밍: 네이티브 Gemini의 사고가 생성 중 reasoning_content로 점진적으로 스트리밍되어(/v1/chat/completions) 답변보다 먼저 타이핑 효과로 표시됩니다. 패널의 '답변이 사고보다 먼저' 문제 수정. 마지막 프레임은 전체 사고를 폴백으로 유지. 사고 미사용/일반 채팅은 무회귀 |
| 2026-08-14 22:40:00 | v1.6.31 - 🌊 스트리밍 간헐적 끊김 수정: 모델 생성 중 무음 구간에 네 개의 스트리밍 API(/v1/chat/completions, /v1/responses, /v1/messages, 네이티브 Gemini streamGenerateContent)에서 keepalive 하트비트를 전송하여 긴 응답이 국경 간/게이트웨이 유휴 시간 초과로 끊기지 않도록 함. 오해를 유발하던 패널 오류 문구도 수정 |

---

## 🌟 핵심 기능

> 📖 자세한 사용 문서: [USAGE.md](USAGE.md)

### 🔌 3-in-1 프로토콜 호환

- 하나의 서비스로 OpenAI, Claude, Gemini 세 가지 SDK 형식 동시 제공
- SSE 스트리밍 출력(OpenAI / Claude) + Chunked JSON(Gemini)
- 함수 호출(Function Calling) 세 가지 형식 모두 지원
- Deep Research 다단계 심층 연구
- **사고 단계 구분**: `reasoning_effort`의 `low` / `medium` / `high`가 각각 다른 사고 깊이로 매핑됩니다(`none` / `minimal`은 low로, `xhigh`는 high로 클램프). 이 파라미터를 보내지 않으면 동작은 이전 버전과 동일합니다
- **첨부 파일이 있어도 진짜 스트리밍**: 이미지나 파일이 포함된 요청도 전체 생성이 끝날 때까지 기다리지 않고 첫 토큰부터 내보냅니다(도구 호출이 포함된 요청은 여전히 buffered —— 도구 인자는 완전한 JSON이어야 파싱할 수 있기 때문)

### 🔐 보안 및 인증

- API Key 자동 생성(`sk-` 접두사 + 32자 무작위 문자열)
- `Authorization: Bearer` 및 `x-api-key` 두 가지 인증 방식 지원
- 첫 배포 시 자동으로 키 생성, 사용자 정의 수정 가능
- **액세스 키**: 관리자가 배포용 인바운드 키를 여러 개 발급할 수 있습니다. 키마다 유효 기간("최초 사용 시점부터 계산"하는 지연 활성화 지원), 요청 한도, 바인딩 계정, 허용 모델을 따로 설정할 수 있고 언제든 비활성화하거나 삭제할 수 있습니다
- `.env`의 `API_KEY`는 항상 모든 권한을 가지며, 액세스 키는 **추가** 계층일 뿐입니다. 또한 액세스 키는 업무 API만 호출할 수 있고 `/admin/*`에는 접근할 수 없습니다(자세한 내용은 아래 [🔑 액세스 키](#-액세스-키))

### 🔄 다중 계정 로테이션 및 쿠키 자가 치유

- **다중 계정 로드 밸런싱**: round-robin(순환) 및 failover(장애 조치) 두 가지 전략 지원
- 계정별 독립적인 동시성 제어로 단일 계정 과부하 방지
- 연속 실패 시 자동으로 비정상 표시, 장애 계정 자동 건너뛰기
- 백그라운드 자동 쿠키 로테이션, 무감각 갱신
- 쿠키 핫 업데이트 API, 컨테이너 재시작 불필요
- API를 통한 계정 동적 추가/제거 지원
- 건강 검사 기록, 웹 패널에 데이터 제공
- **쿠키 로테이션 루프가 시작 시점부터 상주**: 이전에는 "시작할 때 토큰을 가져오지 못한" 경우에만 로테이션 루프가 올라왔기 때문에, 정상적으로 시작한 게이트웨이는 한 번도 로테이션하지 않고 쿠키가 몇 시간 만에 죽었습니다([issue #11](https://github.com/xwteam/gemini2api/issues/11)). 이제는 무조건 상주합니다
- **HTTP 200 안의 거부 블록 인식**: Gemini는 때때로 200 응답 본문에 거부 블록(속도 제한 / 세션 만료 / 컨텍스트 초과 / CAPTCHA)을 담아 보냅니다. 예전에는 이런 요청이 "빈 응답"으로 나타나고 자가 복구도 전혀 작동하지 않았지만, 이제는 명확한 오류로 변환되어 쿨다운 + 계정 전환 재시도를 거칩니다. `BARD_ERROR_CODES`로 개별 코드에 의미를 지정할 수 있습니다

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
- **액세스 키**: 배포용 인바운드 키를 발급/편집/비활성화/삭제하며, 상태·사용량·적용 범위가 목록에 바로 표시됩니다(아래의 "API Key 관리"와는 무관합니다. 그쪽은 타사 **아웃바운드** Key를 관리합니다)
- **API Key 관리**: 타사 대형 모델 API Key 중앙 관리(OpenAI/Anthropic/Gemini/OpenRouter/사용자 정의), 가져오기/내보내기 지원
- Playground: 온라인 API 요청 테스트
- 실시간 로그: 구조화된 테이블 표시, 방향 필터링, 텍스트 검색, 페이지네이션(페이지당 15개), JSON 세부 정보 패널, 디스크에 로그 지속(재시작 후에도 유지)
- 다크/라이트 테마 전환, 반응형 모바일 적응

### 🔀 통합 전달 엔진

- 요청 모델이 Gemini Web 사용 가능 목록에 없을 때 API Key 풀에서 자동 매칭 및 해당 Provider로 전달
- OpenAI 호환 형식 직접 전달(스트리밍 포함), Anthropic 형식 양방향 변환
- `/openai/v1/models`는 Gemini Web 모델 + API Key 풀의 타사 모델 자동 집계
- 하나의 인터페이스, 하나의 Key로 모든 대형 모델 호출
- 타사 자동 폴백(`FALLBACK_ENABLED`, 기본 꺼짐): 임의의 Gemini 모델이 오류를 내거나 빈 응답을 반환하면 API Key 풀의 타사 모델로 자동 전환하여 네이티브 재시도, 클라이언트는 무감각하며 여전히 하나의 모델 이름만 사용; 기본적으로 풀에서 "채팅에 적합한" 모든 타사 모델을 자동 선택(image/video 등 비채팅 모델 제외)하여 무작위 로테이션, 실패 시 다음으로 전환, `FALLBACK_MODELS`로 선택적으로 정확히 지정 가능

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
| POST | `/responses` | OpenAI Responses API(텍스트/스트리밍/도구 호출, Codex CLI 등 신규 클라이언트가 사용) |

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

> 액세스 키의 `/admin/access-keys` 엔드포인트 6개는 아래 [🔑 액세스 키](#-액세스-키)에 정리되어 있습니다.

---

## 🔑 액세스 키

`.env`에 있는 전권 `API_KEY` 외에, 관리자는 **배포용** 액세스 키를 원하는 만큼 발급할 수 있습니다. 키마다 유효 기간, 요청 한도, 사용 가능한 계정, 허용 모델을 따로 설정해 사람별로 나눠주고, 언제든 개별적으로 비활성화하거나 삭제할 수 있습니다. 패널에는 시각적으로 관리할 수 있는 "액세스 키" 페이지가 추가되었고, 백엔드는 `/admin/access-keys` 계열 엔드포인트에 대응합니다.

키는 `data/access_keys.json`(`data/`는 docker-compose의 영속 bind mount)에 저장되므로 재시작해도 사라지지 않습니다.

### 키마다 설정할 수 있는 필드

| 필드 | 설명 |
|------|------|
| `name` | 라벨. 이 키를 누구에게 줬는지 기억하기 위한 항목(비우면 `key-{id}`로 표시) |
| `enabled` | 활성/비활성 스위치. 비활성화하면 소지자는 즉시 401이 되지만, 키는 목록에 남아 언제든 되살릴 수 있습니다 |
| `expires_at` | 절대 만료 시각(ISO8601). 그 시점에 무효화됩니다 |
| `duration_days` | 유효 일수. **지연 활성화**: 나눠주는 것만으로는 시간이 흐르지 않고, 소지자의 첫 요청부터 N일을 계산합니다 |
| `request_limit` | 요청 한도. 누적 횟수가 도달하면 무효화됩니다("사용량 초기화"로 0으로 되돌리면 계속 사용 가능) |
| `bound_account_ids` | 바인딩 계정. 지정한 Gemini 계정만 사용 허용(비우면 = 제한 없음) |
| `allowed_models` | 허용 모델. 지정한 모델 이름만 호출 허용(비우면 = 제한 없음) |

`expires_at`과 `duration_days`는 둘 중 하나만 지정하며, 둘 다 비우면 만료되지 않는 키가 됩니다.

### 키 상태

| 상태 | 의미 |
|------|------|
| 유효 | 정상적으로 호출 가능 |
| 비활성 | 관리자가 `enabled`를 끈 상태 |
| 미활성 | `duration_days`는 설정됐지만 아직 사용된 적이 없어 계산이 시작되지 않음 |
| 만료됨 | `expires_at`이 지남 |
| 한도 초과 | `request_count`가 `request_limit`에 도달함 |

판정은 "비활성 → 만료됨 → 한도 초과 → 미활성 → 유효" 우선순위로 단축 평가됩니다.

### 엔드포인트

| 메서드 | 엔드포인트 | 기능 |
|------|------|------|
| GET | `/admin/access-keys` | 모든 액세스 키 목록(상태·사용량·적용 범위 포함) |
| GET | `/admin/access-keys/options` | 패널 발급 폼의 선택 항목(계정 풀의 계정 + 외부에 노출되는 모델 이름) |
| POST | `/admin/access-keys` | 키 발급. `count`로 일괄 발급(최대 50) |
| PATCH | `/admin/access-keys/{id}` | 설정 변경(특정 필드를 비우려면 `clear` 배열 사용, 아래 참조) |
| DELETE | `/admin/access-keys/{id}` | 키 삭제 |
| POST | `/admin/access-keys/{id}/reset-usage` | 요청 카운트 초기화 |

```bash
# 1개 발급: 최초 사용 시점부터 7일 유효, 최대 500회 요청, flash만 허용
curl -X POST http://localhost:5918/admin/access-keys \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-내API키" \
  -d '{"name":"홍길동","duration_days":7,"request_limit":500,"allowed_models":["gemini-flash"]}'

# 같은 설정의 키를 20개 일괄 발급(이름은 trial-1 … trial-20으로 자동 번호 부여)
curl -X POST http://localhost:5918/admin/access-keys \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-내API키" \
  -d '{"name":"trial","count":20,"duration_days":3}'

# 모든 키 목록
curl http://localhost:5918/admin/access-keys \
  -H "Authorization: Bearer sk-내API키"

# 3번 키 비활성화
curl -X PATCH http://localhost:5918/admin/access-keys/3 \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-내API키" \
  -d '{"enabled":false}'

# 3번 키의 요청 한도와 모델 제한 해제: JSON의 null은 "변경하지 않음"을 뜻하므로,
# 필드를 비우려면 필드 이름을 clear 배열에 넣어야 합니다
curl -X PATCH http://localhost:5918/admin/access-keys/3 \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-내API키" \
  -d '{"clear":["request_limit","allowed_models"]}'

# 사용량 카운트 초기화
curl -X POST http://localhost:5918/admin/access-keys/3/reset-usage \
  -H "Authorization: Bearer sk-내API키"
```

### ⚠ 꼭 알아야 할 세 가지 경계

> [!IMPORTANT]
> **1. `.env`의 `API_KEY`는 여전히 모든 권한을 가집니다.** 액세스 키는 **추가** 계층이며 대체가 아닙니다: `API_KEY`에 일치하는 요청은 즉시 통과하고, 키 저장소를 조회하지도 사용량을 집계하지도 않습니다. **액세스 키를 하나도 발급하지 않으면 인증 동작은 이전 버전과 완전히 동일합니다.**
>
> **2. 액세스 키는 업무 API만 호출할 수 있고 `/admin/*`에는 절대 접근할 수 없습니다.** 관리 영역은 여전히 `API_KEY` / `ADMIN_API_KEY`만이 지킵니다. 그래서 외부인에게 액세스 키를 건네도 안전합니다 —— 계정 쿠키를 읽을 수 없고, 설정을 바꿀 수 없으며, 다른 사람의 키도 볼 수 없습니다.
>
> **3. 모든 업무 요청은 `GET /v1/models`를 포함해 +1 집계됩니다.** 카운트는 인증 입구에서 원자적으로 증가하며 단조 증가하고 환불되지 않습니다(업스트림 오류도 집계됨). 일부 클라이언트는 대화마다 모델 목록을 먼저 조회하므로 **한 번의 대화에 2회 소비**합니다 —— `request_limit`을 설정할 때 여유를 두세요.

---

## ⚙ 설정

> [!IMPORTANT]
> **패널에서 변경한 설정 항목은 환경 변수보다 우선합니다.** 웹 패널의 "설정"
> 페이지에서 저장한 항목은 `data/settings-overrides.json`(`data/`는 docker-compose의
> 영속 bind mount)에 기록되고, 시작할 때마다 다시 적용되어 아래 표의 해당 환경 변수를
> **덮어씁니다**. 이는 의도된 동작입니다. 패널에서 `LOG_BODIES_ENABLED`를 끈 뒤
> `docker compose restart`로 다시 켜져서는 안 되기 때문입니다.
>
> 따라서 **`.env`를 수정하고 재시작했는데 반영되지 않는다면** 해당 항목이 패널 설정에
> 덮어써졌을 가능성이 큽니다. 시작 로그의
> `Applied N panel setting override(s) from data/settings-overrides.json: ...`
> 줄이 해당 항목을 알려줍니다. `data/settings-overrides.json`을 삭제하면 환경 변수가
> 다시 제어권을 가집니다.

| 변수 | 필수 | 기본값 | 설명 |
|------|------|--------|------|
| `GEMINI_PSID` | ✅ | — | 브라우저 `__Secure-1PSID` |
| `GEMINI_PSIDTS` | ✅ | — | 브라우저 `__Secure-1PSIDTS` |
| `API_KEY` | ❌ | 자동 생성 | API 액세스 키(`sk-`로 시작, 비워두면 첫 시작 시 자동 생성) |
| `REFRESH_INTERVAL` | ❌ | `30` | 쿠키 새로고침 주기(분, 최소 10) |
| `MAX_RETRIES` | ❌ | `3` | 실패 재시도 횟수(지수 백오프) |
| `PORT` | ❌ | `5918` | 서비스 포트 |
| `LOG_LEVEL` | ❌ | `info` | 로그 레벨(debug/info/warning/error) |
| `RATE_LIMIT_ENABLED` | ❌ | `false` | 속도 제한 활성화 |
| `RATE_LIMIT_WINDOW` | ❌ | `60` | 속도 제한 시간 창(초) |
| `RATE_LIMIT_MAX` | ❌ | `10` | 시간 창 내 최대 요청 수 |
| `HEALTH_CHECK_ENABLED` | ❌ | `true` | 정기 계정 상태 검사 활성화 |
| `HEALTH_CHECK_INTERVAL` | ❌ | `5` | 검사 간격(분) |
| `ACCOUNTS_FILE` | ❌ | `accounts.json` | 다중 계정 설정 파일 경로(존재하지 않으면 환경 변수 단일 계정 모드 사용) |
| `ROTATION_STRATEGY` | ❌ | `round-robin` | 로테이션 전략: `round-robin`(순환) / `failover`(장애 조치) |
| `MAX_CONCURRENT_PER_ACCOUNT` | ❌ | `8` | 계정당 최대 동시 요청 수 |
| `ACQUIRE_TIMEOUT` | ❌ | `60.0` | 동시성 만재 시 사용 가능한 슬롯을 대기열에서 기다리는 상한(초), 기다려도 없으면 오류 |
| `SAME_ACCOUNT_5XX_RETRIES` | ❌ | `1` | 5xx 발생 시 동일 계정 빠른 재시도 횟수(긴 백오프 없음), 그래도 실패하면 failover로 계정 전환 |
| `FAILOVER_COOLDOWN` | ❌ | `30.0` | 5xx로 제한된 계정이 쿨다운에 진입하는 시간(초), 그동안 우선 선택하지 않음 |
| `FINGERPRINT_CONFIG_PATH` | ❌ | `data/fingerprint.json` | 지문 설정 파일 경로 |
| `VERSION_SYNC_ENABLED` | ❌ | `true` | Chrome 버전 자동 동기화 활성화 |
| `VERSION_SYNC_INTERVAL` | ❌ | `24` | 버전 동기화 간격(시간) |
| `JITTER_ENABLED` | ❌ | `true` | 요청 시간 지터 활성화(인간 행동 모의) |
| `USAGE_STATS_ENABLED` | ❌ | `true` | 사용 통계 활성화(시계열 스냅샷 + 지속화) |
| `USAGE_STATS_INTERVAL` | ❌ | `300` | 스냅샷 수집 간격(초) |
| `USAGE_STATS_RETENTION_DAYS` | ❌ | `30` | 히스토리 데이터 보존 일수 |
| `MODEL_WHITELIST` | ❌ | — | 모델 화이트리스트(쉼표 구분, 비워두면 필터링 안 함; 비어 있지 않으면 각 `/models` 목록을 필터링) |
| `CHAT_CLEANUP_ENABLED` | ❌ | `true` | Gemini 웹 측 세션 자동 정리 활성화 |
| `CHAT_CLEANUP_KEEP_HOURS` | ❌ | `24.0` | 웹 세션 보존 기간(시간), 초과 시 정리 |
| `CHAT_CLEANUP_INTERVAL_HOURS` | ❌ | `6.0` | 자동 정리 작업 실행 간격(시간) |
| `CHAT_CLEANUP_SKIP_PINNED` | ❌ | `true` | 정리 시 고정 세션 건너뛰기 |
| `ADMIN_API_KEY` | ❌ | — | 관리 패널/`/admin` 전용 인증 키(비워두면 `API_KEY`로 폴백) |
| `CORS_ALLOW_ORIGINS` | ❌ | `*` | CORS 허용 출처(쉼표 구분, `*`는 전체) |
| `CORS_ALLOW_CREDENTIALS` | ❌ | `true` | CORS 자격 증명 전송 허용 여부 |
| `IMAGE_DOWNLOAD_SIZE_SUFFIX` | ❌ | `=s2048` | 이미지 생성 대리 다운로드 크기 접미사(`=s0`은 전체 해상도 원본) |
| `IMAGE_DOWNLOAD_TIMEOUT` | ❌ | `25.0` | 단일 이미지 다운로드 HTTP 타임아웃(초) |
| `FALLBACK_ENABLED` | ❌ | `false` | Gemini→타사 폴백 활성화: 임의의 Gemini 모델(flash/pro/thinking)이 오류를 내거나 빈 응답을 반환하면 API Key 풀의 타사 모델로 자동 전환하여 "네이티브 재시도" |
| `FALLBACK_MODELS` | ❌ | — | 폴백 모델(쉼표 구분, 순서대로 시도); 비워두면 풀에서 "채팅에 적합한" 모든 타사 모델을 자동 선택(이름으로 image/video/audio/embedding 등 비채팅 모델 제외)하여 무작위 로테이션, 하나가 실패(오류/빈 응답)하면 다음으로 전환 |
| `EXTENDED_THINKING_ENABLED` | ❌ | `true` | 네이티브 Gemini 확장 사고 마스터 스위치(끄면 `reasoning_effort`가 적용되지 않음) |
| `THIRDPARTY_FAILOVER_COOLDOWN` | ❌ | `180` | 동일 모델명을 공유하는 서드파티 간 장애 조치 시 실패한 제공자의 쿨다운(초, 0이면 비활성화) |
| `BARD_ERROR_CODES` | ❌ | — | Gemini가 **HTTP 200** 본문으로 반환하는 거부 블록의 code→의미 대조표. `1152=rate_limit,404=session_expired` 형식이며 분류는 `rate_limit` / `session_expired` / `context_too_long` / `captcha`. **비워두면 모든 거부 블록을 알 수 없는 것으로 처리합니다(해당 계정 쿨다운 + 다른 계정으로 재시도). 이는 의도된 안전 폴백입니다**. 설정하면 분류별 전용 처리가 활성화됩니다(세션 만료는 쿠키 자가 복구 유발, 컨텍스트 초과는 400 반환 후 재시도하지 않음, CAPTCHA는 해당 계정을 내놓음) |
| `GENERATE_TIMEOUTS` | ❌ | — | 비스트리밍 생성 타임아웃을 모델 패밀리 단위로 재정의. `pro=300,flash=120` 형식. 비워두면 내장 단계 설정 사용(flash-lite 60 / flash 120 / flash-thinking 120 / pro 300, 인식되지 않는 패밀리는 60으로 폴백) |
| `GENERATE_TIMEOUT_IMAGE` | ❌ | `180` | 이미지 생성으로 추정되는 요청의 비스트리밍 타임아웃(초). 모델 패밀리 값과 비교해 **더 큰 쪽**을 채택하고, 비스트리밍 경로에만 적용됩니다 |

---

## ⚠ 주의사항

1. **쿠키 유효 기간**: Google 쿠키는 정기적으로 만료됩니다(일반적으로 수 시간에서 수 일). 서비스에 자동 새로고침 메커니즘이 내장되어 있지만, 계정이 로그아웃되거나 비밀번호가 변경되면 쿠키를 다시 획득해야 합니다.

2. **스트리밍 출력**: 모든 API 엔드포인트는 기본적으로 스트리밍 방식으로 반환됩니다. `stream: false`로 설정하면 서비스 내부에서 여전히 스트리밍 방식으로 데이터를 수신하고, 수집 완료 후 전체 JSON을 한 번에 반환합니다.

3. **모델 가용성**: 사용 가능한 모델 목록은 Google 계정 권한에 따라 다릅니다. 무료 계정과 Gemini Advanced 계정이 보는 모델이 다르며, 서비스 시작 시 자동으로 감지됩니다.

4. **요청 빈도**: 내장 속도 제한을 끄더라도(`RATE_LIMIT_ENABLED=false`) Google 측에는 여전히 빈도 제한이 있습니다. 고빈도 요청은 CAPTCHA 또는 임시 차단을 유발할 수 있으므로 호출 빈도를 합리적으로 제어하는 것이 좋습니다.

5. **네트워크 환경**: 배포 서버는 `gemini.google.com`에 직접 액세스할 수 있어야 하며, 일부 지역에서는 프록시 구성이 필요할 수 있습니다.

6. **비스트리밍 타임아웃과 앞단 프록시**: 비스트리밍(`stream: false`) 요청의 타임아웃은 모델 패밀리 단위로 구분됩니다 —— flash-lite 60초, flash와 flash-thinking 120초, pro 300초(`GENERATE_TIMEOUTS`로 재정의 가능. 이미지 생성으로 추정되면 `GENERATE_TIMEOUT_IMAGE`, 기본 180초). 또한 타임아웃은 더 이상 3번 재시도하지 않습니다. 이 구간 내내 연결에는 **0바이트**가 흐른다는 점에 주의하세요. 즉 유휴 타임아웃이 아니라 **첫 바이트까지**의 타임아웃입니다: **pro 비스트리밍은 최대 300초를 무응답으로 기다리게 되어 흔한 앞단 프록시의 첫 바이트 한도를 넘깁니다**(EdgeOne 무료 버전 15초, 많은 리버스 프록시의 기본값 60초). 그러면 클라이언트가 받는 것은 이 서비스의 오류 본문이 아니라 프록시의 504입니다. 이런 상황에서는 스트리밍 요청을 권장합니다.

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
- [x] [issues #2](https://github.com/xwteam/gemini2api/issues/2) 사용자 지정 Gemini Gem 지원(패널 목록/생성/수정/삭제 + 모델 이름으로 노출)
- [x] [issues #6](https://github.com/xwteam/gemini2api/issues/6) [#7](https://github.com/xwteam/gemini2api/issues/7) 네이티브 Gemini 확장 사고 지원(`reasoning_effort`로 활성화, 사고가 프레임 단위로 스트리밍되어 답변보다 먼저 표시 + 모델 테스트 패널 "사고" 토글 + 원클릭 끄기, 일반 채팅에 영향 없음)
- [x] API 관리 페이지 Gemini 폴백 토글(즉시 온/오프 및 영구 저장, .env 수정·재시작 불필요)

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
