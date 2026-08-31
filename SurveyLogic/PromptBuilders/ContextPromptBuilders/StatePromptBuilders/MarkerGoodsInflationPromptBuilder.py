from datetime import date

from SurveyLogic.PromptBuilders.BasePromptBuilder import BasePromptBuilder
from SurveyLogic.PromptBuilders.Profiles.ProfileData import ProfileData
from SurveyLogic.PromptBuilders.StatisticsProviders.InflationProviderLogic.BaseInflationProvider import \
    BaseInflationProvider
from SurveyLogic.PromptBuilders.commonHelpers import getDescriptionWeeks, getDescriptionMonth


class MarkerGoodsInflationPromptBuilder(BasePromptBuilder):
    def __init__(self, inflationProvider: BaseInflationProvider, regularGoods: list[str], durableGoods: list[str], services: list[str]):
        self.services = services
        self.durableGoods = durableGoods
        self.regularGoods = regularGoods

        self.inflationProvider = inflationProvider

    def buildPrompt(self, surveyDate: date, profile: ProfileData):

        regularGoodsDescription = self._getDescription(surveyDate, profile, self.regularGoods)
        durableGoodsDescription = self._getDescription(surveyDate, profile, self.durableGoods, [False, False, True, True, True, True])
        servicesDescription = self._getDescription(surveyDate, profile, self.services, [False, False, True, True, True, True])

        return f'Инфляция на товары-маркеры регулярного потребления:\n{regularGoodsDescription}\nИнфляция на товары-маркеры длительного потребления:\n{durableGoodsDescription}\nИнфляция на услуги-маркеры:\n{servicesDescription}'

    def _getDescription(self, surveyDate: date, profile: ProfileData, goods: list[str], mask: list[bool] = None):
        if mask is None:
            mask = [True] * 6

        description = ''
        region = profile.currentLocalityRegionCode

        for good in goods:
            currentDescription = ''

            inflation1w = self.inflationProvider.getProductsCommonWeeklyInflationLastNWeeks(surveyDate, [good], 1)[0]
            inflation2w = self.inflationProvider.getProductsCommonWeeklyInflationLastNWeeks(surveyDate, [good], 2)[0]

            inflation1m = self.inflationProvider.getProductsRegionalYearInflationLastNMonth(surveyDate, region, [good],
                                                                                            1)[0]
            inflation3m = self.inflationProvider.getProductsRegionalYearInflationLastNMonth(surveyDate, region, [good],
                                                                                            3)[0]
            inflation6m = self.inflationProvider.getProductsRegionalYearInflationLastNMonth(surveyDate, region, [good],
                                                                                            6)[0]
            inflation12m = self.inflationProvider.getProductsRegionalYearInflationLastNMonth(surveyDate, region, [good],
                                                                                             12)[0]

            if inflation1w is not None and mask[0]:
                currentDescription += f' {getDescriptionWeeks(inflation1w, 1)},'

            if inflation2w is not None and mask[1]:
                currentDescription += f' {getDescriptionWeeks(inflation2w, 2)},'

            if inflation1m is not None and mask[2]:
                currentDescription += f' {getDescriptionMonth(inflation1m, 1, isInflation=True)},'

            if inflation3m is not None and mask[3]:
                currentDescription += f' {getDescriptionMonth(inflation3m, 3, isInflation=True)},'

            if inflation6m is not None and mask[4]:
                currentDescription += f' {getDescriptionMonth(inflation6m, 6, isInflation=True)},'

            if inflation12m is not None and mask[5]:
                currentDescription += f' {getDescriptionMonth(inflation12m, 12, isInflation=True)}'

            if currentDescription == '':
                continue

            description += f'{good}:{currentDescription}\n'

        return description