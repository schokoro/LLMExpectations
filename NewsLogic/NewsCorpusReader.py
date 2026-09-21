import hashlib
import json
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Self

import numpy as np
import sqlite_vec

from NewsLogic import NewsRagConfiguration as newsRagConfiguration
from NewsLogic.newsExceptions import NewsContextError
from NewsLogic.newsHelpers import moscowDate

# Полный скан messages дорог: успешная проверка кешируется на весь процесс.
# Ключ — разрешённый путь, размер и mtime_ns файла; перестройка меняет ключ.
corpusDateFormatChecks: dict[tuple[Path, int, int], bool] = {}


def canonicalQueryList(queries: list[str]) -> str:
    """Сериализация списка запросов ровно так, как её делал amnesiacDB."""
    return json.dumps(queries, ensure_ascii=False, separators=(',', ':'))


def queryListHash(queries: list[str]) -> str:
    return hashlib.sha256(canonicalQueryList(queries).encode('utf-8')).hexdigest()


class NewsCorpusReader:
    """Read-only доступ к корпусу новостей.

    Корпус общий на несколько проектов, поэтому соединение всегда `mode=ro`:
    запись отсюда способна повредить работу соседнего проекта.
    """

    def __init__(self, corpusPath: Path):
        self.corpusPath = Path(corpusPath)
        self.connection: sqlite3.Connection | None = None

    def __enter__(self) -> Self:
        self.open()
        return self

    def __exit__(self, exceptionType, exceptionValue, traceback):
        self.close()
        return False

    def open(self) -> None:
        if not self.corpusPath.exists():
            raise NewsContextError(f'Корпус не найден: {self.corpusPath}')

        # Без загруженного vec0 корпус не читается вообще: в схеме есть
        # виртуальная таблица, и SQLite падает на любом запросе.
        connection = sqlite3.connect(f'file:{self.corpusPath}?mode=ro', uri=True)
        connection.enable_load_extension(True)
        sqlite_vec.load(connection)
        connection.enable_load_extension(False)

        self.connection = connection

    def close(self) -> None:
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def assertCorpusContract(self) -> None:
        """Сверить эмбеддинги, схему и формат дат до отбора окна."""
        meta = self.getCorpusMeta()

        expected = {
            'schema_version': str(newsRagConfiguration.corpusSchemaVersion),
            'embedding_model': newsRagConfiguration.corpusEmbeddingModel,
            'embedding_dim': str(newsRagConfiguration.corpusEmbeddingDimension),
            'embedding_dtype': newsRagConfiguration.corpusEmbeddingDtype,
            'embedding_input': newsRagConfiguration.corpusEmbeddingInput,
        }

        for key, expectedValue in expected.items():
            actualValue = meta.get(key)
            if actualValue != expectedValue:
                raise NewsContextError(
                    f'Контракт корпуса нарушен: {key} = {actualValue!r}, ожидалось {expectedValue!r}. '
                    f'Векторы несовместимы, продолжать нельзя.'
                )

        resolvedPath = self.corpusPath.resolve()
        statistics = resolvedPath.stat()
        corpusIdentity = (resolvedPath, statistics.st_size, statistics.st_mtime_ns)
        if corpusIdentity not in corpusDateFormatChecks:
            rowCount, invalidCount = self._getConnection().execute(
                'SELECT COUNT(*), COALESCE(SUM(date NOT GLOB ?), 0) FROM messages',
                (newsRagConfiguration.corpusDatePattern,),
            ).fetchone()
            if rowCount == 0:
                raise NewsContextError(
                    'Контракт корпуса нарушен: messages.date — корпус пуст (0 строк). '
                    'Границам окна доверять нельзя.'
                )
            if invalidCount:
                invalidValues = self._getConnection().execute(
                    'SELECT date FROM messages WHERE date NOT GLOB ? LIMIT 3',
                    (newsRagConfiguration.corpusDatePattern,),
                ).fetchall()
                raise NewsContextError(
                    f'Контракт корпуса нарушен: messages.date — нарушений: {invalidCount}, '
                    f'примеры: {[row[0] for row in invalidValues]!r}, '
                    f'ожидался шаблон {newsRagConfiguration.corpusDatePattern!r}. '
                    f'Границам окна доверять нельзя.'
                )
            corpusDateFormatChecks[corpusIdentity] = True

    def getCorpusMeta(self) -> dict[str, str]:
        try:
            rows = self._getConnection().execute('SELECT key, value FROM corpus_meta').fetchall()
        except sqlite3.OperationalError as error:
            raise NewsContextError(f'Не читается corpus_meta: {error}') from error

        return {row[0]: row[1] for row in rows}

    def getCoverage(self) -> tuple[date, date]:
        """Первый и последний полностью покрытые корпусом дни.

        Крайние сутки корпуса собраны частично (`corpus_start` — вечер,
        `corpus_end` — ночь), поэтому в покрытие они не входят.
        """
        meta = self.getCorpusMeta()
        corpusStart = self._getTimestamp(meta, 'corpus_start')
        corpusEnd = self._getTimestamp(meta, 'corpus_end')

        return moscowDate(corpusStart) + timedelta(days=1), moscowDate(corpusEnd) - timedelta(days=1)

    def loadWindow(
        self,
        windowFromUtc: datetime,
        windowToExclusiveUtc: datetime,
        excludeChannels: tuple[str, ...] = (),
    ) -> list[dict]:
        """Сообщения с эмбеддингами между явными UTC-моментами границ.

        UTC-границы получены из московских полуночей; верхняя исключающая, поэтому
        московский день опроса не входит. Все timestamp корпуса имеют единый
        формат с суффиксом `+00:00`, поэтому строковое сравнение совпадает с
        хронологическим.

        Порядок `(date, message_id)` — не `date`, как в blind_prophet: на
        одинаковых таймстампах порядок иначе не определён, а от него зависят и
        дедупликация, и выдача.
        """
        sql = """
            SELECT message_id, channel, date, processed_text, embedding
            FROM message_embeddings
            WHERE date >= ? AND date < ?
        """
        parameters: list = [windowFromUtc.isoformat(), windowToExclusiveUtc.isoformat()]

        if excludeChannels:
            placeholders = ','.join('?' * len(excludeChannels))
            sql += f' AND channel NOT IN ({placeholders})'
            parameters.extend(excludeChannels)

        sql += ' ORDER BY date, message_id'

        rows = self._getConnection().execute(sql, parameters).fetchall()

        return [
            {
                'messageId': row[0],
                'channel': row[1],
                'date': row[2],
                'processedText': row[3],
                'embeddingBlob': row[4],
            }
            for row in rows
        ]

    def countBandMessages(
        self,
        bandFromUtc: datetime,
        bandToExclusiveUtc: datetime,
        excludeChannels: tuple[str, ...] = (),
    ) -> int:
        """Число сообщений с эмбеддингами в UTC-полосе для живого cutoff-гейта."""
        sql = """
            SELECT COUNT(*) FROM message_embeddings
            WHERE date >= ? AND date < ?
        """
        parameters: list = [bandFromUtc.isoformat(), bandToExclusiveUtc.isoformat()]
        if excludeChannels:
            placeholders = ','.join('?' * len(excludeChannels))
            sql += f' AND channel NOT IN ({placeholders})'
            parameters.extend(excludeChannels)

        return self._getConnection().execute(sql, parameters).fetchone()[0]

    def getAxisVector(self, axis: str, queries: list[str]) -> np.ndarray | None:
        """Вектор оси по ПОЛНОМУ ключу.

        Кеш `query_vectors` общий на несколько проектов: одноимённые оси с
        другими текстами запросов лежат рядом, и выбор по одному имени молча
        найдёт чужой вектор.
        """
        row = self._getConnection().execute(
            """
            SELECT vector
            FROM query_vectors
            WHERE axis = ?
              AND query_hash = ?
              AND embedding_model = ?
              AND dimension = ?
            """,
            (
                axis,
                queryListHash(queries),
                newsRagConfiguration.corpusEmbeddingModel,
                newsRagConfiguration.corpusEmbeddingDimension,
            ),
        ).fetchone()

        if row is None:
            return None

        vector = np.frombuffer(row[0], dtype=newsRagConfiguration.corpusEmbeddingDtype).copy()
        if vector.shape != (newsRagConfiguration.corpusEmbeddingDimension,):
            raise NewsContextError(
                f'Вектор оси {axis!r} имеет размерность {vector.shape}, '
                f'ожидалась {(newsRagConfiguration.corpusEmbeddingDimension,)}'
            )

        return vector

    def getCorpusManifest(self) -> dict:
        """Машинный манифест корпуса: что именно читалось в этом прогоне."""
        statistics = self.corpusPath.resolve().stat()

        return {
            'path': str(self.corpusPath.resolve()),
            'size_bytes': statistics.st_size,
            'mtime': statistics.st_mtime,
            'meta': self.getCorpusMeta(),
        }

    def _getConnection(self) -> sqlite3.Connection:
        if self.connection is None:
            raise NewsContextError('Соединение с корпусом не открыто')

        return self.connection

    @staticmethod
    def _getTimestamp(meta: dict[str, str], key: str) -> str:
        value = meta.get(key)
        if not value:
            raise NewsContextError(f'В corpus_meta нет ключа {key}')

        return value
