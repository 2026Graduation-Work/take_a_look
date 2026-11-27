# 백테스트 실험실

차트 연구용 실행기와 같은 Python 환경에서 `frontend/`의 `pnpm lab`을 실행하고
[백테스트 실험실](http://127.0.0.1:3000/lab/backtest)을 연다. 다른 Python을 쓰려면
`BACKTEST_LAB_PYTHON=/path/to/venv/bin/python pnpm lab`을 실행한다.
Python 환경은 `backend/analysis/chart/experiments/requirements.txt`를 따른다.

워크스페이스는 `backend/analysis/chart/workspace/experiments/`다. 실험실은
`runs/`의 결과를 읽고, `lab/configs/`에 검사한 설정을, `lab/jobs/`에 실행 로그를 쓴다.
기준 설정은 차트의 `experiments/configs/`와 워크스페이스의 `lab/configs/`에서 선택한다.
검사 결과에 예측 캐시가 없으면 해당 설정으로 학습한 후 다시 검사한다.
같은 결과 폴더를 다시 사용할 때는 실행 전에 덮어쓰기를 확인한다.
