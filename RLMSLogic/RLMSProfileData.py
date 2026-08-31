from dataclasses import dataclass


@dataclass
class RLMSProfileData:
    respondentId: str

    age: int
    sex: str
    education: str
    LocalityOfBirth: str
    currentLocality: str
    currentLocalityRegion: str
    currentLocalityRegionCode: str
    typeOfLocality: str
    currentStatus: str
    job: str
    jobSector: str
    familyStatus: str
    nationality: str

    hasSavings: bool
    hasCredit: bool

    economicsSourceOfKnowledge: str

    moneyStatusLastThreeYears: str
    salary: str
    lastMonthSalary: str

    idIndividualrespondent: float
    idHHrespondent: float
    hhHasChildren: int
    totalFamilyMembers: float
    allFamilyMonthIncome: float

    familyHasActiveCredits: str
    totalFamilyCreditDebt: float
    familyHouseType: str
    familyHouseAllocationType: str
    familyHouseTotalSquare: float

    hasRussianCar: str
    yearsOfRussianCar: float
    hasForeignCar: str
    yearsOfForeignCar: float

    hasCountryHouse: str
    hasOtherMortgage: str
    hasLand: str
    landOwner: str

    vacationForeign: int
    vacationDomestic: int

    regular: dict[str, float]
    durable: dict[str, float]
    services: dict[str, float]
