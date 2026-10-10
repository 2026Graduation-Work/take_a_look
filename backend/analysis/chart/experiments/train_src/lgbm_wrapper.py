import gc
import json
import os
from pathlib import Path

import lightgbm as lgb
from sklearn.utils.class_weight import compute_sample_weight

from .base_model import BaseModel


class LGBMWrapper(BaseModel):
    def __init__(self, config: dict):
        super().__init__(config)
        self.params = config.get("model", {}).get("params", {})
        # 현재 파일(lgbm_wrapper.py)의 절대경로 기준 cache 디렉토리 지정
        CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
        self.cache_dir = config.get("cache_dir", str(Path(CURRENT_DIR).parents[1] / "workspace/experiments/cache/training"))
        os.makedirs(self.cache_dir, exist_ok=True)

    def _write_cache_manifest(self, path, feature_names, kind, parameters):
        if self.config.get("contract_version") != 3:
            return
        from shared.io import atomic_json, sha256

        atomic_json(
            str(path) + ".manifest.json",
            {
                "kind": kind,
                "feature_columns": list(feature_names),
                "parameters": parameters,
                "sha256": sha256(path),
                "processing_contract": self.config.get("processing_contract"),
            },
        )

    def _validate_cache(self, path, kind):
        if self.config.get("contract_version") != 3:
            return
        from shared.io import sha256

        manifest_path = Path(str(path) + ".manifest.json")
        if not manifest_path.exists():
            raise ValueError(
                f"Missing {kind} manifest; remove invalid cache and rerun train.py: {path}"
            )
        manifest = json.loads(manifest_path.read_text())
        if (
            manifest.get("kind") != kind
            or manifest.get("feature_columns") != self.config["feature_columns"]
            or manifest.get("sha256") != sha256(path)
            or manifest.get("processing_contract") != self.config.get("processing_contract")
        ):
            raise ValueError(f"Invalid {kind} cache; remove and rerun train.py: {path}")

    def load_cached_model(self, path):
        self._validate_cache(path, "model")
        self.model = lgb.Booster(model_file=path)
        if (
            self.config.get("contract_version") == 3
            and self.model.feature_name() != self.config["feature_columns"]
        ):
            raise ValueError("Model feature order differs from config")

    def load_cached_dataset(self, path):
        self._validate_cache(path, "dataset")
        return lgb.Dataset(path, free_raw_data=False)

    def sample_weights(self, y):
        class_weight = self.params.get("class_weight")
        return compute_sample_weight(class_weight, y) if class_weight is not None else None

    def _build_dataset(self, X, y, bin_path: str):
        """DataFrame을 lgb.Dataset(.bin)으로 변환하고 캐싱합니다."""
        if os.path.exists(bin_path):
            print(
                f"  [CACHE HIT] 기존 캐시된 .bin 파일 로드 (1초 컷): {os.path.basename(bin_path)}"
            )
            return self.load_cached_dataset(bin_path)

        print(f"  [BUILD] 새로운 .bin 파일 굽는 중... (Shape: {X.shape})")
        sample_weights = self.sample_weights(y)

        dataset = lgb.Dataset(
            X,
            label=y,
            weight=sample_weights,
            params={"max_bin": self.params.get("max_bin", 255)},
            free_raw_data=False,
        )
        dataset.construct()

        tmp_path = bin_path + ".tmp"
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

        dataset.save_binary(tmp_path)
        os.replace(tmp_path, bin_path)
        self._write_cache_manifest(
            bin_path,
            dataset.feature_name,
            "dataset",
            {
                "class_weight": self.params.get("class_weight"),
                "max_bin": self.params.get("max_bin", 255),
            },
        )

        return dataset

    def fit(self, X_train, y_train, X_val=None, y_val=None, cache_hash=None):
        if isinstance(X_train, lgb.Dataset):
            print("[LGBM] 사전 생성된 Train/Validation 데이터셋 수신 완료.")
            train_data = X_train
            valid_data = y_train
        else:
            if cache_hash is None:
                cache_hash = "default_hash"

            train_bin_path = os.path.join(self.cache_dir, f"{cache_hash}_train.bin")
            print("[LGBM] Train 데이터셋 준비 중...")
            train_data = self._build_dataset(X_train, y_train, train_bin_path)

            del X_train, y_train
            gc.collect()

            valid_data = None
            if X_val is not None and y_val is not None:
                print("[LGBM] Validation 데이터셋 준비 중 (bin mapper 동기화)...")
                sample_weights_val = self.sample_weights(y_val)
                valid_data = lgb.Dataset(
                    X_val,
                    label=y_val,
                    weight=sample_weights_val,
                    reference=train_data,
                    free_raw_data=False,
                )
                del X_val, y_val
                gc.collect()

        print("[LGBM] 🚀 모델 학습 시작...")

        default_params = {
            "objective": "multiclass",
            "num_class": 3,
            "metric": "multi_logloss",
            "boosting_type": "gbdt",
            "random_state": 42,
            "verbose": -1,
            "n_jobs": -1,
        }
        lgb_params = {**default_params, **self.params}
        lgb_params.pop("class_weight", None)
        lgb_params["deterministic"] = True
        lgb_params["force_col_wise"] = True
        self.applied_params = lgb_params.copy()
        n_estimators = lgb_params.pop("n_estimators", 1000)

        callbacks = []
        if valid_data:
            callbacks.append(lgb.early_stopping(stopping_rounds=50, verbose=False))
            callbacks.append(lgb.log_evaluation(period=100))

        self.model = lgb.train(
            params=lgb_params,
            train_set=train_data,
            num_boost_round=n_estimators,
            valid_sets=[train_data, valid_data] if valid_data else [train_data],
            callbacks=callbacks,
        )

        print("[LGBM] ✅ 학습 완료!")

        if cache_hash is not None:
            models_dir = os.path.join(self.cache_dir, "models")
            os.makedirs(models_dir, exist_ok=True)
            model_save_path = os.path.join(models_dir, f"{cache_hash}_model.txt")
            self.model.save_model(model_save_path)
            self._write_cache_manifest(
                model_save_path, self.model.feature_name(), "model", self.applied_params
            )
            print(f"[LGBM] 모델 파라미터(Booster) 저장 완료 -> {model_save_path}")

        del train_data, valid_data
        gc.collect()

    def predict(self, X_test):
        if self.model is None:
            raise ValueError("모델이 학습되지 않았습니다. fit()을 먼저 호출하세요.")

        probs = self.model.predict(X_test)
        return probs[:, 2]
