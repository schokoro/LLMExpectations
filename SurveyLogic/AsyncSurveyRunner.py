import asyncio
import traceback
from datetime import date

from Logging.BaseLogger import BaseLogger
from SurveyLogic.BaseSurveyRunner import BaseSurveyRunner
from SurveyLogic.PromptBuilders.Profiles.BaseProfilesProvider import BaseProfilesProvider
from SurveyLogic.PromptBuilders.Profiles.ProfileData import ProfileData
from SurveyLogic.SurveyExecution.BaseSurveyExecutor import BaseSurveyExecutor
from SurveyLogic.SurveyExecution.StandardAsyncSurveyExecutor import StandardAsyncSurveyExecutor
from SurveyLogic.SurveyResults.InflationSurveyRespond import InflationSurveyRespond
from SurveyLogic.SurveyResultsSerialization.BaseSurveySerializer import BaseSurveySerializer


class AsyncSurveyRunner(BaseSurveyRunner):
    def __init__(self, serializer: BaseSurveySerializer, surveyExecutor: StandardAsyncSurveyExecutor, profilesProvider: BaseProfilesProvider, logger: BaseLogger, maxConnectionsLimit: int = 10):
        self.logger = logger
        self.surveyExecutor = surveyExecutor
        self.serializer = serializer
        self.profilesProvider = profilesProvider
        self.semaphore = asyncio.Semaphore(maxConnectionsLimit)

    async def _executeWithLimit(self, surveyDate: date, profile: ProfileData, index: int):
        async with self.semaphore:
            try:
                result = await self.surveyExecutor.executeSurvey(surveyDate, profile)
                return (index, result, None)
            except Exception as e:
                self.logger.logDebug(f'Survey #{index} FAILED: {e}')
                self.logger.logDebug(traceback.format_exc())
                return (index, None, str(e))

    async def RunSurvey(self, surveyDate: date) -> list[InflationSurveyRespond]:
        self.logger.logDebug(f'Executing survey for date {surveyDate}')
        profiles = self.profilesProvider.getProfiles(surveyDate)

        tasks = []
        for i in range(len(profiles)):
            p = profiles[i]
            self.logger.logDebug(f'Executing survey for profile #{i} (of {len(profiles)}): {p}...')
            task = self._executeWithLimit(surveyDate, p, i)
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
        for r in results:
            print(r[0])
            print(r[1])
            r[1].hasCredit = profiles[r[0]].hasCredit
            r[1].hasSavings = profiles[r[0]].hasSavings

        completedSurveyes = [x[1] for x in results]

        self.serializer.saveSurvey(completedSurveyes, surveyDate)
        self.logger.logDebug(f'Saved survey.')

        return completedSurveyes
