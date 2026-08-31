import random
from datetime import date

from SurveyLogic.PromptBuilders.Profiles.BaseProfilesProvider import BaseProfilesProvider
from SurveyLogic.PromptBuilders.Profiles.ProfileData import ProfileData


class RandomSubsampleProfilesProvider(BaseProfilesProvider):
    def __init__(self, provider: BaseProfilesProvider, count: int):
        self.count = count
        self.provider = provider

    def getProfiles(self, surveyDate: date):
        profiles = self.provider.getProfiles(surveyDate)
        n = len(profiles)
        k = max(1, min(self.count, n))

        return random.sample(profiles, k)
