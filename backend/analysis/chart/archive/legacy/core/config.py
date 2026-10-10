import os

import yaml

# 현재 파일(config.py)의 절대경로 기준으로 yaml 설정 탐색
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(CURRENT_DIR, "config.yaml")
EXAMPLE_CONFIG_PATH = os.path.join(CURRENT_DIR, "config.example.yaml")


def load_config() -> dict:
    """
    config.yaml 설정을 로드합니다.
    만약 config.yaml이 없으면 안내 메세지와 함께 config.example.yaml을 로드합니다.
    """
    if os.path.exists(CONFIG_PATH):
        target_path = CONFIG_PATH
    else:
        print(
            f"[WARN] config.yaml을 찾을 수 없습니다. 예시 설정({EXAMPLE_CONFIG_PATH})을 로드합니다."
        )
        target_path = EXAMPLE_CONFIG_PATH

    with open(target_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    return config


# 전역 변수로 바로 사용할 수 있도록 설정 객체 노출
cfg = load_config()
