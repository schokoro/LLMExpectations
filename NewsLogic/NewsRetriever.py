from datetime import date, datetime, timedelta

import numpy as np
from amnesiac.select import select_by_axis

from Logging.BaseLogger import BaseLogger
from NewsLogic.NewsCorpusReader import NewsCorpusReader
from NewsLogic.NewsDocument import NewsDocument
from NewsLogic.newsExceptions import NewsContextError, NewsContextUnavailableError
from NewsLogic.newsHelpers import moscowDate, moscowDayStartUtc
from NewsLogic.NewsRagConfiguration import NewsRagConfiguration


class NewsRetriever:
    """Отбор новостей из корпуса по осям на дату опроса.

    Отбор детерминирован: тот же корпус и тот же конфиг дают тот же список
    message_id с тем же порядком. Обращений к эмбеддеру нет — векторы осей
    берутся готовыми из корпуса.
    """

    def __init__(self, configuration: NewsRagConfiguration, logger: BaseLogger):
        self.configuration = configuration
        self.logger = logger

    def getWindow(self, runDate: date) -> tuple[date, date]:
        """Окно `[runDate - horizonDays, runDate)`. День опроса не входит."""
        return runDate - timedelta(days=self.configuration.horizonDays), runDate

    def getWindowUtcBounds(self, runDate: date) -> tuple[datetime, datetime]:
        """Явные UTC-границы окна московских суток."""
        windowFrom, windowToExclusive = self.getWindow(runDate)
        windowFromUtc = moscowDayStartUtc(windowFrom)
        windowToExclusiveUtc = moscowDayStartUtc(windowToExclusive)
        return windowFromUtc, windowToExclusiveUtc

    def retrieve(self, runDate: date) -> dict[str, list[NewsDocument]]:
        windowFrom, windowToExclusive = self.getWindow(runDate)
        windowFromUtc, windowToExclusiveUtc = self.getWindowUtcBounds(runDate)

        with NewsCorpusReader(self.configuration.corpusPath) as reader:
            reader.assertCorpusContract()
            self._assertCoverage(reader, windowFrom, windowToExclusive)

            rows = reader.loadWindow(
                windowFromUtc,
                windowToExclusiveUtc,
                self.configuration.excludeChannels,
            )
            if not rows:
                raise NewsContextError(
                    f'В окне [{windowFrom}, {runDate}) нет ни одного сообщения. '
                    f'Расширять окно нельзя: это скрыло бы дефект отбора.'
                )

            queries = self._loadAxisVectors(reader)

        texts = [row['processedText'] for row in rows]
        dayNumbers = [self._getDayNumber(row['date'], windowFrom) for row in rows]
        documentVectors = np.asarray(
            [np.frombuffer(row['embeddingBlob'], dtype='<f4') for row in rows],
            dtype=np.float32,
        )

        selectedIndices = select_by_axis(
            documentVectors,
            queries,
            texts=texts,
            top_k=self.configuration.topKPerAxis,
            dedup_threshold=self.configuration.dedupThreshold,
            order_by=dayNumbers,
        )

        normalizedVectors = self._normalize(documentVectors)

        retrieved: dict[str, list[NewsDocument]] = {}
        for axis in self.configuration.axes:
            indices = selectedIndices[axis]
            axisVector = queries[axis] / np.linalg.norm(queries[axis])

            retrieved[axis] = [
                NewsDocument(
                    messageId=rows[index]['messageId'],
                    channel=rows[index]['channel'],
                    publishedAt=rows[index]['date'],
                    dayNumber=dayNumbers[index],
                    text=rows[index]['processedText'],
                    axis=axis,
                    position=position,
                    score=float(normalizedVectors[index] @ axisVector),
                )
                for position, index in enumerate(indices)
            ]

        self.logger.logDebug(
            f'News retrieval for {runDate}: window [{windowFrom}, {runDate}), '
            f'{len(rows)} messages in window, '
            f'{sum(len(documents) for documents in retrieved.values())} selected across '
            f'{len(retrieved)} axes'
        )

        return retrieved

    def _assertCoverage(
        self,
        reader: NewsCorpusReader,
        windowFrom: date,
        windowToExclusive: date,
    ) -> None:
        firstCoveredDay, lastCoveredDay = reader.getCoverage()
        lastWindowDay = windowToExclusive - timedelta(days=1)

        if windowFrom < firstCoveredDay or lastWindowDay > lastCoveredDay:
            raise NewsContextUnavailableError(
                f'Окно [{windowFrom}, {windowToExclusive}) не покрыто корпусом: '
                f'корпус содержит полные сутки с {firstCoveredDay} по {lastCoveredDay}.'
            )

    def _loadAxisVectors(self, reader: NewsCorpusReader) -> dict[str, np.ndarray]:
        queries: dict[str, np.ndarray] = {}

        for axis, axisQueries in self.configuration.axes.items():
            vector = reader.getAxisVector(axis, axisQueries)
            if vector is None:
                raise NewsContextError(
                    f'В корпусе нет вектора оси {axis!r} для заданных текстов запросов. '
                    f'Считать его здесь нельзя: эмбеддинг новой оси — задача amnesiacDB.'
                )

            queries[axis] = np.asarray(vector, dtype=np.float32)

        return queries

    @staticmethod
    def _getDayNumber(publishedAt: str, windowFrom: date) -> int:
        publishedDay = moscowDate(publishedAt)
        return (publishedDay - windowFrom).days + 1

    @staticmethod
    def _normalize(vectors: np.ndarray) -> np.ndarray:
        normalized = vectors.copy()
        for vector in normalized:
            norm = np.linalg.norm(vector)
            if norm > 0:
                vector /= norm

        return normalized
