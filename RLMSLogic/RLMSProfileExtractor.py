import glob
import json
import os
import re
import pandas as pd
import random
from dataclasses import asdict, fields
from pathlib import Path
from typing import List

import pyreadstat

from RLMSLogic.SimpleRLMSProfileConverter import SimpleRLMSProfileConverter
from RLMSLogic.RLMSProfileData import RLMSProfileData
from RLMSLogic.extractionHelpers import norm, value_to_label, safe_filename, safe_value_to_label, safe_norm


def _checkIfAnswerIsNotEmpty(answer):
    if answer is None or pd.isna(answer):
        return False

    if answer > 99999990:
        return False

    return True


class RLMSProfileExtractor:
    def __init__(self, converter: SimpleRLMSProfileConverter, regularGoods: Path, durableGoods: Path, services: Path):
        self.prefixConstant = '{{prefix}}'
        self.questionCodeSeparator = '_'
        self.sourcePrefixConstant = 'cc'

        self.converter = converter
        self.prefix = {33: 'cc', 32: 'bb', 31: 'aa', 30: 'z', 29: 'y', 28: 'x', 27: 'w', 26: 'v', 25: 'u', 24: 't', 23: 's', 22: 'r', 21: 'q', 20: 'p', 19: 'o', 18: 'n'}

        self.regular = self._parseMapFileAndInitialize(regularGoods)
        self.durable = self._parseMapFileAndInitialize(durableGoods)
        self.services = self._parseMapFileAndInitialize(services)

    def extractAndSaveRLMSProfiles(self, dta_path: Path, hhFile: Path, output_path: Path, sampleSize: int) -> List[RLMSProfileData]:
        """
        Загружает данные RLMS, извлекает профиль каждого респондента и сохраняет JSON-файлы.

        Аргументы:
            dta_path (str): путь к файлу .dta с данными RLMS.
            output_dir (str): путь к папке для сохранения JSON-файлов.
            year (int): год проведения опроса (используется для вычисления возраста).

        Возвращает:
            List[RLMSProfileData]: список объектов для всех респондентов.
        """
        # Чтение данных без применения меток (чтобы получить числовые коды)

        match = re.search(r'.*r(\d+)i.*', dta_path.name)
        waveNumber = int(match.group(1))
        p = self.prefix[waveNumber]
        separator = '_' if waveNumber >= 25 else '.'

        df, meta = self._readConcreteWaveData(str(dta_path), waveNumber)
        dfhh, metahh = self._readConcreteWaveData(str(hhFile), waveNumber)

        curId = f'{p}id_h' if p != 'z' else 'ZID_H'
        dfhh_indexed = dfhh.set_index(curId)

        output_path.mkdir(parents=True, exist_ok=True)

        profiles = []

        totalElemets = len(df)
        randomElements = set(random.sample(range(totalElemets), sampleSize))

        for i, row in df.iterrows():
            if i not in randomElements:
                continue

            # Идентификатор респондента
            respondent_id = norm(row.get('idind'))
            if respondent_id is None:
                continue  # пропускаем записи без id

            hhRow = dfhh_indexed.loc[row[curId.lower()]]
            numberOfFamilyMembers = norm(hhRow[f'{p}_nfm'])
            allFamilyIncome = norm(hhRow[f'{p}f14'])

            # Возраст: вычисляем из года рождения (переменная CCJ69.0)
            age = norm(row.get(f'{p}_age'))

            # Пол (CCH5)
            sex = value_to_label(f'{p}h5', row.get(f'{p}h5'), meta)

            highestEducation = value_to_label(f'{p}j72_18a'.replace('_', separator), row.get(f'{p}j72_18a'.replace('_', separator)), meta)
            commonEducation = value_to_label(f'{p}_educ', row.get(f'{p}_educ'), meta)
            diploma = value_to_label(f'{p}_diplom', row.get(f'{p}_diplom'), meta)
            education = f'{diploma}, {commonEducation}, {highestEducation}'

            # Место рождения: комбинация ответов на вопросы 1-3
            loc_birth = value_to_label(f'{p}i1', row.get(f'{p}i1'), meta)  # другой/тот же
            country = value_to_label(f'{p}i2', row.get(f'{p}i2'), meta)
            place_type = value_to_label(f'{p}i3', row.get(f'{p}i3'), meta)
            parts = [p for p in (loc_birth, country, place_type) if p]
            LocalityOfBirth = ', '.join(parts)

            # Текущее место жительства – используем переменную s_type (тип поселения)
            localityStatus = value_to_label('status', row.get('status'), meta)
            psu_raw = str(int(row.get('psu')))

            psu = value_to_label('psu', row.get('psu'), meta)
            region = value_to_label('region', row.get('region'), meta)

            currentLocality = f'{localityStatus}, {region}'
            currentLocalityRegion = psu
            currentLocalityRegionCode = psu_raw

            typeOfPlace = localityStatus

            # Должность/профессия (вопрос 3: CCJ2_3a – должность, CCJ2_3b – профессия)
            occupation = value_to_label(f'{p}_occup08', row.get(f'{p}_occup08'), meta)
            numberOfEmployees = value_to_label(f'{p}j13', row.get(f'{p}j13'), meta)

            if occupation is None:
                job = 'Нет информации'
            else:
                if numberOfEmployees is not None:
                    numberOfEmployees = f' (численность {numberOfEmployees})'
                else:
                    numberOfEmployees = ''

                job = f'{occupation}{numberOfEmployees}'

            # Отрасль (вопрос 6, CCJ5A)
            jobSector = value_to_label(f'{p}j4_1'.replace('_', separator), row.get(f'{p}j4_1'.replace('_', separator)), meta)

            # Зарплата: среднемесячная за 12 месяцев (вопрос 32, CCJ13)
            salary_raw = norm(row.get(f'{p}j13_2'.replace('_', separator)))
            salary = str(salary_raw) if salary_raw is not None else None

            # Сбережения: банковский депозит (вопрос 79.1, CCJ596.1)
            deposit = value_to_label(f'{p}j596_1', row.get(f'{p}j596_1'), meta)
            equities = value_to_label(f'{p}j596_3', row.get(f'{p}j596_3'), meta)
            brokerAccount = value_to_label(f'{p}j596_4', row.get(f'{p}j596_4'), meta)
            last12monthSavedKey = f'{p}j60_4a8'.replace('_', separator)
            last12monthSaved = value_to_label(last12monthSavedKey, last12monthSavedKey, meta)

            if deposit == 'Да' or equities == 'Да' or brokerAccount == 'Да' or last12monthSaved == 'Да':
                hasSavings = True
            elif deposit == 'Нет' and equities == 'Нет' and brokerAccount == 'Нет' or last12monthSaved == 'Нет':
                hasSavings = False
            else:
                hasSavings = None

            # Кредит: невыплаченный кредит (вопрос 79.2, CCJ596.2)
            credit_raw = value_to_label(f'{p}j596_2', row.get(f'{p}j596_2'), meta)
            if credit_raw == 'Да':
                hasCredit = True
            elif credit_raw == 'Нет':
                hasCredit = False
            else:
                hasCredit = None

            familyStatus = value_to_label(f'{p}_marst', row.get(f'{p}_marst'), meta)
            currentStatus = value_to_label(f'{p}j1', row.get(f'{p}j1'), meta)
            nationality = value_to_label(f'{p}i4', row.get(f'{p}i4'), meta)
            lastMonthSalary = str(norm(row.get(f'{p}j60')))

            currentSources = []
            for i in range(1, 11):
                curLabel = f'{p}j597_{i}'
                curValue = value_to_label(curLabel, row.get(curLabel), meta)
                if curValue is not None:
                    currentSources.append(curValue)

            economicsSourceOfKnowledge = ','.join(currentSources)
            moneyStatusLastThreeYears = value_to_label(f'{p}j60_5b', row.get(f'{p}j60_5b'), meta)

            idHHrespondent = hhRow[f'{p}a8']
            idIndividualrespondent = row[f'{p}h4']
            hhHasChildrenKey = f'{p}e6_2'.replace('_', separator)
            hhHasChildrenValue = value_to_label(hhHasChildrenKey, hhRow.get(hhHasChildrenKey), metahh)

            activeCreditKey = f'{p}f14_8'.replace('_', separator)
            if not activeCreditKey in hhRow:
                activeCreditKey = f'{p}f14_8_1'.replace('_', separator)

            familyHasActiveCredits = safe_value_to_label(activeCreditKey, hhRow, metahh)

            totalFamilyCreditDebt = safe_norm(f'{p}f14_9', hhRow)

            familyHouseType = value_to_label(f'{p}c1', hhRow[f'{p}c1'], metahh)
            familyHouseAllocationType = value_to_label(f'{p}c3', hhRow[f'{p}c3'], metahh)
            familyHouseTotalSquare = safe_norm(f'{p}c5', hhRow)

            hasRussianCar = safe_value_to_label(f'{p}c9_7_2a'.replace('_', separator), hhRow, metahh)
            yearsOfRussianCar = safe_norm(f'{p}c9_7_2b'.replace('_', separator), hhRow)
            hasForeignCar = safe_value_to_label(f'{p}c9_7_3a'.replace('_', separator), hhRow, metahh)
            yearsOfForeignCar = safe_norm(f'{p}c9_7_3b'.replace('_', separator), hhRow)

            hasCountryHouse = safe_value_to_label(f'{p}c9_101a'.replace('_', separator), hhRow, metahh)
            hasOtherMortgage = safe_value_to_label(f'{p}c9_12a'.replace('_', separator), hhRow, metahh)
            hasLand = safe_value_to_label(f'{p}d2', hhRow, metahh)
            landOwner = safe_value_to_label(f'{p}d4', hhRow, metahh)

            vacationForeign = safe_norm(f'{p}e42_5'.replace('_', separator), hhRow)
            vacationDomestic = safe_norm(f'{p}e42_6'.replace('_', separator), hhRow)

            regular = self._processMap(self.regular, hhRow, p, separator)
            durable = self._processMap(self.durable, hhRow, p, separator)
            services = self._processMap(self.services, hhRow, p, separator)

            profile = RLMSProfileData(
                respondentId=str(respondent_id),
                age=age,
                sex=sex,
                education=education,
                LocalityOfBirth=LocalityOfBirth,
                currentLocality=currentLocality,
                currentLocalityRegion=currentLocalityRegion,
                currentLocalityRegionCode=currentLocalityRegionCode,
                typeOfLocality=typeOfPlace,
                job=job,
                jobSector=jobSector,
                salary=salary,
                hasSavings=hasSavings,
                hasCredit=hasCredit,
                familyStatus=familyStatus,
                currentStatus=currentStatus,
                nationality=nationality,
                lastMonthSalary=lastMonthSalary,
                economicsSourceOfKnowledge=economicsSourceOfKnowledge,
                moneyStatusLastThreeYears=moneyStatusLastThreeYears,
                idIndividualrespondent=idIndividualrespondent,
                idHHrespondent=idHHrespondent,
                hhHasChildren=hhHasChildrenValue,
                totalFamilyMembers=numberOfFamilyMembers,
                allFamilyMonthIncome=allFamilyIncome,
                familyHasActiveCredits=familyHasActiveCredits,
                totalFamilyCreditDebt=totalFamilyCreditDebt,
                familyHouseType=familyHouseType,
                familyHouseAllocationType=familyHouseAllocationType,
                familyHouseTotalSquare=familyHouseTotalSquare,

                hasRussianCar=hasRussianCar,
                yearsOfRussianCar=yearsOfRussianCar,
                hasForeignCar=hasForeignCar,
                yearsOfForeignCar=yearsOfForeignCar,

                hasCountryHouse=hasCountryHouse,
                hasOtherMortgage=hasOtherMortgage,
                hasLand=hasLand,
                landOwner=landOwner,

                vacationForeign=vacationForeign,
                vacationDomestic=vacationDomestic,

                regular=regular,
                durable=durable,
                services=services
            )

            # Сохраняем JSON
            filename = f"{safe_filename(respondent_id)}.json"
            filepath = output_path / filename
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(asdict(profile), f, ensure_ascii=False, indent=2)

            profiles.append(profile)

        return profiles

    def generateAndSaveProfilesFromRLMS(self, rlmsProfilesFolder: Path, folderPath: Path, sample_size: int, adultAge: int, seed: int = 42):
        pattern = os.path.join(str(rlmsProfilesFolder), "*.json")
        json_files = glob.glob(pattern)

        total = len(json_files)
        if sample_size <= 0 or sample_size > total:
            raise ValueError(f'Incorrect value of sample size: {sample_size}, it should be 0 < {sample_size} <= {total}')

        folderPath.mkdir(parents=True, exist_ok=True)

        # Случайная выборка без повторений
        random.seed(seed)
        selectedFiles = random.sample(json_files, len(json_files))

        counter = 0

        for f in selectedFiles:
            if counter >= sample_size:
                break

            with open(f, 'r', encoding='utf-8') as ff:
                profile = json.load(ff)

            valid_field_names = {f.name for f in fields(RLMSProfileData)}
            filtered_data = {k: v for k, v in profile.items() if k in valid_field_names}

            profile = RLMSProfileData(**filtered_data)
            resultProfile = self.converter.convert(profile)

            if resultProfile.age < adultAge:
                print(f'Skipping profile {resultProfile.respondentId} because of age: {resultProfile.age} < {adultAge}')
                continue

            path = folderPath / f'{resultProfile.respondentId}.json'
            with open(path, 'w', encoding='utf-8') as ff:
                json.dump(asdict(resultProfile), ff, ensure_ascii=False, indent=2)

            counter = counter + 1

    def _parseMapFileAndInitialize(self, path: Path) -> set:
        result = set()
        pattern = r'^[^\s]+'
        with open(path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            for line in lines:
                parsed = re.match(pattern, line).group().replace(self.sourcePrefixConstant, f'{self.prefixConstant}').replace('.', f'{self.questionCodeSeparator}')
                result.add(parsed)

        return result

    def _processMap(self, map: set, row, prefix: str, separator: str) -> dict[str, float]:
        result = dict[str, float]()
        for item in map:

            curQuestion = item.replace(self.prefixConstant, prefix)
            curQuestion = curQuestion.replace('_', separator)
            if curQuestion not in row:
                continue

            answer = row[curQuestion]

            if _checkIfAnswerIsNotEmpty(answer):
                result[item.replace(self.prefixConstant, self.sourcePrefixConstant)] = answer

        return result

    def _readConcreteWaveData(self, path: str, waveNumber: int):
        if waveNumber >= 25:
            df, meta = pyreadstat.read_dta(
                path,
                apply_value_formats=False,
                formats_as_category=False,
                user_missing=False
            )
            return df, meta

        df, meta = pyreadstat.read_sav(
            path,
            apply_value_formats=False,
            formats_as_category=False,
            user_missing=False
        )
        return df, meta
