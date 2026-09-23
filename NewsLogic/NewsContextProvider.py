import asyncio
import json
from datetime import date

from amnesiac.exceptions import SummarizeError
from amnesiac.summarize import TooManyAxisFailures, Usage

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
        self.usageByDate: dict[date, Usage] = {}
        self.usageCompleteByDate: dict[date, bool] = {}

    def prepare(self, surveyDate) -> NewsContext:
        """Посчитать контекст на дату. Идемпотентно в пределах прогона."""
        runDate = asDate(surveyDate)

        if runDate in self.contexts:
            return self.contexts[runDate]

        self.usageByDate.setdefault(runDate, Usage())
        self.usageCompleteByDate.setdefault(runDate, True)
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
        configHash = self.configuration.configHash()
        cached = self.summariesCache.getSummary(
            runDate,
            self.configuration.horizonDays,
            self.configuration.summarizeModel,
            configHash,
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

        if self._hasRunningEventLoop():
            raise RuntimeError(
                'NewsContextProvider.prepare() вызван внутри работающего event loop. '
                'Контекст считается до запуска опроса, а не во время него.'
            )

        horizonDays = self.configuration.horizonDays
        model = self.configuration.summarizeModel
        documentCounts = {axis: len(documents) for axis, documents in retrieved.items()}
        cachedAxes = self.summariesCache.getAxisSummaries(runDate, horizonDays, model, configHash)
        missing = {
            axis: documents for axis, documents in retrieved.items() if axis not in cachedAxes
        }

        if missing:
            try:
                axesResult = asyncio.run(self.summarizer.buildAxisSummaries(missing))
            except SummarizeError as error:
                self._recordFailedUsage(runDate, error)
                if isinstance(error, TooManyAxisFailures):
                    self.summariesCache.saveAxisSummaries(
                        runDate, horizonDays, model, error.axis_summaries, documentCounts, configHash
                    )
                raise
            except BaseException:
                # Транспортный отказ не возвращает usage незавершённой стадии.
                self.usageCompleteByDate[runDate] = False
                raise

            self.usageByDate[runDate] += axesResult.usage

            failed = set(axesResult.failed_axes)
            self.summariesCache.saveAxisSummaries(
                runDate,
                horizonDays,
                model,
                {
                    axis: summary
                    for axis, summary in axesResult.axis_summaries.items()
                    if axis not in failed
                },
                documentCounts,
                configHash,
            )
            ready = cachedAxes | axesResult.axis_summaries
            failedAxes = tuple(axesResult.failed_axes)
            usage = axesResult.usage
        else:
            ready, failedAxes, usage = cachedAxes, (), Usage()

        # Порядок осей — часть входа мета-промпта, в том числе при досчёте хвоста.
        merged = {axis: ready[axis] for axis in retrieved}
        try:
            metaResult = asyncio.run(self.summarizer.buildMetaSummary(merged))
        except SummarizeError as error:
            self._recordFailedUsage(runDate, error)
            raise
        except BaseException:
            self.usageCompleteByDate[runDate] = False
            raise
        self.usageByDate[runDate] += metaResult.usage
        usage = usage + metaResult.usage

        self.summariesCache.saveSummary(
            runDate,
            horizonDays,
            metaResult.meta,
            sum(documentCounts.values()),
            model,
            failedAxes,
            configHash,
        )

        self.logger.logDebug(
            f'News summary for {runDate} computed: {len(metaResult.meta)} characters, '
            f'{usage.calls} provider calls, {usage.total_tokens} tokens'
        )

        return metaResult.meta, failedAxes, False

    def _recordFailedUsage(self, runDate: date, error: SummarizeError) -> None:
        usage = getattr(error, 'usage', None)
        if usage is None:
            self.usageCompleteByDate[runDate] = False
        else:
            self.usageByDate[runDate] += usage

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
