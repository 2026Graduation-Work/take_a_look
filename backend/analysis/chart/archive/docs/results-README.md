# 대표 실험 결과

이 디렉터리에는 Git으로 공유할 **대표 결과 요약만** 남긴다. 개별 실험의
예측 캐시, 모델 캐시, 거래 내역, 일별 수익률, HTML 리포트와 전체 결과 폴더는
로컬 또는 팀의 별도 스토리지에 보관한다.

## 보관 규칙

- 재현에 필요한 코드는 `experiments/`, 설정은 `experiments/configs/`에 둔다.
- 각 실행의 산출물은 `experiments/results/<experiment_name>/`에 로컬 저장한다.
- 채택·비교 대상 결과만 이 문서에 실험명, 설정 파일, 기간, 핵심 지표와 결론을 기록한다.
- 결과를 업데이트할 때는 사용한 데이터 기간, 거래 비용, 분할 방식, prediction hash와 `data.version`을 함께 기록한다.
- 아래 수익률은 과거 백테스트 결과이며 미래 수익을 보장하거나 투자 판단을 권유하지 않는다.

## 현재 대표 비교 결과

동일한 백테스트 엔진과 각 설정의 검증 분할을 기준으로 기록한 후보 결과다.
정확한 기간·수수료·분할 파라미터는 실행 결과 폴더의 `config_snapshot.yaml`을 기준으로 확인한다.
개별 설정 파일은 로컬 전용이므로 표의 파일명은 실험 식별용 기록이며 fresh checkout에서 존재한다고 가정하지 않는다.

| Horizon | 실험명 | 설정 | 총수익률 | CAGR | Sharpe | 최대 낙폭 | 거래 수 | Fold 정합성 |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| H5 | `tb_lgbm_h5_u175_d150_alpha158_regime4` | `configs/tb_lgbm_h5_u175_d150_alpha158_regime4.yaml` | 126.44% | 22.18% | 1.09 | -15.12% | 827 | exact (4 folds) |
| H10 | `tb_lgbm_h10_u250_d225_alpha158_current_sigma_selection2020_2022` | `configs/tb_lgbm_h10_u250_d225_alpha158_current_sigma_selection2020_2022.yaml` | 92.32% | 23.83% | 1.14 | -16.07% | 386 | exact (3 folds) |
| H20 | `tb_lgbm_h20_u375_d300_alpha158_current_sigma_selection2020_2022` | `configs/tb_lgbm_h20_u375_d300_alpha158_current_sigma_selection2020_2022.yaml` | 82.89% | 21.81% | 1.10 | -13.15% | 310 | exact (3 folds) |

`prediction_hash`는 각각 H5 `f51893d6`, H10 `7c362764`, H20 `7493ede1`이다.
대표 후보의 선택은 단일 성과 지표가 아니라 기간별 재현성, 최대 낙폭, 거래 수와
향후 holdout 검증을 함께 고려해 확정한다.
