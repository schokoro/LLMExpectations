from datetime import date, datetime, time

from SurveyLogic.PromptBuilders.Profiles.ProfileData import ProfileData
from SurveyLogic.PromptBuilders.ProfileSepcificPromptBuilders.CommonProfilePromptBuilder import (
    CommonProfilePromptBuilder,
)


class NewsProfilePromptBuilder(CommonProfilePromptBuilder):
    """Adapt calendar dates from the news runner for inherited profile statistics."""

    def buildPrompt(self, surveyDate: date, profile: ProfileData) -> str:
        if isinstance(surveyDate, date) and not isinstance(surveyDate, datetime):
            surveyDate = datetime.combine(surveyDate, time.min)
        return super().buildPrompt(surveyDate, profile)
