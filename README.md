# hotdeal_bot

라즈베리파이에서 동작하는 핫딜 추적 자동화입니다.  
핵심은 전수 스캔이 아니라 `Discovery(넓게)` + `Tracker(깊게)` 2단계 구조입니다.

## 핵심 구조
- Discovery(저빈도): 키워드별 후보 상품 수집, watchlist 갱신
- Tracker(고빈도): watchlist 중심으로 가격 변동 추적
- Scoring: 단순 할인율이 아니라 `직전 급락 + 7/30일 기준 + 저점 근접 + 신뢰도`로 점수화
- Alert: 점수 임계치 + 쿨다운으로 스팸 억제 후 텔레그램 전송
- Chat Commands: 텔레그램 대화로 키워드 추가/삭제/조회

## 주의
- 쿠팡 관련 데이터 접근은 반드시 약관/정책 범위에서 사용해야 합니다.
- `algumon_rank` provider는 공개 웹 페이지 기반(비공식) 수집입니다. 과도한 호출을 피하고 서비스 정책을 준수하세요.
- 본 시스템은 정보 알림 자동화이며 구매 추천이 아닙니다.

## 설치
```bash
cd /home/hyeonbin/hotdeal_bot
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt

cp .env.example .env
# .env 입력: TELEGRAM, COUPANG 키 등

python scripts/init_db.py
python scripts/check_provider.py
python src/jobs/run_discovery.py
python src/jobs/run_tracker.py
python src/jobs/run_nightly.py
```

## 주요 환경변수
- `DATA_PROVIDER`: `algumon_rank`(무키) 또는 `coupang_affiliate`(API 키 필요)
- `DISCOVERY_KEYWORDS`: 후보 탐색 키워드 목록
- `DISCOVERY_LIMIT_PER_KEYWORD`: Discovery 수집 개수
- `TRACK_BATCH_SIZE`: Tracker가 검사할 추적 대상 수
- `ALERT_SCORE_MIN`: 알림 최소 점수
- `ALERT_COOLDOWN_HOURS`: 동일 상품 재알림 대기 시간
- `MIN_DROP_PREV`, `MIN_DROP_7D`: 급락 트리거 기준
- `ALGUMON_RANK_URL`: 알구몬 랭킹 페이지 URL
- `PREFERRED_FOOD_KEYWORDS`: 식품 우선 키워드(제목/카테고리/키워드 매칭)
- `PREFERRED_EVENT_KEYWORDS`: 이벤트/적립 우선 키워드
- `FOOD_BONUS_PER_HIT`, `EVENT_BONUS_PER_HIT`: 선호 매칭 가산점
- `ALERT_PREFERENCE_RELAX`: 선호상품에 대한 점수 기준 완화폭
- `ALERT_MAX_PER_RUN`: 트래커 1회당 최대 알림 개수
- `TRACKER_DIGEST_ENABLED`: 알림 없을 때 근접후보 요약 전송 여부

## DB 테이블
- `products`: 상품 마스터
- `price_history`: 가격 히스토리
- `watchlist`: 추적 대상
- `deal_snapshots`: 트래킹 시점별 지표
- `alerts`: 알림 이력 및 쿨다운
- `discovery_runs`, `tracking_runs`: 작업 실행 로그

## systemd (user) 등록
```bash
./scripts/install_startup.sh
```

## 운영 팁
- Discovery 키워드는 넓게(생활/가전/식품 등), Tracker는 점수 기준으로 자동 좁혀집니다.
- 초기 2~3일은 히스토리가 얕아서 오탐이 있을 수 있습니다.
- `ALERT_SCORE_MIN`을 72~80 범위에서 조정하면 알림량을 빠르게 튜닝할 수 있습니다.

## 텔레그램 명령어
- `/키워드목록`
- `/키워드추가 <단어>`
- `/키워드삭제 <단어>`
- `/최근`
- `/상태`
- `/도움말`
