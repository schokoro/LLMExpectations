import asyncio
from pathlib import Path

from Configuration import configuration
from Configuration.configuration import mlcluster_key
from Logging.SimpleLogger import SimpleLogger
from SurveyLogic.PromptBuilders.profileBuildersHelpers import createNewsPromptBuilder
from SurveyLogic.SurveyResultsSerialization.SurveySerializer import SurveySerializer
from SurveyLogic.Surveyers.AsyncSurveyer import AsyncSurveyer
from SurveyLogic.Surveyers.StubSurveyer import StubSurveyer
from SurveyLogic.surveyHelpers import createAsyncSurveyRunner, copyPromptTemplatesToFolder, \
    getDatesRowWithWeeklyStep

experimentUniqueName='mlcluster_qwen36_async_news'
profilesFolder = Path('./data/Target profiles')
profilesCount = 100
resultsFolder = Path('data/SurveyResults/')/experimentUniqueName
copyPromptTemplatesToFolder(Path('SurveyLogic/PromptBuilders/Prompts/'), resultsFolder/'Prompts')

surveyDates = getDatesRowWithWeeklyStep('2022.01.12', '2022.09.07')

systemPromptBuilder, promptBuilder = createNewsPromptBuilder()
logger = SimpleLogger()

surveyer = AsyncSurveyer(modelToUse='Qwen/Qwen3.6-27B', key=mlcluster_key, logger=logger, baseUrl=configuration.mlclusterUrl)
#surveyer = StubSurveyer()

surveySerializer = SurveySerializer(resultsFolder)

for surveyDate in surveyDates:
    runner = createAsyncSurveyRunner(profilesFolder, systemPromptBuilder, promptBuilder, surveySerializer, surveyer, profilesCount,
                                     logger)
    surveyResults = asyncio.run(runner.RunSurvey(surveyDate))
    surveySerializer.saveSurvey(surveyResults, surveyDate)
