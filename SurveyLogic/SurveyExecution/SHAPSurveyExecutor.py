import asyncio
import traceback
from datetime import date

from Logging.BaseLogger import BaseLogger
from SHAPAnalysis.BaseSHAPCalculator import BaseSHAPCalculator
from SurveyLogic.PromptBuilders.BasePromptBuilder import BasePromptBuilder
from SurveyLogic.PromptBuilders.Profiles.ProfileData import ProfileData
from SurveyLogic.SurveyExecution.BaseSurveyExecutor import BaseSurveyExecutor
from SurveyLogic.SurveyResults.InflationSurveyRespond import InflationSurveyRespond
from SurveyLogic.SurveyResults.SHAPSurveyRespond import SHAPSurveyRespond
from SurveyLogic.Surveyers.AsyncSurveyer import AsyncSurveyer


class SHAPSurveyExecutor(BaseSurveyExecutor):
    def __init__(self, systemPromptBuilder: BasePromptBuilder, promptBuilders: list[BasePromptBuilder], surveyer: AsyncSurveyer, shapCalculator: BaseSHAPCalculator, logger: BaseLogger, maxConnectionsLimit: int = 10):

        self.shapCalculator = shapCalculator
        self.logger = logger
        self.surveyer = surveyer
        self.promptBuilders = promptBuilders
        self.systemPromptBuilder = systemPromptBuilder
        self.limit = maxConnectionsLimit
        #self.semaphore = asyncio.Semaphore(maxConnectionsLimit)

    async def _executeWithLimit(self, surveyDate: date, profile: ProfileData, index: int):
        async with self.semaphore:
            try:
                systemPrompt = self.systemPromptBuilder.buildPrompt(surveyDate, profile)
                userPrompt = self.promptBuilders[index].buildPrompt(surveyDate, profile)

                result = await self.surveyer.askSurvey(systemPrompt, userPrompt, profile.respondentId, surveyDate)
                return (index, result, None)
            except Exception as e:
                self.logger.logDebug(f'Survey #{index} FAILED: {e}')
                self.logger.logDebug(traceback.format_exc())
                return (index, None, str(e))

    async def _executeSurveyInternal(self, surveyDate: date, profile: ProfileData) -> list[InflationSurveyRespond]:

        self.logger.logDebug(f'Executing SHAP survey for date {surveyDate} and profile {profile.respondentId}')

        tasks = []
        for i in range(len(self.promptBuilders)):
            self.logger.logDebug(f'Executing survey for prompt #{i} (of {len(self.promptBuilders)})')
            task = self._executeWithLimit(surveyDate, profile, i)
            tasks.append(task)

        results = []
        completed = 0
        failed_count = 0
        total = len(tasks)

        for coro in asyncio.as_completed(tasks):
            index, result, e = await coro

            if e:
                failed_count += 1
                self.logger.logDebug(f'Survey #{index} failed: {e}')
            else:
                results.append((index, result))
                self.logger.logDebug(f'Surveyed profile # {index}.')
                completed += 1

            if completed % 10 == 0 or completed == total:
                self.logger.logDebug(f'Progress: {completed}/{total} (failed: {failed_count})')

        # Сортируем по индексу для сохранения порядка
        results.sort(key=lambda x: x[0])
        completedSurveyes = [x[1] for x in results]

        return completedSurveyes

    def executeSurvey(self, surveyDate: date, profile: ProfileData) -> SHAPSurveyRespond:
        self.semaphore = asyncio.Semaphore(self.limit)
        surveyResults = asyncio.run(self._executeSurveyInternal(surveyDate, profile))
        responds = [x.expected_inflation_12m_pct for x in surveyResults]
        shapValues = self.shapCalculator.calculateShapValues(responds)

        shapRespond = SHAPSurveyRespond(
            respondent_id=profile.respondentId,
            target_date=surveyDate.strftime('%d.%m.%Y'),
            shapValues=shapValues
        )

        return shapRespond