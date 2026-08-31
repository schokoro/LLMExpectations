from dataclasses import dataclass

@dataclass
class ProfileData:
    respondentId: str

    age: int
    sex: str
    education: str
    LocalityOfBirth: str
    currentLocality: str
    currentLocalityRegionCode: str
    currentLocalityRegion: str
    typeOfLocality: str
    job: str
    jobSector: str
    currentStatus: str
    salary: str
    hasSavings: bool
    hasCredit: bool
    familyStatus: str
    nationality: str

    economicsSourceOfKnowledge: str

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

    hasCountryHouse: str
    hasOtherMortgage: str
    hasLand: str
    landOwner: str

    vacationForeign: int
    vacationDomestic: int

    hasRussianCar: str
    yearsOfRussianCar: float
    hasForeignCar: str
    yearsOfForeignCar: float

    regular: dict[str, float]
    durable: dict[str, float]
    services: dict[str, float]

    nonDurableGoods: list[str]
    newsSources: list[str]
