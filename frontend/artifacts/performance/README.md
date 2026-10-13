# 비교실험 결과 연결

검증된 비교실험의 `comparison_results.json`을 이 디렉토리에 두면
`/performance`가 빌드 시 자동으로 읽습니다.

```text
frontend/artifacts/performance/comparison_results.json
```

- 파일이 없으면 화면 검증용 목데이터와 `샘플 데이터` 배지를 사용합니다.
- 파일이 존재하지만 JSON 구조나 B-A 델타가 잘못되면 빌드를 실패시킵니다.
- 같은 디렉토리의 다른 결과 파일을 사용할 때는 서버 전용
  `PERFORMANCE_RESULTS_FILE`에 파일명을 설정합니다.
- 러너의 `manifest.json`과 원본 CSV는 재현성 증빙을 위해 실험 결과 저장소에 함께 보관합니다.

현재 자료는 `psychology_ab_2019_2025`의 완료된 H5/H20 × A/B 결과다. A는 운영 모델과 같은 170개 입력 구성이고 B는 시장 심리 4개를 추가한 174개다. 과거 연도마다 별도로 학습했으므로 현재 운영 pack 자체의 과거 성적이 아니다.

차트 디렉터리에서 다음 명령으로 원본·모델 해시와 공통 표본을 검증한 뒤 내보낸다. 재학습·원격 수집·운영 모델 변경은 하지 않는다.

```bash
python -m experiments.export_performance \
  --suite-dir workspace/experiments/runs/psychology_ab_2019_2025 \
  --output ../../../frontend/artifacts/performance/comparison_results.json
```

실행 환경에 따라 `--suite-dir`에 보존된 실험의 절대 경로를 지정한다. 상태 기록에 원본 파일의 절대 경로가 있으므로 다른 PC로 옮기면 원본 위치를 복원하거나 해시를 보존한 상태로 경로를 명시적으로 재연결해야 한다.

ROC-AUC·상승 여부 일치율(임계 0.5)·Brier·ECE는 연도별 단순평균이다. 주지표는 ROC-AUC다. 수익률·Sharpe·MDD도 매년 1,000만 원으로 시작한 독립 연도의 단순평균이며 거래 수는 합계다. 고변동일은 각 연도 공통 예측 표본의 일별 Sigma 평균 상위 20%(날짜 수 올림, 동점 날짜순)로 고른다. 이 표본의 별도 백테스트는 실행하지 않아 `null`로 표시한다.

`performance-provenance.json`은 내보내기 코드·완료 상태·자료 해시를 기록한다. 데이터·정보 시점의 한계가 있는 공통 표본의 연구 비교이며 통계적 유의성이나 미래 성과를 보장하지 않는다.
