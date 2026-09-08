import asyncio
from pathlib import Path

from Configuration import configuration
from Configuration.configuration import mlcluster_key
from Logging.SimpleLogger import SimpleLogger
from NewsLogic.NewsContextProvider import NewsContextProvider
from NewsLogic.NewsRagConfiguration import NewsRagConfiguration, twoStageMode
from NewsLogic.newsExceptions import NewsContextUnavailableError
from SurveyLogic.PromptBuilders.profileBuildersHelpers import createNewsPromptBuilder
from SurveyLogic.SurveyResultsSerialization.SurveySerializer import SurveySerializer
from SurveyLogic.Surveyers.AsyncSurveyer import AsyncSurveyer
from SurveyLogic.surveyHelpers import createAsyncSurveyRunner, extractDatesFromFile, copyPromptTemplatesToFolder

offsetDays = -14
experimentUniqueName='mlcluster_qwen36_async_news'
profilesFolder = Path('./data/Target profiles')
profilesCount = 100
resultsFolder = Path('data/SurveyResults/')/experimentUniqueName
copyPromptTemplatesToFolder(Path('SurveyLogic/PromptBuilders/Prompts/'), resultsFolder/'Prompts')

surveyDates = extractDatesFromFile(configuration.inflationSurveysDates, offsetDays=offsetDays)
#surveyDates = getDatesRowWithWeeklyStep('2022.01.12', '2022.09.07')
#surveyDates = pd.date_range(start='2016-04-01', end='2026-04-01', freq='QS', inclusive='both').tolist()

logger = SimpleLogger()

# Новостной контекст считается до опроса и один раз на дату: buildPrompt()
# синхронный и вызывается на каждого респондента. Режим two_stage кеширует
# саммари в data/newsDB/project.db, rawMode отдаёт отобранные сообщения как есть.
newsConfiguration = NewsRagConfiguration(mode=twoStageMode, artefactsFolder=resultsFolder/'News')
newsContextProvider = NewsContextProvider(newsConfiguration, logger)

systemPromptBuilder, promptBuilder = createNewsPromptBuilder(newsContextProvider)

surveyer = AsyncSurveyer(modelToUse='Qwen/Qwen3.6-27B', key=mlcluster_key, logger=logger, baseUrl=configuration.mlclusterUrl)
#surveyer = StubSurveyer()

surveySerializer = SurveySerializer(resultsFolder)

for surveyDate in surveyDates:
    try:
        newsContextProvider.prepare(surveyDate)
    except NewsContextUnavailableError as e:
        # Даты вне периода сбора корпуса пропускаются целиком: опрос без
        # новостей на них превратил бы эксперимент news в no-news молча.
        logger.logDebug(f'SKIPPED survey date {surveyDate}: {e}')
        continue

    runner = createAsyncSurveyRunner(profilesFolder, systemPromptBuilder, promptBuilder, surveySerializer, surveyer, profilesCount,
                                     logger)
    surveyResults = asyncio.run(runner.RunSurvey(surveyDate))
    surveySerializer.saveSurvey(surveyResults, surveyDate)
