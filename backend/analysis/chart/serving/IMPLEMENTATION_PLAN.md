# H5·H20 서비스 전용 서빙 작업 장부

이 문서는 2026-09-25 확정된 H5·H20 서비스 계획의 실행 장부다. 기존
`chart_detail_preview_v0`/수익률 분포는 새 계약의 입력이나 대체물이 아니다.
기존 미커밋 연구 변경은 보존한다. 상태를 바꾸려면 검증 증거를 함께 적는다.

## 확정 규칙

- 최신 확정 일봉으로 H5(`aggressive`)·H20(`stable`) 마지막 fold 모델을 추론한다.
- 같은 종목·H·학습 정책의 2019~2025 당시 fold OOS 예측 중
  `abs(p_up-old_up) <= .01`, `abs(p_down-old_down) <= .01`,
  `abs(Sigma-old_Sigma) <= Sigma * .10`을 **모두** 충족한 행만 고른다.
  비교 전에 반올림하지 않는다. 표본 하한·범위 확대·대체 종목은 없다.
  정책 ID는 `same_stock_up_down_001_sigma_rel010_v1`이다.
- H5 배리어는 수정종가 × `(1+1.75 Sigma)`, `(1-1.50 Sigma)`이고 H20은
  `(1+3.75 Sigma)`, `(1-3.00 Sigma)`다. 다음 H개 **실거래 세션**에서
  고가 상방, 종가 하방을 각각 독립 관측한다. 탐색 상한은 `int(H*2.5)`행이다.
  미완료는 제외한다. 학습 class는 첫 충족일 비교, 동시에는 하방 우선이다.
  `neither = sample - up - down + both`.
- 0건은 정상 `no_cases`이고 비율은 null이다. `unavailable`은 원천 누락 등
  조회 불능이다. 과거 fold 사이 점수 비교와 연속 관측 중첩을 화면에 밝힌다.
- class 2 출력은 ‘상방 먼저’ 사건 점수다. 독립 상방 충족 비율을 모델 적중률이나
  미래 상승 확률로 표현하지 않는다. 기여도는 class 2 raw margin 공간이다.
- 별도 `chart_signal_detail_v1` 계약을 사용한다. freeze된 `schema/`는 수정하지
  않는다. 운영 artifact는 `CHART_SERVING_DATA_DIR` 아래에 둔다.

## 작업 장부

| ID | 상태 | 담당 | 선행 | 변경 파일 | 검증 결과 | 커밋·PR | 남은 문제 |
|---|---|---|---|---|---|---|---|
| U00 계획·계약 | DONE | Codex | 없음 | `serving/IMPLEMENTATION_PLAN.md`, `config.yaml`, `contracts/`, `README.md`, `DATA_CONTRACT.md` | 4예제 계약 검사 통과 | 미커밋 | 없음 |
| U01 산출물 manifest | BLOCKED | Codex | U00 | `serving/artifacts.py`, `INPUT_AUDIT.md` | 14개 모델·두 캐시·PIT 검사; 비개장일 82,701행/기간 발견 | 미커밋 | 비개장일 포함 OOS 재생성 |
| U02 공용 계산 | BLOCKED | Codex | U01 | `serving/calendar.py`, `prices.py`, `features.py`, `barriers.py`, 연구 wrappers | 관련 테스트 14개 통과; 실제 입력 parity 미검증 | 미커밋 | 실제 VWAP 과거 원천 필요 |
| U03 3-class 복원 | BLOCKED | Codex | U01,U02 | `serving/history.py` | 삼성전자 2019·2025 fold H5/H20 `Prob` 정확히 일치 | 미커밋 | 전체 캐시 수정 후 14-fold 대조 |
| U04 독립 사례 원장 | BLOCKED | Codex | U02,U03 | `serving/history.py` | 삼성전자 1,797건/H 진단 원장; 비개장일 검사 차단 | 미커밋 | 전체 공식 거래일 원장 필요 |
| U05 유사 사례 | IN_PROGRESS | Codex | U04 | `serving/cohorts.py` | 경계·AND·0/1건 테스트 통과 | 미커밋 | 검증된 전체 원장 필요 |
| U06 release·추론 | BLOCKED | Codex | U02,U05 | `serving/release.py`, `inference.py`, `export.py` | 2026-06-12 삼성전자 H5/H20 계약 검증 통과 | 미커밋 | 최신 원천·피처 parity·검증 release 필요 |
| U07 DB | IN_PROGRESS | Codex | U00,U06 | `supabase/migrations/0005_chart_signal_detail_v1.sql` | 정적 SQL 검사; 기존 demo `stocks` 목록과 독립된 전체 종목 키 확인 | 미커밋 | 실DB 적용·RLS 검증 |
| U08 일일 배치 | IN_PROGRESS | Codex | U06,U07 | `serving/publish.py`, `run_daily.py` | 업로드 실패 시 비공개 테스트; 삼성전자 2개 snapshot 동일 ID 재실행 통과 | 미커밋 | 전체 dry-run·실DB 발행/철회 검증 |
| U09 상세 화면 | IN_PROGRESS | Codex | U07,U08 | `frontend/` | TS·lint·단위 9개·Next webpack 프로덕션 빌드 통과 | 미커밋 | 실배치 상태 화면 검증 |
| U10 운영 정리 | IN_PROGRESS | Codex | U08,U09 | `serving/OPERATIONS.md`, `docs/` | 운영 절차·문서 연결 작성 | 미커밋 | 예약 실행·최초 공개·레거시 분리 |

상태: `TODO`, `IN_PROGRESS`, `BLOCKED`, `DONE`. 실제 DB 적용·예약 실행·첫 공개
배치는 코드 작성과 별도 증거를 요구한다. 선행 작업이 미완료면 의존 작업을
`DONE`으로 표시하지 않는다. 이동/리네임과 계산 변경은 별도 커밋으로 나눈다.

## 작업별 실행 내용과 완료 기준

- **U00:** 계약 Schema와 정상·양쪽 충족·0건·제공 불가 예제를 고정한다.
  설정 파일에 세 거리 폭과 정책 ID, H별 배리어를 둔다. 환경변수·CLI·저장
  위치·상태 의미를 문서화한다. 네 예제가 구조와 건수 불변식을 통과해야 완료다.
- **U01:** 각 YAML의 7개 당시 fold 모델, OOS 캐시와 학습 입력을 해시로
  연결한다. 학습 종료·테스트 구간·161 피처 순서·feature/label 배리어를 분리해
  기록한다. 중복, 공식 KRX 날짜, PIT 상장 구간, 누락을 감사한다. 하나라도
  미검증이면 release를 차단한다. registry를 마지막 fold로 가정하지 않는다.
- **U02:** 서비스만 설치한 환경에서 달력·수정주가·실제 VWAP·피처·Sigma와
  배리어 관측이 작동하게 한다. 피처는 미래 라벨 없이 만든다. 같은 계산의
  연구 호출부는 얇은 wrapper로 바꾼다. 학습 입력과 동등성·prefix causality,
  라벨 동등성을 확인하고 서비스 import에 연구 모듈이나 파일 생성이 없어야 한다.
- **U03:** fold OOS 행만 그 당시 모델과 저장된 피처 순서로 다시 추론해
  down/neutral/up을 저장한다. 확률 합·범위·유한성과 기존 `Prob`의 up을
  `rtol=1e-6`, `atol=1e-8`로 비교한다. 불일치 시 모델·피처·반복수·버전을
  조사하고 승격을 중단한다. 원 캐시는 덮어쓰지 않는다.
- **U04:** 2019~2025 OOS 출력에 당시 가격·Sigma를 붙여 상방/하방 독립
  충족, 첫 충족일, 학습 class, 관측 완료일을 저장한다. 정지·상폐·가격 누락·
  기간 말 미완료를 사유별 감사한다. 미완료를 neither에 넣지 않고 중복 키를
  금지한다. 임의 사례를 원천 일봉으로 재현해야 한다.
- **U05:** 같은 종목·H·정책, 세 거리의 AND 조건으로만 고른다. 경계 포함,
  Sigma 0의 정확한 일치, 미래 확정 제외, 결정론적 정렬을 검증한다. 최소 표본
  또는 bucket을 두지 않는다. 0/1건도 정상이며 다섯 건수·기간·fold/연도
  분포·정책/원장 해시를 반환한다. 건수 불변식을 항상 만족해야 한다.
- **U06:** 공식 최신 확정 세션과 전체 현재 KOSPI 보통주를 결정하고 H5/H20
  fold-6 모델, feature contract, 사례 원장, 설정을 release로 묶는다. class 2
  raw margin 전체 기여도+기준값이 raw score와 맞는지 검사한다. 절댓값 상위
  5개는 이름 순 동점 처리와 검토된 한글 설명을 사용한다. 삼성전자 최신 확정
  일자 JSON 2개, 과거 입력 절단 불변성과 동일 결과 해시가 완료 증거다.
- **U07:** 세 새 테이블, 키/FK/필수값, 공개 배치 전용 RLS 읽기, 서비스 역할
  쓰기, H5/H20 완비 검사와 원자적 공개/철회 RPC를 적용한다. 기존 테이블과
  freeze 계약은 유지한다. 코드 작성과 실DB 적용을 별도로 기록한다.
- **U08:** `python -m serving.run_daily`가 수집→피처→추론→사례→검증→발행을
  소유한다. `--as-of`, 기본 `--dry-run`, `--publish`, 철회와 중복 잠금을 제공한다.
  모든 예상 종목의 두 H 결과 또는 명시적 불가 상태를 저장한다. 예상 밖 오류는
  전체 공개를 막고 이전 배치를 유지한다. 동일 입력은 동일 ID로 재실행하며
  부분 업로드/발행 직전 실패/철회와 비밀 로그 비노출을 검증한다.
- **U09:** 최신 공개 배치만 조회하고 데모 밖 상세 라우트를 허용한다. 성향에
  따른 초기 H5/H20과 전환, 독립 건수·분모·비율·중복 설명·유사 조건,
  3+2개 signed 기여도, 실제 60일 가격과 출처를 표시한다. 실데이터에 수익률
  밴드·히스토그램·H10을 만들지 않는다. 0/1건·양쪽·불가·오래된 날짜,
  모바일·키보드·스크린리더와 문구·빌드 검증이 완료 조건이다.
- **U10:** 18:00 KST 평일 예약 예제, 휴장일·확정 데이터 재검사, 재시도·철회,
  구조화 로그와 문서 색인을 둔다. 사용하지 않는 preview/분포는 호출자 확인
  후 연구 위치로 옮기고 서비스 의존성을 분리한다. 연구 디렉터리 없는 실행,
  실제 예약과 최초 정상 배치 공개를 확인해야 완료다.

## 배포 순서

추가 migration → release/사례 검증 → 비공개 배치 검토 → 화면 배포 → 첫 배치
공개 → 평일 18:00 KST 예약 및 실패 복구 검증. PR 전 chart `ruff check .`,
`pytest`, 영향받은 연구 테스트, 프론트 테스트와 `pnpm build`를 실행한다.

이번 범위에서 전체 종목 비교, 도달일 그래프, 정책 폭 최적화, 재학습,
2019~2025 참조 기간 확장은 제외한다.
