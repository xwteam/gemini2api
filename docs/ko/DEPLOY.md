# 배포 가이드

Gemini2API 서비스를 배포하는 방법을 상세히 설명합니다.

## 환경 요구사항

| 구성 요소 | 최소 버전 | 설명 |
|---------|---------|------|
| Docker | 20.10+ | Docker 배포 권장 |
| Docker Compose | 1.29+ | 컨테이너 오케스트레이션 도구 |
| 메모리 | 2GB+ | 4GB 이상 권장 |
| 디스크 | 500MB+ | 로그 및 설정 저장용 |
| 운영 체제 | Linux/Mac/Windows | Docker를 지원하는 모든 시스템 |
| 네트워크 | gemini.google.com 직접 연결 | Google 서비스 접근 필요 |

## Cookie 획득 절차

### 사전 조건

- 유효한 Google 계정 필요
- [gemini.google.com](https://gemini.google.com)에 정상 접근 가능
- Chrome 또는 Edge 브라우저 사용

### 단계별 가이드

1. 브라우저를 열고 [gemini.google.com](https://gemini.google.com)에 접속

2. Google 계정으로 로그인하여 Gemini 대화 정상 작동 확인

3. `F12` 키를 눌러 개발자 도구 열기

4. 상단 메뉴에서 **Application**(응용 프로그램) 탭 클릭

5. 좌측 사이드바에서 **Cookies** 옵션 찾기

6. `https://gemini.google.com` 항목 클릭

7. Cookie 목록에서 다음 두 값 찾기:

   | Cookie 이름 | 특징 | 예시 |
   |-----------|------|------|
   | `__Secure-1PSID` | `g.`로 시작, 보통 50-100자 | `g.a000xxx...` |
   | `__Secure-1PSIDTS` | 짧은 문자열, 보통 20-40자 | `sidts-xxx...` |

8. Value 열을 더블클릭하여 전체 값 복사

9. 두 값을 안전한 위치에 저장

### 획득 팁

- 검색창에 `__Secure-1P`를 입력하여 관련 Cookie 빠르게 필터링
- 시크릿 모드에서 작업하고 획득 후 즉시 창 닫기 권장
- 페이지 새로고침으로 인한 Cookie 갱신 방지
- 복사 시 여분의 공백이나 줄바꿈 없는지 확인

### Cookie 유효 기간

- Google Cookie 일반적 유효 기간: 2-24시간
- 데이터센터 IP: 1-2시간 (더 짧음)
- 주거용 IP: 6-24시간 (더 길음)
- 서비스 갑자기 작동 불가 시 먼저 Cookie 만료 여부 확인

## Docker 배포

### 빠른 시작

```bash
# 1. 저장소 복제
git clone https://github.com/xwteam/gemini2api.git
cd gemini2api

# 2. 환경 변수 템플릿 복사
cp .env.example .env

# 3. .env 파일 편집하여 Cookie 입력
nano .env
# 또는
vim .env
```

### .env 파일 설정

`.env` 파일을 편집하여 획득한 Cookie 값 입력:

```env
# 필수: 브라우저에서 획득한 Cookie
GEMINI_PSID=g.a000xxx...
GEMINI_PSIDTS=sidts-xxx...

# 선택: API 접근 키 (비워두면 자동 생성)
API_KEY=

# 선택: 서비스 포트 (기본값 5918)
PORT=5918

# 선택: Cookie 갱신 주기 (분, 기본값 30; 코드에서 10분 하한을 강제하므로 더 작게 쓰면 10으로 올라갑니다)
REFRESH_INTERVAL=30

# 선택: 실패 재시도 횟수 (기본값 3)
MAX_RETRIES=3

# 선택: 로그 레벨 (debug/info/warning/error, 기본값 info)
LOG_LEVEL=info
```

### 중요 사항

- 값 앞뒤에 따옴표 불필요
- 여분의 공백이나 줄바꿈 없어야 함
- 복사한 값이 완전한지 확인, 끝 문자 누락 방지

### 서비스 시작

```bash
docker compose up -d
```

### 시작 확인

```bash
docker compose logs -f
```

다음 메시지 확인:
- `"Account pool ready: 1/1 active"` - 계정 풀 준비 완료
- `"SNlM0e not found"` - Cookie 무효, 다시 획득 필요

## 다중 계정 설정

여러 Google 계정으로 부하 분산을 구현하려면 프로젝트의 `data/` 디렉터리에 `accounts.json` 생성(즉 `data/accounts.json`; `data/`는 마운트된 볼륨이라 업그레이드로 컨테이너를 다시 만들어도 사라지지 않음):

```json
{
  "accounts": [
    {
      "id": "account-0",
      "psid": "g.a000xxx...",
      "psidts": "sidts-xxx...",
      "label": "주 계정"
    },
    {
      "id": "account-1",
      "psid": "g.a000yyy...",
      "psidts": "sidts-yyy...",
      "label": "보조 계정"
    }
  ]
}
```

### 참고 사항

- `data/accounts.json` 미생성 시 `.env`의 단일 계정 모드 자동 사용
- `POST /admin/accounts` API로 실행 중 동적 계정 추가 가능

### Cookie 자동 보활

gemini2api는 내장 Cookie 자동 갱신 메커니즘 포함:
- 기본 30분마다(`REFRESH_INTERVAL`, 하한 10분) Google RotateCookies API를 통해 `__Secure-1PSIDTS` 갱신
- batchexecute 하트비트로 브라우저 활동 모의
- 세션 수명 연장

> `REFRESH_INTERVAL` 기본값은 5분에서 30분으로 바뀌었고 하한 10분이 강제됩니다. 예전에는 "시작할 때 토큰을 가져오지 못한" 경우에만 로테이션 루프가 올라왔기 때문에 정상적으로 시작한 게이트웨이는 아예 로테이션하지 않았습니다([issue #11](https://github.com/xwteam/gemini2api/issues/11)). 이제 루프가 항상 상주하므로 같은 간격이면 Google 쪽 백그라운드 요청량이 약 3.5배가 되어, 간격도 그만큼 넓혀야 합니다 —— 너무 자주 로테이션하면 Google 입장에서 자동화로 보여 오히려 세션이 차단됩니다.

Web 패널의 "계정 관리" → "Cookie 업데이트"로 수동 갱신 가능 (서비스 재시작 불필요).

> Cookie 수명은 Google 위험 관리 정책의 영향을 받습니다. 데이터센터 IP는 보통 수 시간 유지 가능합니다. Cookie 자주 만료되면 주거용 IP 사용 또는 계정 수 증가 권장.

## 검증

### 헬스 체크

```bash
curl http://localhost:5918/health
```

예상 응답:
```json
{"status":"ok","service":"gemini2api"}
```

### 모델 목록 조회

```bash
curl http://localhost:5918/openai/v1/models \
  -H "Authorization: Bearer sk-당신의API키"
```

### 테스트 요청

```bash
curl -X POST http://localhost:5918/openai/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-당신의API키" \
  -d '{"model":"gemini-2.0-flash","messages":[{"role":"user","content":"안녕하세요"}]}'
```

AI 응답 텍스트가 보이면 배포 성공입니다. 401 반환 시 API 키 확인하세요.

## 문제 해결

### .env를 수정하고 재시작해도 반영되지 않음

**증상:** `.env`의 설정 항목을 변경하고 `docker compose restart`해도 값이 바뀌지 않음.

**원인:** 웹 패널의 "설정" 페이지에서 저장한 항목은
`data/settings-overrides.json`에 기록되어 시작할 때마다 다시 적용되며
**환경 변수보다 우선**합니다. 이는 의도된 동작입니다. 패널에서
`LOG_BODIES_ENABLED`를 끈 뒤 재시작으로 다시 켜져서는 안 되기 때문입니다.

**진단:** 시작 로그에서 다음 줄을 찾으면 덮어써진 항목을 알 수 있습니다:

```bash
docker compose logs | grep "panel setting override"
# [INFO] app.main: Applied 2 panel setting override(s) from data/settings-overrides.json: log_bodies_enabled=False, max_retries=7
```

**해결:** 패널에서 값을 변경하거나(권장), `data/settings-overrides.json`을 삭제해
`.env` / 환경 변수에 제어권을 넘긴 뒤 재시작하세요.

### Cookie 약 2시간 후 만료

**증상**: 요청 시 `SNlM0e not found` 또는 `401 Unauthorized` 오류

**해결책**:
1. Web 패널 접속 (http://localhost:5918)
2. "계정 관리" 탭에서 "Cookie 업데이트" 클릭
3. 새로운 Cookie 값 입력 후 저장
4. 또는 API 사용:

```bash
curl -X PUT http://localhost:5918/admin/accounts/account-0/cookies \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-당신의API키" \
  -d '{"psid":"g.새로운값...","psidts":"sidts-새로운값..."}'
```

### 포트 충돌

**증상**: `Address already in use` 오류

**해결책**: `.env` 파일에서 PORT 변경:

```env
PORT=5919
```

그 후 `docker compose up -d` 재실행

### 메모리 부족

**증상**: 컨테이너 자주 재시작, `OOMKilled` 오류

**해결책**:

1. SWAP 추가 (Linux):
```bash
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
```

2. 또는 docker-compose.yml에서 메모리 제한 조정:
```yaml
services:
  gemini2api:
    mem_limit: 4g
    memswap_limit: 6g
```

### 계정 상태 확인

```bash
curl http://localhost:5918/admin/accounts \
  -H "Authorization: Bearer sk-당신의API키"
```

### 전체 Cookie 갱신

```bash
curl -X POST http://localhost:5918/admin/reload-cookies \
  -H "Authorization: Bearer sk-당신의API키"
```

### 서비스 재시작

```bash
docker compose restart
```

또는 Web 패널 우측 상단 제어 표시줄에서 "재시작" 버튼 클릭

## 로그 확인

```bash
# 실시간 로그 보기
docker compose logs -f

# 마지막 100줄 보기
docker compose logs --tail=100

# 특정 시간 이후 로그 보기
docker compose logs --since 10m
```

## 다음 단계

배포 완료 후:
1. [USAGE.md](USAGE.md)에서 Web 패널 및 API 사용법 확인
2. [API.md](API.md)에서 API 엔드포인트 상세 정보 확인
3. 서드파티 클라이언트 연동 설정
