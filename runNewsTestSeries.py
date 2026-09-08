import asyncio
from datetime import date
from pathlib import Path

from Configuration import configuration
from Configuration.configuration import bothub_key
from Logging.SimpleLogger import SimpleLogger
from NewsLogic.NewsContextProvider import NewsContextProvider
from NewsLogic.NewsRagConfiguration import NewsRagConfiguration, twoStageMode
from SurveyLogic.PromptBuilders.profileBuildersHelpers import createNewsPromptBuilder
from SurveyLogic.Surveyers.AsyncSurveyer import AsyncSurveyer
from SurveyLogic.surveyHelpers import (
    copyPromptTemplatesToFolder,
    createAsyncSurveyRunner,
)
from SurveyLogic.SurveyResultsSerialization.SurveySerializer import SurveySerializer

# Тестовая серия: проверяем, что цепочка «отбор → суммаризация → промпт → опрос»
# работает, а не сопоставляем результат с рядом ИнФОМ. Отсюда и состав дат:
# тринадцать саммари уже лежат в project.db (посчитаны в blind_prophet тем же
# горизонтом и той же моделью), две точки считаются заново — они и проверяют,
# что генерация действительно идёт, а не только чтение кеша.
experimentUniqueName = 'bothub_qwen38_async_news_test'
profilesFolder = Path('./data/Target profiles')
profilesCount = 10
resultsFolder = Path('data/SurveyResults/') / experimentUniqueName
copyPromptTemplatesToFolder(Path('SurveyLogic/PromptBuilders/Prompts/'), resultsFolder / 'Prompts')

cachedDates = ['2020-04-20', '2021-09-20', '2021-10-20', '2021-11-20', '2021-12-20',
               '2022-01-20', '2022-02-20', '2022-03-20', '2022-03-25', '2022-04-20',
               '2022-05-20', '2022-06-20', '2023-05-01']
generatedDates = ['2026-02-26', '2026-03-27']

surveyDates = [date.fromisoformat(x) for x in sorted(cachedDates + generatedDates)]

logger = SimpleLogger()

newsConfiguration = NewsRagConfiguration(mode=twoStageMode, artefactsFolder=resultsFolder / 'News')
newsContextProvider = NewsContextProvider(newsConfiguration, logger)

systemPromptBuilder, promptBuilder = createNewsPromptBuilder(newsContextProvider)

# Шаг 1. Все контексты считаются до опроса: провал суммаризации виден раньше,
# чем потрачены вызовы модели-респондента. Ключ модели-респондента здесь не
# нужен, поэтому шаг проходит независимо от неё.
for surveyDate in surveyDates:
    context = newsContextProvider.prepare(surveyDate)
    logger.logDebug(
        f'CONTEXT {surveyDate:%Y-%m-%d}: docs={context.documentsCount}, '
        f'summary={len(context.summary)} chars, fromCache={context.summaryFromCache}, '
        f'failedAxes={context.failedAxes if context.failedAxes is not None else "НЕИЗВЕСТНО"}'
    )

if not bothub_key.strip():
    raise SystemExit(
        'Ключ модели-респондента пуст: Configuration/bothub_key.txt. '
        'Новостные контексты подготовлены и лежат в project.db, повторный запуск '
        'их не пересчитает; заполните ключ и запустите скрипт снова.'
    )

# Респондент опрашивается через BotHub: mlcluster недоступен (ключ пуст), а на
# BotHub нет Qwen3.6-27B — из доступных ближе всего qwen3.8-27b, тот же размер и
# то же семейство. Решение человека в чате 2026-09-05.
surveyer = AsyncSurveyer(modelToUse='qwen3.8-27b', key=bothub_key.strip(), logger=logger,
                         baseUrl=configuration.bothubUrl)
surveySerializer = SurveySerializer(resultsFolder)

# Шаг 2. Опрос по подготовленным датам.
for surveyDate in surveyDates:
    runner = createAsyncSurveyRunner(profilesFolder, systemPromptBuilder, promptBuilder, surveySerializer,
                                     surveyer, profilesCount, logger)
    surveyResults = asyncio.run(runner.RunSurvey(surveyDate))
    logger.logDebug(f'SURVEY {surveyDate:%Y-%m-%d}: {len(surveyResults)} responses saved')
