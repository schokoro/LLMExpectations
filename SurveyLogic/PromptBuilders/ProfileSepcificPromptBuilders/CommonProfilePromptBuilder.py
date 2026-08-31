from datetime import date

from SurveyLogic.PromptBuilders import constants
from SurveyLogic.PromptBuilders.BasePromptBuilder import BasePromptBuilder
from SurveyLogic.PromptBuilders.Profiles.ProfileData import ProfileData
from SurveyLogic.PromptBuilders.StatisticsProviders.BaseAverageExpensesProvider import BaseAverageExpensesProvider
from SurveyLogic.PromptBuilders.StatisticsProviders.MROTProvider import MROTProvider
from SurveyLogic.PromptBuilders.commonHelpers import months_ru, processIfNone, processBoolToYesNo, checkNoAnswer, \
    getNoAnswerDescription


class CommonProfilePromptBuilder(BasePromptBuilder):
    def __init__(self, prompt: str, mrotProvider: MROTProvider, averageExpensesProvider: BaseAverageExpensesProvider):
        self.averageExpensesProvider = averageExpensesProvider
        self.mrotProvider = mrotProvider
        self.prompt = prompt

    def buildPrompt(self, surveyDate: date, profile: ProfileData):

        prompt = self.prompt.replace(constants.surveyDateTag, months_ru[surveyDate.month%12])
        prompt = prompt.replace(constants.ageTag, processIfNone(profile.age))
        prompt = prompt.replace(constants.sexTag, processIfNone(profile.sex))
        prompt = prompt.replace(constants.localityTag, processIfNone(profile.currentLocality))
        prompt = prompt.replace(constants.localityTypeTag, processIfNone(profile.typeOfLocality))
        prompt = prompt.replace(constants.educationTag, processIfNone(profile.education))
        prompt = prompt.replace(constants.nationalityTag, processIfNone(profile.nationality))
        prompt = prompt.replace(constants.familyStatusTag, processIfNone(profile.familyStatus))
        prompt = prompt.replace(constants.currentStatusTag, processIfNone(profile.currentStatus))
        prompt = prompt.replace(constants.jobSectorTag, processIfNone(profile.jobSector))
        prompt = prompt.replace(constants.jobTag, processIfNone(profile.job))

        salary = self._processSalary(surveyDate, profile)

        prompt = prompt.replace(constants.salaryTag, salary)
        prompt = prompt.replace(constants.economicsSourceOfKnowledge, processIfNone(profile.economicsSourceOfKnowledge))
        prompt = prompt.replace(constants.hasSavingsTag, processBoolToYesNo(profile.hasSavings))
        prompt = prompt.replace(constants.hasCreditsTag, processBoolToYesNo(profile.hasCredit))

        return prompt

    def _processSalary(self, surveyDate: date, profile: ProfileData) -> str:
        if checkNoAnswer(profile.salary):
            return getNoAnswerDescription(profile.salary)

        s = float(profile.salary)
        mrot = self.mrotProvider.getMROT(surveyDate)
        averageExpenses = self.averageExpensesProvider.getRegionAverageExpenses(profile.currentLocalityRegionCode, surveyDate)/12

        salaryInMrot = s / mrot
        salaryInAverages = s / averageExpenses

        salary = f'{salaryInMrot: .1f} в терминах МРОТ (по всей России), {salaryInAverages: .1f} в терминах средних трат по региону проживания {profile.currentLocalityRegion}'
        return salary
