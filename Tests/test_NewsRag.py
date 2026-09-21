import json
import os
import shutil
import sqlite3
import tempfile
from datetime import date, datetime
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from amnesiac.summarize import (
    AxisSummariesResult,
    MetaResult,
    MetaSummaryError,
    TooManyAxisFailures,
    Usage,
)

from Logging.BaseLogger import BaseLogger
from NewsLogic.NewsContext import NewsContext
from NewsLogic.NewsContextProvider import NewsContextProvider
from NewsLogic.NewsCorpusReader import NewsCorpusReader
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


class StubSummarizer:
    """Провайдер в тестах не вызывается: сеть в гейте тестов запрещена."""

    def __init__(self, meta: str = 'мета-саммари', failedAxes: tuple[str, ...] = ()):
        self.meta = meta
        self.failedAxes = failedAxes
        self.axisInputs = []
        self.metaInputs = []
        self.axisUsage = Usage(calls=2, total_tokens=100)
        self.metaUsage = Usage(calls=1, total_tokens=37)
        self.axisError = None
        self.metaError = None

    async def buildAxisSummaries(self, retrieved) -> AxisSummariesResult:
        self.axisInputs.append(retrieved)
        if self.axisError is not None:
            raise self.axisError

        # Как в amnesiac: отказавшая ось передаётся в мету с заглушкой.
        axisSummaries = {
            axis: (failedAxisPlaceholder if axis in self.failedAxes else f'саммари оси {axis}')
            for axis in retrieved
        }
        return AxisSummariesResult(
            failed_axes=list(self.failedAxes),
            axis_errors={axis: 'ошибка провайдера' for axis in self.failedAxes},
            usage=self.axisUsage,
            axis_summaries=axisSummaries,
        )

    async def buildMetaSummary(self, axisSummaries) -> MetaResult:
        self.metaInputs.append(axisSummaries)
        if self.metaError is not None:
            raise self.metaError
        return MetaResult(meta=self.meta, usage=self.metaUsage)


class ExplodingSummarizer:
    async def buildAxisSummaries(self, retrieved):
        raise AssertionError('Суммаризация вызвана при попадании в кеш')

    async def buildMetaSummary(self, axisSummaries):
        raise AssertionError('Суммаризация вызвана при попадании в кеш')


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


class TestCorpusTimestampContract(NewsFixtureTestCase):
    def test_corpus_with_a_foreign_timestamp_format_is_rejected(self):
        corpusPath = newsFixtures.createCorpusFixture(
            self.folder / 'foreign.db', withForeignTimestamp=True
        )
        with self.assertRaisesRegex(NewsContextError, r'messages\.date'):
            self.retrieve(corpusPath=corpusPath)

    def test_corpus_with_a_space_separated_timestamp_is_rejected(self):
        timestamp = '2022-03-23 12:00:00+00:00'
        corpusPath = newsFixtures.createCorpusFixture(
            self.folder / 'spaceSeparated.db', withForeignTimestamp=timestamp
        )
        with self.assertRaisesRegex(NewsContextError, r'messages\.date') as raised:
            self.retrieve(corpusPath=corpusPath)
        self.assertIn('нарушений: 1', str(raised.exception))
        self.assertIn(repr(timestamp), str(raised.exception))

    def test_the_timestamp_format_is_checked_before_the_window_is_loaded(self):
        corpusPath = newsFixtures.createCorpusFixture(
            self.folder / 'foreignOrder.db', withForeignTimestamp=True
        )
        # Без проверки формата это окно непустое, несмотря на испорченную строку.
        with NewsCorpusReader(corpusPath) as reader:
            rows = reader.loadWindow(
                datetime.fromisoformat('2022-03-21T21:00:00+00:00'),
                datetime.fromisoformat('2022-03-24T21:00:00+00:00'),
            )
            self.assertTrue(rows)
        with patch.object(NewsCorpusReader, 'loadWindow', autospec=True) as loadWindow:
            with self.assertRaisesRegex(NewsContextError, r'messages\.date'):
                self.retrieve(corpusPath=corpusPath)
            loadWindow.assert_not_called()

    def test_a_well_formed_corpus_passes_the_format_check(self):
        with NewsCorpusReader(self.corpusPath) as reader:
            reader.assertCorpusContract()
        self.assertEqual(
            newsFixtures.inWindowMessageIds,
            [document.messageId for document in self.retrieve()[newsFixtures.firstAxis]],
        )

    def test_timestamp_scan_is_cached_across_readers_but_metadata_is_checked(self):
        corpusPath = newsFixtures.createCorpusFixture(self.folder / 'cachedFormat.db')
        queries = []
        for _ in range(2):
            with NewsCorpusReader(corpusPath) as reader:
                reader.connection.set_trace_callback(queries.append)
                reader.assertCorpusContract()
        self.assertEqual(1, sum('FROM messages' in query for query in queries))
        self.assertEqual(2, sum('FROM corpus_meta' in query for query in queries))

    def test_changed_corpus_identity_rechecks_timestamp_format(self):
        corpusPath = newsFixtures.createCorpusFixture(self.folder / 'changedFormat.db')
        with NewsCorpusReader(corpusPath) as reader:
            reader.assertCorpusContract()
        statistics = corpusPath.stat()
        with sqlite3.connect(corpusPath) as connection:
            connection.execute("UPDATE messages SET date = '2022-03-23 12:00:00' WHERE id = 3")
        # Явный сдвиг исключает зависимость теста от точности часов файловой системы.
        os.utime(corpusPath, ns=(statistics.st_atime_ns, statistics.st_mtime_ns + 1000000000))
        with self.assertRaisesRegex(NewsContextError, r'messages\.date'):
            self.retrieve(corpusPath=corpusPath)

    def test_empty_corpus_is_rejected_by_timestamp_format_check(self):
        corpusPath = newsFixtures.createCorpusFixture(self.folder / 'emptyFormat.db')
        with sqlite3.connect(corpusPath) as connection:
            connection.execute('DELETE FROM messages')
        with self.assertRaisesRegex(NewsContextError, r'messages\.date — корпус пуст \(0 строк\)'):
            self.retrieve(corpusPath=corpusPath)

    def test_naive_timestamp_is_rejected_instead_of_falling_back_to_the_machine_zone(self):
        with self.assertRaisesRegex(NewsContextError, '2022-03-24T23:59:00.*UTC'):
            moscowDate('2022-03-24T23:59:00')

    def test_moscow_date_of_an_aware_timestamp_is_unchanged(self):
        self.assertEqual(date(2022, 3, 24), moscowDate('2022-03-24T20:59:00+00:00'))
        self.assertEqual(date(2022, 3, 25), moscowDate('2022-03-24T21:00:00+00:00'))
        self.assertEqual(date(2022, 3, 25), moscowDate('2022-03-24T23:59:00+00:00'))


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

        self.assertEqual(1, len(summarizer.axisInputs))
        self.assertEqual(1, len(summarizer.metaInputs))
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

    def test_axis_summaries_are_saved_before_the_meta_call(self):
        cache = NewsSummariesCache(self.cachePath)
        runDate = date.fromisoformat(newsFixtures.runDate)
        storedAtMeta = {}

        class InspectingSummarizer(StubSummarizer):
            async def buildMetaSummary(self, axisSummaries):
                storedAtMeta.update(
                    cache.getAxisSummaries(runDate, newsFixtures.horizonDays, 'test/model')
                )
                return await super().buildMetaSummary(axisSummaries)

        summarizer = InspectingSummarizer()
        NewsContextProvider(self.configuration, SilentLogger(), summarizer=summarizer).prepare(runDate)

        self.assertEqual(
            {axis: f'саммари оси {axis}' for axis in self.configuration.axes}, storedAtMeta
        )

    def test_axis_summaries_survive_a_failing_meta_call(self):
        runDate = date.fromisoformat(newsFixtures.runDate)
        cache = NewsSummariesCache(self.cachePath)
        summarizer = StubSummarizer()
        summarizer.metaError = MetaSummaryError(
            axis_summaries={}, failed_axes=[], axis_errors={}, usage=Usage()
        )
        provider = NewsContextProvider(self.configuration, SilentLogger(), summarizer=summarizer)

        with self.assertRaises(MetaSummaryError) as raised:
            provider.prepare(runDate)

        self.assertIs(summarizer.metaError, raised.exception)
        self.assertEqual(1, len(summarizer.axisInputs))
        self.assertEqual(1, len(summarizer.metaInputs))
        self.assertEqual(
            {axis: f'саммари оси {axis}' for axis in self.configuration.axes},
            cache.getAxisSummaries(runDate, newsFixtures.horizonDays, 'test/model'),
        )
        self.assertIsNone(cache.getSummary(runDate, newsFixtures.horizonDays, 'test/model'))

        recovered = StubSummarizer()
        context = NewsContextProvider(
            self.configuration, SilentLogger(), summarizer=recovered
        ).prepare(runDate)
        self.assertEqual([], recovered.axisInputs)
        self.assertEqual(1, len(recovered.metaInputs))
        self.assertEqual(recovered.meta, context.summary)

    def test_cached_axes_are_merged_with_recomputed_ones_in_the_configured_order(self):
        runDate = date.fromisoformat(newsFixtures.runDate)
        secondAxis = list(self.configuration.axes)[1]
        NewsSummariesCache(self.cachePath).saveAxisSummaries(
            runDate, newsFixtures.horizonDays, 'test/model',
            {secondAxis: 'из кеша'}, {secondAxis: 1},
        )
        summarizer = StubSummarizer()
        NewsContextProvider(self.configuration, SilentLogger(), summarizer=summarizer).prepare(runDate)

        self.assertEqual(1, len(summarizer.metaInputs))
        self.assertEqual(list(self.configuration.axes), list(summarizer.metaInputs[0]))
        self.assertEqual('из кеша', summarizer.metaInputs[0][secondAxis])
        self.assertEqual(
            f'саммари оси {newsFixtures.firstAxis}',
            summarizer.metaInputs[0][newsFixtures.firstAxis],
        )

    def test_only_missing_axes_are_recomputed(self):
        runDate = date.fromisoformat(newsFixtures.runDate)
        cache = NewsSummariesCache(self.cachePath)
        secondAxis = list(self.configuration.axes)[1]
        cache.saveAxisSummaries(
            runDate, newsFixtures.horizonDays, 'test/model',
            {secondAxis: 'из кеша'}, {secondAxis: 1},
        )
        summarizer = StubSummarizer()
        provider = NewsContextProvider(self.configuration, SilentLogger(), summarizer=summarizer)
        retrieved = provider.retriever.retrieve(runDate)
        provider.prepare(runDate)
        self.assertEqual(
            [{axis: documents for axis, documents in retrieved.items() if axis != secondAxis}],
            summarizer.axisInputs,
        )

        # Отдельная дата с полным кешем осей, но без готовой меты.
        otherDate = date(2022, 3, 26)
        cached = {axis: f'кеш {axis}' for axis in retrieved}
        cache.saveAxisSummaries(
            otherDate, newsFixtures.horizonDays, 'test/model',
            cached, {axis: len(documents) for axis, documents in retrieved.items()},
        )
        allCached = StubSummarizer()
        logger = SilentLogger()
        provider = NewsContextProvider(self.configuration, logger, summarizer=allCached)
        context = provider.prepare(otherDate)
        self.assertEqual([], allCached.axisInputs)
        self.assertEqual([cached], allCached.metaInputs)
        self.assertEqual(
            (allCached.meta, (), False),
            (context.summary, context.failedAxes, context.summaryFromCache),
        )
        self.assertIn(
            f'News summary for {otherDate} computed: {len(allCached.meta)} characters, '
            '1 provider calls, 37 tokens',
            logger.messages,
        )

    def test_failed_axis_placeholder_still_reaches_the_meta_prompt(self):
        summarizer = StubSummarizer(failedAxes=(newsFixtures.firstAxis,))
        NewsContextProvider(
            self.configuration, SilentLogger(), summarizer=summarizer
        ).prepare(date.fromisoformat(newsFixtures.runDate))

        self.assertEqual(1, len(summarizer.metaInputs))
        self.assertEqual(list(self.configuration.axes), list(summarizer.metaInputs[0]))
        self.assertEqual(failedAxisPlaceholder, summarizer.metaInputs[0][newsFixtures.firstAxis])

    def test_computed_axes_are_saved_when_too_many_axes_fail(self):
        runDate = date.fromisoformat(newsFixtures.runDate)
        axes = list(self.configuration.axes)
        computed = {axes[0]: 'успешная ось'}
        summarizer = StubSummarizer()
        summarizer.axisError = TooManyAxisFailures(
            {axis: 'ошибка' for axis in axes[1:]},
            axis_summaries=computed, usage=Usage(calls=3, total_tokens=123),
        )
        provider = NewsContextProvider(self.configuration, SilentLogger(), summarizer=summarizer)

        with self.assertRaises(TooManyAxisFailures) as raised:
            provider.prepare(runDate)

        self.assertIs(summarizer.axisError, raised.exception)
        self.assertEqual(1, len(summarizer.axisInputs))
        self.assertEqual([], summarizer.metaInputs)
        cache = NewsSummariesCache(self.cachePath)
        self.assertEqual(computed, cache.getAxisSummaries(runDate, newsFixtures.horizonDays, 'test/model'))
        self.assertIsNone(cache.getSummary(runDate, newsFixtures.horizonDays, 'test/model'))

        recovered = StubSummarizer()
        NewsContextProvider(self.configuration, SilentLogger(), summarizer=recovered).prepare(runDate)
        self.assertEqual(1, len(recovered.axisInputs))
        self.assertEqual(axes[1:], list(recovered.axisInputs[0]))
        self.assertEqual(1, len(recovered.metaInputs))
        self.assertEqual(axes, list(recovered.metaInputs[0]))
        self.assertEqual(computed[axes[0]], recovered.metaInputs[0][axes[0]])

    def test_usage_of_both_stages_is_summed(self):
        summarizer = StubSummarizer()
        summarizer.axisUsage = Usage(calls=7, total_tokens=123)
        summarizer.metaUsage = Usage(calls=2, total_tokens=45)
        logger = SilentLogger()
        NewsContextProvider(self.configuration, logger, summarizer=summarizer).prepare(date.fromisoformat(newsFixtures.runDate))

        self.assertIn(
            f'News summary for {newsFixtures.runDate} computed: {len(summarizer.meta)} characters, '
            '9 provider calls, 168 tokens',
            logger.messages,
        )

    def test_failed_date_does_not_land_in_the_summary_cache(self):
        summarizer = StubSummarizer()
        summarizer.metaError = MetaSummaryError(
            axis_summaries={}, failed_axes=[], axis_errors={}, usage=Usage()
        )
        provider = NewsContextProvider(self.configuration, SilentLogger(), summarizer=summarizer)
        runDate = date.fromisoformat(newsFixtures.runDate)

        with self.assertRaises(MetaSummaryError):
            provider.prepare(runDate)

        self.assertEqual(1, len(summarizer.metaInputs))
        self.assertIsNone(
            NewsSummariesCache(self.cachePath).getSummary(runDate, newsFixtures.horizonDays, 'test/model'),
            'Провалившаяся дата не должна попадать в кеш',
        )

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
        summary = NewsSummariesCache(self.cachePath).getSummary(
            runDate, newsFixtures.horizonDays, 'test/model'
        )
        self.assertEqual(('мета', sum(len(docs) for docs in provider.getContext(runDate).documents.values()),
                          (failedAxis,)), summary)

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
