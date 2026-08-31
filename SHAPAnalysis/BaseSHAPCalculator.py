from abc import ABC, abstractmethod


class BaseSHAPCalculator(ABC):
    @abstractmethod
    def calculateShapValues(self, responds) -> dict[str, float]:
        pass