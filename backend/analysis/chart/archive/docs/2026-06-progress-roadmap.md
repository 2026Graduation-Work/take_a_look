# 2026-06 차트 실험 결과: Multiplier Screening, Horizon 확장, Factor 검증

작성 기준: 2026-07-01
대상 범위: `backend/analysis/chart/`

> 2026년 6월까지 진행한 당시 실험의 결과 기록이다. 현재 배포 정본과 실행법은
> `backend/analysis/chart/ONBOARDING.md`와 `core/models/registry.yaml`을 따른다.

## 1. 이번 작업 요약

이전 모임 전까지는 **H=5 기준 LightGBM 모델의 기본 성능 평가**까지 진행했다. 이번 작업에서는 같은 차트 기반 예측 모델을 더 엄격하게 검증하기 위해, 라벨 생성 방식과 평가 범위를 크게 확장했다.

핵심적으로는 다음을 수행했다.

- H=5에서 사용하던 트리플 배리어 라벨을 고정하지 않고, **상방/하방 barrier multiplier 조합을 여러 개 탐색**했다.
- H=5뿐 아니라 **H=10, H=20으로 horizon을 확장**해 각 보유 기간에 맞는 multiplier 후보를 찾았다.
- 후보 multiplier별로 다시 train, validation, test, backtest를 돌려 **최종 H5/H10/H20 후보 모델**을 정리했다.
- Backtest 지표와 ML validation 지표를 늘려 모델을 단순 정확도뿐 아니라 **수익성, 위험, 랭킹 품질, 확률 calibration** 관점에서 평가했다.
- 각 모델이 어떤 factor, 자산군, 종목 특성에 기대고 있는지 분석해 **모델 편향과 집중도를 점검하는 검증 방식**을 추가했다.

현재까지의 방향성은 “예측 확률이 높은 모델”을 만드는 것을 넘어서, **그 확률이 어떤 시장 조건과 종목 특성에서 발생하는지 설명하고, 실제 백테스트에서도 재현 가능한지 검증하는 체계**를 만드는 것이다.

## 2. 전체 로드맵 관점

현재 차트 블록은 다음 단계로 발전했다.

1. H=5 단일 모델 성능 평가
2. Multiplier screener로 라벨 후보 탐색
3. H=5, H=10, H=20 horizon별 최적 후보 선정
4. 후보 모델별 train, validation, test, backtest 재실행
5. ML 지표와 trading 지표를 분리한 다각도 평가
6. Factor attribution과 factor-neutral backtest를 통한 편향 검증

## 3. 이번 업데이트 내용

### 3.1 Multiplier Screener 구현 및 개념

기존 H=5 모델은 트리플 배리어 라벨의 상방/하방 기준이 사실상 하나의 설정에 묶여 있었다. 이번에는 이 설정을 고정하지 않고, 여러 multiplier 조합을 체계적으로 검사하는 screener를 도입했다.
개념적으로 라벨은 다음 방식으로 만들어진다.

- **변동성(`Sigma`) 계산**:
  - 일일 로그 수익률 계산: $Log\_Ret = \ln(Close_t / Close_{t-1})$. 거래정지일(`Trading_Halt == 1`)인 날은 로그 수익률을 `0.0`으로 처리합니다.
  - 최근 20 실거래일(거래정지일 제외) 로그 수익률의 롤링 표준편차로 변동성을 정의합니다 (`rolling(20, min_periods=10).std()`).
- `up barrier = 기준가격 * (1 + up_mult * sigma)`를 만든다.
- `down barrier = 기준가격 * (1 - down_mult * sigma)`를 만든다.
- horizon 기간 안에 상방 barrier를 먼저 터치하면 상승 라벨, 하방 barrier를 먼저 터치하면 하락 라벨, 둘 다 명확하지 않으면 중립 라벨로 본다.
- 이때 `up_mult`, `down_mult`를 바꿔가며 라벨 분포와 train/test 안정성을 확인한다.

Screener에서 본 핵심 기준은 다음이다.

- 상승/하락/중립 라벨 비율이 전략 의도와 맞는가
- 라벨 불균형이 의도된 희소 이벤트 탐지 결과인지, barrier가 너무 좁거나 넓어서 생긴 기계적 쏠림인지 구분되는가
- 중립 라벨이 지나치게 적어 “매매하지 않을 구간”을 학습하기 어려운 구조가 되지는 않는가
- train 구간과 test 구간의 라벨 분포 차이가 크지 않은가
- horizon이 길어질수록 더 넓은 barrier가 필요한지 확인되는가
- 최종적으로 모델 학습과 백테스트에서 해석 가능한 후보인가

트리플 배리어 라벨은 반드시 균등해야 하는 방식은 아니다. 특정 투자 전략은 자연스럽게 상승 라벨이 적거나 중립 라벨이 많을 수 있다. 다만 이번 screener에서는 라벨 쏠림 자체를 금지한 것이 아니라, **그 쏠림이 전략적으로 해석 가능한지, train/test 기간에서 안정적인지, 모델이 단순 라벨 빈도만 외우는 구조가 아닌지**를 확인했다.

이 작업으로 “좋아 보이는 백테스트 결과를 내는 임의 라벨”이 아니라, **라벨의 경제적 의미와 기간 안정성을 먼저 확인한 후보만 학습 대상으로 삼는 구조**를 만들었다.

### 3.2 H=5 후보 재학습 및 결과 정리

이전까지 H=5 모델의 기본 성능 평가가 있었다면, 이번에는 H=5 안에서도 여러 multiplier 후보를 다시 검토했다. 특히 `u125/d100`, `u150/d120`, `u175/d150` 계열 후보를 비교했다.

H=5에서 중요한 관찰은 다음이다.

- `u125/d100`은 거래 수가 많고 더 민감하게 진입하지만, 수익률과 Sharpe가 상대적으로 낮았다.
- `u175/d150`은 거래 수는 줄었지만 평균 수익, payoff ratio, MDD 측면에서 더 안정적인 후보로 확인됐다.
- ML 지표만 보면 후보 간 차이가 극단적으로 크지는 않지만, top-N 전략으로 연결했을 때 trading 성과 차이가 더 분명하게 나타났다.

H=5 주요 후보 비교:

| 후보           | Total Return |   CAGR | Sharpe |     MDD | Trades | Win Rate | 비고                                |
| -------------- | -----------: | -----: | -----: | ------: | -----: | -------: | ----------------------------------- |
| H5 `u125/d100` |       80.61% | 15.59% |  0.914 | -18.82% |  1,251 |   50.04% | 진입이 많지만 성과/위험 효율이 낮음 |
| H5 `u175/d150` |      126.44% | 22.18% |  1.088 | -15.12% |    827 |   51.51% | 최종 H5 후보로 유지                 |

H5 최종 후보인 `u175/d150`의 ML validation 특징:

- ROC-AUC: 0.607
- PR-AUC: 0.465
- Rank IC mean: 0.135
- IC positive day ratio: 86.38%
- Fold alignment: 정상

해석하면, H=5 모델은 단순 분류 정확도보다는 **일별 횡단면 랭킹 품질**이 더 중요한 모델에 가깝다. 즉 “전체 종목을 맞히는 모델”이라기보다, 매일 후보군 중 상대적으로 좋은 종목을 위로 올리는 능력을 평가해야 한다.

### 3.3 H=10, H=20 확장 및 최종 후보 선정

H=5에서 만든 multiplier screening 방식을 H=10과 H=20에도 확장했다. Horizon이 길어지면 가격이 움직일 시간이 늘어나므로, 같은 sigma multiplier를 쓰면 라벨이 지나치게 쉽게 상방/하방으로 갈 수 있다. 그래서 H=10, H=20 각각에 맞는 barrier 폭을 다시 찾아야 했다.

구현 방식은 H=5와 동일하다.

- horizon별 후보 multiplier grid를 만든다.
- 각 조합별 라벨 분포를 생성한다.
- 중립 비율, 상승/하락 비율, train/test 분포 차이를 확인한다.
- 통과한 후보를 대상으로 LightGBM 학습과 ML validation을 수행한다.
- 동일한 backtest rule로 trading 성과를 비교한다.

최종 후보는 다음으로 정리했다.

| Horizon | 최종 후보   | 실험 이름                                                         | Total Return |   CAGR | Sharpe |     MDD | Trades | Benchmark 대비 초과수익 |
| ------- | ----------- | ----------------------------------------------------------------- | -----------: | -----: | -----: | ------: | -----: | ----------------------: |
| H5      | `u175/d150` | `tb_lgbm_h5_u175_d150_alpha158_regime4`                           |      126.44% | 22.18% |  1.088 | -15.12% |    827 |                 132.43% |
| H10     | `u250/d225` | `tb_lgbm_h10_u250_d225_alpha158_current_sigma_selection2020_2022` |       92.32% | 23.83% |  1.139 | -16.07% |    386 |                  88.21% |
| H20     | `u375/d300` | `tb_lgbm_h20_u375_d300_alpha158_current_sigma_selection2020_2022` |       82.89% | 21.81% |  1.103 | -13.15% |    310 |                  78.77% |

정리하면 H5는 총수익률이 가장 높고, H10은 Sharpe와 CAGR이 가장 높으며, H20은 거래 수가 적고 MDD가 가장 낮은 편이다. 각 horizon이 서로 다른 투자 성격을 갖는다는 점이 확인됐다.

### 3.4 Backtest 평가 방식 확장

Backtest는 단순 누적 수익률만 보는 방식에서 벗어나, 다음 지표들을 함께 기록하도록 확장했다.

- Total Return
- CAGR
- Annualized Volatility
- Sharpe Ratio
- Sortino Ratio
- Max Drawdown
- Win Rate
- Average Win / Average Loss
- Payoff Ratio
- Profit Factor
- Number of Trades
- Benchmark 대비 초과수익

또한 VectorBT 실행 정합성을 개선했다.

- entry와 exit가 같은 날 겹칠 때 청산이 누락되지 않도록 entry를 masking했다.
- stop rule을 각각 따로 계산하지 않고, 하나의 position state에서 hard stop, take profit, soft stop, time exit를 동기화했다.
- 주문 체결 가격과 일별 평가 가격을 분리해 결과 왜곡 가능성을 줄였다.
- KOSPI/KOSDAQ 기반 Custom KRX benchmark를 만들고, benchmark가 비정상일 때 invalid reason을 기록하도록 했다.

이 업데이트의 목적은 “수익률이 높다”가 아니라, **어떤 위험과 거래 특성으로 그 수익률이 만들어졌는지 설명 가능하게 만드는 것**이다.

### 3.5 ML Validation 방식 확장

ML validation도 accuracy 중심에서 다음 기준으로 확장했다.

- Balanced Accuracy: 상승/비상승 라벨 불균형을 고려
- Macro F1: 클래스별 성능 균형 확인
- Brier Score: 예측 확률의 품질 확인
- ROC-AUC / PR-AUC: threshold와 무관한 분류 품질 확인
- Probability Calibration: 예측 확률 구간별 실제 상승 hit rate 확인
- Rank IC: 같은 날짜의 종목들 사이에서 예측 확률 순위가 실제 라벨 순위와 맞는지 확인
- Fold Alignment: prediction cache가 config의 test fold와 정확히 일치하는지 확인

특히 이 프로젝트에서는 top-N 종목을 고르는 전략을 쓰므로, 단순 accuracy보다 **Rank IC와 probability bucket별 realized return**이 더 중요하다. 그래서 예측값을 “0.5 이상이면 상승”처럼만 해석하지 않고, 매일 종목 간 상대 순위를 얼마나 잘 잡는지 보도록 평가 체계를 바꿨다.

### 3.6 Horizon별 신호 비교 및 대시보드 확장

H5, H10, H20이 서로 완전히 같은 신호인지, 아니면 다른 시간축의 정보를 잡는지 확인하기 위해 horizon별 비교 분석을 추가했다.

2021~2024 실험

분석 항목:

- H별 최종 성과 비교
- probability bucket별 실제 수익률 proxy
- H5/H10/H20 예측 확률 상관
- top-5, top-10, top-10% 종목 overlap
- H5 high / H20 high 등 조합별 성과
- top-N, threshold, weighting 방식에 따른 rule sensitivity
- 종목별/시장별 손익 기여도

주요 결과:

| 비교    | Pearson Corr | Daily Rank Corr Mean | Top-5 Overlap | Top-10 Overlap | Top-10% Overlap | 해석                                     |
| ------- | -----------: | -------------------: | ------------: | -------------: | --------------: | ---------------------------------------- |
| H5-H10  |        0.963 |                0.939 |        50.45% |         52.74% |          72.95% | 단기와 중단기 신호가 상당히 유사         |
| H5-H20  |        0.891 |                0.846 |        25.40% |         28.48% |          56.17% | H20은 H5와 다른 종목을 더 많이 포착      |
| H10-H20 |        0.962 |                0.945 |        50.30% |         54.24% |          74.11% | H10과 H20은 중기 신호 성격이 강하게 겹침 |

Probability/Top quantile 결과:

| Horizon | 구간   | Average Realized Return | Label Hit Rate | 해석                                           |
| ------- | ------ | ----------------------: | -------------: | ---------------------------------------------- |
| H5      | top 1% |                   0.61% |         57.82% | 상위 랭킹 구간에서 hit rate와 수익률 개선      |
| H5      | top 5% |                   0.44% |         53.01% | 넓은 추천 후보군에서도 양수 수익률 유지        |
| H10     | top 1% |                   1.44% |         54.82% | H10 상위 신호는 수익률 proxy가 H5보다 큼       |
| H10     | top 5% |                   1.08% |         52.70% | 중기 후보군으로 볼 때 안정적인 양수 구간       |
| H20     | top 1% |                   2.64% |         52.55% | horizon이 길어질수록 개별 거래 기대수익이 커짐 |
| H20     | top 5% |                   2.21% |         51.05% | hit rate는 높지 않지만 payoff가 큰 구조        |

H5/H20 신호 조합도 따로 확인했다.

| 그룹               | Sample Count | Average Realized Return | Label Hit Rate | 해석                                         |
| ------------------ | -----------: | ----------------------: | -------------: | -------------------------------------------- |
| H5 high / H20 high |      106,763 |                   0.48% |         51.88% | 단기와 중기 신호가 모두 강한 안정 후보       |
| H5 high / H20 low  |       83,302 |                   0.49% |         51.28% | 단기 모멘텀은 강하지만 중기 확신은 낮은 후보 |
| H5 low / H20 high  |       83,286 |                   0.32% |         46.35% | 중기 신호만 강한 후보는 추가 필터 필요       |
| H5 low / H20 low   |    1,623,789 |                  -0.03% |         37.20% | 양쪽 신호가 모두 약한 회피 후보              |

시장별 기여도에서는 KOSDAQ 비중이 높게 나타났다.

- H5: KOSDAQ 599건, KOSPI 202건, KOSDAQ 손익 기여가 가장 큼
- H10: KOSDAQ 277건, KOSPI 82건, KOSDAQ 중심 성과가 유지됨
- H20: KOSDAQ 226건, KOSPI 65건, KOSPI 기여는 음수로 나타남

이 결과는 모델이 전체 시장을 균등하게 설명한다기보다, **KOSDAQ 및 모멘텀/변동성 성격이 강한 종목군에서 더 많은 기회를 찾는 구조**일 가능성을 보여준다. 따라서 platform에서는 단순히 “상승 확률”만 표시하지 말고, 해당 신호가 어느 horizon에서 강한지, 단기/중기 신호가 일치하는지, KOSDAQ/소형주/고변동성 편향이 있는지를 함께 보여줘야 한다.

이 분석은 추후 platform에서 “단기 신호와 중기 신호가 동시에 강한 종목” 또는 “단기만 강하고 중기는 약한 종목”처럼 사용자에게 더 설명력 있는 정보를 제공하기 위한 기반이다.

### 3.7 Factor Attribution과 모델 편향 분석

각 모델이 실제로 어떤 종목 특성에 집중하는지 보기 위해 factor attribution 분석을 추가했다.

분석한 대표 factor:

- market
- size
- momentum 20
- momentum 60
- volatility
- liquidity
- preferred stock
- SPAC
- speculative proxy

주요 관찰:

- H10, H20은 momentum 20/60 노출이 강하게 나타났다.
- H5도 momentum 노출이 있지만, H10/H20보다는 짧은 구간의 선택 특성이 더 섞여 있다.
- 세 horizon 모두 상대적으로 작은 종목, 변동성이 높은 종목, 유동성이 낮은 종목 쪽으로 일부 기울어지는 경향이 있다.
- H5에서는 SPAC 관련 노출이 눈에 띄었고, H10/H20에서는 speculative proxy와 momentum 노출이 중요하게 나타났다.
- 대표 factor를 제거한 뒤에도 alpha는 양수였지만, 통계적으로 강하게 유의하다고 단정하기는 어렵다.

이 분석의 의미는 모델 성과를 더 엄격하게 보는 데 있다. 예를 들어 수익이 난 이유가 “차트 신호를 잘 잡아서”인지, 아니면 “우연히 특정 시장 factor에 강하게 베팅해서”인지를 구분해야 한다.

### 3.8 Factor-Neutral Backtest 도입

Factor attribution에서 끝내지 않고, 실제로 factor 영향을 제거한 점수로 다시 백테스트를 돌리는 방식도 추가했다.

방법:

- 기존 raw `Prob >= threshold` 조건은 유지한다.
- 날짜별 횡단면에서 `Prob`를 대표 factor들로 회귀한다.
- 회귀 잔차를 factor-neutral score로 본다.
- 이 잔차 점수로 top-N을 다시 고른다.
- 같은 `SwingStrategy`와 `VectorBTEngine`으로 백테스트를 재실행한다.

결과:

| Horizon | Raw Return | Neutral Return | Raw Sharpe | Neutral Sharpe | 해석                                                |
| ------- | ---------: | -------------: | ---------: | -------------: | --------------------------------------------------- |
| H5      |    107.95% |         69.24% |      1.064 |          0.865 | factor 제거 후에도 성과는 남지만 약화               |
| H10     |     77.14% |         54.72% |      1.107 |          0.898 | factor-neutral signal이 일부 유지                   |
| H20     |     68.72% |         57.16% |      1.102 |          0.985 | 세 horizon 중 neutral 이후 방어력이 상대적으로 좋음 |

결론적으로 모델 성과 일부는 momentum, liquidity, size 같은 factor 노출에서 오지만, factor-neutral 조건에서도 성과가 완전히 사라지지는 않았다. 이는 모델이 factor exposure만으로 설명되지는 않지만, factor 편향을 사용자 설명과 리스크 관리에 반영해야 한다는 뜻이다.

## 4. 앞으로 해야 할 일

### 4.1 모델 성능 고도화 방향

현재 모델은 LightGBM 기반 DT 계열 모델로, 설명 가능성과 성능 사이의 균형이 좋다. 당장 블랙박스 딥러닝으로 바꾸기보다는, 같은 화이트박스/준화이트박스 계열 안에서 성능을 끌어올리는 것이 우선이다.

우선순위:

- LightGBM의 objective, class weight, sampling, regularization을 horizon별로 다시 튜닝한다.
- H5/H10/H20을 완전히 별도 모델로 둘지, horizon을 feature로 넣는 multi-horizon 구조를 만들지 비교한다.
- 단일 모델의 확률값만 쓰지 말고, probability rank, confidence, calibration-adjusted probability를 함께 만든다.
- XGBoost, CatBoost, RandomForest, ExtraTrees 같은 DT 계열 후보를 비교한다.
- 모델 교체 기준은 단순 수익률이 아니라 Rank IC, calibration, factor-neutral 성과, holdout 안정성까지 포함한다.
- LSTM/Transformer류 모델은 설명 가능성이 떨어지므로 주 모델 후보보다는 보조 실험 또는 baseline 비교용으로 제한한다.

### 4.2 Feature 개선 방향

현재는 Alpha158 기반 기술 지표와 가격/거래량 중심 feature가 핵심이다. 앞으로는 단순 지표 추가보다, 모델이 실제로 어떤 시장 구조를 놓치고 있는지 보고 feature를 설계해야 한다.

추가 검토할 feature:

- 시장 국면 feature: KOSPI/KOSDAQ 수익률, 변동성, 시장 breadth, 상승 종목 비율
- 상대 강도 feature: 종목 수익률과 업종/시장 수익률의 차이
- 유동성 feature: 거래대금, 거래량 변화율, 저유동성 위험 proxy
- 변동성 구조 feature: 단기/중기 realized volatility, volatility regime 변화
- 이벤트/위험 feature: 거래정지, 관리종목, 상장폐지 위험, SPAC/우선주 여부
- 재무 factor: value, quality, profitability, growth, leverage
- 텍스트 factor: 뉴스 감성, 이슈 강도, 재무제표 요약 점수, SNS/커뮤니티 심리

Feature를 추가할 때는 반드시 SHAP/feature importance, factor exposure, factor-neutral backtest로 “성능이 오른 이유”를 같이 확인해야 한다. 성능이 올라도 특정 자산군 편향만 커졌다면 서비스 설명에는 리스크로 반영해야 한다.

### 4.3 Y Target 재설계 방향

현재 target은 horizon별 트리플 배리어 라벨이다. 앞으로는 투자 전략 목적에 맞게 y target을 여러 방식으로 비교해야 한다.

검토할 target:

- 현재 방식: H일 안에 상방/하방 barrier 중 무엇을 먼저 터치했는가
- Forward return target: H일 후 수익률 자체를 회귀 또는 rank target으로 사용
- Excess return target: 시장 또는 업종 benchmark 대비 초과수익
- Risk-adjusted target: 수익률을 volatility 또는 drawdown 위험으로 보정
- Top quantile target: 같은 날짜 종목 중 상위 q% 수익률 종목인지 분류

중요한 점은 target을 바꾸면 모델이 추구하는 투자 전략도 바뀐다는 것이다. 예를 들어 barrier target은 “특정 수익/손실 구간 도달”에 강하고, rank target은 “매일 상대적으로 좋은 종목 고르기”에 더 적합하다. 우리 서비스가 일반 사용자에게 제공할 결과가 “상승 확률”인지, “시장 대비 유망도”인지, “위험 대비 매력도”인지에 따라 target을 다시 선택해야 한다.

### 4.4 사용자 심리 데이터 결합 방향

프로젝트의 차별점은 행동재무학 기반 투자 심리 지수를 결합하는 것이다. 따라서 chart 모델은 단독 예측기로 끝나면 안 되고, 사용자 심리와 결합할 수 있는 구조로 확장해야 한다.

결합 방식 후보:

- 사용자 위험 성향에 따라 horizon 선택을 다르게 한다.
  - 단기/고위험 성향: H5 중심
  - 중립 성향: H10 중심
  - 보수적 성향: H20 또는 변동성 낮은 후보 중심
- 같은 chart signal이라도 사용자 프로필에 따라 노출 방식을 다르게 한다.
  - 공격형 사용자: 기대수익과 momentum 근거 강조
  - 보수형 사용자: MDD, 변동성, factor 편향, 손실 가능성 강조
- 사용자 심리 점수를 모델 feature로 직접 넣을지, 추천/랭킹 후처리 단계에서 사용할지 비교한다.
- 개인별 심리 데이터가 모델 학습에 들어가면 개인정보/편향 문제가 생기므로, 초기에는 모델 feature가 아니라 output filtering 또는 explanation layer에서 쓰는 것이 안전하다.
- 사용자 설문 결과와 chart 모델 결과를 결합해 “이 종목이 좋은가”가 아니라 “이 사용자가 감당 가능한 신호인가”를 판단한다.

### 4.5 개별 종목 조회/추천 기준 평가 체계

현재 평가는 top-N 종목을 기계적으로 매수/매도했을 때 성과가 나는지 확인하는 성격이 강하다. 하지만 최종 서비스에서는 사용자가 추천 종목을 보기도 하고, 임의의 개별 종목을 직접 조회하기도 한다. 따라서 모델 검증도 “자동매매 전략 성과”뿐 아니라 **개별 종목 화면에서 보여줄 예측값이 얼마나 믿을 만한가**를 평가하는 방향으로 확장해야 한다.

추가해야 할 평가:

- 종목별 예측 확률 분포
- 종목별 hit rate
- 종목별 Brier score
- 종목별 calibration error
- 종목별 예측이 반복적으로 과신/과소신되는지 여부
- KOSPI/KOSDAQ, 대형주/소형주, 고변동성/저변동성, 고유동성/저유동성 그룹별 calibration
- 각 확률 구간별 표본 수와 유사 사례 수
- 모델이 신뢰도 낮음으로 표시해야 할 종목군의 비율

이 평가가 필요한 이유는 전체 평균 calibration이 좋아도 특정 종목군에서는 확률의 의미가 달라질 수 있기 때문이다. 예를 들어 전체적으로 “60~70% 예측 구간의 실제 상승률이 64%”라 해도, 대형주는 66%, 소형 테마주는 48%일 수 있다. 이 경우 소형 테마주 화면에서 단순히 “상승 확률 65%”라고 보여주면 사용자가 과도하게 신뢰할 수 있다.

따라서 개별 종목 화면에는 단일 확률보다 다음 정보를 함께 제공해야 한다.

- 이 종목의 현재 예측 확률
- 같은 확률 구간의 과거 실제 hit rate
- 유사 종목군에서의 hit rate
- 예측 신뢰도 또는 불확실성
- 유사 사례 수
- 고변동성, 저유동성, 소형주, SPAC 등 risk flag
- H5/H10/H20 신호 일관성

서비스 표현도 다음처럼 바뀌어야 한다.

- 부적절한 표현: “상승 확률 65%”
- 더 적절한 표현: “현재 신호는 중간 이상이지만, 이 종목군에서는 과거 예측 신뢰도가 낮아 주의가 필요합니다.”

즉 앞으로의 평가는 top-N backtest와 별도로, **개별 종목 예측 신뢰도 평가**와 **추천/탐색 UX 기준의 품질 평가**를 추가해야 한다.

### 4.6 예측 결과 활용 방식

모델 output은 단순히 `prob_up` 하나로 platform에 넘기면 설명력이 부족하다. 사용자는 금융 지식이 부족할 수 있으므로, 결과값을 투자 판단에 바로 쓰기보다 이해 가능한 신호 묶음으로 변환해야 한다.

필요한 output:

- `code`
- `name`
- `date`
- `horizon`
- `prob_up`
- `rank_percentile`
- `confidence`
- `calibration_bucket`
- `bucket_hit_rate`
- `peer_group_hit_rate`
- `similar_case_count`
- `uncertainty`
- `top_features`
- `factor_exposures`
- `risk_flags`
- `benchmark_index`
- `expected_holding_days`
- `model_version`
- `prediction_hash`
- `disclaimer`

Platform에서는 다음처럼 사용하는 것이 적절하다.

- “상승 확률 70%”처럼 단정적으로 보여주기보다 “과거 유사 조건에서 상위 신호 구간”으로 표현한다.
- H5/H10/H20 신호를 함께 보여줘 단기와 중기 방향성이 일치하는지 알려준다.
- factor 편향이 큰 경우 “소형주/고변동성/저유동성 성향이 강한 신호”라고 표시한다.
- 사용자의 위험 성향과 맞지 않는 신호는 경고하거나 낮은 우선순위로 보여준다.
- 최종 문구는 “투자 추천”이 아니라 “설명 가능한 참고 신호”로 제한한다.

### 4.7 전체 프로젝트 통합 방향

차트 모델은 `analysis/chart` 안에서 끝나는 것이 아니라 `profiling`, `analysis/text`, `platform`과 결합되어야 한다.

통합 구조:

- `analysis/chart`: 가격/거래량 기반 확률, horizon별 신호, 기술적 근거 제공
- `analysis/text`: 뉴스 감성, 재무제표 요약, 기업 이벤트, 시장 이슈 점수 제공
- `profiling`: 사용자 위험 성향, 투자 기간, 손실 회피 성향, 관심 업종 제공
- `schema`: 각 블록이 주고받는 output contract 정의
- `platform`: chart/text/profile 결과를 합쳐 사용자에게 설명 가능한 화면으로 제공

우선 구현해야 할 통합 과제:

- chart output schema 초안 작성
- text sentiment/value score와 chart score를 결합하는 rule 또는 meta-model 설계
- 사용자 profile이 horizon 선택과 risk warning에 반영되는 로직 설계
- 최종 종합 점수를 만들 경우, chart/text/profile 각각의 기여도를 분리해 보여주는 방식 설계
- 모든 수치의 출처와 계산식을 추적할 수 있도록 `model_version`, `config_hash`, `prediction_hash`를 유지

## 5. 팀 회의에서 정해야 할 내용

### 5.1 최종 horizon 운영 방식

- H5, H10, H20을 모두 서비스에 노출할지, 하나의 대표 horizon만 먼저 쓸지 결정해야 한다.
- 모두 노출한다면 사용자에게 “단기, 중기, 장기”를 어떤 표현으로 안내할지 정해야 한다.
- H5/H20 신호가 충돌하는 경우 platform에서 어떻게 보여줄지 정해야 한다.

### 5.2 최종 모델 선택 기준

- 최종 모델을 Total Return 기준으로 고를지, Sharpe/MDD/거래 수를 함께 보는 종합 점수로 고를지 정해야 한다.
- ML validation 지표와 backtest 지표 중 어떤 지표를 더 우선할지 합의해야 한다.
- factor-neutral 성과를 필수 통과 기준으로 둘지, 참고 지표로 둘지 정해야 한다.

### 5.3 사용자 설명 방식

- 예측 확률을 그대로 보여줄지, 위험 등급이나 신뢰도 구간으로 변환해 보여줄지 정해야 한다.
- factor 편향을 일반 사용자에게 어느 수준까지 설명할지 정해야 한다.
- 투자 자문이 아니라는 고지 문구와 위치를 정해야 한다.

### 5.4 블록 간 인터페이스

- `analysis/chart`의 예측 output을 `platform`이 어떤 schema로 받을지 정해야 한다.
- `analysis/text`의 뉴스 감성/재무제표 점수와 chart score를 어떻게 합칠지 정해야 한다.
- `profiling`의 사용자 위험 성향이 horizon 선택이나 결과 표현에 영향을 줄지 정해야 한다.

### 5.5 산출물 관리

- 실험 config는 Git에 남기되, 대용량 cache와 결과 parquet/html은 어디에 저장할지 정해야 한다.
- 발표/논문/시연에 사용할 대표 report 파일을 어떤 형식으로 고정할지 정해야 한다.
- 최종 모델 파일과 prediction hash를 release artifact처럼 관리할지 논의가 필요하다.
