from datetime import date

import pandas as pd

from SurveyLogic.PromptBuilders.StatisticsProviders.InflationProviderLogic.BaseSingleDateInflationProvider import \
    BaseSingleDateInflationProvider
from SurveyLogic.PromptBuilders.StatisticsProviders.InflationProviderLogic.BaseWeeklyInflationProvider import \
    BaseWeeklyInflationProvider


class RosstatWeeklyInflationProvider(BaseWeeklyInflationProvider):
    def __init__(self, inflationProvider: BaseSingleDateInflationProvider):
        self.provider = inflationProvider

    def getWeeklyInflation(self, d: date, products: list[str], weeksOffset: int) -> list[float]:
        result = []

        for p in products:
            curInflation = self._getProductWeeklyInflation(d, p, weeksOffset)
            result.append(curInflation)

        return result

    def _getProductWeeklyInflation(self, d: date, product: str, weeksOffset: int):
        inflation = 1
        allInflationsAreNone = True

        for i in range(weeksOffset):
            currentDate = (d - pd.DateOffset(days=7*i + 1)).date()
            curInflation = self.provider.getInflation(currentDate, product)

            if curInflation is None:
                continue

            allInflationsAreNone = False
            inflation = inflation * curInflation/100

        if allInflationsAreNone:
            return None

        return inflation**(365 / (7 * weeksOffset)) - 1
