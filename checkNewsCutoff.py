"""Живой cutoff-гейт: выдача по MSK и обе полосы 21:00–24:00Z на границах окна.

Читает общий корпус только через mode=ro, без вызовов провайдера. Полные сканы
занимают минуты. Код возврата: 0 — ЗЕЛЁНЫЙ, 1 — КРАСНЫЙ.

    .venv/bin/python -u checkNewsCutoff.py
    .venv/bin/python -u checkNewsCutoff.py 2022-03-26
"""

import sys
from datetime import UTC, date, datetime, timedelta

from Logging.SimpleLogger import SimpleLogger
from NewsLogic.NewsCorpusReader import NewsCorpusReader
from NewsLogic.newsExceptions import NewsContextError
from NewsLogic.newsHelpers import moscowDate
from NewsLogic.NewsRagConfiguration import NewsRagConfiguration
from NewsLogic.NewsRetriever import NewsRetriever

defaultDates = (
    '2016-04-06',
    '2020-03-05',
    '2022-03-04',
    '2022-03-26',
    '2024-06-05',
    '2026-04-04',
)


class Quiet(SimpleLogger):
    def logDebug(self, obj: object) -> None:
        pass


def utcBand(day: date) -> tuple[datetime, datetime]:
    """Полоса задана независимо от преобразования границ в production-коде."""
    bandFrom = datetime(day.year, day.month, day.day, 21, 0, tzinfo=UTC)
    return bandFrom, bandFrom + timedelta(hours=3)


def main() -> int:
    configuration = NewsRagConfiguration()
    retriever = NewsRetriever(configuration, Quiet())
    dateStrings = sys.argv[1:] or defaultDates
    passedDates = 0
    totalLowerBand = 0

    for dateString in dateStrings:
        print(f'=== {dateString} ===')
        try:
            runDate = date.fromisoformat(dateString)
        except ValueError:
            print('КРАСНЫЙ: требуется дата в формате YYYY-MM-DD')
            continue

        windowFrom = runDate - timedelta(days=configuration.horizonDays)
        windowFromUtc, windowToExclusiveUtc = retriever.getWindowUtcBounds(runDate)
        print(f'Окно MSK: [{windowFrom}, {runDate})')
        print(f'Границы production UTC: [{windowFromUtc}, {windowToExclusiveUtc})')
        try:
            retrieved = retriever.retrieve(runDate)
            checkedDocuments = 0
            invalidDocuments = 0
            for documents in retrieved.values():
                for document in documents:
                    checkedDocuments += 1
                    if not windowFrom <= moscowDate(document.publishedAt) < runDate:
                        invalidDocuments += 1
                        print(f'Вне окна: {document.messageId}, {document.publishedAt}')
            print(
                f'Проверено документов по всем осям: {checkedDocuments}; '
                f'вне окна: {invalidDocuments}'
            )

            lowerFrom, lowerTo = utcBand(windowFrom - timedelta(days=1))
            upperFrom, upperTo = utcBand(runDate - timedelta(days=1))
            with NewsCorpusReader(configuration.corpusPath) as reader:
                reader.assertCorpusContract()
                rows = reader.loadWindow(
                    windowFromUtc, windowToExclusiveUtc, configuration.excludeChannels
                )
                lowerInCorpus = reader.countBandMessages(
                    lowerFrom, lowerTo, configuration.excludeChannels
                )
                upperInCorpus = reader.countBandMessages(
                    upperFrom, upperTo, configuration.excludeChannels
                )

            lowerInWindow = 0
            upperInWindow = 0
            for row in rows:
                publishedAt = datetime.fromisoformat(row['date'])
                lowerInWindow += lowerFrom <= publishedAt < lowerTo
                upperInWindow += upperFrom <= publishedAt < upperTo
            del rows

            totalLowerBand += lowerInCorpus
            print(
                f'Нижняя полоса [{lowerFrom}, {lowerTo}): '
                f'в корпусе {lowerInCorpus}, в окне {lowerInWindow}'
            )
            print(
                f'Верхняя полоса [{upperFrom}, {upperTo}): '
                f'в корпусе {upperInCorpus}, в окне {upperInWindow}'
            )
            passed = invalidDocuments == 0 and lowerInWindow == lowerInCorpus and upperInWindow == 0
        except NewsContextError as error:
            # Включая NewsContextUnavailableError: остальные даты проверяем дальше.
            print(f'КРАСНЫЙ: {error}')
            continue

        passedDates += passed
        print('ЗЕЛЁНЫЙ' if passed else 'КРАСНЫЙ')

    passed = passedDates == len(dateStrings) and totalLowerBand > 0
    print(f'Итого: {passedDates}/{len(dateStrings)} дат прошли проверку')
    print(f'Всего сообщений нижних полос в корпусе: {totalLowerBand} (требуется > 0)')
    print('ЗЕЛЁНЫЙ' if passed else 'КРАСНЫЙ')
    return 0 if passed else 1


if __name__ == '__main__':
    sys.exit(main())
