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

from Configuration import configuration
from Configuration.configuration import bothub_key
from Logging.SimpleLogger import SimpleLogger
from NewsLogic.NewsContextProvider import NewsContextProvider
from NewsLogic.NewsCorpusReader import NewsCorpusReader
from NewsLogic.newsExceptions import NewsContextUnavailableError
from NewsLogic.NewsRagConfiguration import NewsRagConfiguration, twoStageMode
from SurveyLogic.PromptBuilders.profileBuildersHelpers import createNewsPromptBuilder
from SurveyLogic.Surveyers.AsyncSurveyer import AsyncSurveyer
from SurveyLogic.surveyHelpers import (
    copyPromptTemplatesToFolder,
    createAsyncSurveyRunner,
)
from SurveyLogic.SurveyResultsSerialization.SurveySerializer import SurveySerializer

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


arguments = parseArguments()

if arguments.horizon <= 0:
    raise SystemExit(f'Горизонт должен быть положительным, получено {arguments.horizon}')

experimentUniqueName = (arguments.experiment
                        or f'bothub_{arguments.model.replace(".", "").replace("-", "")}'
                           f'_{arguments.dates.stem}_h{arguments.horizon}')
profilesFolder = Path('./data/Target profiles')
resultsFolder = Path('data/SurveyResults/') / experimentUniqueName
resultsFolder.mkdir(parents=True, exist_ok=True)
copyPromptTemplatesToFolder(Path('SurveyLogic/PromptBuilders/Prompts/'), resultsFolder / 'Prompts')

logger = SimpleLogger()

newsConfiguration = NewsRagConfiguration(
    mode=twoStageMode,
    horizonDays=arguments.horizon,
    artefactsFolder=resultsFolder / 'News',
)

allDates = readRunDates(arguments.dates)
if not allDates:
    raise SystemExit(f'В файле {arguments.dates} не найдено ни одной даты вида ГГГГ-ММ-ДД')

surveyDates, uncoveredDates = splitByCoverage(allDates, newsConfiguration.corpusPath)

logger.logDebug(f'PLAN эксперимент {experimentUniqueName}')
logger.logDebug(f'PLAN файл дат {arguments.dates}: {len(allDates)} дат, '
                f'горизонт {arguments.horizon} дней, респондентов на дату {arguments.profiles}')
logger.logDebug(f'PLAN результаты: {resultsFolder}')

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

# Шаг 1. Контексты считаются до опроса: провал суммаризации виден раньше, чем
# потрачены вызовы модели-респондента, и ключ респондента здесь не нужен.
preparedDates = []
for surveyDate in surveyDates:
    try:
        context = newsContextProvider.prepare(surveyDate)
    except NewsContextUnavailableError as error:
        logger.logDebug(f'SKIPPED survey date {surveyDate}: {error}')
        continue

    failedAxes = context.failedAxes if context.failedAxes is not None else 'НЕИЗВЕСТНО'
    logger.logDebug(
        f'CONTEXT {surveyDate:%Y-%m-%d}: docs={context.documentsCount}, '
        f'summary={len(context.summary)} chars, fromCache={context.summaryFromCache}, '
        f'failedAxes={failedAxes}'
    )
    preparedDates.append(surveyDate)

logger.logDebug(f'CONTEXTS готово: {len(preparedDates)} из {len(surveyDates)}')

if arguments.contexts_only:
    raise SystemExit(0)

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
