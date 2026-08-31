from abc import ABC, abstractmethod
from datetime import date


class BaseInflationExpectationsProvider(ABC):
    @abstractmethod
    def getInflationExpectations(self, surveyDate: date):
        pass