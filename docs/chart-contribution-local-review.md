# 전체 피처 기여도·히스토그램 로컬 검토

작업 브랜치: `fix/local-contribution-histogram`. 로컬에서 검토한 뒤 사용자 요청으로 PR을 준비한다. 운영 DB 발행은 CI와 계약 검토 후 진행한다.

## 표시와 계산

- 기존 모델 근거 탭·막대·5개 피처 행을 유지한다.
- 상방 클래스의 개별 SHAP 기여값 절댓값 / **전체 피처**의 SHAP 기여값 절댓값 합 × 100.
- 모델 기준값(마지막 bias 열)은 분모에서 제외한다. 상위 5개를 다시 100%로 정규화하지 않는다.
- 빨강 ▲는 상방 내부 점수를 높이는 기여, 파랑 ▼는 낮추는 기여다. 하방 클래스 기여도는 아니다.
- 원래 기여값과 분모는 ‘계산값 보기’를 열어 확인한다. 분모가 없으면 % 미제공, 모든 피처가 0이면 0%다.
- 과거 사례 원수익률을 2%p 간격(…−4%~−2%, −2%~0%, 0%~2%…)으로 집계한다. 모든 사례와 극단값을 포함한다.
- 기존 12등분 집계와 시그마는 무관하다. 시그마는 유사 사례 선정 조건이며 히스토그램 막대 폭이 아니다.
- 68% 범위는 원사례의 16·84 분위수로 그대로 계산한다. 가로축 눈금은 겹치지 않도록 막대 폭과 별도로 선택한다.

## 계약 변경

`inference.contribution_abs_sum`을 추가하는 안이다. 유한한 0 이상의 수이며 상위 5개 절댓값 합보다 작을 수 없다.
동결된 `schema/`의 v1 계약은 변경하지 않는다. 상세 화면용 v2 JSON Schema에는 선택 필드로 추가해 기존 snapshot과 호환한다.
serving은 새 snapshot에 분모를 제공하고 Python·프론트 검증기는 유효성을 검사한다. 기록된 시험 배치도 원래 점수·상위 5개·사례 수를 유지하면서 분모와 2%p histogram을 포함하는 새 ID로 준비한다. 기존 배치를 덮어쓰지 않는다.

## 재현

`backend/analysis/chart`에서 같은 날짜의 전체 피처 행을 준비한다. 생성기는 기존 점수·상위 5개와 일치하는지 검증하고 로컬용 배치 ID를 별도로 만든다.

```bash
python -m serving.local_display_preview \
  --features /tmp/takealook-display-features.parquet \
  --output ../../../frontend/public/chart-local-preview.json
```

`frontend/.env.local`에 기존 Supabase 공개 연결 설정을 유지하고 아래 값을 추가한다.

```dotenv
NEXT_PUBLIC_CHART_LOCAL_PREVIEW=1
```

```bash
cd frontend
pnpm dev --port 3100
```

`http://localhost:3100/stocks/005930`에서 확인한다. JSON과 `.env.local`은 Git에서 제외한다.
로컬 데이터 확인 분기는 개발 서버에서만 동작한다. 원래 공개 DB 표시로 돌아가려면 플래그를 제거하고 재시작한다.

검토 데이터 날짜는 2026-09-21이다. 재구성한 입력의 해시를 기록하며, 모델 점수와 상위 5개 기여값은 기록된 시험 결과와 같지만 기존 배치를 덮어쓰지 않는다.
