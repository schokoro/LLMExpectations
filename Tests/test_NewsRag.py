import json
import os
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from unittest import TestCase

from amnesiac.exceptions import ConfigurationError, SummarizeError, TooManyAxisFailures

from Logging.BaseLogger import BaseLogger
from NewsLogic.NewsContext import NewsContext
from NewsLogic.NewsContextProvider import NewsContextProvider
from NewsLogic.NewsDocument import NewsDocument
from NewsLogic.newsExceptions import (
    NewsContextError,
    NewsContextNotPreparedError,
    NewsContextUnavailableError,
)
from NewsLogic.newsHelpers import moscowDate, readSecret
from NewsLogic.NewsRagConfiguration import NewsRagConfiguration, rawMode, twoStageMode
from NewsLogic.NewsRetriever import NewsRetriever
from NewsLogic.newsSectionRenderer import renderNewsSection
from NewsLogic.NewsSummariesCache import NewsSummariesCache
from SurveyLogic.PromptBuilders.ContextPromptBuilders.NewsPromptBuilder import (
    NewsPromptBuilder,
)
from Tests import newsFixtures

failedAxisPlaceholder = '(нет данных по оси из-за ошибки провайдера)'


class SilentLogger(BaseLogger):
    def __init__(self):
        super().__init__()
        self.messages = []

    def logDebug(self, obj):
        self.messages.append(str(obj))


@dataclass
class StubUsage:
    calls: int = 1
    total_tokens: int = 100


@dataclass
class StubSummarizeResult:
    meta: str
    failed_axes: list[str]
    usage: StubUsage
    axis_summaries: dict[str, str] = field(default_factory=dict)


class StubSummarizer:
    """Провайдер в тестах не вызывается: сеть в гейте тестов запрещена."""

    def __init__(self, meta: str = 'мета-саммари', failedAxes: tuple[str, ...] = ()):
        self.meta = meta
        self.failedAxes = failedAxes
        self.calls = 0

    async def buildSummary(self, retrieved) -> StubSummarizeResult:
        self.calls += 1

        # Как в amnesiac: отказавшая ось присутствует в axis_summaries, но с
        # заглушкой вместо текста.
        axisSummaries = {
            axis: (failedAxisPlaceholder if axis in self.failedAxes else f'саммари оси {axis}')
            for axis in retrieved
        }

        return StubSummarizeResult(meta=self.meta, failed_axes=list(self.failedAxes),
                                   usage=StubUsage(), axis_summaries=axisSummaries)


class ExplodingSummarizer:
    async def buildSummary(self, retrieved):
        raise AssertionError('Суммаризация вызвана при попадании в кеш')


class FlakySummarizer(StubSummarizer):
    """Падает заданное число раз, потом отдаёт результат.

    Воспроизводит наблюдавшийся сбой: провайдер отвечает успешно, но с пустым
    содержимым, и `amnesiac` превращает это в `SummarizeError`.
    """

    def __init__(self, failuresBeforeSuccess: int, error: Exception | None = None):
        super().__init__('саммари со второй попытки')
        self.failuresBeforeSuccess = failuresBeforeSuccess
        self.error = error or SummarizeError('Model returned empty content for meta summary')

    async def buildSummary(self, retrieved):
        if self.calls < self.failuresBeforeSuccess:
            self.calls += 1
            raise self.error

        # Счётчик увеличивает базовый класс, поэтому calls == отказы + успехи.
        return await super().buildSummary(retrieved)


class NewsFixtureTestCase(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = Path(tempfile.mkdtemp(prefix='newsRagTests'))
        cls.corpusPath = newsFixtures.createCorpusFixture(cls.folder / 'corpus.db')
        cls.projectDbPath = newsFixtures.createProjectDbFixture(cls.folder / 'project.db')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.folder, ignore_errors=True)

    def createConfiguration(self, **overrides) -> NewsRagConfiguration:
        parameters = {
            'axes': newsFixtures.axes,
            'horizonDays': newsFixtures.horizonDays,
            'topKPerAxis': 50,
            'dedupThreshold': 0.9,
            'excludeChannels': ('prime1',),
            'mode': rawMode,
            'corpusPath': self.corpusPath,
            'projectDbPath': self.projectDbPath,
        }
        parameters.update(overrides)

        return NewsRagConfiguration(**parameters)

    def retrieve(self, runDate: date | None = None, **overrides) -> dict[str, list[NewsDocument]]:
        retriever = NewsRetriever(self.createConfiguration(**overrides), SilentLogger())

        return retriever.retrieve(runDate or date.fromisoformat(newsFixtures.runDate))


class TestNewsRetrievalCutoff(NewsFixtureTestCase):
    def test_no_document_is_dated_by_the_survey_day_or_later(self):
        retrieved = self.retrieve()

        for axis, documents in retrieved.items():
            for document in documents:
                self.assertLess(moscowDate(document.publishedAt),
                                date.fromisoformat(newsFixtures.runDate),
                                f'Ось {axis}: документ {document.messageId} не старше даты опроса')

    def test_last_day_before_the_survey_day_is_included(self):
        retrieved = self.retrieve()

        messageIds = {document.messageId for document in retrieved[newsFixtures.firstAxis]}
        self.assertIn(12, messageIds, 'Сообщение за день до опроса должно попасть в выдачу')

    def test_survey_day_messages_are_excluded(self):
        retrieved = self.retrieve()

        messageIds = {document.messageId
                      for documents in retrieved.values()
                      for document in documents}
        self.assertNotIn(5, messageIds, 'Ночное сообщение дня опроса не должно попадать в выдачу')
        self.assertNotIn(6, messageIds, 'Дневное сообщение дня опроса не должно попадать в выдачу')

    def test_message_before_the_window_is_excluded(self):
        retrieved = self.retrieve()

        messageIds = {document.messageId
                      for documents in retrieved.values()
                      for document in documents}
        self.assertNotIn(11, messageIds, 'Сообщение накануне окна не должно попадать в выдачу')

    def test_both_window_bounds_follow_moscow_midnights(self):
        retrieved = self.retrieve()

        messageIds = {document.messageId
                      for documents in retrieved.values()
                      for document in documents}

        self.assertNotIn(11, messageIds, '23:59 MSK перед первым днём окна')
        self.assertIn(1, messageIds, '02:50 MSK первого дня окна')
        self.assertIn(12, messageIds, '23:30 MSK последнего дня окна')
        self.assertNotIn(4, messageIds, '02:59 MSK дня опроса')

    def test_day_numbers_start_at_the_first_day_of_the_window(self):
        retrieved = self.retrieve()

        dayNumbers = {document.messageId: document.dayNumber
                      for document in retrieved[newsFixtures.firstAxis]}

        self.assertEqual({1: 1, 2: 1, 3: 2, 12: 3}, dayNumbers)

    def test_day_number_comes_from_the_moscow_publication_date(self):
        retrieved = self.retrieve()

        dayNumbers = {document.messageId: document.dayNumber
                      for document in retrieved[newsFixtures.firstAxis]}

        self.assertEqual(1, dayNumbers[1])


class TestNewsRetrievalSelection(NewsFixtureTestCase):
    def test_excluded_channel_invalid_and_unembedded_messages_are_dropped(self):
        retrieved = self.retrieve()

        messageIds = {document.messageId
                      for documents in retrieved.values()
                      for document in documents}

        self.assertNotIn(7, messageIds, 'Канал из exclude_channels')
        self.assertNotIn(8, messageIds, 'is_valid = 0')
        self.assertNotIn(9, messageIds, 'Сообщение без эмбеддинга')

    def test_near_duplicate_is_deduplicated(self):
        retrieved = self.retrieve()

        messageIds = [document.messageId for document in retrieved[newsFixtures.firstAxis]]

        self.assertNotIn(newsFixtures.duplicateMessageId, messageIds)
        self.assertEqual(newsFixtures.inWindowMessageIds, messageIds)

    def test_near_duplicate_survives_a_threshold_above_its_similarity(self):
        retrieved = self.retrieve(dedupThreshold=1.01)

        messageIds = [document.messageId for document in retrieved[newsFixtures.firstAxis]]

        self.assertIn(newsFixtures.duplicateMessageId, messageIds)

    def test_retrieval_is_deterministic_with_order(self):
        first = self.retrieve()
        second = self.retrieve()

        for axis in first:
            self.assertEqual(
                [document.messageId for document in first[axis]],
                [document.messageId for document in second[axis]],
            )

    def test_axis_vector_is_taken_by_full_key_not_by_name(self):
        # В фикстуре у оси «ось-а» есть чужой одноимённый вектор, направленный по
        # второй оси. Взяли бы его — top-2 состояли бы из документов оси «б».
        retrieved = self.retrieve(topKPerAxis=2)

        messageIds = {document.messageId for document in retrieved[newsFixtures.firstAxis]}

        self.assertEqual({1, 2}, messageIds)

    def test_documents_are_ordered_by_day(self):
        retrieved = self.retrieve()

        for documents in retrieved.values():
            dayNumbers = [document.dayNumber for document in documents]
            self.assertEqual(sorted(dayNumbers), dayNumbers)

    def test_scores_are_higher_for_documents_closer_to_the_axis(self):
        retrieved = self.retrieve()

        scores = {document.messageId: document.score for document in retrieved[newsFixtures.firstAxis]}

        self.assertGreater(scores[1], scores[2])
        self.assertGreater(scores[2], scores[3])
        self.assertGreater(scores[3], scores[12])


class TestNewsRetrievalCoverage(NewsFixtureTestCase):
    def test_date_before_corpus_coverage_is_unavailable(self):
        with self.assertRaises(NewsContextUnavailableError):
            self.retrieve(date(2022, 3, 3))

    def test_date_after_corpus_coverage_is_unavailable(self):
        with self.assertRaises(NewsContextUnavailableError):
            self.retrieve(date(2022, 4, 3))

    def test_first_utc_coverage_day_is_not_a_full_moscow_day(self):
        with self.assertRaises(NewsContextUnavailableError):
            self.retrieve(date(2022, 3, 5))

    def test_last_full_moscow_day_is_covered(self):
        with self.assertRaises(NewsContextError) as raised:
            self.retrieve(date(2022, 4, 2))

        self.assertNotIsInstance(raised.exception, NewsContextUnavailableError)

    def test_empty_window_is_a_loud_failure(self):
        with self.assertRaises(NewsContextError):
            self.retrieve(date(2022, 3, 10))


class TestNewsSectionRendering(TestCase):
    def createContext(self, mode: str, summary: str | None = None) -> NewsContext:
        documents = {
            'дкп': [
                NewsDocument(101, 'tass', '2022-03-22T00:10:00+00:00', 1,
                             'ЦБ сохранил ставку', 'дкп', 0, 0.7),
                NewsDocument(102, 'rbc', '2022-03-24T10:00:00+00:00', 3,
                             'Ставка обсуждается', 'дкп', 1, 0.6),
            ],
            'инфляция': [],
        }

        return NewsContext(
            runDate=date(2022, 3, 25),
            windowFrom=date(2022, 3, 11),
            windowToExclusive=date(2022, 3, 25),
            horizonDays=14,
            mode=mode,
            documents=documents,
            summary=summary,
            summaryModel='test/model' if summary else None,
        )

    def test_two_stage_section_matches_fixture(self):
        expected = (
            'Новостной фон за 14 дней, предшествовавших опросу. Дни пронумерованы от начала '
            'периода: день 1 — самый ранний, день 14 — накануне опроса.\n'
            '\n'
            'Узел 1. Ставка и цены.'
        )

        section = renderNewsSection(self.createContext(twoStageMode, 'Узел 1. Ставка и цены.'))

        self.assertEqual(expected, section)

    def test_raw_section_matches_fixture(self):
        expected = (
            'Новостные сообщения за 14 дней, предшествовавших опросу, сгруппированные по темам. '
            'Дни пронумерованы от начала периода: день 1 — самый ранний, день 14 — накануне опроса.\n'
            '\n'
            '--- Тема: дкп ---\n'
            '[день 1 | tass] ЦБ сохранил ставку\n'
            '[день 3 | rbc] Ставка обсуждается\n'
            '\n'
            '--- Тема: инфляция ---\n'
            '(нет сообщений по теме)'
        )

        section = renderNewsSection(self.createContext(rawMode))

        self.assertEqual(expected, section)

    def test_empty_summary_is_a_loud_failure(self):
        with self.assertRaises(NewsContextError):
            renderNewsSection(self.createContext(twoStageMode, ''))


class TestNewsPromptBuilder(NewsFixtureTestCase):
    def createProvider(self, **overrides) -> NewsContextProvider:
        configuration = self.createConfiguration(**overrides)

        return NewsContextProvider(
            configuration,
            SilentLogger(),
            summarizer=StubSummarizer(),
        )

    def test_builder_fails_when_context_is_not_prepared(self):
        builder = NewsPromptBuilder(self.createProvider())

        with self.assertRaises(NewsContextNotPreparedError):
            builder.buildPrompt(date.fromisoformat(newsFixtures.runDate), None)

    def test_builder_returns_the_prepared_section(self):
        provider = self.createProvider()
        provider.prepare(date.fromisoformat(newsFixtures.runDate))
        builder = NewsPromptBuilder(provider)

        section = builder.buildPrompt(date.fromisoformat(newsFixtures.runDate), None)

        self.assertIn('--- Тема: ось-а ---', section)
        self.assertIn('[день 1 | tass] сообщение первого дня окна', section)

    def test_section_does_not_depend_on_the_profile(self):
        provider = self.createProvider()
        provider.prepare(date.fromisoformat(newsFixtures.runDate))
        builder = NewsPromptBuilder(provider)

        runDate = date.fromisoformat(newsFixtures.runDate)

        self.assertEqual(builder.buildPrompt(runDate, None), builder.buildPrompt(runDate, object()))

    def test_datetime_and_date_address_the_same_context(self):
        provider = self.createProvider()
        provider.prepare(datetime.fromisoformat('2022-03-25T00:00:00'))
        builder = NewsPromptBuilder(provider)

        section = builder.buildPrompt(date(2022, 3, 25), None)

        self.assertIn('--- Тема: ось-а ---', section)


class TestSecretReading(TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp(prefix='newsRagSecrets'))
        self.environmentFile = self.folder / '.env'

    def tearDown(self):
        shutil.rmtree(self.folder, ignore_errors=True)
        os.environ.pop('NEWS_RAG_TEST_KEY', None)

    def test_value_is_read_from_the_environment_file(self):
        self.environmentFile.write_text('NEWS_RAG_TEST_KEY=fromFile\n', encoding='utf-8')

        self.assertEqual('fromFile', readSecret('NEWS_RAG_TEST_KEY', self.environmentFile))

    def test_quotes_comments_and_blank_lines_are_handled(self):
        self.environmentFile.write_text(
            '# комментарий\n'
            '\n'
            'OTHER_KEY=другое\n'
            'NEWS_RAG_TEST_KEY="fromFile"\n',
            encoding='utf-8',
        )

        self.assertEqual('fromFile', readSecret('NEWS_RAG_TEST_KEY', self.environmentFile))

    def test_environment_wins_over_the_file(self):
        self.environmentFile.write_text('NEWS_RAG_TEST_KEY=fromFile\n', encoding='utf-8')
        os.environ['NEWS_RAG_TEST_KEY'] = 'fromEnvironment'

        self.assertEqual('fromEnvironment', readSecret('NEWS_RAG_TEST_KEY', self.environmentFile))

    def test_missing_key_and_missing_file_give_none(self):
        self.environmentFile.write_text('OTHER_KEY=другое\n', encoding='utf-8')

        self.assertIsNone(readSecret('NEWS_RAG_TEST_KEY', self.environmentFile))
        self.assertIsNone(readSecret('NEWS_RAG_TEST_KEY', self.folder / 'нет-такого-файла'))


class TestNewsRagConfigurationValidation(TestCase):
    """Охраны конфигурации: неверное значение должно падать при сборке.

    Конфигурация собирается один раз в начале прогона, а сказывается через часы
    работы, поэтому проверка на входе — единственное дешёвое место.
    """

    def test_zero_attempts_is_rejected(self):
        with self.assertRaises(ValueError):
            NewsRagConfiguration(summarizeAttempts=0)

    def test_negative_attempts_is_rejected(self):
        with self.assertRaises(ValueError):
            NewsRagConfiguration(summarizeAttempts=-1)

    def test_single_attempt_is_allowed(self):
        # Одна попытка — это «без повторов», законная настройка.
        self.assertEqual(1, NewsRagConfiguration(summarizeAttempts=1).summarizeAttempts)

    def test_negative_retry_delay_is_rejected(self):
        with self.assertRaises(ValueError):
            NewsRagConfiguration(summarizeRetryDelaySeconds=-1)

    def test_zero_retry_delay_is_allowed(self):
        self.assertEqual(0, NewsRagConfiguration(summarizeRetryDelaySeconds=0).summarizeRetryDelaySeconds)

    def test_non_positive_horizon_is_rejected(self):
        with self.assertRaises(ValueError):
            NewsRagConfiguration(horizonDays=0)

    def test_non_positive_top_k_is_rejected(self):
        with self.assertRaises(ValueError):
            NewsRagConfiguration(topKPerAxis=0)

    def test_empty_axes_are_rejected(self):
        with self.assertRaises(ValueError):
            NewsRagConfiguration(axes={})

    def test_unknown_mode_is_rejected(self):
        with self.assertRaises(ValueError):
            NewsRagConfiguration(mode='summarized')


class TestNewsSummaryCaching(NewsFixtureTestCase):
    def setUp(self):
        self.cachePath = self.folder / f'cache_{self.id()}.db'
        newsFixtures.createProjectDbFixture(self.cachePath)
        self.configuration = self.createConfiguration(
            mode=twoStageMode,
            projectDbPath=self.cachePath,
            summarizeModel='test/model',
        )

    def test_summary_is_computed_once_and_reused_within_the_run(self):
        summarizer = StubSummarizer('первое саммари')
        provider = NewsContextProvider(self.configuration, SilentLogger(), summarizer=summarizer)

        runDate = date.fromisoformat(newsFixtures.runDate)
        first = provider.prepare(runDate)
        second = provider.prepare(runDate)

        self.assertEqual(1, summarizer.calls)
        self.assertIs(first, second)
        self.assertEqual('первое саммари', first.summary)
        self.assertFalse(first.summaryFromCache)

    def test_summary_is_read_back_from_the_project_database(self):
        summarizer = StubSummarizer('сохранённое саммари')
        runDate = date.fromisoformat(newsFixtures.runDate)

        NewsContextProvider(self.configuration, SilentLogger(), summarizer=summarizer).prepare(runDate)

        context = NewsContextProvider(
            self.configuration,
            SilentLogger(),
            summarizer=ExplodingSummarizer(),
        ).prepare(runDate)

        self.assertEqual('сохранённое саммари', context.summary)
        self.assertTrue(context.summaryFromCache)

    def test_cached_summary_of_another_horizon_is_ignored(self):
        cache = NewsSummariesCache(self.cachePath)
        runDate = date.fromisoformat(newsFixtures.runDate)
        cache.saveSummary(runDate, newsFixtures.horizonDays + 1, 'чужой горизонт', 10, 'test/model', ())

        self.assertIsNone(cache.getSummary(runDate, newsFixtures.horizonDays, 'test/model'))

    def test_cached_summary_of_another_model_is_ignored(self):
        cache = NewsSummariesCache(self.cachePath)
        runDate = date.fromisoformat(newsFixtures.runDate)
        cache.saveSummary(runDate, newsFixtures.horizonDays, 'чужая модель', 10, 'other/model', ())

        self.assertIsNone(cache.getSummary(runDate, newsFixtures.horizonDays, 'test/model'))

    def test_failed_axes_survive_a_round_trip_through_the_cache(self):
        cache = NewsSummariesCache(self.cachePath)
        runDate = date.fromisoformat(newsFixtures.runDate)
        cache.saveSummary(runDate, newsFixtures.horizonDays, 'неполное саммари', 10, 'test/model', ('курс', 'дкп'))

        summary, documentsCount, failedAxes = cache.getSummary(
            runDate, newsFixtures.horizonDays, 'test/model'
        )

        self.assertEqual('неполное саммари', summary)
        self.assertEqual(10, documentsCount)
        self.assertEqual(('курс', 'дкп'), failedAxes)

    def test_no_failed_axes_is_stored_as_empty_list_not_as_unknown(self):
        cache = NewsSummariesCache(self.cachePath)
        runDate = date.fromisoformat(newsFixtures.runDate)
        cache.saveSummary(runDate, newsFixtures.horizonDays, 'полное саммари', 10, 'test/model', ())

        self.assertEqual((), cache.getSummary(runDate, newsFixtures.horizonDays, 'test/model')[2])

        stored = sqlite3.connect(str(self.cachePath)).execute(
            'SELECT failed_axes FROM summaries WHERE run_date = ?', (runDate.isoformat(),)
        ).fetchone()[0]
        self.assertEqual('[]', stored)

    def test_legacy_row_without_failed_axes_reports_unknown_rather_than_none_failed(self):
        runDate = date.fromisoformat(newsFixtures.runDate)
        connection = sqlite3.connect(str(self.cachePath))
        connection.execute(
            """
            INSERT INTO summaries (run_date, horizon_days, summary, doc_count, model, failed_axes)
            VALUES (?, ?, ?, ?, ?, NULL)
            """,
            (runDate.isoformat(), newsFixtures.horizonDays, 'саммари из blind_prophet', 10, 'test/model'),
        )
        connection.commit()
        connection.close()

        failedAxes = NewsSummariesCache(self.cachePath).getSummary(
            runDate, newsFixtures.horizonDays, 'test/model'
        )[2]

        self.assertIsNone(failedAxes)

    def test_failed_axes_reach_the_context_and_the_artefact(self):
        artefactsFolder = self.folder / f'artefacts_{self.id()}'
        configuration = self.createConfiguration(
            mode=twoStageMode,
            projectDbPath=self.cachePath,
            summarizeModel='test/model',
            artefactsFolder=artefactsFolder,
        )
        summarizer = StubSummarizer('саммари без оси', failedAxes=('курс',))
        runDate = date.fromisoformat(newsFixtures.runDate)

        computed = NewsContextProvider(configuration, SilentLogger(), summarizer=summarizer).prepare(runDate)
        self.assertEqual(('курс',), computed.failedAxes)

        # Главное: после перезапуска отказ виден так же, а не растворяется в кеше.
        fromCache = NewsContextProvider(
            configuration,
            SilentLogger(),
            summarizer=ExplodingSummarizer(),
        ).prepare(runDate)

        self.assertTrue(fromCache.summaryFromCache)
        self.assertEqual(('курс',), fromCache.failedAxes)

        artefact = json.loads(
            (artefactsFolder / f'{newsFixtures.runDate}_{twoStageMode}.json').read_text(encoding='utf-8')
        )
        self.assertEqual(['курс'], artefact['failed_axes'])

    def test_unknown_failed_axes_are_not_rendered_as_an_empty_list_in_the_artefact(self):
        artefactsFolder = self.folder / f'artefacts_{self.id()}'
        configuration = self.createConfiguration(
            mode=twoStageMode,
            projectDbPath=self.cachePath,
            summarizeModel='test/model',
            artefactsFolder=artefactsFolder,
        )
        runDate = date.fromisoformat(newsFixtures.runDate)
        connection = sqlite3.connect(str(self.cachePath))
        connection.execute(
            """
            INSERT INTO summaries (run_date, horizon_days, summary, doc_count, model, failed_axes)
            VALUES (?, ?, ?, ?, ?, NULL)
            """,
            (runDate.isoformat(), newsFixtures.horizonDays, 'старое саммари', 10, 'test/model'),
        )
        connection.commit()
        connection.close()

        context = NewsContextProvider(
            configuration,
            SilentLogger(),
            summarizer=ExplodingSummarizer(),
        ).prepare(runDate)

        self.assertIsNone(context.failedAxes)

        artefact = json.loads(
            (artefactsFolder / f'{newsFixtures.runDate}_{twoStageMode}.json').read_text(encoding='utf-8')
        )
        self.assertIsNone(artefact['failed_axes'])

    def test_transient_summarization_failure_is_retried(self):
        configuration = self.createConfiguration(
            mode=twoStageMode, projectDbPath=self.cachePath, summarizeModel='test/model',
            summarizeAttempts=3, summarizeRetryDelaySeconds=0,
        )
        summarizer = FlakySummarizer(failuresBeforeSuccess=2)
        runDate = date.fromisoformat(newsFixtures.runDate)

        context = NewsContextProvider(configuration, SilentLogger(), summarizer=summarizer).prepare(runDate)

        self.assertEqual(3, summarizer.calls)
        self.assertEqual('саммари со второй попытки', context.summary)

    def test_too_many_axis_failures_is_retried_as_well(self):
        # TooManyAxisFailures — подкласс SummarizeError и такой же временный сбой
        # провайдера, как пустой ответ: 2026-09-06 все девять осей отвалились
        # разом по 403 и вернулись через минуту.
        configuration = self.createConfiguration(
            mode=twoStageMode, projectDbPath=self.cachePath, summarizeModel='test/model',
            summarizeAttempts=2, summarizeRetryDelaySeconds=0,
        )
        summarizer = FlakySummarizer(failuresBeforeSuccess=1,
                                     error=TooManyAxisFailures({'дкп': 'PermissionDeniedError(403)'}))
        runDate = date.fromisoformat(newsFixtures.runDate)

        NewsContextProvider(configuration, SilentLogger(), summarizer=summarizer).prepare(runDate)

        self.assertEqual(2, summarizer.calls)

    def test_summarization_failure_is_raised_after_the_last_attempt(self):
        configuration = self.createConfiguration(
            mode=twoStageMode, projectDbPath=self.cachePath, summarizeModel='test/model',
            summarizeAttempts=2, summarizeRetryDelaySeconds=0,
        )
        summarizer = FlakySummarizer(failuresBeforeSuccess=99)
        runDate = date.fromisoformat(newsFixtures.runDate)

        with self.assertRaises(SummarizeError):
            NewsContextProvider(configuration, SilentLogger(), summarizer=summarizer).prepare(runDate)

        self.assertEqual(2, summarizer.calls)
        self.assertIsNone(
            NewsSummariesCache(self.cachePath).getSummary(runDate, newsFixtures.horizonDays, 'test/model'),
            'Провалившаяся дата не должна попадать в кеш',
        )

    def test_non_summarization_errors_are_not_retried(self):
        # Ошибка конфигурации или шаблона повтором не лечится: она наша, а не
        # провайдера, и повторы её только прячут.
        configuration = self.createConfiguration(
            mode=twoStageMode, projectDbPath=self.cachePath, summarizeModel='test/model',
            summarizeAttempts=5, summarizeRetryDelaySeconds=0,
        )
        summarizer = FlakySummarizer(failuresBeforeSuccess=99, error=ConfigurationError('axes cannot be empty'))
        runDate = date.fromisoformat(newsFixtures.runDate)

        with self.assertRaises(ConfigurationError):
            NewsContextProvider(configuration, SilentLogger(), summarizer=summarizer).prepare(runDate)

        self.assertEqual(1, summarizer.calls, 'Повтор не должен применяться к ошибкам не от провайдера')

    def test_successful_summarization_is_not_retried(self):
        configuration = self.createConfiguration(
            mode=twoStageMode, projectDbPath=self.cachePath, summarizeModel='test/model',
            summarizeAttempts=3, summarizeRetryDelaySeconds=0,
        )
        summarizer = StubSummarizer('с первого раза')
        runDate = date.fromisoformat(newsFixtures.runDate)

        NewsContextProvider(configuration, SilentLogger(), summarizer=summarizer).prepare(runDate)

        self.assertEqual(1, summarizer.calls)

    def test_axis_summaries_are_stored_for_every_successful_axis(self):
        provider = NewsContextProvider(self.configuration, SilentLogger(),
                                       summarizer=StubSummarizer('мета'))
        runDate = date.fromisoformat(newsFixtures.runDate)
        provider.prepare(runDate)

        stored = NewsSummariesCache(self.cachePath).getAxisSummaries(
            runDate, newsFixtures.horizonDays, 'test/model'
        )

        self.assertEqual(set(self.configuration.axes), set(stored))
        for axis, summary in stored.items():
            self.assertEqual(f'саммари оси {axis}', summary)

    def test_failed_axis_placeholder_is_not_stored_as_a_summary(self):
        failedAxis = newsFixtures.firstAxis
        provider = NewsContextProvider(self.configuration, SilentLogger(),
                                       summarizer=StubSummarizer('мета', failedAxes=(failedAxis,)))
        runDate = date.fromisoformat(newsFixtures.runDate)
        provider.prepare(runDate)

        stored = NewsSummariesCache(self.cachePath).getAxisSummaries(
            runDate, newsFixtures.horizonDays, 'test/model'
        )

        self.assertNotIn(failedAxis, stored)
        self.assertNotIn(failedAxisPlaceholder, stored.values())
        self.assertEqual(len(self.configuration.axes) - 1, len(stored))

    def test_axis_summaries_of_another_horizon_or_model_are_not_returned(self):
        cache = NewsSummariesCache(self.cachePath)
        runDate = date.fromisoformat(newsFixtures.runDate)
        cache.saveAxisSummaries(runDate, newsFixtures.horizonDays, 'test/model',
                                {'курс': 'саммари'}, {'курс': 5})

        self.assertEqual({'курс': 'саммари'},
                         cache.getAxisSummaries(runDate, newsFixtures.horizonDays, 'test/model'))
        self.assertEqual({}, cache.getAxisSummaries(runDate, newsFixtures.horizonDays + 1, 'test/model'))
        self.assertEqual({}, cache.getAxisSummaries(runDate, newsFixtures.horizonDays, 'other/model'))

    def test_axis_document_counts_are_stored_alongside_summaries(self):
        provider = NewsContextProvider(self.configuration, SilentLogger(),
                                       summarizer=StubSummarizer('мета'))
        runDate = date.fromisoformat(newsFixtures.runDate)
        context = provider.prepare(runDate)

        rows = dict(sqlite3.connect(str(self.cachePath)).execute(
            'SELECT axis, doc_count FROM axis_summaries WHERE run_date = ?', (runDate.isoformat(),)
        ).fetchall())

        for axis, documents in context.documents.items():
            self.assertEqual(len(documents), rows[axis])

    def test_database_without_the_axis_summaries_table_is_reported(self):
        legacyPath = self.folder / f'noaxis_{self.id()}.db'
        newsFixtures.createProjectDbFixture(legacyPath, withAxisSummaries=False)
        runDate = date.fromisoformat(newsFixtures.runDate)

        with self.assertRaises(NewsContextError) as raised:
            NewsSummariesCache(legacyPath).getSummary(runDate, newsFixtures.horizonDays, 'test/model')

        self.assertIn('axis_summaries', str(raised.exception))
        self.assertIn('013_axis_summaries.sql', str(raised.exception))

    def test_database_without_the_migration_is_reported_instead_of_being_used(self):
        legacyPath = self.folder / f'legacy_{self.id()}.db'
        newsFixtures.createProjectDbFixture(legacyPath, withFailedAxes=False)
        runDate = date.fromisoformat(newsFixtures.runDate)

        with self.assertRaises(NewsContextError) as raised:
            NewsSummariesCache(legacyPath).getSummary(runDate, newsFixtures.horizonDays, 'test/model')

        self.assertIn('failed_axes', str(raised.exception))
        self.assertIn('012_summaries_failed_axes.sql', str(raised.exception))

    def test_malformed_failed_axes_column_is_reported_instead_of_being_guessed(self):
        # 'курс' — не JSON вовсе, '{"курс": 1}' — валидный JSON неверной формы.
        # Разные ветви разбора, поэтому проверяются обе.
        for stored in ('курс', '{"курс": 1}', '[1, 2]'):
            with self.subTest(stored=stored):
                path = self.folder / f'malformed_{abs(hash(stored))}.db'
                newsFixtures.createProjectDbFixture(path)
                runDate = date.fromisoformat(newsFixtures.runDate)

                connection = sqlite3.connect(str(path))
                connection.execute(
                    """
                    INSERT INTO summaries (run_date, horizon_days, summary, doc_count, model, failed_axes)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (runDate.isoformat(), newsFixtures.horizonDays, 'саммари', 10, 'test/model', stored),
                )
                connection.commit()
                connection.close()

                with self.assertRaises(NewsContextError):
                    NewsSummariesCache(path).getSummary(runDate, newsFixtures.horizonDays, 'test/model')

    def test_artefact_is_written_with_documents_and_configuration(self):
        artefactsFolder = self.folder / f'artefacts_{self.id()}'
        configuration = self.createConfiguration(
            mode=twoStageMode,
            projectDbPath=self.cachePath,
            summarizeModel='test/model',
            artefactsFolder=artefactsFolder,
        )
        provider = NewsContextProvider(configuration, SilentLogger(), summarizer=StubSummarizer())
        provider.prepare(date.fromisoformat(newsFixtures.runDate))

        path = artefactsFolder / f'{newsFixtures.runDate}_{twoStageMode}.json'
        artefact = json.loads(path.read_text(encoding='utf-8'))

        self.assertEqual(newsFixtures.runDate, artefact['run_date'])
        self.assertEqual('2022-03-22', artefact['window_from'])
        self.assertEqual(newsFixtures.runDate, artefact['window_to_exclusive'])
        self.assertEqual(
            newsFixtures.inWindowMessageIds,
            [document['message_id'] for document in artefact['documents'][newsFixtures.firstAxis]],
        )
        self.assertEqual(newsFixtures.horizonDays, artefact['config']['horizon_days'])
