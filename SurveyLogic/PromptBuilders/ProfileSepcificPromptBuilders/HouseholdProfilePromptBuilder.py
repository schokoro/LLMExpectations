from datetime import date
from SurveyLogic.PromptBuilders import constants
from SurveyLogic.PromptBuilders.BasePromptBuilder import BasePromptBuilder
from SurveyLogic.PromptBuilders.Profiles.ProfileData import ProfileData
from SurveyLogic.PromptBuilders.StatisticsProviders.BaseAverageExpensesProvider import BaseAverageExpensesProvider
from SurveyLogic.PromptBuilders.commonHelpers import checkNoAnswer, getNoAnswerDescription, getSafeDescription, \
    processYesNo


class HouseholdProfilePromptBuilder(BasePromptBuilder):
    def __init__(self, prompt: str, provider: BaseAverageExpensesProvider):
        self.prompt = prompt
        self.provider = provider

    def buildPrompt(self, surveyDate: date, profile: ProfileData):
        hhAverageExpenses = self.provider.getRegionAverageExpenses(profile.currentLocalityRegionCode, surveyDate)

        expensesRepresentation = self._getExpensesRepresentation(profile, hhAverageExpenses)
        prompt = self.prompt.replace(constants.familyTotalMonthExpenses, expensesRepresentation)

        familyTtotalMembersDescription = self._getFamilyMembersDescription(profile)
        prompt = prompt.replace(constants.familyTotalMembers, familyTtotalMembersDescription)

        mortgageDescription = self._getMortgageDescription(profile)
        prompt = prompt.replace(constants.mortgageInformation, mortgageDescription)

        sameRespondent = self._getSameRespondentInformation(profile)
        prompt = prompt.replace(constants.individualAndHouseholdRespndent, sameRespondent)

        creditDebt = self._getCreditDebt(profile)
        prompt = prompt.replace(constants.creditDebt, creditDebt)

        carsDescription = self._getCarsDescription(profile)
        prompt = prompt.replace(constants.householdCars, carsDescription)

        vacation = self._getVacationDescription(profile)
        prompt = prompt.replace(constants.vacationTag, vacation)

        return prompt

    def _getVacationDescription(self, profile: ProfileData):
        foreign = profile.vacationForeign
        domestic = profile.vacationDomestic

        foreignHasNoAnswer = checkNoAnswer(foreign)
        domesticHasNoAnswer = checkNoAnswer(domestic)

        if foreignHasNoAnswer and domesticHasNoAnswer:
            return 'нет информации'

        isForeign = processYesNo(foreign)
        isDomestic = processYesNo(domestic)

        if not isForeign and not isDomestic:
            return 'у семьи нет возможности отдохнуть вместе ни на российском курорте ни за границей'

        if isForeign and isDomestic:
            return 'есть возможность провести всей семьей отпуск на российском курорте и за границей'

        if isDomestic:
            return 'есть возможность провести всей семьей отпуск только на российском курорте'

        return 'есть возможность провести всей семьей отпуск только на за границей'

    def _getSameRespondentInformation(self, profile: ProfileData):
        if profile.idIndividualrespondent == profile.idHHrespondent:
            return 'тот же самый, что и дает ответы на вопрос анкеты о домохозяйтсве'

        return 'другой член домохозяйства давал ответы на вопросы анкеты о домохозястве'

    def _getExpensesRepresentation(self, profile: ProfileData, expenses: float):
        if checkNoAnswer(profile.allFamilyMonthIncome):
            return getNoAnswerDescription(profile.allFamilyMonthIncome)

        ratio = profile.allFamilyMonthIncome / (expenses * profile.totalFamilyMembers / 12)
        return f'{ratio: .1f} в регионе {profile.currentLocalityRegion}'

    def _getMortgageDescription(self, profile):
        baseInformation = f'Тип жилья - {getSafeDescription(profile.familyHouseType)}, семья занимает {getSafeDescription(profile.familyHouseAllocationType)}, общая площадь - {getSafeDescription(profile.familyHouseTotalSquare)}'
        countryInformation = f'Есть дача: {getSafeDescription(profile.hasCountryHouse)}, есть иная недвижимость: {profile.hasOtherMortgage}'
        landInformation = f'Семья пользуется землей: {getSafeDescription(profile.hasLand)}, собственность: {getSafeDescription(profile.landOwner)}'

        return f'\n{baseInformation}\n{countryInformation}\n{landInformation}.'

    def _getCreditDebt(self, profile):
        if profile.familyHasActiveCredits == 'Нет':
            return 'у домохозяйства нет активных кредитов.'

        if checkNoAnswer(profile.totalFamilyCreditDebt):
            return getNoAnswerDescription(profile.totalFamilyCreditDebt)

        ratio = profile.totalFamilyCreditDebt / (profile.allFamilyMonthIncome * 12)

        return f'Совокупная задолженность домохозяйства по всем кредитам эквивалентна {ratio: .1f} годам работы семьи при условии, что все заработанные деньги будут уходить на погашение кредита.'

    def _getCarsDescription(self, profile):
        domesticCar = f'отечественный автомобиль {'имеется' if profile.hasRussianCar == 'Да' else 'отсутствует'}'
        foreignCar = f'иностранный автомобиль {'имеется' if profile.hasForeignCar == 'Да' else 'отсутствует'}'

        return f'{domesticCar}, {foreignCar}.'

    def _getFamilyMembersDescription(self, profile: ProfileData) -> str:
        totalMembers = str(int(profile.totalFamilyMembers))
        hasNoChildren = profile.hhHasChildren == 99999996
        desc = ''
        if hasNoChildren:
            desc = ' (детей нет)'
        else:
            desc = ' (дети есть)'

        return f'{totalMembers}{desc}'


