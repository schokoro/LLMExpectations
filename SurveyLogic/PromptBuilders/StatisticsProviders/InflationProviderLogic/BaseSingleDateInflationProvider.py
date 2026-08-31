from abc import ABC, abstractmethod
from datetime import date


class BaseSingleDateInflationProvider(ABC):
    @abstractmethod
    def getInflation(self, d: date, product: str) -> float:
        pass