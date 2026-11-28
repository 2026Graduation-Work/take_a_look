import fcntl
import gc
import json
import os
import tempfile
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

    def _write_cache_manifest(self, path, feature_names, kind, parameters, cache_key):
        if self.config.get("contract_version") != 3:
            return
        from shared.io import atomic_json, sha256

        atomic_json(
            str(path) + ".manifest.json",
            {
                "kind": kind,
                "cache_key": cache_key,
                "feature_columns": list(feature_names),
                "parameters": parameters,
                "sha256": sha256(path),
                "processing_contract": self.config.get("processing_contract"),
            },
        )

    def _validate_cache(self, path, kind, *, cache_key=None):
        if self.config.get("contract_version") != 3:
            return
        from shared.io import sha256
        from shared.processing import processing_compatible

        manifest_path = Path(f"{path}.manifest.json")
        try:
            manifest = json.loads(manifest_path.read_text())
            contract = self.config.get("processing_contract")
            recorded = manifest.get("processing_contract")
            compatible = (recorded is None if contract is None else processing_compatible(recorded, contract))
            if (
                manifest.get("kind") == kind
                and (cache_key is None or manifest.get("cache_key") == cache_key)
                and manifest.get("feature_columns") == self.config["feature_columns"]
                and manifest.get("sha256") == sha256(path)
                and compatible
            ):
                return
        except (AttributeError, OSError, ValueError):
            pass
        raise ValueError(f"Invalid {kind} cache: {path}")

    def cache_entry(self, base, kind):
        from experiments.experiment_utils import cache_slot

        def valid(path):
            try:
                self._validate_cache(path, kind, cache_key=Path(base).name)
                return True
            except ValueError:
                return False

        return cache_slot(base, valid)

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
        base = Path(bin_path)
        with Path(f"{base}.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            path, reusable = self.cache_entry(base, "dataset")
            if reusable:
                print(f"  [CACHE HIT] Train .bin: {path.name}")
                return self.load_cached_dataset(str(path))

            print(f"  [BUILD] Train .bin (shape: {X.shape})")
            parameters = {"class_weight": self.params.get("class_weight"), "max_bin": self.params.get("max_bin", 255)}
            dataset = lgb.Dataset(X, label=y, weight=self.sample_weights(y),
                                  params={"max_bin": parameters["max_bin"]}, free_raw_data=False)
            dataset.construct()
            with tempfile.TemporaryDirectory(dir=base.parent) as staging:
                temporary = Path(staging) / path.name
                dataset.save_binary(str(temporary))
                temporary.replace(path)
            self._write_cache_manifest(path, dataset.feature_name, "dataset", parameters, base.name)
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
            base = Path(models_dir) / f"{cache_hash}_model.txt"
            with Path(f"{base}.lock").open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                model_save_path, reusable = self.cache_entry(base, "model")
                if not reusable:
                    with tempfile.TemporaryDirectory(dir=models_dir) as staging:
                        temporary = Path(staging) / base.name
                        self.model.save_model(str(temporary))
                        temporary.replace(model_save_path)
                    self._write_cache_manifest(model_save_path, self.model.feature_name(), "model",
                                               self.applied_params, base.name)
            print(f"[LGBM] 모델 파라미터(Booster) 저장 완료 -> {model_save_path}")

        del train_data, valid_data
        gc.collect()

    def predict(self, X_test):
        if self.model is None:
            raise ValueError("모델이 학습되지 않았습니다. fit()을 먼저 호출하세요.")

        probs = self.model.predict(X_test)
        return probs[:, 2]
