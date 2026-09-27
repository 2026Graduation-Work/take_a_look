# 기존 종목 상세 화면용 차트 데이터 전달

프론트 소스는 `main` 기준으로 유지한다. 차트 serving은 `public.latest_chart_signal_snapshots`에서 종목별 H5/H20 `chart_signal_detail_v2` snapshot을 공개한다. 브라우저는 Publishable 또는 anon key로 이 view를 읽을 수 있고, 가격 원장과 비공개 피처 Storage에는 접근하지 않는다.

## 기존 `StockDetail` 필드와의 대응

`python -m serving.frontend_handoff --snapshots <snapshots.json> --output <frontend_handoff.json>`은 공개 snapshot을 `frontend_chart_handoff_v1` 배열로 변환한다. 각 행의 `stockDetailPatch`는 프론트의 `StockDetail` 타입 중 차트 블록이 실제로 채울 수 있는 필드만 담는다.

| 기존 화면 필드 | 실제 원천 |
|---|---|
| `code`, `name`, `asOf`, `returnHorizon` | snapshot의 종목·기준일·H5/H20 |
| `currentPrice`, `changePercent`, `priceHistory`, `priceDates`, `priceProvenance` | 확정 수정종가의 최근 60거래행 |
| `returnBand` | 선택된 과거 사례 수익률의 16·84백분위, 사례가 있을 때만 |
| `realizedReturns` | 12개 등폭 히스토그램의 `{from,to,count}` 배열, 사례가 있을 때만 |
| `similarCaseCount` | 그 히스토그램에 사용한 사례 수 |
| `reasons` | 상방 클래스 내부 원점수 기여 상위 3개 피처 |

별도 `model.scores`에 실제 LightGBM의 `up`, `down`, `neutral` 출력을 담고, `model.sigma`와 기여도 공간도 함께 제공한다. `historicalComparison`에는 **상방 점수 ±0.01 및 Sigma ±5%** 조건, 포함 종목 수, 표본 기간을 담는다. 과거 사례는 예측일 수정종가와 H번째 후속 실거래행 수정종가로 계산한 실현 수익률이며 손실도 포함한다. 0건일 때는 `returnBand`와 `realizedReturns`를 만들지 않는다.

이 전달 자료는 **완전한 `StockDetail`이 아니다.** 현재 v2 공개 배치만으로는 기존 타입의 `riskGrade`, `riskFlags`, `rankPercentile`, `signalLight`, `hitRate`, `horizonAgreement.h10`, 성향·수급·재무를 정직하게 채울 수 없다. 이 값에 임의 기본값을 넣어 `predictions` 테이블의 NOT NULL 제약을 통과시키지 않는다. 원래 `main` 프론트는 `predictions`/`prediction_features`를 조회하고, 상세 화면 가격·히스토그램은 정적 데모 자료에서 읽는다. 실제 공개 snapshot을 화면에 보이게 하는 조회·결합은 프론트 담당 변경이 필요하다.

## 로컬에서 전달 자료 확인

```bash
cd backend/analysis/chart
python -m serving.frontend_handoff \
  --snapshots serving/data/batches/<batch-id>/snapshots.json \
  --output serving/data/batches/<batch-id>/frontend_handoff.json
```

삼성전자 로컬 배치는 2026-06-12 기준 H5 699건, H20 615건이다. H20 수익률의 최솟값은 약 −41.19%, 최댓값은 약 +154.27%이므로 12개 구간 폭은 약 16.29%p다. 이 수익률들은 당시 여러 종목의 실제 후속 가격에서 왔고, 현재 모델의 미래 가격 예측값이 아니다. 이 미리보기의 가공 피처 계산 버전은 미확인이라 pack ID 끝에 `_legacy_preview`를 붙였다.
