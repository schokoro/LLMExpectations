from datetime import date

from SurveyLogic.PromptBuilders import constants
from SurveyLogic.PromptBuilders.BasePromptBuilder import BasePromptBuilder
from SurveyLogic.PromptBuilders.Profiles.ProfileData import ProfileData
from SurveyLogic.PromptBuilders.StatisticsProviders.InflationProviderLogic.BaseInflationProvider import BaseInflationProvider
from SurveyLogic.PromptBuilders.commonHelpers import showInflation, getDescriptionMonth


class StateInflationContextPromptBuilder(BasePromptBuilder):
    def __init__(self, promptTemplate: str, provider: BaseInflationProvider):
        self.prompt = promptTemplate
        self.inflationProvider = provider

    def buildPrompt(self, surveyDate: date, profile: ProfileData):
        inflation1m = self.inflationProvider.getAverageCommonYearInflationLastNMonth(surveyDate, 1)
        inflation3m = self.inflationProvider.getAverageCommonYearInflationLastNMonth(surveyDate, 3)
        inflation6m = self.inflationProvider.getAverageCommonYearInflationLastNMonth(surveyDate, 6)
        inflation1Y = self.inflationProvider.getAverageCommonYearInflationLastNMonth(surveyDate, 12)

        prompt = self.prompt.replace(constants.inflation1M, getDescriptionMonth(inflation1m, 1, True))
        prompt = prompt.replace(constants.inflation3M, getDescriptionMonth(inflation3m, 3, True))
        prompt = prompt.replace(constants.inflation6M, getDescriptionMonth(inflation6m, 6, True))
        prompt = prompt.replace(constants.inflation1Y, getDescriptionMonth(inflation1Y, 12, True))

        return prompt
