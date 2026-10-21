# Chart

수정가격·시장 심리 피처를 근거로 H5/H20 상대 스코어와 과거 유사 사례를 제공한다. 자동 매매는 하지 않는다.

- `shared/`: 공급자 호출, 원본 OHLC 보정, 실제 VWAP, 거래일 검증, 정규화, Alpha158, Sigma, 수급 피처, 해시·원자적 저장.
- `experiments/`: 장기 구축·재개, 미래 정보가 필요한 라벨·표본 선택, 학습·평가·백테스트, 검증된 결과의 pack 내보내기.
- `serving/`: 운영 입력 갱신·재실행, pack 검사, 추론·Supabase 저장·발행. 연구 코드와 연구 저장 경로를 참조하지 않는다.
- `workspace/experiments/`, `workspace/serving/`, `workspace/archive/`: 데이터·캐시·산출물. 전체 Git 제외.
- `archive/`: 이전 코드·문서 원문. 현재 실행 경로가 아니다.

모든 명령은 `backend/analysis/chart`에서 `python -m experiments...`, `python -m serving...`로 실행한다.

`shared/settings.py`는 실험과 서빙이 함께 쓰는 피처 계산 기본값, 저장 경로, 코드와 설정의 호환성 해시를 정의한다. 같은 가격이 학습과 운영에서 다르게 계산되는 것을 막기 위한 공통 코드다. 입력 열 `Barrier_Up`, `Barrier_Down`의 배수 1.5/1.2는 미래 정답을 정하는 H5/H20 라벨 배수와 별개다. 학습 라벨은 실험 설정의 `labels`, 내보낸 운영 모델에서는 pack manifest의 `horizons.h5/h20.label_barriers`가 정본이다.

`settings.py`는 원문 해시까지 pack 계약에 포함된다. 설명을 추가하는 변경도 기존 pack과의 호환성을 확인해야 하므로, 채점 오류를 고치려고 공통 피처 설정을 바꾸지 않는다.

실행법: [실험](experiments/README.md), [serving](serving/OPERATIONS.md). 해석 전 [품질 제한](docs/DATA_QUALITY.md)을 확인한다.

대표 결과는 [RESULTS.md](docs/RESULTS.md), 이동·검증 기록은 [VALIDATION.md](docs/VALIDATION.md), 삭제 검토 목록은 [DELETION_CANDIDATES.md](docs/DELETION_CANDIDATES.md)에 있다.
