from abc import ABC, abstractmethod
from datetime import date
from SurveyLogic.PromptBuilders.Profiles.ProfileData import ProfileData
from SurveyLogic.SurveyResults.InflationSurveyRespond import InflationSurveyRespond


class BaseSurveyExecutor(ABC):
    @abstractmethod
    def executeSurvey(self, surveyDate: date, profile: ProfileData):
        pass