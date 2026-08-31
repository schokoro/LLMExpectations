from datetime import date

from SurveyLogic.PromptBuilders.BasePromptBuilder import BasePromptBuilder
from SurveyLogic.PromptBuilders.Profiles.ProfileData import ProfileData
from SurveyLogic.PromptBuilders.StatisticsProviders.BaseInflationExpectationsProvider import \
    BaseInflationExpectationsProvider


class PrevoiusInflationExpectationsPromptBuilder(BasePromptBuilder):
    def __init__(self, inflationExpectationsProvider: BaseInflationExpectationsProvider):
        self.inflationExpectationsProvider = inflationExpectationsProvider

    def buildPrompt(self, surveyDate: date, profile: ProfileData):
        previousInflationExpectations = self.inflationExpectationsProvider.getInflationExpectations(surveyDate)

        return f'По последней доступной до текущего опроса волне общероссийского опроса медианная оценка ожидаемой населением инфляции на следующие 12 месяцев составляла {previousInflationExpectations: .1f}%.'