from abc import ABC, abstractmethod


class BaseModel(ABC):
    def __init__(self, config: dict):
        self.config = config
        self.model = None

    @abstractmethod
    def fit(self, X_train, y_train, X_val=None, y_val=None, cache_hash=None):
        pass

    @abstractmethod
    def predict(self, X_test):
        pass
