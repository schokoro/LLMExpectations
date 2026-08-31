from datetime import date
from pathlib import Path

from SurveyLogic.PromptBuilders.StatisticsProviders.InflationProviderLogic.BaseSingleDateInflationProvider import \
    BaseSingleDateInflationProvider
from SurveyLogic.PromptBuilders.StatisticsProviders.InflationProviderLogic.SingleDateWeeklyInflationProvider import \
    SingleDateWeeklyInflationProvider


class MultipleWeeklyInflationProvider(BaseSingleDateInflationProvider):
    def __init__(self, path: Path, years: list[int]):
        providersMap = dict[int, BaseSingleDateInflationProvider]()
        for year in years:
            providersMap[year] = SingleDateWeeklyInflationProvider(path, year)

        self.providers = providersMap

    def getInflation(self, d: date, product: str):
        curYear = d.year
        if curYear not in self.providers:
            return None

        inflation = self.providers[curYear].getInflation(d, product)
        return inflation
