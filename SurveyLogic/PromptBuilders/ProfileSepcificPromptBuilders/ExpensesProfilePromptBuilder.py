from datetime import date
from pathlib import Path

from SurveyLogic.PromptBuilders import constants
from SurveyLogic.PromptBuilders.BasePromptBuilder import BasePromptBuilder
from SurveyLogic.PromptBuilders.Profiles.ProfileData import ProfileData
from SurveyLogic.PromptBuilders.StatisticsProviders.InflationProviderLogic.BaseInflationProvider import \
    BaseInflationProvider
from SurveyLogic.PromptBuilders.commonHelpers import loadRlmsGoodsToRosstatGoodsMap, getTop5, \
    getDescriptionMonth


class ExpensesProfilePromptBuilder(BasePromptBuilder):
    def __init__(self, promptTemplate: str, provider: BaseInflationProvider, pathes: list[Path]):
        self.prompt = promptTemplate
        self.inflationProvider = provider

        self.map = loadRlmsGoodsToRosstatGoodsMap(pathes)

    def buildPrompt(self, surveyDate: date, profile: ProfileData):

        goods = [profile.regular, profile.durable, profile.services]
        goodNames = [constants.regularTag, constants.durableTag, constants.servicesTag]

        result = self.prompt
        for i in range(len(goods)):
            top5Goods = getTop5(self.map, goods[i])

            inflation1m = self.inflationProvider.getProductsRegionalYearInflationLastNMonth(surveyDate, profile.currentLocalityRegionCode, top5Goods, 1)
            inflation3m = self.inflationProvider.getProductsRegionalYearInflationLastNMonth(surveyDate, profile.currentLocalityRegionCode, top5Goods, 3)
            inflation6m = self.inflationProvider.getProductsRegionalYearInflationLastNMonth(surveyDate, profile.currentLocalityRegionCode, top5Goods, 6)

            currentPrompt = self._getCurrentGoodsPromptSet(top5Goods, inflation1m, inflation3m, inflation6m)
            result = result.replace(goodNames[i], currentPrompt)

        return result

    def _getCurrentGoodsPromptSet(self, top5Goods: list[str], inflation1m: list[float], inflation3m: list[float], inflation6m: list[float]) -> str:
        result = '\n'

        for i in range(len(top5Goods)):
            inflation1mDescription = getDescriptionMonth(inflation1m[i], 1)
            inflation3mDescription = getDescriptionMonth(inflation3m[i], 3)
            inflation6mDescription = getDescriptionMonth(inflation6m[i], 6)
            inflation12mDescription = getDescriptionMonth(inflation6m[i], 12)

            result += f'#{i}. {top5Goods[i]}: {inflation1mDescription}, {inflation3mDescription}, {inflation6mDescription}, {inflation12mDescription}\n'

        return result




