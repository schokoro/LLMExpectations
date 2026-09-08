import asyncio
import json
import time
from datetime import date

from amnesiac.exceptions import SummarizeError

from Logging.BaseLogger import BaseLogger
from NewsLogic import NewsRagConfiguration as newsRagConfiguration
from NewsLogic.NewsContext import NewsContext
from NewsLogic.NewsCorpusReader import NewsCorpusReader
from NewsLogic.newsExceptions import NewsContextNotPreparedError
from NewsLogic.newsHelpers import asDate
from NewsLogic.NewsRagConfiguration import NewsRagConfiguration
from NewsLogic.NewsRetriever import NewsRetriever
from NewsLogic.NewsSummariesCache import NewsSummariesCache
from NewsLogic.NewsSummarizer import NewsSummarizer


class NewsContextProvider:
    """Готовит новостной контекст на дату и отдаёт его builder'у.

    Разделение обязательно: `buildPrompt()` синхронный и вызывается внутри
    async-исполнителя опроса на каждого респондента. Retrieval и суммаризация
    выполняются здесь, до запуска опроса, ровно один раз на дату.
    """

    def __init__(
        self,
        configuration: NewsRagConfiguration,
        logger: BaseLogger,
        retriever: NewsRetriever | None = None,
        summarizer: NewsSummarizer | None = None,
        summariesCache: NewsSummariesCache | None = None,
    ):
        self.configuration = configuration
        self.logger = logger
        self.retriever = retriever if retriever is not None else NewsRetriever(configuration, logger)
        self.summarizer = summarizer if summarizer is not None else NewsSummarizer(configuration, logger)
        self.summariesCache = (summariesCache if summariesCache is not None
                               else NewsSummariesCache(configuration.projectDbPath))

        self.contexts: dict[date, NewsContext] = {}

    def prepare(self, surveyDate) -> NewsContext:
        """Посчитать контекст на дату. Идемпотентно в пределах прогона."""
        runDate = asDate(surveyDate)

        if runDate in self.contexts:
            return self.contexts[runDate]

        retrieved = self.retriever.retrieve(runDate)
        windowFrom, windowToExclusive = self.retriever.getWindow(runDate)

        summary = None
        summaryModel = None
        failedAxes: tuple[str, ...] | None = ()
        summaryFromCache = False

        if self.configuration.mode == newsRagConfiguration.twoStageMode:
            summary, failedAxes, summaryFromCache = self._getSummary(runDate, retrieved)
            summaryModel = self.configuration.summarizeModel

        context = NewsContext(
            runDate=runDate,
            windowFrom=windowFrom,
            windowToExclusive=windowToExclusive,
            horizonDays=self.configuration.horizonDays,
            mode=self.configuration.mode,
            documents=retrieved,
            summary=summary,
            summaryModel=summaryModel,
            failedAxes=failedAxes,
            summaryFromCache=summaryFromCache,
            corpusManifest=self._getCorpusManifest(),
        )

        self.contexts[runDate] = context
        self._saveArtefact(context)

        return context

    def getContext(self, surveyDate) -> NewsContext:
        runDate = asDate(surveyDate)

        context = self.contexts.get(runDate)
        if context is None:
            raise NewsContextNotPreparedError(
                f'Новостной контекст на {runDate} не подготовлен. '
                f'Вызовите NewsContextProvider.prepare({runDate}) до запуска опроса: '
                f'retrieval внутри синхронного builder\'а заблокировал бы event loop.'
            )

        return context

    def _getSummary(
        self,
        runDate: date,
        retrieved: dict,
    ) -> tuple[str, tuple[str, ...] | None, bool]:
        cached = self.summariesCache.getSummary(
            runDate,
            self.configuration.horizonDays,
            self.configuration.summarizeModel,
        )

        if cached is not None:
            summary, documentsCount, failedAxes = cached
            self.logger.logDebug(
                f'News summary for {runDate} taken from project.db cache '
                f'({documentsCount} documents, {self.configuration.summarizeModel})'
            )

            if failedAxes is None:
                self.logger.logDebug(
                    f'Failed axes for {runDate} are UNKNOWN: the cached row predates the '
                    f'failed_axes column. The summary may have been built from fewer axes.'
                )
            elif failedAxes:
                self.logger.logDebug(
                    f'Cached summary for {runDate} was built WITHOUT axes: {", ".join(failedAxes)}'
                )

            return summary, failedAxes, True

        result = self._runSummarization(retrieved)
        documentsCount = sum(len(documents) for documents in retrieved.values())

        self.summariesCache.saveSummary(
            runDate,
            self.configuration.horizonDays,
            result.meta,
            documentsCount,
            self.configuration.summarizeModel,
            tuple(result.failed_axes),
        )

        # Осевые саммари первого этапа: провенанс меты и материал для анализа по
        # осям. Отказавшие оси пропускаются — вместо текста там заглушка.
        failed = set(result.failed_axes)
        self.summariesCache.saveAxisSummaries(
            runDate,
            self.configuration.horizonDays,
            self.configuration.summarizeModel,
            {axis: summary for axis, summary in result.axis_summaries.items() if axis not in failed},
            {axis: len(documents) for axis, documents in retrieved.items()},
        )

        self.logger.logDebug(
            f'News summary for {runDate} computed: {len(result.meta)} characters, '
            f'{result.usage.calls} provider calls, {result.usage.total_tokens} tokens'
        )

        return result.meta, tuple(result.failed_axes), False

    def _runSummarization(self, retrieved: dict):
        if self._hasRunningEventLoop():
            raise RuntimeError(
                'NewsContextProvider.prepare() вызван внутри работающего event loop. '
                'Контекст считается до запуска опроса, а не во время него.'
            )

        attempts = self.configuration.summarizeAttempts
        for attempt in range(1, attempts + 1):
            try:
                return asyncio.run(self.summarizer.buildSummary(retrieved))
            except SummarizeError as error:
                # Повторяются только сбои суммаризации: пустой ответ модели и
                # превышение лимита отказавших осей. Ошибки конфигурации и
                # шаблонов — не подкласс SummarizeError и наверх уходят сразу,
                # потому что повтор их не исправит.
                if attempt >= attempts:
                    self.logger.logDebug(
                        f'Summarization failed after {attempts} attempts: {error}'
                    )
                    raise

                self.logger.logDebug(
                    f'Summarization attempt {attempt}/{attempts} failed: {error}. '
                    f'Retrying in {self.configuration.summarizeRetryDelaySeconds} s '
                    f'(the whole date is recomputed: amnesiac 0.2 carries the computed axis '
                    f'summaries on the exception, but this retry does not use them yet).'
                )
                time.sleep(self.configuration.summarizeRetryDelaySeconds)

        raise AssertionError('unreachable: цикл повторов либо возвращает результат, либо бросает')

    @staticmethod
    def _hasRunningEventLoop() -> bool:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return False

        return True

    def _getCorpusManifest(self) -> dict:
        with NewsCorpusReader(self.configuration.corpusPath) as reader:
            return reader.getCorpusManifest()

    def _saveArtefact(self, context: NewsContext) -> None:
        if self.configuration.artefactsFolder is None:
            return

        folder = self.configuration.artefactsFolder
        folder.mkdir(parents=True, exist_ok=True)

        path = folder / f'{context.runDate.isoformat()}_{context.mode}.json'
        path.write_text(
            json.dumps(
                context.toArtefact(self.configuration.toDictionary()),
                ensure_ascii=False,
                indent=2,
            ),
            encoding='utf-8',
        )

        self.logger.logDebug(f'News artefact saved: {path}')
