import shutil
from datetime import datetime
from typing import Optional

import pandas as pd
from pathlib import Path

from Logging.BaseLogger import BaseLogger
from SHAPAnalysis.BaseSHAPCalculator import BaseSHAPCalculator
from SHAPAnalysis.BruteforceSHAPCalculator import BruteforceSHAPCalculator
from SurveyLogic.AsyncSurveyRunner import AsyncSurveyRunner
from SurveyLogic.PromptBuilders.BasePromptBuilder import BasePromptBuilder
from SurveyLogic.PromptBuilders.Profiles.ProfileDataLoader import ProfileDataLoader
from SurveyLogic.PromptBuilders.Profiles.RandomSubsampleProfilesProvider import RandomSubsampleProfilesProvider
from SurveyLogic.PromptBuilders.Profiles.StandardProfilesProvider import StandardProfilesProvider
from SurveyLogic.StandardSurveyRunner import StandardSurveyRunner
from SurveyLogic.SurveyExecution.AdditionalInformationSurveyExecutor import AdditionalInformationSurveyExecutor
from SurveyLogic.SurveyExecution.SHAPSurveyExecutor import SHAPSurveyExecutor
from SurveyLogic.SurveyExecution.StandardAsyncSurveyExecutor import StandardAsyncSurveyExecutor
from SurveyLogic.SurveyExecution.StandardSurveyExecutor import StandardSurveyExecutor
from SurveyLogic.SurveyResultsSerialization.BaseSurveySerializer import BaseSurveySerializer
from SurveyLogic.Surveyers.AsyncSurveyer import AsyncSurveyer
from SurveyLogic.Surveyers.BaseSurveyer import BaseSurveyer


def createSurveyRunner(profilesFolder: Path, systemPromptBuilder: BasePromptBuilder, promptBuilder: BasePromptBuilder, surveySerializer: BaseSurveySerializer, surveyer: BaseSurveyer, logger: BaseLogger) -> StandardSurveyRunner:
    profilesProvider = StandardProfilesProvider(profilesFolder, ProfileDataLoader())
    surveyExecutor = StandardSurveyExecutor(systemPromptBuilder, promptBuilder, surveyer)
    surveyExecutor = AdditionalInformationSurveyExecutor(surveyExecutor)

    runner = StandardSurveyRunner(surveySerializer, surveyExecutor, profilesProvider, logger)
    return runner

def createSHAPSurveyRunner(profilesFolder: Path, systemPromptBuilder: BasePromptBuilder, promptBuilders: list[BasePromptBuilder], shapCalculator: BaseSHAPCalculator, surveySerializer: BaseSurveySerializer, surveyer: AsyncSurveyer, profilesCount: int, logger: BaseLogger) -> StandardSurveyRunner:
    profilesProvider = StandardProfilesProvider(profilesFolder, ProfileDataLoader())
    profilesProvider = RandomSubsampleProfilesProvider(profilesProvider, profilesCount)

    surveyExecutor = SHAPSurveyExecutor(systemPromptBuilder, promptBuilders, surveyer, shapCalculator, logger)

    runner = StandardSurveyRunner(surveySerializer, surveyExecutor, profilesProvider, logger)
    return runner

def createAsyncSurveyRunner(profilesFolder: Path, systemPromptBuilder: BasePromptBuilder, promptBuilder: BasePromptBuilder, surveySerializer: BaseSurveySerializer, surveyer: AsyncSurveyer, profilesCount: int, logger: BaseLogger) -> AsyncSurveyRunner:
    profilesProvider = StandardProfilesProvider(profilesFolder, ProfileDataLoader())
    profilesProvider = RandomSubsampleProfilesProvider(profilesProvider, profilesCount)
    surveyExecutor = StandardAsyncSurveyExecutor(systemPromptBuilder, promptBuilder, surveyer)
    #surveyExecutor = AdditionalInformationSurveyExecutor(surveyExecutor)

    runner = AsyncSurveyRunner(surveySerializer, surveyExecutor, profilesProvider, logger)
    return runner

def getDatesRowWithMonthlyStep(start: str, end: str):
    return pd.date_range(start=start, end=end, freq='MS', inclusive='both').tolist()

def getDatesRowWithWeeklyStep(start: str, end: str):
    return pd.date_range(start=start, end=end, freq='7D', inclusive='both').tolist()


def extractDatesFromFile(
        path: Path,
        offsetDays: int,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
) -> list[datetime]:
    """
    Извлекает даты из заголовков Excel файла с возможностью фильтрации по диапазону.

    Args:
        path: Путь к Excel файлу
        offsetDays: Смещение в днях для каждой даты
        start_date: Начальная дата фильтра (включительно). Если None - фильтр не применяется
        end_date: Конечная дата фильтра (включительно). Если None - фильтр не применяется

    Returns:
        Отсортированный список дат, отфильтрованный по диапазону
    """
    df = pd.read_excel(path, sheet_name=0, header=0)

    # Получаем заголовки (первая строка)
    headers = df.columns.tolist()

    # Парсим каждую дату
    parsed_dates = []
    for header in headers:
        dt = header.to_pydatetime()
        dt = (dt + pd.DateOffset(days=offsetDays))
        parsed_dates.append(dt)

    # Применяем фильтр по датам
    if start_date is not None:
        parsed_dates = [d for d in parsed_dates if d >= start_date]

    if end_date is not None:
        parsed_dates = [d for d in parsed_dates if d <= end_date]

    parsed_dates.sort()

    return parsed_dates

def getDatesFromStrings(dates: list[str]):
    return [datetime.strptime(x, '%d.%m.%Y') for x in dates]

def copyPromptTemplatesToFolder(promptFolder: Path, resultsFolder: Path):
    if resultsFolder.exists():
        shutil.rmtree(resultsFolder)
    resultsFolder.mkdir(parents=True, exist_ok=True)

    # Находим все .txt файлы
    txt_files = list(promptFolder.glob('*.txt'))

    # Копируем каждый файл
    for file_path in txt_files:
        dst_path = resultsFolder / file_path.name
        shutil.copy2(file_path, dst_path)  # copy2 сохраняет метаданные

