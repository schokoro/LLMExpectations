from datetime import date
from pathlib import Path

from SurveyLogic.PromptBuilders import constants
from SurveyLogic.PromptBuilders.BasePromptBuilder import BasePromptBuilder
from SurveyLogic.PromptBuilders.Profiles.ProfileData import ProfileData
from SurveyLogic.PromptBuilders.StatisticsProviders.InflationProviderLogic.BaseInflationProvider import \
    BaseInflationProvider
from SurveyLogic.PromptBuilders.commonHelpers import loadRlmsGoodsToRosstatGoodsMap, getTop5, getDescriptionWeeks


class StateExpensesProfilePromptBuilder(BasePromptBuilder):
    def __init__(self, promptTemplate: str, inflationProvider: BaseInflationProvider, pathes: list[Path]):
        self.prompt = promptTemplate
        self.inflationProvider = inflationProvider

        self.map = loadRlmsGoodsToRosstatGoodsMap(pathes)

    def buildPrompt(self, surveyDate: date, profile: ProfileData):
        goods = [profile.regular, profile.durable, profile.services]
        goodNames = [constants.regularTag, constants.durableTag, constants.servicesTag]

        allGoodsAreOff = True
        result = self.prompt
        for i in range(len(goods)):
            top5Goods = getTop5(self.map, goods[i])

            inflation1w = self.inflationProvider.getProductsCommonWeeklyInflationLastNWeeks(surveyDate, top5Goods, 1)
            inflation2w = self.inflationProvider.getProductsCommonWeeklyInflationLastNWeeks(surveyDate, top5Goods, 2)
            inflation4w = self.inflationProvider.getProductsCommonWeeklyInflationLastNWeeks(surveyDate, top5Goods, 4)

            if any(x is not None for x in inflation1w) or any(x is not None for x in inflation2w) or any(x is not None for x in inflation4w):
                allGoodsAreOff = False

            currentPrompt = self._getCurrentGoodsPromptSet(top5Goods, inflation1w, inflation2w, inflation4w)
            result = result.replace(goodNames[i], currentPrompt)

        if allGoodsAreOff:
            return 'Нет информации по недельныим данным'

        return result

    def _getCurrentGoodsPromptSet(self, top5Goods: list[str], inflation1m: list[float], inflation3m: list[float], inflation6m: list[float]) -> str:
        result = '\n'

        for i in range(len(top5Goods)):
            inflation1wDescription = getDescriptionWeeks(inflation1m[i], 1)
            inflation2wDescription = getDescriptionWeeks(inflation3m[i], 2)
            inflation4wDescription = getDescriptionWeeks(inflation6m[i], 4)

            result += f'#{i}. {top5Goods[i]}: {inflation1wDescription}, {inflation2wDescription}, {inflation4wDescription}\n'

        return result