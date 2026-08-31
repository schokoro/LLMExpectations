from RLMSLogic.RLMSProfileData import RLMSProfileData
from SurveyLogic.PromptBuilders.Profiles.ProfileData import ProfileData


class SimpleRLMSProfileConverter:
    def convert(self, profile: RLMSProfileData) -> ProfileData:


        age = int(profile.age)

        return ProfileData(
            respondentId=profile.respondentId,
            age=age,
            sex=profile.sex,
            education=profile.education,
            LocalityOfBirth=profile.LocalityOfBirth,
            currentLocality=profile.currentLocality,
            currentLocalityRegion=profile.currentLocalityRegion,
            currentLocalityRegionCode=profile.currentLocalityRegionCode,
            typeOfLocality=profile.typeOfLocality,
            job=profile.job,
            jobSector=profile.jobSector,
            currentStatus=profile.currentStatus,
            nationality=profile.nationality,
            familyStatus=profile.familyStatus,
            economicsSourceOfKnowledge=profile.economicsSourceOfKnowledge,
            salary=profile.salary,
            hasCredit=profile.hasCredit,
            hasSavings=profile.hasSavings,

            idIndividualrespondent=profile.idIndividualrespondent,
            idHHrespondent=profile.idHHrespondent,
            hhHasChildren=profile.hhHasChildren,
            totalFamilyMembers=profile.totalFamilyMembers,
            allFamilyMonthIncome=profile.allFamilyMonthIncome,

            familyHasActiveCredits=profile.familyHasActiveCredits,
            totalFamilyCreditDebt=profile.totalFamilyCreditDebt,
            familyHouseType=profile.familyHouseType,
            familyHouseAllocationType=profile.familyHouseAllocationType,
            familyHouseTotalSquare=profile.familyHouseTotalSquare,

            hasRussianCar=profile.hasRussianCar,
            yearsOfRussianCar=profile.yearsOfRussianCar,
            hasForeignCar=profile.hasForeignCar,
            yearsOfForeignCar=profile.yearsOfForeignCar,

            hasCountryHouse=profile.hasCountryHouse,
            hasOtherMortgage=profile.hasOtherMortgage,
            hasLand=profile.hasLand,
            landOwner=profile.landOwner,
            vacationForeign=profile.vacationForeign,
            vacationDomestic=profile.vacationDomestic,

            regular=profile.regular,
            durable=profile.durable,
            services=profile.services,

            newsSources=[],
            nonDurableGoods=[]
        )