import asyncio
from datetime import datetime
from pathlib import Path

from Configuration import configuration
from Configuration.configuration import mlcluster_key
from Logging.SimpleLogger import SimpleLogger
from SurveyExecutionTools.surveyExecutionHelpers import saveExperimentConfiguration
from SurveyLogic.PromptBuilders.PromptBuilderFactory import PromptBuilderFactory
from SurveyLogic.SurveyResultsSerialization.SurveySerializer import SurveySerializer
from SurveyLogic.Surveyers.AsyncSurveyer import AsyncSurveyer
from SurveyLogic.Surveyers.StubSurveyer import StubSurveyer
from SurveyLogic.surveyHelpers import createAsyncSurveyRunner, extractDatesFromFile, copyPromptTemplatesToFolder, \
    getDatesRowWithMonthlyStep, getDatesRowWithWeeklyStep
from experimentsConfiguration import ExperimentsConfiguration

offsetDays = -6
experimentUniqueName=f'mlcluster_qwen38_async_all_{offsetDays}d'
profilesFolder = Path('./data/Target profiles')
profilesCount = 100
resultsFolder = Path('data/SurveyResults/')/experimentUniqueName
copyPromptTemplatesToFolder(Path('SurveyLogic/PromptBuilders/Prompts/'), resultsFolder/'Prompts')

surveyDates = extractDatesFromFile(configuration.inflationSurveysDates, offsetDays=offsetDays)

#surveyDates = getDatesRowWithMonthlyStep('2020.12.01', '2021.01.01')
#surveyDates = getDatesRowWithWeeklyStep('2022.03.12', '2022.05.07')

cfg = ExperimentsConfiguration(
    useIndividualRLMSData=True,
    useFamilyInformation=True,
    useFamilyExpenses=True,
    useStateExpenses=True,
    useEconomy=True,
    useInflation=True,
    usePreviousInflationExpectations=True
    )

saveExperimentConfiguration(cfg, resultsFolder)

factory = PromptBuilderFactory()
systemPromptBuilder, promptBuilder = factory.createCustomPromptBuilder(cfg)
logger = SimpleLogger()

#surveyer = AsyncSurveyer(modelToUse='Qwen/Qwen3.8-27B', key=mlcluster_key, logger=logger, baseUrl=configuration.mlclusterUrl)
surveyer = StubSurveyer()

surveySerializer = SurveySerializer(resultsFolder)

for surveyDate in surveyDates:
    runner = createAsyncSurveyRunner(profilesFolder, systemPromptBuilder, promptBuilder, surveySerializer, surveyer, profilesCount,
                                     logger)
    surveyResults = asyncio.run(runner.RunSurvey(surveyDate))
    surveySerializer.saveSurvey(surveyResults, surveyDate)
