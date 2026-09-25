import json
import os
import shutil
import sqlite3
import sys
import tempfile
from argparse import Namespace
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import AsyncMock, Mock, patch

from amnesiac.exceptions import ConfigurationError, PromptRenderError, SummarizeError
from amnesiac.summarize import (
    AxisSummariesResult,
    MetaResult,
    MetaSummaryError,
    SummarizeConfig,
    TooManyAxisFailures,
    Usage,
)
from amnesiac.summarize.prompts import RU_MACRO_V1

from Logging.BaseLogger import BaseLogger
from NewsLogic import NewsRagConfiguration as newsRagConfiguration
from NewsLogic.NewsContext import NewsContext
from NewsLogic.NewsContextProvider import NewsContextProvider
from NewsLogic.NewsCorpusReader import NewsCorpusReader, queryListHash
from NewsLogic.NewsDocument import NewsDocument
from NewsLogic.newsExceptions import (
    NewsContextError,
    NewsContextNotPreparedError,
    NewsContextUnavailableError,
)
from NewsLogic.newsHelpers import moscowDate, readSecret
from NewsLogic.NewsRagConfiguration import (
    NewsRagConfiguration,
    defaultAxes,
    defaultAxisOrder,
    rawMode,
    twoStageMode,
)
from NewsLogic.NewsRetriever import NewsRetriever
from NewsLogic.newsSectionRenderer import renderNewsSection
from NewsLogic.NewsSummariesCache import NewsSummariesCache
from NewsLogic.NewsSummarizer import NewsSummarizer
from NewsLogic.RunManifest import RunManifest, readCodeEnvironment, readRespondentData
from runMySeriesWithNews import (
    SummarizationCircuitBreakerError,
    prepareContexts,
    runPreflight,
)
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


class TestNewsConfigurationHash(TestCase):
    def test_default_axis_order_is_the_exact_agreed_sequence(self):
        expected = [
            'дкп',
            'инфляция',
            'продовольствие',
            'курс',
            'тарифы',
            'зарплаты',
            'труд',
            'кризис',
            'бюджет',
        ]
        self.assertIsInstance(defaultAxisOrder, tuple)
        self.assertEqual(expected, list(defaultAxisOrder))
        self.assertEqual(expected, list(defaultAxes))
        self.assertEqual(expected, list(NewsRagConfiguration().axes))

    def test_hash_changes_with_axis_order(self):
        configuration = NewsRagConfiguration()
        axes = dict(reversed(list(configuration.axes.items())))
        self.assertNotEqual(
            configuration.configHash(), replace(configuration, axes=axes).configHash()
        )

    def test_hash_changes_with_axis_query_texts(self):
        configuration = NewsRagConfiguration()
        axes = {axis: list(queries) for axis, queries in configuration.axes.items()}
        axes['дкп'][0] += ' изменённый запрос'
        self.assertNotEqual(
            configuration.configHash(), replace(configuration, axes=axes).configHash()
        )

    def test_hash_ignores_dictionary_construction_history_with_the_same_axis_order(self):
        configuration = NewsRagConfiguration()
        reversedAxes = dict(reversed(list(configuration.axes.items())))
        axes = {axis: reversedAxes[axis] for axis in defaultAxisOrder}
        self.assertEqual(configuration.configHash(), replace(configuration, axes=axes).configHash())

    def test_hash_serialization_is_canonical_across_payload_key_order_and_formatting(self):
        configuration = NewsRagConfiguration()
        dumps = json.dumps
        with patch.object(newsRagConfiguration.json, 'dumps', wraps=dumps) as serialize:
            actual = configuration.configHash()
        payload = serialize.call_args.args[0]
        reordered = dict(reversed(list(payload.items())))
        reordered['summarizePromptPack'] = dict(
            reversed(list(reordered['summarizePromptPack'].items()))
        )
        reformatted = json.loads(dumps(reordered, indent=4, ensure_ascii=True))
        canonical = dumps(reformatted, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
        self.assertEqual(sha256(canonical.encode('utf-8')).hexdigest(), actual)
        self.assertEqual(
            [[axis, list(queries)] for axis, queries in configuration.axes.items()], payload['axes']
        )
        self.assertEqual(RU_MACRO_V1.model_dump(exclude={'params'}), payload['summarizePromptPack'])

    def test_hash_changes_with_topKPerAxis(self):
        configuration = NewsRagConfiguration()
        self.assertNotEqual(
            configuration.configHash(), replace(configuration, topKPerAxis=51).configHash()
        )

    def test_hash_changes_with_dedupThreshold(self):
        configuration = NewsRagConfiguration()
        self.assertNotEqual(
            configuration.configHash(), replace(configuration, dedupThreshold=0.8).configHash()
        )

    def test_hash_changes_with_excludeChannels(self):
        configuration = NewsRagConfiguration()
        self.assertNotEqual(
            configuration.configHash(),
            replace(configuration, excludeChannels=('other',)).configHash(),
        )

    def test_hash_changes_with_mode(self):
        configuration = NewsRagConfiguration()
        self.assertNotEqual(
            configuration.configHash(), replace(configuration, mode=rawMode).configHash()
        )

    def test_hash_changes_with_summarizeTemperature(self):
        configuration = NewsRagConfiguration()
        self.assertNotEqual(
            configuration.configHash(),
            replace(configuration, summarizeTemperature=0.5).configHash(),
        )

    def test_hash_changes_with_summarizeMaxFailedAxes(self):
        configuration = NewsRagConfiguration()
        self.assertNotEqual(
            configuration.configHash(),
            replace(configuration, summarizeMaxFailedAxes=1).configHash(),
        )

    def test_hash_changes_with_summarizeBaseUrl(self):
        configuration = NewsRagConfiguration()
        self.assertNotEqual(
            configuration.configHash(),
            replace(configuration, summarizeBaseUrl='https://example.invalid/v1').configHash(),
        )

    def test_hash_changes_with_summarizeProvider(self):
        configuration = NewsRagConfiguration()
        self.assertNotEqual(
            configuration.configHash(),
            replace(configuration, summarizeProvider='other/fp8').configHash(),
        )

    def test_hash_changes_with_windowRule(self):
        configuration = NewsRagConfiguration()
        original = configuration.configHash()
        with patch.object(newsRagConfiguration, 'windowRule', 'different_window_rule'):
            self.assertNotEqual(original, configuration.configHash())

    def test_hash_changes_with_moscowUtcOffsetHours(self):
        configuration = NewsRagConfiguration()
        original = configuration.configHash()
        with patch.object(newsRagConfiguration, 'moscowUtcOffsetHours', 4):
            self.assertNotEqual(original, configuration.configHash())

    def test_hash_changes_with_prompt_pack_name(self):
        configuration = NewsRagConfiguration()
        original = configuration.configHash()
        changed = RU_MACRO_V1.model_copy(update={'name': RU_MACRO_V1.name + ' изменение'})
        with patch.object(newsRagConfiguration, 'RU_MACRO_V1', changed):
            self.assertNotEqual(original, configuration.configHash())

    def test_hash_changes_with_prompt_pack_axis_system(self):
        configuration = NewsRagConfiguration()
        original = configuration.configHash()
        changed = RU_MACRO_V1.model_copy(
            update={'axis_system': RU_MACRO_V1.axis_system + ' изменение'}
        )
        with patch.object(newsRagConfiguration, 'RU_MACRO_V1', changed):
            self.assertNotEqual(original, configuration.configHash())

    def test_hash_changes_with_prompt_pack_axis_user(self):
        configuration = NewsRagConfiguration()
        original = configuration.configHash()
        changed = RU_MACRO_V1.model_copy(update={'axis_user': RU_MACRO_V1.axis_user + ' изменение'})
        with patch.object(newsRagConfiguration, 'RU_MACRO_V1', changed):
            self.assertNotEqual(original, configuration.configHash())

    def test_hash_changes_with_prompt_pack_meta_system(self):
        configuration = NewsRagConfiguration()
        original = configuration.configHash()
        changed = RU_MACRO_V1.model_copy(
            update={'meta_system': RU_MACRO_V1.meta_system + ' изменение'}
        )
        with patch.object(newsRagConfiguration, 'RU_MACRO_V1', changed):
            self.assertNotEqual(original, configuration.configHash())

    def test_hash_changes_with_prompt_pack_meta_user(self):
        configuration = NewsRagConfiguration()
        original = configuration.configHash()
        changed = RU_MACRO_V1.model_copy(update={'meta_user': RU_MACRO_V1.meta_user + ' изменение'})
        with patch.object(newsRagConfiguration, 'RU_MACRO_V1', changed):
            self.assertNotEqual(original, configuration.configHash())

    def test_hash_changes_with_prompt_pack_doc_template(self):
        configuration = NewsRagConfiguration()
        original = configuration.configHash()
        changed = RU_MACRO_V1.model_copy(
            update={'doc_template': RU_MACRO_V1.doc_template + ' изменение'}
        )
        with patch.object(newsRagConfiguration, 'RU_MACRO_V1', changed):
            self.assertNotEqual(original, configuration.configHash())

    def test_hash_changes_with_prompt_pack_doc_separator(self):
        configuration = NewsRagConfiguration()
        original = configuration.configHash()
        changed = RU_MACRO_V1.model_copy(
            update={'doc_separator': RU_MACRO_V1.doc_separator + ' изменение'}
        )
        with patch.object(newsRagConfiguration, 'RU_MACRO_V1', changed):
            self.assertNotEqual(original, configuration.configHash())

    def test_hash_changes_with_prompt_pack_axis_block_template(self):
        configuration = NewsRagConfiguration()
        original = configuration.configHash()
        changed = RU_MACRO_V1.model_copy(
            update={'axis_block_template': RU_MACRO_V1.axis_block_template + ' изменение'}
        )
        with patch.object(newsRagConfiguration, 'RU_MACRO_V1', changed):
            self.assertNotEqual(original, configuration.configHash())

    def test_hash_changes_with_prompt_pack_axis_block_separator(self):
        configuration = NewsRagConfiguration()
        original = configuration.configHash()
        changed = RU_MACRO_V1.model_copy(
            update={'axis_block_separator': RU_MACRO_V1.axis_block_separator + ' изменение'}
        )
        with patch.object(newsRagConfiguration, 'RU_MACRO_V1', changed):
            self.assertNotEqual(original, configuration.configHash())

    def test_hash_ignores_horizonDays(self):
        configuration = NewsRagConfiguration()
        self.assertEqual(
            configuration.configHash(), replace(configuration, horizonDays=7).configHash()
        )

    def test_hash_ignores_summarizeModel(self):
        configuration = NewsRagConfiguration()
        self.assertEqual(
            configuration.configHash(),
            replace(configuration, summarizeModel='other/model').configHash(),
        )

    def test_hash_ignores_summarizeConcurrency(self):
        configuration = NewsRagConfiguration()
        self.assertEqual(
            configuration.configHash(), replace(configuration, summarizeConcurrency=2).configHash()
        )

    def test_hash_ignores_summarizeTimeout(self):
        configuration = NewsRagConfiguration()
        self.assertEqual(
            configuration.configHash(), replace(configuration, summarizeTimeout=123.0).configHash()
        )

    def test_hash_ignores_summarizeApiKeyVariable(self):
        configuration = NewsRagConfiguration()
        self.assertEqual(
            configuration.configHash(),
            replace(configuration, summarizeApiKeyVariable='OTHER_KEY').configHash(),
        )

    def test_hash_ignores_corpusPath(self):
        configuration = NewsRagConfiguration()
        self.assertEqual(
            configuration.configHash(),
            replace(configuration, corpusPath=Path('otherCorpus.db')).configHash(),
        )

    def test_hash_ignores_projectDbPath(self):
        configuration = NewsRagConfiguration()
        self.assertEqual(
            configuration.configHash(),
            replace(configuration, projectDbPath=Path('otherProject.db')).configHash(),
        )

    def test_hash_ignores_artefactsFolder(self):
        configuration = NewsRagConfiguration()
        self.assertEqual(
            configuration.configHash(),
            replace(configuration, artefactsFolder=Path('otherArtefacts')).configHash(),
        )

    def test_hash_ignores_prompt_pack_bound_params(self):
        configuration = NewsRagConfiguration()
        original = configuration.configHash()
        with patch.object(newsRagConfiguration, 'RU_MACRO_V1', RU_MACRO_V1.bind(horizon_days=99)):
            self.assertEqual(original, configuration.configHash())


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

        NewsContextProvider(self.configuration, SilentLogger(), summarizer=summarizer).prepare(
            runDate
        )

        context = NewsContextProvider(
            self.configuration,
            SilentLogger(),
            summarizer=ExplodingSummarizer(),
        ).prepare(runDate)

        self.assertEqual('сохранённое саммари', context.summary)
        self.assertTrue(context.summaryFromCache)

    def test_cached_summary_of_another_config_hash_is_ignored(self):
        cache = NewsSummariesCache(self.cachePath)
        runDate = date.fromisoformat(newsFixtures.runDate)
        cache.saveSummary(runDate, newsFixtures.horizonDays, 'старое', 10, 'test/model', (), 'old')
        self.assertIsNone(cache.getSummary(runDate, newsFixtures.horizonDays, 'test/model', 'new'))
        summarizer = StubSummarizer()
        context = NewsContextProvider(
            self.configuration, SilentLogger(), summarizer=summarizer
        ).prepare(runDate)
        self.assertFalse(context.summaryFromCache)
        self.assertEqual(summarizer.meta, context.summary)

    def test_axis_summaries_of_another_config_hash_are_not_returned(self):
        cache = NewsSummariesCache(self.cachePath)
        runDate = date.fromisoformat(newsFixtures.runDate)
        cached = {axis: 'старое' for axis in self.configuration.axes}
        cache.saveAxisSummaries(runDate, newsFixtures.horizonDays, 'test/model', cached, {}, 'old')
        self.assertEqual(
            {}, cache.getAxisSummaries(runDate, newsFixtures.horizonDays, 'test/model', 'new')
        )
        summarizer = StubSummarizer()
        NewsContextProvider(self.configuration, SilentLogger(), summarizer=summarizer).prepare(
            runDate
        )
        self.assertEqual(list(self.configuration.axes), list(summarizer.axisInputs[0]))

    def test_both_cache_tables_round_trip_with_the_same_config_hash(self):
        cache = NewsSummariesCache(self.cachePath)
        runDate = date.fromisoformat(newsFixtures.runDate)
        configHash = self.configuration.configHash()
        cache.saveSummary(
            runDate, newsFixtures.horizonDays, 'мета', 10, 'test/model', ('курс',), configHash
        )
        cache.saveAxisSummaries(
            runDate, newsFixtures.horizonDays, 'test/model', {'дкп': 'ось'}, {'дкп': 4}, configHash
        )
        self.assertEqual(
            ('мета', 10, ('курс',)),
            cache.getSummary(runDate, newsFixtures.horizonDays, 'test/model', configHash),
        )
        self.assertEqual(
            {'дкп': 'ось'},
            cache.getAxisSummaries(runDate, newsFixtures.horizonDays, 'test/model', configHash),
        )
        with sqlite3.connect(self.cachePath) as connection:
            for table in ('summaries', 'axis_summaries'):
                self.assertEqual(
                    (configHash,), connection.execute(f'SELECT config_hash FROM {table}').fetchone()
                )

    def test_migration_015_adds_nullable_hash_columns_to_both_tables(self):
        path = self.folder / 'apply015.db'
        newsFixtures.createProjectDbFixture(path, withConfigHash=False)
        migration = Path('../data/newsDB/migrations/015_summaries_config_hash.sql').read_text()
        with sqlite3.connect(path) as connection:
            connection.executescript(migration)
            for table in ('summaries', 'axis_summaries'):
                columns = {row[1]: row for row in connection.execute(f'PRAGMA table_info({table})')}
                self.assertEqual(('TEXT', 0, None), columns['config_hash'][2:5])
            with self.assertRaisesRegex(sqlite3.OperationalError, 'duplicate column'):
                connection.executescript(migration)

    def test_null_config_hash_is_a_miss_in_both_tables(self):
        cache = NewsSummariesCache(self.cachePath)
        runDate = date.fromisoformat(newsFixtures.runDate)
        configHash = self.configuration.configHash()
        cache.saveSummary(runDate, newsFixtures.horizonDays, 'мета', 1, 'test/model', (), configHash)
        cache.saveAxisSummaries(
            runDate, newsFixtures.horizonDays, 'test/model', {'дкп': 'ось'}, {}, configHash
        )
        with sqlite3.connect(self.cachePath) as connection:
            connection.execute('UPDATE summaries SET config_hash = NULL')
            connection.execute('UPDATE axis_summaries SET config_hash = NULL')
        self.assertIsNone(cache.getSummary(runDate, newsFixtures.horizonDays, 'test/model', configHash))
        self.assertEqual({}, cache.getAxisSummaries(runDate, newsFixtures.horizonDays, 'test/model', configHash))

    def test_database_without_015_is_reported_instead_of_being_used(self):
        path = self.folder / 'without015.db'
        newsFixtures.createProjectDbFixture(path, withConfigHash=False)
        with self.assertRaisesRegex(NewsContextError, '015_summaries_config_hash.sql'):
            NewsSummariesCache(path).getSummary(date(2022, 3, 25), 14, 'test/model', 'hash')

    def test_database_without_axis_config_hash_is_reported(self):
        path = self.folder / 'withoutAxis015.db'
        newsFixtures.createProjectDbFixture(path, withConfigHash=False)
        with sqlite3.connect(path) as connection:
            connection.execute('ALTER TABLE summaries ADD COLUMN config_hash TEXT')
        with self.assertRaisesRegex(
            NewsContextError, 'axis_summaries.*015_summaries_config_hash.sql'
        ):
            NewsSummariesCache(path).getAxisSummaries(date(2022, 3, 25), 14, 'test/model', 'hash')

    def test_cached_summary_of_another_horizon_is_ignored(self):
        cache = NewsSummariesCache(self.cachePath)
        runDate = date.fromisoformat(newsFixtures.runDate)
        cache.saveSummary(runDate, newsFixtures.horizonDays + 1, 'чужой горизонт', 10, 'test/model', (), configHash=self.configuration.configHash())

        self.assertIsNone(cache.getSummary(runDate, newsFixtures.horizonDays, 'test/model', configHash=self.configuration.configHash()))

    def test_cached_summary_of_another_model_is_ignored(self):
        cache = NewsSummariesCache(self.cachePath)
        runDate = date.fromisoformat(newsFixtures.runDate)
        cache.saveSummary(runDate, newsFixtures.horizonDays, 'чужая модель', 10, 'other/model', (), configHash=self.configuration.configHash())

        self.assertIsNone(cache.getSummary(runDate, newsFixtures.horizonDays, 'test/model', configHash=self.configuration.configHash()))

    def test_failed_axes_survive_a_round_trip_through_the_cache(self):
        cache = NewsSummariesCache(self.cachePath)
        runDate = date.fromisoformat(newsFixtures.runDate)
        cache.saveSummary(runDate, newsFixtures.horizonDays, 'неполное саммари', 10, 'test/model', ('курс', 'дкп'), configHash=self.configuration.configHash())

        summary, documentsCount, failedAxes = cache.getSummary(
            runDate, newsFixtures.horizonDays, 'test/model', configHash=self.configuration.configHash()
        )

        self.assertEqual('неполное саммари', summary)
        self.assertEqual(10, documentsCount)
        self.assertEqual(('курс', 'дкп'), failedAxes)

    def test_no_failed_axes_is_stored_as_empty_list_not_as_unknown(self):
        cache = NewsSummariesCache(self.cachePath)
        runDate = date.fromisoformat(newsFixtures.runDate)
        cache.saveSummary(runDate, newsFixtures.horizonDays, 'полное саммари', 10, 'test/model', (), configHash=self.configuration.configHash())

        self.assertEqual((), cache.getSummary(runDate, newsFixtures.horizonDays, 'test/model', configHash=self.configuration.configHash())[2])

        stored = sqlite3.connect(str(self.cachePath)).execute(
            'SELECT failed_axes FROM summaries WHERE run_date = ?', (runDate.isoformat(),)
        ).fetchone()[0]
        self.assertEqual('[]', stored)

    def test_legacy_row_without_failed_axes_reports_unknown_rather_than_none_failed(self):
        runDate = date.fromisoformat(newsFixtures.runDate)
        connection = sqlite3.connect(str(self.cachePath))
        connection.execute(
            """
            INSERT INTO summaries (run_date, horizon_days, summary, doc_count, model, failed_axes, config_hash)
            VALUES (?, ?, ?, ?, ?, NULL, ?)
            """,
            (runDate.isoformat(), newsFixtures.horizonDays, 'саммари из blind_prophet', 10, 'test/model', self.configuration.configHash()),
        )
        connection.commit()
        connection.close()

        failedAxes = NewsSummariesCache(self.cachePath).getSummary(
            runDate, newsFixtures.horizonDays, 'test/model', configHash=self.configuration.configHash()
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
            INSERT INTO summaries (run_date, horizon_days, summary, doc_count, model, failed_axes, config_hash)
            VALUES (?, ?, ?, ?, ?, NULL, ?)
            """,
            (runDate.isoformat(), newsFixtures.horizonDays, 'старое саммари', 10, 'test/model', self.configuration.configHash()),
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
        configHash = self.configuration.configHash()

        class InspectingSummarizer(StubSummarizer):
            async def buildMetaSummary(self, axisSummaries):
                storedAtMeta.update(
                    cache.getAxisSummaries(runDate, newsFixtures.horizonDays, 'test/model', configHash=configHash)
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
            cache.getAxisSummaries(runDate, newsFixtures.horizonDays, 'test/model', configHash=self.configuration.configHash()),
        )
        self.assertIsNone(cache.getSummary(runDate, newsFixtures.horizonDays, 'test/model', configHash=self.configuration.configHash()))

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
            {secondAxis: 'из кеша'}, {secondAxis: 1}, configHash=self.configuration.configHash(),
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
            {secondAxis: 'из кеша'}, {secondAxis: 1}, configHash=self.configuration.configHash(),
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
            cached, {axis: len(documents) for axis, documents in retrieved.items()}, configHash=self.configuration.configHash(),
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
        self.assertEqual(computed, cache.getAxisSummaries(runDate, newsFixtures.horizonDays, 'test/model', configHash=self.configuration.configHash()))
        self.assertIsNone(cache.getSummary(runDate, newsFixtures.horizonDays, 'test/model', configHash=self.configuration.configHash()))

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
            NewsSummariesCache(self.cachePath).getSummary(runDate, newsFixtures.horizonDays, 'test/model', configHash=self.configuration.configHash()),
            'Провалившаяся дата не должна попадать в кеш',
        )

    def test_axis_summaries_are_stored_for_every_successful_axis(self):
        provider = NewsContextProvider(self.configuration, SilentLogger(),
                                       summarizer=StubSummarizer('мета'))
        runDate = date.fromisoformat(newsFixtures.runDate)
        provider.prepare(runDate)

        stored = NewsSummariesCache(self.cachePath).getAxisSummaries(
            runDate, newsFixtures.horizonDays, 'test/model', configHash=self.configuration.configHash()
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
            runDate, newsFixtures.horizonDays, 'test/model', configHash=self.configuration.configHash()
        )

        self.assertNotIn(failedAxis, stored)
        self.assertNotIn(failedAxisPlaceholder, stored.values())
        self.assertEqual(len(self.configuration.axes) - 1, len(stored))
        summary = NewsSummariesCache(self.cachePath).getSummary(
            runDate, newsFixtures.horizonDays, 'test/model', configHash=self.configuration.configHash()
        )
        self.assertEqual(('мета', sum(len(docs) for docs in provider.getContext(runDate).documents.values()),
                          (failedAxis,)), summary)

    def test_axis_summaries_of_another_horizon_or_model_are_not_returned(self):
        cache = NewsSummariesCache(self.cachePath)
        runDate = date.fromisoformat(newsFixtures.runDate)
        cache.saveAxisSummaries(runDate, newsFixtures.horizonDays, 'test/model',
                                {'курс': 'саммари'}, {'курс': 5}, configHash=self.configuration.configHash())

        self.assertEqual({'курс': 'саммари'},
                         cache.getAxisSummaries(runDate, newsFixtures.horizonDays, 'test/model', configHash=self.configuration.configHash()))
        self.assertEqual({}, cache.getAxisSummaries(runDate, newsFixtures.horizonDays + 1, 'test/model', configHash=self.configuration.configHash()))
        self.assertEqual({}, cache.getAxisSummaries(runDate, newsFixtures.horizonDays, 'other/model', configHash=self.configuration.configHash()))

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
            NewsSummariesCache(legacyPath).getSummary(runDate, newsFixtures.horizonDays, 'test/model', configHash=self.configuration.configHash())

        self.assertIn('axis_summaries', str(raised.exception))
        self.assertIn('013_axis_summaries.sql', str(raised.exception))

    def test_database_without_the_migration_is_reported_instead_of_being_used(self):
        legacyPath = self.folder / f'legacy_{self.id()}.db'
        newsFixtures.createProjectDbFixture(legacyPath, withFailedAxes=False)
        runDate = date.fromisoformat(newsFixtures.runDate)

        with self.assertRaises(NewsContextError) as raised:
            NewsSummariesCache(legacyPath).getSummary(runDate, newsFixtures.horizonDays, 'test/model', configHash=self.configuration.configHash())

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
                    INSERT INTO summaries (run_date, horizon_days, summary, doc_count, model, failed_axes, config_hash)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (runDate.isoformat(), newsFixtures.horizonDays, 'саммари', 10, 'test/model', stored, self.configuration.configHash()),
                )
                connection.commit()
                connection.close()

                with self.assertRaises(NewsContextError):
                    NewsSummariesCache(path).getSummary(runDate, newsFixtures.horizonDays, 'test/model', configHash=self.configuration.configHash())

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


class TestRunManifest(NewsFixtureTestCase):
    def setUp(self):
        self.runFolder = self.folder / self.id()
        self.configuration = self.createConfiguration(mode=twoStageMode)
        self.startedAt = datetime(2026, 9, 22, 10, 11, 12, 123456, tzinfo=UTC)
        self.firstDate = date(2022, 3, 25)
        self.nextDate = self.firstDate + timedelta(days=1)

    def createManifest(self, startedAt=None):
        return RunManifest(
            'dry-construction', self.configuration, 'fixture/respondent',
            'https://respondent.invalid/v1', self.runFolder / 'results',
            self.runFolder / 'manifests', startedAt or self.startedAt,
        )

    def createProvider(self, outcomes):
        context = SimpleNamespace(summary='саммари', summaryFromCache=True,
                                  documentsCount=3, failedAxes=())
        return SimpleNamespace(
            prepare=Mock(side_effect=[context if value is None else value for value in outcomes]),
            usageByDate={}, usageCompleteByDate={},
        )

    def test_manifest_sections_and_shared_hash_sources(self):
        manifest = self.createManifest()
        self.assertEqual(self.configuration.configHash(), manifest.data['news_rag']['config_hash'])
        with patch.object(NewsRagConfiguration, 'configHash', return_value='cache-key-sentinel'):
            self.assertEqual('cache-key-sentinel',
                             self.createManifest().data['news_rag']['config_hash'])
        for section in ('code_environment', 'corpus', 'news_rag', 'models',
                        'prompt', 'respondent_data', 'totals'):
            self.assertIn(section, manifest.data)
        self.assertEqual(list(self.configuration.axes), manifest.data['news_rag']['axis_order'])
        self.assertEqual(
            {axis: queryListHash(texts) for axis, texts in self.configuration.axes.items()},
            manifest.data['news_rag']['query_hash'],
        )
        self.assertEqual(newsRagConfiguration.windowRule,
                         manifest.data['news_rag']['timezone_rule'])
        self.assertEqual(3, manifest.data['news_rag']['utc_offset_hours'])
        self.assertEqual(SummarizeConfig().model_dump(mode='json'),
                         manifest.data['models']['summarization']['SummarizeConfig'])
        self.assertEqual(self.configuration.summarizeProvider,
                         manifest.data['models']['summarization']['configured_provider'])
        self.assertIsNone(manifest.data['models']['summarization']['provider_pin_verification'])
        self.assertEqual('not_checked', manifest.data['models']['summarization']
                         ['provider_pin_verification_status'])

    def test_collect_inputs_uses_reader_and_records_wave_hashes(self):
        manifest = self.createManifest()
        code = {'commit': 'fixture-commit', 'dirty': True, 'branch': 'fixture',
                'amnesiac': {'tag': 'fixture-tag', 'commit': 'fixture-library-commit'}}
        respondentData = {'seed42_verification': None}
        with (patch('NewsLogic.RunManifest.readCodeEnvironment', return_value=code),
              patch('NewsLogic.RunManifest.readRespondentData', return_value=respondentData)):
            manifest.collectInputs(self.configuration, self.runFolder, 7)
        with NewsCorpusReader(self.corpusPath) as reader:
            self.assertEqual(reader.getCorpusManifest(), manifest.data['corpus'])
        self.assertEqual('fixture-commit', manifest.data['code_environment']['commit'])
        self.assertTrue(manifest.data['code_environment']['dirty'])
        self.assertEqual(self.startedAt.isoformat(),
                         manifest.data['code_environment']['started_at_utc'])
        self.assertEqual(respondentData, manifest.data['respondent_data'])
        self.runFolder.mkdir(parents=True)
        (self.runFolder / 'wave.zip').write_bytes(b'fixture-wave')
        result = readRespondentData(self.runFolder, self.runFolder / 'absent', 7)
        self.assertEqual({str(self.runFolder / 'wave.zip'): sha256(b'fixture-wave').hexdigest()},
                         result['wave_sha256'])
        self.assertEqual(7, result['profiles_per_date'])
        self.assertIsNone(result['seed42_verification'])
        self.assertIsNone(result['extractor_commit'])
        self.assertEqual(result['extractor_seed'], 42)

    def test_code_environment_does_not_copy_installation_url(self):
        installed = {'vcs_info': {'requested_revision': 'v0.fixture', 'commit_id': 'abc'},
                     'url': 'https://secret:password@invalid/repo'}
        with (patch('NewsLogic.RunManifest.subprocess.check_output',
                    side_effect=['head\n', 'branch\n', ' M changed.py\n']) as command,
              patch('NewsLogic.RunManifest.distribution') as package):
            package.return_value.read_text.return_value = json.dumps(installed)
            result = readCodeEnvironment(Path('.'))
        self.assertEqual({'commit': 'head', 'branch': 'branch', 'dirty': True,
                          'amnesiac': {'tag': 'v0.fixture', 'commit': 'abc'}}, result)
        self.assertEqual(3, command.call_count)
        self.assertNotIn('password', json.dumps(result))

    def test_prompt_composition_is_read_from_builder(self):
        manifest = self.createManifest()
        builder = SimpleNamespace(builders=[SimpleNamespace(), Mock()],
                                  headers=['Основные параметры опроса и респондента',
                                           'Новости', 'Задача'])
        manifest.recordPrompt(SimpleNamespace(), builder)
        self.assertEqual(['SimpleNamespace', 'Mock'], manifest.data['prompt']['composition'])
        self.assertEqual(builder.headers, manifest.data['prompt']['section_headers'])
        self.assertIn('D-018', manifest.data['prompt']['experiments_configuration_note'])

    def test_summarization_failure_is_recorded_and_following_date_runs(self):
        manifest = self.createManifest()
        provider = self.createProvider([SummarizeError('empty'), None])
        logger = SilentLogger()
        with manifest:
            prepared = prepareContexts([self.firstDate, self.nextDate], provider, manifest, logger)
        self.assertEqual([self.nextDate], prepared)
        self.assertEqual([self.nextDate.isoformat()], manifest.data['totals']['dates_computed'])
        self.assertEqual([{'date': self.firstDate.isoformat(),
                           'reason': 'SummarizeError: суммаризация даты завершилась отказом'}],
                         manifest.data['totals']['dates_skipped'])
        self.assertEqual(1, manifest.data['totals']['skipped_count'])
        self.assertEqual(2, provider.prepare.call_count)
        self.assertIn('SKIPPED', logger.messages[0])
        self.assertEqual('completed_with_skips',
                         json.loads(manifest.path.read_text())['totals']['status'])

    def test_uncovered_date_is_skipped_with_reason(self):
        manifest = self.createManifest()
        provider = self.createProvider([NewsContextUnavailableError('outside'), None])
        prepared = prepareContexts([self.firstDate, self.nextDate], provider,
                                   manifest, SilentLogger())
        self.assertEqual([self.nextDate], prepared)
        self.assertEqual('NewsContextUnavailableError: окно вне покрытия корпуса',
                         manifest.data['totals']['dates_skipped'][0]['reason'])

    def test_fatal_errors_propagate_and_partial_manifest_is_written(self):
        errors = [NewsContextError('empty window'), ConfigurationError('configuration'),
                  PromptRenderError('render'),
                  TypeError('SECRET-programming-error'),
                  AttributeError('SECRET-attribute'), KeyError('SECRET-key'),
                  KeyboardInterrupt()]
        for index, error in enumerate(errors):
            manifest = self.createManifest(self.startedAt + timedelta(seconds=index))
            provider = self.createProvider([None, error, None])
            with self.assertRaises(type(error)), manifest:
                prepareContexts([self.firstDate, self.nextDate, self.nextDate + timedelta(days=1)],
                                provider, manifest, SilentLogger())
            written = json.loads(manifest.path.read_text())
            self.assertEqual('aborted', written['totals']['status'])
            self.assertEqual(type(error).__name__, written['totals']['abort_type'])
            self.assertEqual([self.firstDate.isoformat()], written['totals']['dates_computed'])
            self.assertEqual([], written['totals']['dates_skipped'])
            self.assertEqual(2, provider.prepare.call_count)
            self.assertNotIn('SECRET', manifest.path.read_text())

    def test_same_provider_failure_has_symmetric_axis_and_meta_outcomes(self):
        from openai import APIConnectionError

        secret = 'SECRET-provider-response'
        providerError = APIConnectionError(message=secret, request=Mock())
        axisError = TooManyAxisFailures({'дкп': repr(providerError)})
        outcomes = []
        for index, (error, stage) in enumerate(((axisError, 'axis'), (providerError, 'meta'))):
            manifest = self.createManifest(self.startedAt + timedelta(seconds=index))
            provider = self.createProvider([error, None])
            logger = SilentLogger()
            with manifest:
                prepared = prepareContexts([self.firstDate, self.nextDate], provider,
                                           manifest, logger)
            written = json.loads(manifest.path.read_text())
            totals = written['totals']
            reason = totals['dates_skipped'][0]['reason']
            self.assertIn(type(error).__name__, reason)
            self.assertIn(f'stage={stage}', reason)
            self.assertIn(reason, logger.messages[0])
            self.assertNotIn(secret, manifest.path.read_text())
            self.assertNotIn(repr(error), manifest.path.read_text())
            self.assertNotIn(secret, '\n'.join(logger.messages))
            outcomes.append((prepared, totals['status'], totals['skipped_count'],
                             [entry['date'] for entry in totals['dates_skipped']],
                             totals['dates_computed'], provider.prepare.call_count))
        self.assertEqual(outcomes[0], outcomes[1])
        self.assertEqual(([self.nextDate], 'completed_with_skips', 1,
                          [self.firstDate.isoformat()], [self.nextDate.isoformat()], 2),
                         outcomes[0])

        # Одинаковый отказ на любой стадии продвигает общий счётчик до трёх.
        breakerOutcomes = []
        dates = [self.firstDate + timedelta(days=index) for index in range(4)]
        for index, errors in enumerate(((axisError, providerError, axisError),
                                        (providerError, axisError, providerError))):
            manifest = self.createManifest(self.startedAt + timedelta(seconds=index + 2))
            provider = self.createProvider([*errors, None])
            with self.assertRaises(SummarizationCircuitBreakerError), manifest:
                prepareContexts(dates, provider, manifest, SilentLogger())
            totals = json.loads(manifest.path.read_text())['totals']
            breakerOutcomes.append((totals['status'], totals['abort_type'],
                                    totals['circuit_breaker']['dates'], totals['skipped_count'],
                                    totals['dates_computed'], provider.prepare.call_count))
            for error, entry in zip(errors, totals['dates_skipped'], strict=True):
                stage = 'axis' if isinstance(error, TooManyAxisFailures) else 'meta'
                self.assertIn(type(error).__name__, entry['reason'])
                self.assertIn(f'stage={stage}', entry['reason'])
            self.assertNotIn(secret, manifest.path.read_text())
        self.assertEqual(breakerOutcomes[0], breakerOutcomes[1])
        self.assertEqual(('aborted', 'SummarizationCircuitBreakerError',
                          [day.isoformat() for day in dates[:3]], 3, [], 3), breakerOutcomes[0])

    def test_api_error_subclasses_skip_without_response_text(self):
        from openai import (
            APIError,
            APIStatusError,
            APITimeoutError,
            InternalServerError,
            PermissionDeniedError,
            RateLimitError,
        )

        secret = 'SECRET-provider-response'
        errors = [APIError(secret, request=Mock(), body=None),
                  APITimeoutError(request=Mock())]
        for errorClass, status in ((APIStatusError, 400), (PermissionDeniedError, 403),
                                   (RateLimitError, 429), (InternalServerError, 500)):
            errors.append(errorClass(secret, response=Mock(status_code=status), body=secret))
        for index, error in enumerate(errors):
            manifest = self.createManifest(self.startedAt + timedelta(seconds=index))
            provider = self.createProvider([error, None])
            with manifest:
                self.assertEqual([self.nextDate], prepareContexts(
                    [self.firstDate, self.nextDate], provider, manifest, SilentLogger()))
            written = json.loads(manifest.path.read_text())
            self.assertEqual(f'{type(error).__name__}: ошибка провайдера; stage=meta',
                             written['totals']['dates_skipped'][0]['reason'])
            self.assertNotIn(secret, manifest.path.read_text())
            self.assertNotIn(str(error), manifest.path.read_text())
            self.assertNotIn(repr(error), manifest.path.read_text())

    def test_run_ids_and_back_references_do_not_overwrite(self):
        first = self.createManifest()
        second = self.createManifest(self.startedAt + timedelta(microseconds=1))
        first.write()
        original = first.path.read_bytes()
        second.write()
        self.assertNotEqual(first.runId, second.runId)
        self.assertLess(first.runId, second.runId)
        self.assertEqual(original, first.path.read_bytes())
        self.assertTrue(second.path.exists())
        for manifest in (first, second):
            reference = json.loads((manifest.resultsFolder /
                                    f'run_manifest_{manifest.runId}.json').read_text())
            self.assertEqual(manifest.runId, reference['run_id'])
            self.assertEqual(manifest.path.resolve(), Path(reference['manifest_path']))
        duplicate = self.createManifest()
        duplicate.data['totals']['abort_type'] = 'must-not-overwrite'
        with self.assertRaises(FileExistsError):
            duplicate.write()
        self.assertEqual(original, first.path.read_bytes())

    def test_secret_values_never_enter_rendered_manifest(self):
        secret = 'test-secret-value-do-not-record'
        with patch.dict(os.environ, {'OPENROUTER_API_KEY': secret}):
            manifest = self.createManifest()
            provider = self.createProvider([SummarizeError(secret), None])
            with manifest:
                prepareContexts([self.firstDate, self.nextDate], provider, manifest, SilentLogger())
        rendered = manifest.path.read_text()
        self.assertNotIn(secret, rendered)
        self.assertNotIn(sha256(secret.encode()).hexdigest(), rendered)
        self.assertNotIn('.env', rendered)
        self.assertIn('OPENROUTER_API_KEY', rendered)


    def test_main_writes_manifest_on_abort_and_contexts_only_return(self):
        import runMySeriesWithNews as seriesRunner

        cases = [(None, None), (NewsContextError('empty window'), None),
                 (None, RuntimeError('SECRET-preflight'))]
        for index, (error, preflightError) in enumerate(cases):
            manifest = self.createManifest(self.startedAt + timedelta(seconds=index))
            provider = self.createProvider([None, error])
            provider.configuration = self.configuration
            provider.summarizer = SimpleNamespace(preflight=AsyncMock(return_value=SimpleNamespace(
                usage=None, choices=[SimpleNamespace(message=SimpleNamespace(content='OK'))],
            ), side_effect=preflightError))
            builder = SimpleNamespace(builders=[], headers=['Новости'])
            config = SimpleNamespace(bothub_key='unused-test-key', bothubUrl='https://invalid')
            factory = SimpleNamespace(createNewsPromptBuilder=Mock(return_value=(builder, builder)))
            helpers = SimpleNamespace(copyPromptTemplatesToFolder=Mock(), createAsyncSurveyRunner=Mock())
            modules = {
                'Configuration': SimpleNamespace(configuration=config),
                'Configuration.configuration': config,
                'SurveyLogic.PromptBuilders.profileBuildersHelpers': factory,
                'SurveyLogic.surveyHelpers': helpers,
            }
            manifest.path.parent.mkdir(parents=True, exist_ok=True)
            manifest.resultsFolder.mkdir(parents=True, exist_ok=True)
            arguments = Namespace(horizon=14, experiment='test-main', model='fixture', profiles=7,
                                  dates=Path('fixture-dates'), contexts_only=True,
                                  allow_horizon_overwrite=False)
            with (patch.dict(sys.modules, modules),
                  patch.object(seriesRunner, 'RunManifest', return_value=manifest),
                  patch.object(manifest, 'collectInputs'),
                  patch.object(seriesRunner, 'NewsContextProvider', return_value=provider),
                  patch.object(seriesRunner, 'SimpleLogger', return_value=SilentLogger()),
                  patch.object(seriesRunner, 'readRunDates', return_value=[self.firstDate, self.nextDate]),
                  patch.object(seriesRunner, 'splitByCoverage',
                               return_value=([self.firstDate, self.nextDate], [])),
                  patch.object(seriesRunner, 'findHorizonConflicts', return_value=[]),
                  patch.object(Path, 'mkdir')):
                if error is None and preflightError is None:
                    seriesRunner.main(arguments)
                else:
                    with self.assertRaises(type(error or preflightError)):
                        seriesRunner.main(arguments)
            written = json.loads(manifest.path.read_text())
            self.assertEqual('completed' if error is None and preflightError is None else 'aborted',
                             written['totals']['status'])
            expectedCount = 0 if preflightError else (2 if error is None else 1)
            self.assertEqual(expectedCount, len(written['totals']['dates_computed']))
            if preflightError:
                provider.prepare.assert_not_called()
                self.assertEqual('failed', written['preflight']['outcome'])
                self.assertNotIn('SECRET-preflight', manifest.path.read_text())
            helpers.createAsyncSurveyRunner.assert_not_called()
            provider.summarizer.preflight.assert_awaited_once()

    def test_provider_axis_failures_are_wrapped_and_trip_breaker_on_third_date(self):
        from openai import PermissionDeniedError

        configuration = replace(self.configuration, summarizeMaxFailedAxes=0)
        summarizer = NewsSummarizer(configuration, SilentLogger())
        secret = 'SECRET-provider-response'
        create = AsyncMock(side_effect=PermissionDeniedError(
            secret, response=Mock(status_code=403), body=None,
        ))
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        retrieved = {
            axis: [NewsDocument(1, 'fixture', '2022-03-24T12:00:00+00:00',
                               1, 'Цены растут.', axis, 1, 0.9)]
            for axis in configuration.axes
        }
        cache = Mock()
        cache.getSummary.return_value = None
        cache.getAxisSummaries.return_value = {}
        retriever = Mock()
        retriever.retrieve.return_value = retrieved
        retriever.getWindow.return_value = (self.firstDate - timedelta(days=14), self.firstDate)
        provider = NewsContextProvider(configuration, SilentLogger(), retriever=retriever,
                                       summarizer=summarizer, summariesCache=cache)
        dates = [self.firstDate + timedelta(days=index) for index in range(4)]
        manifest = self.createManifest()
        with (patch.object(summarizer, '_createClient', return_value=client),
              self.assertRaises(SummarizationCircuitBreakerError), manifest):
            prepareContexts(dates, provider, manifest, SilentLogger())
        written = json.loads(manifest.path.read_text())
        self.assertEqual('aborted', written['totals']['status'])
        self.assertEqual([day.isoformat() for day in dates[:3]],
                         written['totals']['circuit_breaker']['dates'])
        self.assertEqual('Три последовательных отказа суммаризации',
                         written['totals']['circuit_breaker']['reason'])
        self.assertEqual(3, retriever.retrieve.call_count)
        self.assertEqual(3 * len(configuration.axes), create.await_count)
        self.assertEqual(3, written['totals']['skipped_count'])
        self.assertEqual([], written['totals']['dates_computed'])
        for entry in written['totals']['dates_skipped']:
            self.assertEqual(
                'TooManyAxisFailures: суммаризация даты завершилась отказом; stage=axis; '
                f'failed_axes={sorted(configuration.axes)}', entry['reason'],
            )
        self.assertNotIn(secret, manifest.path.read_text())
        self.assertNotIn('PermissionDeniedError', manifest.path.read_text())

    def test_breaker_resets_only_after_success_and_ignores_coverage(self):
        failure = TooManyAxisFailures({'курс': 'SECRET', 'дкп': 'SECRET', 'труд': 'SECRET'})
        coverage = NewsContextUnavailableError('outside')
        computed = SimpleNamespace(summary='саммари', summaryFromCache=False,
                                   documentsCount=3, failedAxes=())
        outcomes = [failure, failure, computed, coverage, coverage, coverage,
                    failure, coverage, failure, computed]
        dates = [self.firstDate + timedelta(days=index) for index in range(len(outcomes))]
        manifest = self.createManifest()
        provider = self.createProvider(outcomes)
        with manifest:
            prepared = prepareContexts(dates, provider, manifest, SilentLogger())
        self.assertEqual([dates[2], dates[9]], prepared)
        self.assertEqual(len(dates), provider.prepare.call_count)
        self.assertEqual('completed_with_skips', manifest.data['totals']['status'])
        self.assertNotIn('circuit_breaker', manifest.data['totals'])
        self.assertNotIn('SECRET', manifest.path.read_text())
        self.assertEqual(
            "TooManyAxisFailures: суммаризация даты завершилась отказом; stage=axis; "
            "failed_axes=['дкп', 'курс', 'труд']",
            manifest.data['totals']['dates_skipped'][0]['reason'],
        )

    def test_all_covered_dates_skipped_still_write_manifest_and_reference(self):
        for index, error in enumerate((NewsContextUnavailableError('window'),
                                       SummarizeError('summary'))):
            manifest = self.createManifest(self.startedAt + timedelta(seconds=index))
            provider = self.createProvider([error, error])
            with manifest:
                self.assertEqual([], prepareContexts(
                    [self.firstDate, self.nextDate], provider, manifest, SilentLogger()))
            self.assertTrue(manifest.path.exists())
            written = json.loads(manifest.path.read_text())
            self.assertEqual('completed_with_skips', written['totals']['status'])
            self.assertEqual([], written['totals']['dates_computed'])
            self.assertEqual(2, written['totals']['skipped_count'])
            self.assertEqual([self.firstDate.isoformat(), self.nextDate.isoformat()],
                             [entry['date'] for entry in written['totals']['dates_skipped']])
            for entry in written['totals']['dates_skipped']:
                self.assertIn(type(error).__name__, entry['reason'])
                self.assertTrue(entry['reason'].split(': ')[1])
            reference = json.loads((manifest.resultsFolder /
                                    f'run_manifest_{manifest.runId}.json').read_text())
            self.assertEqual(str(manifest.path.resolve()), reference['manifest_path'])
            self.assertEqual(0, written['totals']['degraded_dates_count'])
            self.assertEqual(0, written['totals']['unknown_degradation_dates_count'])

    def test_manifest_write_failure_preserves_original_exception(self):
        manifest = self.createManifest()
        original = RuntimeError('original')
        with (patch.object(manifest, 'write', side_effect=ValueError('assembly')),
              self.assertRaises(RuntimeError) as caught, manifest):
            raise original
        self.assertIs(original, caught.exception)
        self.assertEqual(['Манифест не записан: ValueError'], original.__notes__)
        with (patch.object(manifest, 'write', side_effect=ValueError('assembly')),
              self.assertRaisesRegex(ValueError, 'assembly'), manifest):
            pass

    def test_cache_hit_does_not_reset_breaker(self):
        failure = SummarizeError('failure')
        provider = self.createProvider([failure, failure, None, failure, None])
        dates = [self.firstDate + timedelta(days=index) for index in range(5)]
        manifest = self.createManifest()
        with self.assertRaises(SummarizationCircuitBreakerError), manifest:
            prepareContexts(dates, provider, manifest, SilentLogger())
        self.assertEqual(4, provider.prepare.call_count)
        self.assertEqual([dates[index].isoformat() for index in (0, 1, 3)],
                         manifest.data['totals']['circuit_breaker']['dates'])

    def test_preflight_records_served_provider_and_rejects_mismatch(self):
        from openai.types.chat import ChatCompletion

        for index, servedProvider in enumerate((self.configuration.summarizeProvider,
                                                None, 'other/provider')):
            responseData = {'id': 'fixture', 'object': 'chat.completion', 'created': 0,
                            'model': 'fixture', 'choices': []}
            if servedProvider is not None:
                responseData['provider'] = servedProvider
            response = ChatCompletion(**responseData)
            provider = self.createProvider([None])
            provider.configuration = self.configuration
            provider.summarizer = SimpleNamespace(preflight=AsyncMock(return_value=response))
            manifest = self.createManifest(self.startedAt + timedelta(seconds=index))
            if servedProvider == 'other/provider':
                with self.assertRaisesRegex(RuntimeError, 'несовпадение'), manifest:
                    runPreflight(provider, manifest)
                    prepareContexts([self.firstDate], provider, manifest, SilentLogger())
                provider.prepare.assert_not_called()
            else:
                with manifest:
                    runPreflight(provider, manifest)
                    prepareContexts([self.firstDate], provider, manifest, SilentLogger())
                provider.prepare.assert_called_once()
            written = json.loads(manifest.path.read_text())
            self.assertEqual(servedProvider,
                             written['models']['summarization']['provider_pin_verification'])
            self.assertEqual(('verified', 'not_reported', 'mismatch')[index],
                             written['models']['summarization']['provider_pin_verification_status'])
            self.assertEqual('failed' if index == 2 else 'succeeded',
                             written['preflight']['outcome'])
            self.assertEqual('aborted' if index == 2 else 'completed',
                             written['totals']['status'])

    def test_preflight_transport_and_auth_fail_before_dates(self):
        from openai import APIConnectionError, AuthenticationError

        errors = [APIConnectionError(request=Mock()),
                  AuthenticationError('SECRET', response=Mock(status_code=401), body=None)]
        for index, error in enumerate(errors):
            provider = self.createProvider([None])
            provider.configuration = self.configuration
            provider.summarizer = SimpleNamespace(preflight=AsyncMock(side_effect=error))
            manifest = self.createManifest(self.startedAt + timedelta(seconds=index))
            with self.assertRaises(RuntimeError), manifest:
                runPreflight(provider, manifest)
                prepareContexts([self.firstDate], provider, manifest, SilentLogger())
            provider.prepare.assert_not_called()
            self.assertEqual('aborted', manifest.data['totals']['status'])
            self.assertEqual(type(error).__name__, manifest.data['preflight']['error_type'])
            self.assertNotIn('SECRET', manifest.path.read_text())

    def test_empty_completed_manifest_is_an_assembly_error(self):
        for status in ('completed', 'completed_with_skips', 'unexpected'):
            manifest = self.createManifest()
            manifest.data['totals']['status'] = status
            self.assertEqual([], manifest.data['totals']['dates_skipped'])
            with self.assertRaisesRegex(ValueError, 'dates_computed'):
                manifest.write()
            self.assertFalse(manifest.path.exists())
        manifest = self.createManifest()
        with self.assertRaisesRegex(ValueError, 'dates_computed'), manifest:
            pass
        self.assertFalse(manifest.path.exists())

    def test_preflight_failure_prevents_date_preparation(self):
        provider = self.createProvider([None])
        provider.configuration = self.configuration
        provider.summarizer = SimpleNamespace(preflight=AsyncMock(side_effect=RuntimeError('SECRET')))
        manifest = self.createManifest()
        with self.assertRaisesRegex(RuntimeError, self.configuration.summarizeProvider), manifest:
            runPreflight(provider, manifest)
            prepareContexts([self.firstDate], provider, manifest, SilentLogger())
        provider.prepare.assert_not_called()
        written = json.loads(manifest.path.read_text())
        self.assertEqual('aborted', written['totals']['status'])
        self.assertEqual([], written['totals']['dates_computed'])
        self.assertEqual('failed', written['preflight']['outcome'])
        self.assertFalse(written['totals']['usage_complete'])
        self.assertNotIn('SECRET', manifest.path.read_text())

    def test_preflight_usage_survives_per_date_updates(self):
        manifest = self.createManifest()
        response = SimpleNamespace(usage=SimpleNamespace(
            prompt_tokens=2, completion_tokens=1, total_tokens=3, cost=0.00001,
        ))
        manifest.recordPreflight(response)
        provider = self.createProvider([None])
        provider.usageByDate[self.firstDate] = Usage(calls=2, total_tokens=17)
        with manifest:
            prepareContexts([self.firstDate], provider, manifest, SilentLogger())
        self.assertEqual(20, manifest.data['totals']['usage']['total_tokens'])
        self.assertEqual(3, manifest.data['totals']['usage']['calls'])
        self.assertEqual(0.00001, manifest.data['totals']['preflight_reported_cost'])
        self.assertTrue(manifest.data['totals']['usage_complete'])
        self.assertEqual('completed', manifest.data['totals']['status'])
        self.assertEqual(0, manifest.data['totals']['degraded_dates_count'])
        self.assertEqual(0, manifest.data['totals']['unknown_degradation_dates_count'])

    def test_preflight_missing_usage_and_empty_content(self):
        for index, content in enumerate(('OK', '')):
            provider = self.createProvider([None])
            provider.configuration = self.configuration
            provider.summarizer = SimpleNamespace(preflight=AsyncMock(return_value=SimpleNamespace(
                usage=None, choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            )))
            manifest = self.createManifest(self.startedAt + timedelta(seconds=index))
            with manifest:
                runPreflight(provider, manifest)
                prepareContexts([self.firstDate], provider, manifest, SilentLogger())
            provider.prepare.assert_called_once_with(self.firstDate)
            self.assertEqual(1, manifest.data['totals']['usage']['calls'])
            self.assertFalse(manifest.data['totals']['usage_complete'])
            self.assertEqual('Провайдер не вернул usage', manifest.data['preflight']['usage_note'])
            self.assertEqual('succeeded',
                             manifest.data['preflight']['outcome'])

    def test_degradation_and_unknown_axes_survive_json(self):
        manifest = self.createManifest()
        failure = MetaSummaryError(axis_summaries={}, failed_axes=[],
                                   axis_errors={}, usage=Usage())
        provider = self.createProvider([failure, None, None])
        degraded = SimpleNamespace(summary='саммари', summaryFromCache=False,
                                   documentsCount=7, failedAxes=('курс', 'труд'))
        unknown = SimpleNamespace(summary='саммари', summaryFromCache=True,
                                  documentsCount=8, failedAxes=None)
        provider.prepare.side_effect = [failure, degraded, unknown]
        thirdDate = self.nextDate + timedelta(days=1)
        with manifest:
            prepareContexts([self.firstDate, self.nextDate, thirdDate], provider,
                            manifest, SilentLogger())
        written = json.loads(manifest.path.read_text())
        self.assertEqual(['курс', 'труд'],
                         written['totals']['per_date'][self.nextDate.isoformat()]['failed_axes'])
        self.assertEqual(7,
                         written['totals']['per_date'][self.nextDate.isoformat()]['documents_count'])
        self.assertIsNone(written['totals']['per_date'][thirdDate.isoformat()]['failed_axes'])
        self.assertEqual(8,
                         written['totals']['per_date'][thirdDate.isoformat()]['documents_count'])
        self.assertEqual("MetaSummaryError: мета-вызов вернул пустое содержимое; stage=meta",
                         written['totals']['dates_skipped'][0]['reason'])
        self.assertEqual(1, written['totals']['degraded_dates_count'])
        self.assertEqual(1, written['totals']['unknown_degradation_dates_count'])
        self.assertNotIn('SECRET', manifest.path.read_text())



class TestManifestUsage(NewsFixtureTestCase):
    def setUp(self):
        self.cachePath = self.folder / f'{self.id()}.db'
        newsFixtures.createProjectDbFixture(self.cachePath)
        self.configuration = self.createConfiguration(mode=twoStageMode,
                                                       projectDbPath=self.cachePath)
        self.runDate = date.fromisoformat(newsFixtures.runDate)
        self.summarizer = StubSummarizer()
        self.provider = NewsContextProvider(self.configuration, SilentLogger(),
                                            summarizer=self.summarizer)

    def test_usage_is_accumulated_once_and_cache_hit_is_explicit(self):
        self.provider.prepare(self.runDate)
        self.provider.prepare(self.runDate)
        self.assertEqual(Usage(calls=3, total_tokens=137), self.provider.usageByDate[self.runDate])
        cachedProvider = NewsContextProvider(self.configuration, SilentLogger(),
                                             summarizer=ExplodingSummarizer())
        context = cachedProvider.prepare(self.runDate)
        manifest = RunManifest('usage', self.configuration, 'test', 'https://invalid',
                               self.folder, self.folder / 'manifests')
        manifest.recordUsage(self.runDate, cachedProvider, context)
        self.assertEqual(Usage().model_dump(), manifest.data['totals']['usage'])
        self.assertTrue(manifest.data['totals']['per_date'][self.runDate.isoformat()]
                        ['summaryFromCache'])
        manifest.recordUsage(self.runDate, self.provider, self.provider.getContext(self.runDate))
        manifest.recordUsage(self.runDate, self.provider, self.provider.getContext(self.runDate))
        self.assertEqual(137, manifest.data['totals']['usage']['total_tokens'])
        self.assertFalse(manifest.data['totals']['per_date'][self.runDate.isoformat()]
                         ['summaryFromCache'])

    def test_failed_axes_usage_survives_skip(self):
        self.summarizer.axisError = TooManyAxisFailures({'дкп': 'empty'},
                                                       usage=Usage(calls=4, total_tokens=19))
        manifest = RunManifest('axes-error', self.configuration, 'test', 'https://invalid',
                               self.folder, self.folder / 'manifests')
        self.assertEqual([], prepareContexts([self.runDate], self.provider, manifest, SilentLogger()))
        self.assertEqual(Usage(calls=4, total_tokens=19).model_dump(), manifest.data['totals']['usage'])
        self.assertIn('TooManyAxisFailures', manifest.data['totals']['dates_skipped'][0]['reason'])
        self.assertTrue(manifest.data['totals']['usage_complete'])

    def test_meta_failure_includes_successful_axes_usage(self):
        self.summarizer.metaError = MetaSummaryError(
            axis_summaries={}, failed_axes=[], axis_errors={}, usage=Usage(calls=3, total_tokens=17),
        )
        manifest = RunManifest('meta-error', self.configuration, 'test', 'https://invalid',
                               self.folder, self.folder / 'manifests')
        self.assertEqual([], prepareContexts([self.runDate], self.provider, manifest, SilentLogger()))
        self.assertEqual(Usage(calls=5, total_tokens=117).model_dump(), manifest.data['totals']['usage'])
        self.assertIn('MetaSummaryError', manifest.data['totals']['dates_skipped'][0]['reason'])

    def test_meta_errors_after_degraded_axes_do_not_claim_no_failures(self):
        from openai import APIConnectionError

        secret = 'SECRET-meta-response'
        errors = [MetaSummaryError(axis_summaries={'дкп': secret}, failed_axes=[],
                                   axis_errors={}, usage=Usage()),
                  APIConnectionError(message=secret, request=Mock())]
        for index, error in enumerate(errors):
            with self.subTest(error=type(error).__name__):
                runDate = self.runDate + timedelta(days=index)
                self.summarizer.failedAxes = ('дкп',)
                self.summarizer.metaError = error
                manifest = RunManifest(f'meta-error-{index}', self.configuration, 'test',
                                       'https://invalid', self.folder,
                                       self.folder / 'manifests')
                logger = SilentLogger()
                with manifest:
                    self.assertEqual([], prepareContexts(
                        [runDate], self.provider, manifest, logger))
                written = json.loads(manifest.path.read_text())
                reason = written['totals']['dates_skipped'][0]['reason']
                self.assertIn(type(error).__name__, reason)
                self.assertIn('stage=meta', reason)
                self.assertNotIn('failed_axes=[]', reason)
                if isinstance(error, MetaSummaryError):
                    self.assertIn('мета-вызов вернул пустое содержимое', reason)
                self.assertNotIn(secret, manifest.path.read_text())
                self.assertNotIn(str(error), manifest.path.read_text())
                self.assertNotIn(repr(error), manifest.path.read_text())
                self.assertNotIn(secret, '\n'.join(logger.messages))

    def test_transport_failure_marks_usage_incomplete_and_propagates(self):
        self.summarizer.metaError = RuntimeError('transport')
        manifest = RunManifest('transport', self.configuration, 'test', 'https://invalid',
                               self.folder, self.folder / 'manifests')
        with self.assertRaisesRegex(RuntimeError, 'transport'):
            prepareContexts([self.runDate], self.provider, manifest, SilentLogger())
        self.assertEqual(Usage(calls=2, total_tokens=100).model_dump(), manifest.data['totals']['usage'])
        self.assertFalse(manifest.data['totals']['usage_complete'])
        self.assertEqual([], manifest.data['totals']['dates_skipped'])
