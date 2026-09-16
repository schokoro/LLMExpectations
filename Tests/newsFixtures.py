"""Golden fixture корпуса и проектной базы для тестов новостного RAG.

Живой корпус — 15 ГБ и общий на несколько проектов, поэтому тесты работают на
маленькой базе с той же схемой: вью `message_embeddings`, виртуальная таблица
`vec0`, кеш `query_vectors` с полным ключом. Состав фикстуры зафиксирован здесь
и меняется только вместе с ожиданиями тестов.
"""

import math
import sqlite3
from pathlib import Path

import numpy as np
import sqlite_vec

from NewsLogic.NewsCorpusReader import canonicalQueryList, queryListHash

embeddingDimension = 1536
embeddingModel = 'ai-forever/FRIDA'

corpusStart = '2022-03-01T21:30:00+00:00'
corpusEnd = '2022-04-01T21:30:00+00:00'

runDate = '2022-03-25'
horizonDays = 3

firstAxis = 'ось-а'
secondAxis = 'ось-б'
axes = {
    firstAxis: ['первый запрос оси а'],
    secondAxis: ['первый запрос оси б', 'второй запрос оси б'],
}

# id, канал, время публикации, валидность, наличие эмбеддинга, угол, номер шумовой
# координаты, текст. Угол задаёт близость к осям: 0° — точно ось «а», 90° — ось «б».
fixtureMessages = [
    (1, 'tass', '2022-03-21T23:50:00+00:00', 1, True, 0, 0,
     'сообщение после начала окна по Москве, но предыдущих суток по UTC'),
    (2, 'tass', '2022-03-22T00:10:00+00:00', 1, True, 10, 1, 'сообщение первого дня окна'),
    (3, 'tass', '2022-03-23T12:00:00+00:00', 1, True, 30, 2, 'сообщение второго дня окна'),
    (4, 'tass', '2022-03-24T23:59:00+00:00', 1, True, 50, 3,
     'сообщение дня опроса по Москве, но предыдущих суток по UTC'),
    (5, 'tass', '2022-03-25T00:01:00+00:00', 1, True, 5, 4, 'сообщение ночью в день опроса'),
    (6, 'tass', '2022-03-25T10:00:00+00:00', 1, True, 15, 5, 'сообщение днём в день опроса'),
    (7, 'prime1', '2022-03-23T08:00:00+00:00', 1, True, 20, 6, 'сообщение исключённого канала'),
    (8, 'tass', '2022-03-23T09:00:00+00:00', 0, True, 25, 7, 'невалидное сообщение'),
    (9, 'tass', '2022-03-23T10:00:00+00:00', 1, False, 35, 8, 'сообщение без эмбеддинга'),
    (10, 'rbc', '2022-03-23T13:00:00+00:00', 1, True, 30, 2,
     'сообщение второго дня окна, почти дубль предыдущего с более длинным текстом'),
    (11, 'tass', '2022-03-21T20:59:00+00:00', 1, True, 40, 9,
     'сообщение за минуту до начала окна по московскому времени'),
    (12, 'tass', '2022-03-24T20:30:00+00:00', 1, True, 60, 10,
     'сообщение последнего дня окна до московской полуночи'),
]

inWindowMessageIds = [1, 2, 3, 12]
duplicateMessageId = 10


def buildDocumentVector(angleDegrees: int, noiseIndex: int) -> np.ndarray:
    """Вектор документа: направление задаёт угол, шумовая координата разводит документы.

    Косинус между документами с разными шумовыми координатами не превышает 0.49,
    то есть ниже порога дедупликации; документы с одинаковыми углом и шумовой
    координатой совпадают точно и должны схлопываться.
    """
    vector = np.zeros(embeddingDimension, dtype='<f4')
    angle = math.radians(angleDegrees)

    vector[0] = 0.7 * math.cos(angle)
    vector[1] = 0.7 * math.sin(angle)
    vector[2 + noiseIndex] = math.sqrt(1.0 - 0.7 ** 2)

    return vector


def buildAxisVector(index: int) -> np.ndarray:
    vector = np.zeros(embeddingDimension, dtype='<f4')
    vector[index] = 1.0

    return vector


def createCorpusFixture(path: Path) -> Path:
    """Создать корпус-фикстуру со схемой боевого корпуса."""
    connection = sqlite3.connect(str(path))
    connection.enable_load_extension(True)
    sqlite_vec.load(connection)
    connection.enable_load_extension(False)

    connection.executescript(
        """
        CREATE TABLE channels (
            id INTEGER PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            title TEXT,
            last_scraped_msg_id INTEGER,
            scraped_at TIMESTAMP
        );
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY,
            channel_id INTEGER REFERENCES channels(id),
            tg_message_id INTEGER NOT NULL,
            text TEXT,
            date TIMESTAMP NOT NULL,
            views INTEGER,
            forwards INTEGER,
            reply_to_msg_id INTEGER,
            media_type TEXT,
            raw_json TEXT,
            UNIQUE(channel_id, tg_message_id)
        );
        CREATE TABLE processed_messages (
            message_id INTEGER PRIMARY KEY REFERENCES messages(id),
            processed_text TEXT NOT NULL,
            is_valid BOOLEAN NOT NULL DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE VIRTUAL TABLE vec_messages USING vec0(
            message_id INTEGER PRIMARY KEY,
            embedding FLOAT[1536]
        );
        CREATE TABLE query_vectors (
            axis TEXT NOT NULL,
            query_hash TEXT NOT NULL,
            query_list_json TEXT NOT NULL,
            embedding_model TEXT NOT NULL,
            dimension INTEGER NOT NULL CHECK (dimension > 0),
            dtype TEXT NOT NULL CHECK (dtype = '<f4'),
            vector BLOB NOT NULL,
            computed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (axis, query_hash, embedding_model, dimension),
            CHECK (length(vector) = dimension * 4)
        );
        CREATE TABLE corpus_meta (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE VIEW message_embeddings AS
        SELECT
            m.id AS message_id,
            ch.username AS channel,
            m.date AS date,
            pm.processed_text,
            v.embedding AS embedding
        FROM vec_messages v
        JOIN processed_messages pm ON pm.message_id = v.message_id
        JOIN messages m ON m.id = pm.message_id
        JOIN channels ch ON ch.id = m.channel_id
        WHERE pm.is_valid = 1;
        """
    )

    connection.executemany(
        'INSERT INTO corpus_meta (key, value) VALUES (?, ?)',
        [
            ('schema_version', '1'),
            ('embedding_model', embeddingModel),
            ('embedding_dim', str(embeddingDimension)),
            ('embedding_dtype', '<f4'),
            ('embedding_input', 'lead'),
            ('corpus_start', corpusStart),
            ('corpus_end', corpusEnd),
        ],
    )

    channels = {}
    for message in fixtureMessages:
        channelName = message[1]
        if channelName not in channels:
            channels[channelName] = len(channels) + 1
            connection.execute(
                'INSERT INTO channels (id, username, title) VALUES (?, ?, ?)',
                (channels[channelName], channelName, channelName),
            )

    for messageId, channelName, publishedAt, isValid, hasEmbedding, angle, noiseIndex, text in fixtureMessages:
        connection.execute(
            'INSERT INTO messages (id, channel_id, tg_message_id, text, date) VALUES (?, ?, ?, ?, ?)',
            (messageId, channels[channelName], messageId, text, publishedAt),
        )
        connection.execute(
            'INSERT INTO processed_messages (message_id, processed_text, is_valid) VALUES (?, ?, ?)',
            (messageId, text, isValid),
        )
        if hasEmbedding:
            connection.execute(
                'INSERT INTO vec_messages (message_id, embedding) VALUES (?, ?)',
                (messageId, buildDocumentVector(angle, noiseIndex).tobytes()),
            )

    _insertAxisVector(connection, firstAxis, axes[firstAxis], buildAxisVector(0))
    _insertAxisVector(connection, secondAxis, axes[secondAxis], buildAxisVector(1))

    # Ловушка №2: одноимённая ось другого проекта с другими текстами запросов.
    # Её вектор направлен по второй оси, поэтому выбор по одному имени изменил бы выдачу.
    _insertAxisVector(connection, firstAxis, ['чужой запрос другого проекта'], buildAxisVector(1))

    connection.commit()
    connection.close()

    return path


def createProjectDbFixture(path: Path, withFailedAxes: bool = True, withAxisSummaries: bool = True) -> Path:
    """Проектная база с переносимым ядром схемы (data/newsDB/SCHEMA.md).

    `withFailedAxes=False` даёт схему до миграции 012, `withAxisSummaries=False`
    — до 013. Обе нужны, чтобы проверить, что кеш замечает недостающую схему и
    говорит об этом, а не падает на SQL или, того хуже, молча теряет данные.
    """
    failedAxesColumn = ',\n            failed_axes   TEXT' if withFailedAxes else ''
    axisSummariesTable = """
        CREATE TABLE axis_summaries (
            run_date      TEXT NOT NULL,
            axis          TEXT NOT NULL,
            horizon_days  INTEGER NOT NULL CHECK (horizon_days > 0),
            model         TEXT,
            summary       TEXT NOT NULL,
            doc_count     INTEGER,
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (run_date, axis)
        );
    """ if withAxisSummaries else ''

    connection = sqlite3.connect(str(path))
    connection.executescript(
        f"""
        CREATE TABLE summaries (
            id            INTEGER PRIMARY KEY,
            run_date      TEXT NOT NULL UNIQUE,
            horizon_days  INTEGER NOT NULL CHECK (horizon_days > 0),
            summary       TEXT NOT NULL,
            doc_count     INTEGER,
            model         TEXT,
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP{failedAxesColumn}
        );
        {axisSummariesTable}
        """
    )
    connection.commit()
    connection.close()

    return path


def _insertAxisVector(connection: sqlite3.Connection, axis: str, queries: list[str], vector: np.ndarray) -> None:
    connection.execute(
        """
        INSERT INTO query_vectors
            (axis, query_hash, query_list_json, embedding_model, dimension, dtype, vector)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            axis,
            queryListHash(queries),
            canonicalQueryList(queries),
            embeddingModel,
            embeddingDimension,
            '<f4',
            vector.astype('<f4').tobytes(),
        ),
    )
