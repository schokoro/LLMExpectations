import json
import sqlite3
from datetime import date
from pathlib import Path

from NewsLogic.newsExceptions import NewsContextError

failedAxesMigration = 'data/newsDB/migrations/012_summaries_failed_axes.sql'
axisSummariesMigration = 'data/newsDB/migrations/013_axis_summaries.sql'


class NewsSummariesCache:
    """Кеш саммари в проектной базе `project.db`.

    Суммаризация одной даты — десять вызовов LLM, а builder вызывается на
    каждого респондента, поэтому кеш обязателен. Ключ таблицы — `UNIQUE(run_date)`,
    то есть на дату хранится ровно одно актуальное саммари; горизонт и модель
    сверяются при чтении, чтобы чужая строка не подменила результат молча.

    Вместе с текстом хранятся отказавшие оси. Без них саммари, собранное из
    восьми осей вместо девяти, при чтении из кеша выглядело бы полноценным:
    `max_failed_axes > 0` пропускает такую дату как успешную. `NULL` в колонке
    означает не «отказов не было», а «неизвестно» — так помечены строки,
    записанные до миграции.
    """

    def __init__(self, projectDbPath: Path):
        self.projectDbPath = Path(projectDbPath)

    def getSummary(
        self, runDate: date, horizonDays: int, model: str
    ) -> tuple[str, int, tuple[str, ...] | None] | None:
        connection = self._connect()
        try:
            row = connection.execute(
                """
                SELECT summary, doc_count, horizon_days, model, failed_axes
                FROM summaries
                WHERE run_date = ?
                """,
                (runDate.isoformat(),),
            ).fetchone()
        finally:
            connection.close()

        if row is None:
            return None

        summary, documentsCount, storedHorizonDays, storedModel, storedFailedAxes = row
        if storedHorizonDays != horizonDays or storedModel != model:
            return None

        return summary, documentsCount, self._parseFailedAxes(storedFailedAxes)

    def saveSummary(
        self,
        runDate: date,
        horizonDays: int,
        summary: str,
        documentsCount: int,
        model: str,
        failedAxes: tuple[str, ...],
    ) -> None:
        connection = self._connect()
        try:
            connection.execute(
                """
                INSERT OR REPLACE INTO summaries
                    (run_date, horizon_days, summary, doc_count, model, failed_axes)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    runDate.isoformat(),
                    horizonDays,
                    summary,
                    documentsCount,
                    model,
                    json.dumps(list(failedAxes), ensure_ascii=False),
                ),
            )
            connection.commit()
        finally:
            connection.close()

    def saveAxisSummaries(
        self,
        runDate: date,
        horizonDays: int,
        model: str,
        axisSummaries: dict[str, str],
        documentCounts: dict[str, int],
    ) -> None:
        """Сохранить осевые саммари первого этапа.

        Отказавшие оси сюда не попадают: вместо текста `amnesiac` подставляет
        заглушку, и хранить её как саммари значит выдать отсутствие данных за
        данные. Какие оси отвалились, записано в `summaries.failed_axes`.
        """
        if not axisSummaries:
            return

        connection = self._connect()
        try:
            connection.executemany(
                """
                INSERT OR REPLACE INTO axis_summaries
                    (run_date, axis, horizon_days, model, summary, doc_count)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (runDate.isoformat(), axis, horizonDays, model, summary, documentCounts.get(axis))
                    for axis, summary in axisSummaries.items()
                ],
            )
            connection.commit()
        finally:
            connection.close()

    def getAxisSummaries(self, runDate: date, horizonDays: int, model: str) -> dict[str, str]:
        """Осевые саммари даты. Пустой словарь, если их нет или они чужие."""
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT axis, summary
                FROM axis_summaries
                WHERE run_date = ? AND horizon_days = ? AND model = ?
                ORDER BY axis
                """,
                (runDate.isoformat(), horizonDays, model),
            ).fetchall()
        finally:
            connection.close()

        return dict(rows)

    @staticmethod
    def _parseFailedAxes(stored: str | None) -> tuple[str, ...] | None:
        if stored is None:
            return None

        try:
            parsed = json.loads(stored)
        except json.JSONDecodeError as error:
            raise NewsContextError(
                f'Колонка failed_axes содержит не JSON: {stored!r}. Ожидается массив имён осей.'
            ) from error

        if not isinstance(parsed, list) or not all(isinstance(axis, str) for axis in parsed):
            raise NewsContextError(
                f'Колонка failed_axes содержит не массив строк: {stored!r}.'
            )

        return tuple(parsed)

    def _connect(self) -> sqlite3.Connection:
        if not self.projectDbPath.exists():
            raise NewsContextError(f'Проектная база не найдена: {self.projectDbPath}')

        connection = sqlite3.connect(str(self.projectDbPath))
        try:
            connection.execute('SELECT 1 FROM summaries LIMIT 1')
        except sqlite3.OperationalError as error:
            connection.close()
            raise NewsContextError(
                f'В проектной базе {self.projectDbPath} нет таблицы summaries: {error}'
            ) from error

        columns = {row[1] for row in connection.execute('PRAGMA table_info(summaries)')}
        if 'failed_axes' not in columns:
            connection.close()
            raise NewsContextError(
                f'В таблице summaries базы {self.projectDbPath} нет колонки failed_axes. '
                f'Примените миграцию: sqlite3 {self.projectDbPath} < {failedAxesMigration}'
            )

        try:
            connection.execute('SELECT 1 FROM axis_summaries LIMIT 1')
        except sqlite3.OperationalError as error:
            connection.close()
            raise NewsContextError(
                f'В проектной базе {self.projectDbPath} нет таблицы axis_summaries: {error}. '
                f'Примените миграцию: sqlite3 {self.projectDbPath} < {axisSummariesMigration}'
            ) from error

        return connection
