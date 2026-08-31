from pathlib import Path

from Configuration import configuration
from Configuration.configuration import mlcluster_key
from Logging.SimpleLogger import SimpleLogger
from SHAPAnalysis.BruteforceSHAPCalculator import BruteforceSHAPCalculator
from SurveyLogic.PromptBuilders.profileBuildersHelpers import createSHAPBruteforcePromptBuilders, \
    createSHAPZeroPlusOnePromptBuilders, createSHAPAllMinusOnePromptBuilders
from SurveyLogic.SurveyResultsSerialization.SurveySerializer import SurveySerializer
from SurveyLogic.Surveyers.AsyncSurveyer import AsyncSurveyer
from SurveyLogic.surveyHelpers import copyPromptTemplatesToFolder, \
    getDatesFromStrings, createSHAPSurveyRunner

experimentUniqueName='mlcluster_qwen36_async_shap_7_minus_1'
profilesFolder = Path('./data/Target profiles')
profilesCount = 1000

resultsFolder = Path('data/Shap Results/')/experimentUniqueName
copyPromptTemplatesToFolder(Path('SurveyLogic/PromptBuilders/Prompts/'), resultsFolder/'Prompts')

surveyDates = getDatesFromStrings(['09.07.2026', '08.05.2018', '09.12.2014', '05.03.2020', '05.03.2022'])

logger = SimpleLogger()

surveyer = AsyncSurveyer(modelToUse='Qwen/Qwen3.6-27B', key=mlcluster_key, logger=logger, baseUrl=configuration.mlclusterUrl)
#surveyer = StubSurveyer()

surveySerializer = SurveySerializer(resultsFolder)
systemPromptBuilder, promptBuilders, shapCalculator = createSHAPAllMinusOnePromptBuilders()

for surveyDate in surveyDates:
    runner = createSHAPSurveyRunner(profilesFolder, systemPromptBuilder, promptBuilders, shapCalculator, surveySerializer, surveyer, profilesCount,
                                     logger)
    surveyResults = runner.RunSurvey(surveyDate)
    surveySerializer.saveSurvey(surveyResults, surveyDate)
