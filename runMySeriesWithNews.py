"""Серия опросов с новостным контекстом по списку дат из файла.

В отличие от runNewsTestSeries.py, где даты и горизонт зашиты в код, здесь они
приходят аргументами: серий на разных сетках дат ожидается много, а копировать
файл под каждую значит развести копии, которые расходятся.

    .venv/bin/python -u runMySeriesWithNews.py --dates data/run_dates/run_dates_1.txt

Файл дат читается регулярным выражением, поэтому годится и список по строке на
дату, и дамп списка pandas-таймстампов.
"""

import argparse
import asyncio
import re
import sqlite3
from datetime import date
from pathlib import Path

from amnesiac.exceptions import MetaSummaryError, SummarizeError, TooManyAxisFailures
from openai import APIError

from Logging.SimpleLogger import SimpleLogger
from NewsLogic.NewsContextProvider import NewsContextProvider
from NewsLogic.NewsCorpusReader import NewsCorpusReader
from NewsLogic.newsExceptions import NewsContextUnavailableError
from NewsLogic.NewsRagConfiguration import NewsRagConfiguration, twoStageMode
from NewsLogic.RunManifest import RunManifest

defaultHorizonDays = 14
defaultProfilesCount = 100
defaultModel = 'qwen3.8-27b'


def readRunDates(path: Path) -> list[date]:
    """Даты из файла: по строке на дату либо дамп списка pandas-таймстампов."""
    found = re.findall(r'\d{4}-\d{2}-\d{2}', path.read_text(encoding='utf-8'))
    return sorted({date.fromisoformat(x) for x in found})


def splitByCoverage(dates: list[date], corpusPath: Path) -> tuple[list[date], list[date]]:
    """Разделить даты на покрытые корпусом и нет.

    Проверка делается заранее и по всему списку: узнать, что треть серии
    непокрыта, лучше до того, как потрачены сутки на суммаризацию, а не на
    двадцатой дате.
    """
    with NewsCorpusReader(corpusPath) as reader:
        coverageFrom, coverageTo = reader.getCoverage()

    covered = [x for x in dates if coverageFrom <= x <= coverageTo]
    uncovered = [x for x in dates if x not in set(covered)]

    return covered, uncovered


def findHorizonConflicts(dates: list[date], projectDbPath: Path, horizonDays: int) -> list[tuple[str, int]]:
    """Даты, у которых в кеше лежит саммари другого горизонта.

    В `summaries` стоит `UNIQUE(run_date)`: пересчёт с другим горизонтом не
    добавит строку, а затрёт существующую. Молча терять чужой результат нельзя.
    """
    if not projectDbPath.exists():
        return []

    connection = sqlite3.connect(f'file:{projectDbPath}?mode=ro', uri=True)
    try:
        stored = dict(connection.execute('SELECT run_date, horizon_days FROM summaries').fetchall())
    finally:
        connection.close()

    return [(x.isoformat(), stored[x.isoformat()])
            for x in dates
            if x.isoformat() in stored and stored[x.isoformat()] != horizonDays]


def countSavedResponses(resultsFolder: Path, surveyDate: date) -> int:
    return len(list(resultsFolder.glob(f'{surveyDate:%d.%m.%Y}_*.json')))


def parseArguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--dates', type=Path, required=True,
                        help='файл со списком дат опроса')
    parser.add_argument('--horizon', type=int, default=defaultHorizonDays,
                        help=f'глубина окна новостей в днях (по умолчанию {defaultHorizonDays})')
    parser.add_argument('--profiles', type=int, default=defaultProfilesCount,
                        help=f'сколько респондентов на дату (по умолчанию {defaultProfilesCount})')
    parser.add_argument('--model', default=defaultModel,
                        help=f'модель-респондент на BotHub (по умолчанию {defaultModel})')
    parser.add_argument('--experiment', default=None,
                        help='имя эксперимента; по умолчанию собирается из имени файла дат и горизонта')
    parser.add_argument('--allow-horizon-overwrite', action='store_true',
                        help='разрешить пересчёт дат, у которых в кеше саммари другого горизонта')
    parser.add_argument('--contexts-only', action='store_true',
                        help='посчитать только новостные контексты, опрос не запускать')

    return parser.parse_args()


class SummarizationCircuitBreakerError(RuntimeError):
    """Три последовательных отказа суммаризации требуют остановки серии."""


def runPreflight(provider: NewsContextProvider, manifest: RunManifest) -> None:
    """Проверить доступность закреплённого провайдера до подготовки дат."""
    configuration = provider.configuration
    try:
        response = asyncio.run(provider.summarizer.preflight())
        manifest.recordPreflight(response)
    except BaseException as error:
        manifest.recordPreflightFailure(type(error).__name__)
        if not isinstance(error, Exception):
            raise
        verification = manifest.data['models']['summarization']['provider_pin_verification_status']
        reason = 'несовпадение закреплённого провайдера; ' if verification == 'mismatch' else ''
        raise RuntimeError(
            f'{reason}Preflight не выполнен: provider={configuration.summarizeProvider}, '
            f'model={configuration.summarizeModel}, ошибка={type(error).__name__}'
        ) from None


def prepareContexts(
    surveyDates: list[date],
    newsContextProvider: NewsContextProvider,
    manifest: RunManifest,
    logger: SimpleLogger,
) -> list[date]:
    """Пропускать только непокрытое окно и отказ суммаризации конкретной даты."""
    preparedDates = []
    consecutiveFailures = []
    for surveyDate in surveyDates:
        context = None
        try:
            context = newsContextProvider.prepare(surveyDate)
        except (NewsContextUnavailableError, SummarizeError, APIError) as error:
            # Текст и repr ошибок провайдера не должны попадать в манифест.
            reason = 'окно вне покрытия корпуса'
            if isinstance(error, (SummarizeError, APIError)):
                failedAxes = None
                reason = 'суммаризация даты завершилась отказом'
                if isinstance(error, TooManyAxisFailures):
                    failedAxes = sorted(error.failures)
                    reason += '; stage=axis'
                elif isinstance(error, MetaSummaryError):
                    failedAxes = sorted(error.failed_axes) or None
                    reason = 'мета-вызов вернул пустое содержимое; stage=meta'
                elif isinstance(error, APIError):
                    # Осевой этап amnesiac оборачивает ошибки в TooManyAxisFailures.
                    reason = 'ошибка провайдера; stage=meta'
                if failedAxes is not None:
                    reason += f'; failed_axes={failedAxes}'
                consecutiveFailures.append(surveyDate.isoformat())
            manifest.recordSkipped(surveyDate, f'{type(error).__name__}: {reason}')
            logger.logDebug(f'SKIPPED survey date {surveyDate}: {type(error).__name__}: {reason}')
            if len(consecutiveFailures) >= 3:
                manifest.data['totals']['circuit_breaker'] = {
                    'reason': 'Три последовательных отказа суммаризации',
                    'dates': list(consecutiveFailures),
                }
                raise SummarizationCircuitBreakerError(
                    f'Три последовательных отказа суммаризации: {consecutiveFailures}'
                ) from None
            continue
        finally:
            manifest.recordUsage(surveyDate, newsContextProvider, context)

        if context is not None and context.summaryFromCache is False:
            consecutiveFailures.clear()
        failedAxes = context.failedAxes if context.failedAxes is not None else 'НЕИЗВЕСТНО'
        logger.logDebug(
            f'CONTEXT {surveyDate:%Y-%m-%d}: docs={context.documentsCount}, '
            f'summary={len(context.summary or "")} chars, fromCache={context.summaryFromCache}, '
            f'failedAxes={failedAxes}'
        )
        preparedDates.append(surveyDate)
        manifest.data['totals']['dates_computed'].append(surveyDate.isoformat())
    return preparedDates


def main(arguments: argparse.Namespace | None = None) -> None:
    from Configuration import configuration
    from Configuration.configuration import bothub_key
    from SurveyLogic.PromptBuilders.profileBuildersHelpers import createNewsPromptBuilder
    from SurveyLogic.Surveyers.AsyncSurveyer import AsyncSurveyer
    from SurveyLogic.surveyHelpers import (
        copyPromptTemplatesToFolder,
        createAsyncSurveyRunner,
    )
    from SurveyLogic.SurveyResultsSerialization.SurveySerializer import SurveySerializer

    arguments = arguments if arguments is not None else parseArguments()

    if arguments.horizon <= 0:
        raise SystemExit(f'Горизонт должен быть положительным, получено {arguments.horizon}')

    experimentUniqueName = (arguments.experiment
                            or f'bothub_{arguments.model.replace(".", "").replace("-", "")}'
                               f'_{arguments.dates.stem}_h{arguments.horizon}')
    profilesFolder = Path('./data/Target profiles')
    resultsFolder = Path('data/SurveyResults/') / experimentUniqueName
    newsConfiguration = NewsRagConfiguration(
        mode=twoStageMode,
        horizonDays=arguments.horizon,
        artefactsFolder=resultsFolder / 'News',
    )

    manifest = RunManifest(experimentUniqueName, newsConfiguration, arguments.model,
                           configuration.bothubUrl, resultsFolder)
    with manifest:
        manifest.collectInputs(newsConfiguration, profilesFolder, arguments.profiles)
        resultsFolder.mkdir(parents=True, exist_ok=True)
        copyPromptTemplatesToFolder(Path('SurveyLogic/PromptBuilders/Prompts/'), resultsFolder / 'Prompts')

        logger = SimpleLogger()

        allDates = readRunDates(arguments.dates)
        manifest.data['totals']['dates_requested'] = [day.isoformat() for day in allDates]
        if not allDates:
            raise SystemExit(f'В файле {arguments.dates} не найдено ни одной даты вида ГГГГ-ММ-ДД')

        surveyDates, uncoveredDates = splitByCoverage(allDates, newsConfiguration.corpusPath)

        logger.logDebug(f'PLAN эксперимент {experimentUniqueName}')
        logger.logDebug(f'PLAN файл дат {arguments.dates}: {len(allDates)} дат, '
                        f'горизонт {arguments.horizon} дней, респондентов на дату {arguments.profiles}')
        logger.logDebug(f'PLAN результаты: {resultsFolder}')

        for surveyDate in uncoveredDates:
            manifest.recordSkipped(surveyDate, 'NewsContextUnavailableError: дата вне покрытия корпуса')

        if uncoveredDates:
            # Даты вне периода сбора корпуса пропускаются, а не опрашиваются без
            # новостей: иначе эксперимент news молча превратился бы в no-news (D-015).
            logger.logDebug(f'SKIPPED {len(uncoveredDates)} дат вне покрытия корпуса: '
                            f'{", ".join(x.isoformat() for x in uncoveredDates)}')

        if not surveyDates:
            raise SystemExit('Ни одна дата из файла не покрыта корпусом, считать нечего')

        conflicts = findHorizonConflicts(surveyDates, newsConfiguration.projectDbPath, arguments.horizon)
        if conflicts and not arguments.allow_horizon_overwrite:
            listing = ', '.join(f'{runDate} (горизонт {horizon})' for runDate, horizon in conflicts)
            raise SystemExit(
                f'В project.db уже лежат саммари другого горизонта на {len(conflicts)} дат: {listing}.\n'
                f'В таблице summaries стоит UNIQUE(run_date), поэтому пересчёт с горизонтом '
                f'{arguments.horizon} затрёт их безвозвратно.\n'
                f'Если это и требуется, повторите запуск с --allow-horizon-overwrite.'
            )

        if conflicts:
            logger.logDebug(f'OVERWRITE саммари другого горизонта будут затёрты на {len(conflicts)} датах')

        newsContextProvider = NewsContextProvider(newsConfiguration, logger)
        systemPromptBuilder, promptBuilder = createNewsPromptBuilder(newsContextProvider)
        manifest.recordPrompt(systemPromptBuilder, promptBuilder)

        runPreflight(newsContextProvider, manifest)
        preparedDates = prepareContexts(surveyDates, newsContextProvider, manifest, logger)

        logger.logDebug(f'CONTEXTS готово: {len(preparedDates)} из {len(surveyDates)}')

        if arguments.contexts_only:
            return

        if not bothub_key.strip():
            raise SystemExit(
                'Ключ модели-респондента пуст: Configuration/bothub_key.txt. '
                'Новостные контексты подготовлены и лежат в project.db, повторный запуск '
                'их не пересчитает; заполните ключ и запустите скрипт снова.'
            )

        surveyer = AsyncSurveyer(modelToUse=arguments.model, key=bothub_key.strip(), logger=logger,
                                 baseUrl=configuration.bothubUrl)
        surveySerializer = SurveySerializer(resultsFolder)

        # Шаг 2. Опрос по подготовленным датам.
        for surveyDate in preparedDates:
            # Выборка респондентов не сеяна (RandomSubsampleProfilesProvider), поэтому
            # повторный прогон по готовой дате не перезапишет ответы, а подмешает к ним
            # ещё десяток от других респондентов. Готовые даты пропускаются — это же
            # делает прогон возобновляемым после обрыва.
            saved = countSavedResponses(resultsFolder, surveyDate)
            if saved >= arguments.profiles:
                logger.logDebug(f'SURVEY {surveyDate:%Y-%m-%d}: пропущена, {saved} ответов уже сохранено')
                manifest.data['totals']['surveys_already_saved'].append(surveyDate.isoformat())
                continue

            if saved:
                raise SystemExit(
                    f'На дату {surveyDate:%Y-%m-%d} сохранено {saved} ответов из {arguments.profiles} — '
                    f'прогон оборвался посреди даты. Выборка респондентов не сеяна, поэтому дозапуск '
                    f'смешал бы две разные выборки. Удалите файлы {surveyDate:%d.%m.%Y}_*.json '
                    f'из {resultsFolder} и запустите снова.'
                )

            runner = createAsyncSurveyRunner(profilesFolder, systemPromptBuilder, promptBuilder, surveySerializer,
                                             surveyer, arguments.profiles, logger)
            surveyResults = asyncio.run(runner.RunSurvey(surveyDate))
            logger.logDebug(f'SURVEY {surveyDate:%Y-%m-%d}: {len(surveyResults)} responses saved')
            manifest.data['totals']['surveys_completed'].append(surveyDate.isoformat())


if __name__ == '__main__':
    main()
