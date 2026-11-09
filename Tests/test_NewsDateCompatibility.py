import sqlite3
import sys
from collections.abc import Iterator
from datetime import UTC, date, datetime, time, timedelta
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import pytest

import Configuration
from NewsLogic.NewsContext import NewsContext
from NewsLogic.NewsContextProvider import NewsContextProvider
from NewsLogic.NewsCorpusReader import NewsCorpusReader
from NewsLogic.newsHelpers import moscowDate
from NewsLogic.NewsRagConfiguration import NewsRagConfiguration, rawMode, twoStageMode
from NewsLogic.newsSectionRenderer import renderNewsSection
from NewsLogic.RunManifest import RunManifest
from runMySeriesWithNews import readRunDates
from SurveyLogic.PromptBuilders.Profiles.ProfileData import ProfileData
from Tests import newsFixtures
from Tests.test_NewsRag import SilentLogger, StubSummarizer


class PreparedNewsProvider:
    """Supply prepared news offline while leaving profile calculations real."""

    def __init__(self, runDate: date) -> None:
        self.receivedDates: list[date] = []
        self.context = NewsContext(
            runDate=runDate,
            windowFrom=runDate - timedelta(days=14),
            windowToExclusive=runDate,
            horizonDays=14,
            mode=twoStageMode,
            documents={},
            summary='Детерминированный новостной фон.',
        )

    def getContext(self, surveyDate: date) -> NewsContext:
        self.receivedDates.append(surveyDate)
        return self.context


@pytest.fixture(autouse=True)
def profileFiles(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.chdir(Path(__file__).resolve().parents[1])
    # Only file locations are supplied: no secrets are needed for an offline build.
    # Restore both import bindings so other tests can supply their own configuration.
    configuration = SimpleNamespace(
        mrotStatisticsPath=Path('data/MROT_history.xlsx'),
        averageBuyingsDataPath=Path('data/Average Buyings Regions 1980_2026.xlsx'),
        rlmsToInflationRegionsPath=Path('data/rlmsToInflationRegionsMapping.txt'),
    )
    import SurveyLogic.PromptBuilders as package

    missing = object()
    previous = getattr(package, 'profileBuildersHelpers', missing)
    with (
        patch.dict(sys.modules, {'Configuration.configuration': configuration}),
        patch.object(Configuration, 'configuration', configuration, create=True),
    ):
        from SurveyLogic.PromptBuilders import profileBuildersHelpers

        with patch.object(profileBuildersHelpers, 'configuration', configuration):
            yield
    if previous is missing:
        delattr(package, 'profileBuildersHelpers')
    else:
        package.profileBuildersHelpers = previous


@pytest.fixture
def syntheticProfile() -> ProfileData:
    return ProfileData(
        respondentId='synthetic',
        age=40,
        sex='мужской',
        education='высшее',
        LocalityOfBirth='Москва',
        currentLocality='Москва',
        currentLocalityRegionCode='2',
        currentLocalityRegion='Москва',
        typeOfLocality='город',
        job='инженер',
        jobSector='промышленность',
        currentStatus='работает',
        salary='50000',
        hasSavings=True,
        hasCredit=False,
        familyStatus='женат',
        nationality='русский',
        economicsSourceOfKnowledge='новости',
        idIndividualrespondent=0.0,
        idHHrespondent=0.0,
        hhHasChildren=0,
        totalFamilyMembers=1.0,
        allFamilyMonthIncome=50000.0,
        familyHasActiveCredits='нет',
        totalFamilyCreditDebt=0.0,
        familyHouseType='квартира',
        familyHouseAllocationType='собственность',
        familyHouseTotalSquare=40.0,
        hasCountryHouse='нет',
        hasOtherMortgage='нет',
        hasLand='нет',
        landOwner='нет',
        vacationForeign=0,
        vacationDomestic=0,
        hasRussianCar='нет',
        yearsOfRussianCar=0.0,
        hasForeignCar='нет',
        yearsOfForeignCar=0.0,
        regular={},
        durable={},
        services={},
        nonDurableGoods=[],
        newsSources=[],
    )


def checkComposition(
    surveyDate: date, compatibleDate: datetime, profile: ProfileData, tmpPath: Path
) -> None:
    # Production configuration and templates use paths relative to the repository root.
    from SurveyLogic.PromptBuilders.profileBuildersHelpers import createNewsPromptBuilder
    from SurveyLogic.PromptBuilders.ProfileSepcificPromptBuilders.CommonProfilePromptBuilder import (
        CommonProfilePromptBuilder,
    )

    calendarDate = date(surveyDate.year, surveyDate.month, surveyDate.day)
    provider = PreparedNewsProvider(calendarDate)
    systemBuilder, builder = createNewsPromptBuilder(provider)
    profileBuilder, newsBuilder, taskBuilder = builder.builders
    commonBuilder = CommonProfilePromptBuilder(
        profileBuilder.prompt, profileBuilder.mrotProvider, profileBuilder.averageExpensesProvider
    )
    expectedProfile = commonBuilder.buildPrompt(compatibleDate, profile)
    assert 'в терминах МРОТ' in expectedProfile
    assert 'в терминах средних трат по региону проживания Москва' in expectedProfile
    expectedParts = [
        expectedProfile,
        renderNewsSection(provider.context),
        taskBuilder.buildPrompt(surveyDate, profile),
    ]
    expected = expectedParts[0]
    for header, part in zip(['Новости', 'Задача'], expectedParts[1:], strict=True):
        heading = f'======================{header}======================'
        border = '=' * len(heading)
        expected += f'\n{border}\n{heading}\n{border}\n{part}'

    with patch.object(taskBuilder, 'buildPrompt', wraps=taskBuilder.buildPrompt) as taskCall:
        actual = builder.buildPrompt(surveyDate, profile)
    assert provider.receivedDates == [surveyDate]
    assert provider.receivedDates[0] is surveyDate
    assert taskCall.call_args.args[0] is surveyDate
    # Compare every byte without exposing full prompts in failure diagnostics.
    assert sha256(actual.encode()).digest() == sha256(expected.encode()).digest()
    actualProfile = profileBuilder.buildPrompt(surveyDate, profile)
    assert sha256(actualProfile.encode()).digest() == sha256(expectedProfile.encode()).digest()

    manifest = RunManifest(
        'synthetic-date-test',
        NewsRagConfiguration(),
        'offline',
        'offline',
        tmpPath / 'results',
        manifestFolder=tmpPath / 'manifests',
    )
    manifest.recordPrompt(systemBuilder, builder)
    assert manifest.data['prompt']['composition'] == [
        type(profileBuilder).__name__,
        'NewsPromptBuilder',
        'TaskPromptBuilder',
    ]
    assert isinstance(profileBuilder, CommonProfilePromptBuilder)
    assert type(newsBuilder).__name__ == 'NewsPromptBuilder'
    assert manifest.data['prompt']['section_headers'] == [
        'Основные параметры опроса и респондента',
        'Новости',
        'Задача',
    ]
    assert not (tmpPath / 'manifests').exists()


def test_readRunDatesBuildsFullNewsPrompt(tmp_path: Path, syntheticProfile: ProfileData) -> None:
    datesPath = tmp_path / 'dates.txt'
    datesPath.write_text('2019-11-08\n', encoding='utf-8')
    dates = readRunDates(datesPath)
    assert dates == [date(2019, 11, 8)]
    assert type(dates[0]) is date
    checkComposition(
        dates[0], datetime.combine(date(2019, 11, 8), time.min), syntheticProfile, tmp_path
    )


@pytest.mark.parametrize(
    'surveyDate',
    [
        datetime.combine(date(2019, 1, 1), time.min),
        datetime.combine(date(2019, 1, 1), time(12, 34, 56)),
        pd.Timestamp('2019-01-01'),
        pd.Timestamp('2019-01-01 12:34:56'),
    ],
)
def test_compatibleProfileDatesKeepTheirSemantics(
    surveyDate: datetime,
    tmp_path: Path,
    syntheticProfile: ProfileData,
) -> None:
    checkComposition(surveyDate, surveyDate, syntheticProfile, tmp_path)


@pytest.mark.parametrize(
    'day,expectedMrot',
    [
        (date(2019, 12, 31), 11280),
        (date(2020, 1, 1), 11280),
        (date(2020, 2, 28), 12130),
        (date(2020, 2, 29), 12130),
        (date(2020, 3, 1), 12130),
        (date(2018, 4, 30), 9489),
        (date(2018, 5, 1), 9489),
        (date(2018, 5, 2), 11163),
    ],
)
def test_calendarBoundariesForwardExactMidnight(
    day: date, expectedMrot: int, syntheticProfile: ProfileData
) -> None:
    from SurveyLogic.PromptBuilders.profileBuildersHelpers import createNewsPromptBuilder
    from SurveyLogic.PromptBuilders.ProfileSepcificPromptBuilders.CommonProfilePromptBuilder import (
        CommonProfilePromptBuilder,
    )

    _, composite = createNewsPromptBuilder(None)
    adapter = composite.builders[0]
    midnight = datetime.combine(day, time.min)
    common = CommonProfilePromptBuilder(
        adapter.prompt, adapter.mrotProvider, adapter.averageExpensesProvider
    )
    # May 1 really is a change day, but the inherited rule is strictly '<'.
    assert adapter.mrotProvider.getMROT(midnight) == expectedMrot
    if day == date(2018, 5, 1):
        assert adapter.mrotProvider.date_to_value[pd.Timestamp(midnight)] == 11163
        assert adapter.mrotProvider.getMROT(midnight + timedelta(seconds=1)) == 11163
    expected = common.buildPrompt(midnight, syntheticProfile)
    assert 'в терминах МРОТ' in expected
    assert 'в терминах средних трат по региону проживания Москва' in expected
    for value in (day, midnight, pd.Timestamp(midnight)):
        # Observe the REAL inherited computation. Text alone cannot detect a day
        # shift when both statistics and the month name happen to stay identical.
        inherited = CommonProfilePromptBuilder.buildPrompt.__get__(adapter)
        with patch.object(CommonProfilePromptBuilder, 'buildPrompt', wraps=inherited) as call:
            actual = adapter.buildPrompt(value, syntheticProfile)
        call.assert_called_once()
        forwarded, forwardedProfile = call.call_args.args
        assert forwarded == midnight
        assert isinstance(forwarded, datetime)
        assert forwardedProfile is syntheticProfile
        if type(value) is date:
            assert type(forwarded) is datetime
        else:
            assert forwarded is value
        assert sha256(actual.encode()).digest() == sha256(expected.encode()).digest()


@pytest.mark.parametrize('mode', [rawMode, twoStageMode])
@pytest.mark.parametrize('inputType', [date, datetime, pd.Timestamp])
def test_realNewsCompositionKeepsCalendarWindowAndCache(
    mode: str, inputType: type, tmp_path: Path, syntheticProfile: ProfileData
) -> None:
    from SurveyLogic.PromptBuilders.profileBuildersHelpers import createNewsPromptBuilder
    from SurveyLogic.PromptBuilders.ProfileSepcificPromptBuilders.CommonProfilePromptBuilder import (
        CommonProfilePromptBuilder,
    )

    datesPath = tmp_path / 'dates.txt'
    datesPath.write_text(newsFixtures.runDate, encoding='utf-8')
    day = readRunDates(datesPath)[0]
    assert type(day) is date
    compatible = datetime.combine(day, time.min)
    value = {date: day, datetime: compatible, pd.Timestamp: pd.Timestamp(compatible)}[inputType]
    config = NewsRagConfiguration(
        axes=newsFixtures.axes,
        horizonDays=14,
        mode=mode,
        corpusPath=newsFixtures.createCorpusFixture(tmp_path / 'corpus.db'),
        projectDbPath=newsFixtures.createProjectDbFixture(tmp_path / 'cache.db'),
    )
    configHash = config.configHash()
    summarizer = StubSummarizer()
    baseline = NewsContextProvider(config, SilentLogger(), summarizer=summarizer)
    reference = baseline.prepare(day)
    # A fresh provider forces retrieval for the compatible input, rather than
    # accidentally proving equality by returning the same in-memory object.
    provider = NewsContextProvider(config, SilentLogger(), summarizer=summarizer)
    context = provider.prepare(value)
    assert context.runDate == day
    assert type(context.runDate) is date
    assert list(provider.contexts) == [day]
    assert (context.windowFrom, context.windowToExclusive) == (date(2022, 3, 11), day)
    lower, upper = provider.retriever.getWindowUtcBounds(context.runDate)
    assert lower == datetime(2022, 3, 10, 21, tzinfo=UTC)
    assert upper == datetime(2022, 3, 24, 21, tzinfo=UTC)
    assert upper - lower == timedelta(days=14)
    assert context.documents == reference.documents
    # Existing golden messages, now in the full 14-day window: id 11 is
    # included too; the golden duplicate (10) still loses to id 3.
    expectedOrder = {
        newsFixtures.firstAxis: [11, *newsFixtures.inWindowMessageIds],
        # Same-day ties retain similarity order: angle 10 is closer to axis B
        # than angle 0 (the golden vectors define these angles explicitly).
        newsFixtures.secondAxis: [11, 2, 1, 3, 12],
    }
    for axis, documents in context.documents.items():
        assert [document.messageId for document in documents] == expectedOrder[axis]
        for document in documents:
            assert lower <= datetime.fromisoformat(document.publishedAt) < upper
            assert context.windowFrom <= moscowDate(document.publishedAt) < day
            assert (
                document.dayNumber
                == (moscowDate(document.publishedAt) - context.windowFrom).days + 1
            )
    assert provider.getContext(value) is context
    assert config.configHash() == configHash
    artefact = context.toArtefact(config.toDictionary())
    assert artefact['run_date'] == '2022-03-25'
    assert artefact['window_from'] == '2022-03-11'
    assert artefact['window_to_exclusive'] == '2022-03-25'
    with sqlite3.connect(config.projectDbPath) as connection:
        rows = connection.execute(
            'SELECT run_date, horizon_days, config_hash FROM summaries'
        ).fetchall()
        axisRows = connection.execute(
            'SELECT run_date, horizon_days, config_hash FROM axis_summaries ORDER BY axis'
        ).fetchall()
    if mode == twoStageMode:
        assert rows == [('2022-03-25', 14, configHash)]
        assert axisRows == [('2022-03-25', 14, configHash)] * len(newsFixtures.axes)
        assert context.summaryFromCache
        assert len(summarizer.axisInputs) == len(summarizer.metaInputs) == 1
    else:
        assert rows == axisRows == []
        assert summarizer.axisInputs == summarizer.metaInputs == []

    _, composite = createNewsPromptBuilder(provider)
    adapter, news, task = composite.builders
    common = CommonProfilePromptBuilder(
        adapter.prompt, adapter.mrotProvider, adapter.averageExpensesProvider
    )
    # The unadapted production news path is the reference; exact rendering
    # literals are independently locked by TestNewsSectionRendering's golden tests.
    section = renderNewsSection(reference)
    assert news.buildPrompt(value, syntheticProfile) == section
    parts = [
        common.buildPrompt(compatible, syntheticProfile),
        section,
        task.buildPrompt(compatible, syntheticProfile),
    ]
    expected = parts[0]
    for heading, part in zip(['Новости', 'Задача'], parts[1:], strict=True):
        title = f'======================{heading}======================'
        border = '=' * len(title)
        expected += f'\n{border}\n{title}\n{border}\n{part}'
    actual = composite.buildPrompt(value, syntheticProfile)
    assert sha256(actual.encode()).digest() == sha256(expected.encode()).digest()


def test_fourteenDayWindowIncludesLower21AndExcludesUpper21(tmp_path: Path) -> None:
    # Boundary probes reuse golden texts/vectors in a disposable fixture. Move
    # only their timestamps: no expected outputs are captured from the adapter.
    from NewsLogic.NewsRetriever import NewsRetriever

    corpus = newsFixtures.createCorpusFixture(tmp_path / 'boundaries.db')
    with sqlite3.connect(corpus) as connection:
        connection.executemany(
            'UPDATE messages SET date = ? WHERE id = ?',
            [
                ('2022-03-10T20:59:59+00:00', 11),
                ('2022-03-10T21:00:00+00:00', 1),
                ('2022-03-10T21:00:01+00:00', 2),
                ('2022-03-24T20:59:59+00:00', 12),
                ('2022-03-24T21:00:00+00:00', 5),
                ('2022-03-24T21:00:01+00:00', 6),
            ],
        )
    config = NewsRagConfiguration(axes=newsFixtures.axes, corpusPath=corpus, mode=rawMode)
    retriever = NewsRetriever(config, SilentLogger())
    day = date.fromisoformat(newsFixtures.runDate)
    lower, upper = retriever.getWindowUtcBounds(day)
    with NewsCorpusReader(corpus) as reader:
        rows = reader.loadWindow(lower, upper, config.excludeChannels)
    assert [row['messageId'] for row in rows] == [1, 2, 3, 10, 12]
    documents = retriever.retrieve(day)
    expectedOrder = {
        newsFixtures.firstAxis: newsFixtures.inWindowMessageIds,
        newsFixtures.secondAxis: [2, 1, 3, 12],
    }
    for axis, axisDocuments in documents.items():
        assert [document.messageId for document in axisDocuments] == expectedOrder[axis]
        assert [document.dayNumber for document in axisDocuments] == [1, 1, 13, 14]
