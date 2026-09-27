# 차트 종목 상세 데이터 작업 인계 — 2026-09-24

## 2026-09-24 최신 main 기준 재배치

- 후속 작업: 재학습 모델을 나중에 교체할 수 있도록 `serving.build_release`와
  `serving.release`를 추가했다. release는 모델 파일·피처 순서·OOS 분포 파일을
  해시로 묶고, `serving.export --release`는 분포를 종목 점수 구간에 결합한다.
  raw/processed 입력 파일 해시도 preview에 기록한다. release 분포가 예측일보다
  미래 자료이면 실패한다. 실제 OOS CSV 생성과 독립 평가는 아직 필요하다.
  후속 검증은 chart 전체 pytest 135개와 Ruff 통과다.
- 의미 수정: `bucket_hit_rate`는 같은 점수 구간 OOS 사례의 class 2(상방
  배리어 먼저 터치) 빈도다. H거래일 뒤 종가 상승 빈도는 별도
  `positive_return_rate`다. 현재 cohort는 점수 구간만 맞추므로 변동성/배리어
  높이가 비슷한 "유사 사례"로 표현하면 안 된다. 자세한 전달 기준은
  `DATA_CONTRACT.md`를 본다.

- `origin/main`의 `6082ded`에서 `feat/chart-serving-main` 브랜치를 새로 만들고,
  기존 미커밋 서빙 초안과 chart README 연결을 옮겼다. 이 브랜치의 선행 커밋은
  최신 main이며, PIT 브랜치의 `2de941f`, `ecc8517`은 포함하지 않는다.
- 원격 main에는 거래일 달력 캐시 우선 사용·경로 고정·추론 달력 인자 변경이
  들어왔다. 서빙 초안은 거래일 달력 모듈을 직접 호출하지 않아 코드 충돌은 없다.
  OOS 수익률 생성기는 아직 없으므로 구현할 때 main의 달력 정책과 미병합 PIT
  유니버스 정책을 함께 검토해야 한다.
- main 기준 검증: `/tmp/chart-pr-check-venv`에서 Ruff 통과, chart 전체 pytest
  132개 통과, 서빙 테스트 9개 통과, export 도움말과 2종목 가격 preview 성공.
  테스트 환경과 `/tmp/chart-prices-preview-main.json`은 임시 파일이다.
- 아래의 "현재 Git 상태"와 2026-09-23 검증 결과는 이전 브랜치 기록이다.
  현재 상태 확인에는 `git status`를 사용한다.

다음 세션은 이 문서와 [`README.md`](README.md)를 먼저 읽는다. 이번 작업 범위는
**차트 파트가 종목 상세 화면에 제공할 가격·거래량·모델 점수·과거 수익률 분포**다.
투자자 수급, 뉴스, 재무, 다른 화면은 범위 밖이다. 사용자는 데이터 재수집·재학습 등
기존 제안의 1~4번을 나중에 실행하기로 했고, 이번에는 운영 출력·분포 설계·저장 계약
검토(5~7번)를 진행하도록 요청했다.

## 현재 Git 상태와 주의 사항

- 작업 브랜치: `feat/chart-serving-main`. 시작 커밋은 `6082ded` (`origin/main`,
  2026-09-24 확인)이다. 변경은 현재 미커밋이다.
- 수정: `backend/analysis/chart/README.md`.
- 신규: `backend/analysis/chart/serving/{__init__.py,export.py,output.py,distribution.py,README.md,HANDOFF.md}`,
  `backend/analysis/chart/tests/test_serving.py`.
- `docs/images/chart-price-history-band.png`, `docs/images/chart-return-histogram.png`는
  사용자가 제공한 참고 이미지이며 기존부터 untracked였다. 삭제·덮어쓰기·무단
  staging을 하지 않는다. 화면 목적을 확인할 때만 읽는다.
- schema/ 및 Supabase migration은 freeze 상태라 수정하지 않았다. 새 저장 계약은
  팀 합의 후 별도 PR로 진행한다.

## 구현 결과

- `serving.export`: 실험 코드 import 없이 raw Parquet의 종가·거래량·60일 이력과,
  선택한 processed snapshot + registry 모델의 3-class 점수를 JSON으로 쓴다.
  모델 SHA와 필수 피처/날짜를 검증한다. 부분 성공을 공개하지 않고 실패시킨다.
- `output.rank_predictions`: 명시된 코드 집합 안의 class 2 점수 상대 순위.
  전체 시장이 아니라 1종목만 입력하면 0.5이므로 공개 순위로 쓰지 않는다.
- `output.predict_snapshot`: class 2 raw-margin 기여도 상위 3개. 확률이나 수익률
  기여값으로 부르면 안 된다.
- `distribution.build_distribution`: 외부에서 검증한 OOS score와 H거래일 뒤 실제
  종가 수익률을 받아 동일 표본으로 경험적 68% 범위, histogram, 상승 비율을 만든다.
  실제 OOS 추출기는 아직 없다. 현재 preview는 `return_distribution.status=unavailable`.
- 출력 포맷은 `chart_detail_preview_v0`, 상태는 `preview_only`. frozen chart_output
  계약/프론트/Supabase와 아직 연결하지 않는다.

## 검증과 재현

2026-09-23 수행한 검증: chart 루트에서 Ruff 통과, 전체 pytest 143개 통과.
가격 2종목 preview와 삼성전자 1종목 추론 preview 생성 성공.
당시 테스트 환경은 `/tmp/chart-pr-check-venv`였으며 영구 환경으로 가정하지 않는다.
다음 세션에는 적합한 가상환경에서 아래 명령을 재실행한다.

```bash
cd backend/analysis/chart
ruff check .
pytest -q
python -m serving.export --help
```

작동 예시 명령은 [`README.md`](README.md)의 실행 절을 따른다.
검토용 출력은 `/tmp/chart-prices-preview.json`, `/tmp/chart-inference-preview.json`에
만들었으나 `/tmp` 파일은 재시작 후 없어질 수 있다.

실제 파일 확인 당시 raw 3,734개, processed 3,324개였다. 삼성전자 processed는
2026-06-12까지, 현대차 processed는 2026-05-18까지였다. 두 종목 동시 추론을
2026-06-12로 요청하면 날짜 불일치로, 2026-05-18로 요청하면 삼성전자 `cord_5`
NaN 때문에 실패했다. 이는 exporter가 불완전한 피처를 조용히 건너뛰지 않는
의도된 동작이다. 현재 로컬 raw/processed는 최신 운영 데이터가 아니다.

## 그림과 계산 의미

이미지 1은 최근 60개 관측 종가 + 같은 기준일의 H거래일 과거 수익률 범위다.
이미지 2는 그 범위를 만든 **동일 OOS 사례**의 실현 수익률 histogram이다.
현재 LGBM class 2 점수는 triple-barrier 상방 도달 사건의 점수다. “H거래일 뒤
실제로 상승한 비율”은 별도로 `return_pct > 0`에서 계산한다.
동일 score bucket의 검증 사례를 골라 16/84백분위와 막대 건수를 같이 산출한다.
68%는 경험적 중앙 범위이며 미래 확률 보증/평균의 신뢰구간이 아니다.
H5/H20 모델만 registry에 있다. 예시 그림의 “2주 뒤”는 H10으로, 현 모델 값에
이 문구를 붙이거나 H10 방향을 가짜로 채우면 안 된다.

## 다음 작업 순서

1. 이번 변경의 diff와 사용자 이미지 파일 보존 상태를 확인한다. PIT 브랜치가
   main에 머지되면 해당 정책과 서빙/OOS 코드를 함께 검토한다.
2. 서빙 입력의 피처 동등성 문제를 해결한다. 현재 `feature-version`은 문자열뿐이다.
   모델의 feature list/hash, processed 생성 설정과 데이터를 release 단위로 고정하고,
   결측 허용 정책을 학습 때와 맞춘다. 현재 모델은 PIT/VWAP 이전 버전이라 운영 승격 불가.
3. 차트 파트 OOS 결과에서 `code, prediction_date, training_end, outcome_date,
   model_version, horizon_days, score, return_pct`를 **누수 없이** 만드는 생성기를
   설계한다. t+H 수익률은 KRX 거래일·상폐·정지·미확정 라벨 처리 정책을 검증해야 한다.
4. 분포 artifact에서 bucket 정의, 표본 최소치, 구간 실제 포함률을 독립 평가 구간에
   확인한다. 최종 holdout을 보고 bucket을 고친 뒤 같은 holdout을 다시 미사용
   검증이라고 부르면 안 된다. 모델 버전/분포 버전을 묶는다.
5. signal_light 매핑 임계값과 근거 한글 라벨을 팀과 확정한다. 현재 출력에는
   signal_light와 frozen schema 필수 return band/hit rate가 없으므로 Supabase
   predictions에 0/가짜 값으로 채워 발행하지 않는다.
6. 가격 이력과 분포 artifact의 저장 계약을 팀과 합의한다. 현재 DB에는 가격
   이력/histogram 저장소가 없다. 상세 라우트가 데모 종목 외에는 404인 프론트
   문제도 실제 데이터 연결 시 함께 해결해야 한다.
7. 합의한 계약과 새 모델 검증 뒤 publisher/일일 스케줄을 구현한다. 재수집·재학습은
   사용자가 나중에 진행하겠다고 지정했으므로 이번 브랜치에서 임의 실행하지 않는다.

재학습 운영안도 [`README.md`](README.md)에 기록했다. 매일 데이터 갱신·고정 모델
추론과 매월 후보 학습/승격 검토는 다른 작업이며, 기존 모델 덮어쓰기를 피한다.
H5/H20은 최근 5/20거래일의 정답 관측이 끝나야 그 기간을 학습에 넣을 수 있다.
