import os
from datetime import UTC, date, datetime, time
from pathlib import Path

from NewsLogic.newsExceptions import NewsContextError
from NewsLogic.NewsRagConfiguration import moscowTimeZone

defaultEnvironmentFile = Path('.env')


def readSecret(name: str, environmentFile: Path = defaultEnvironmentFile) -> str | None:
    """Значение переменной окружения, при её отсутствии — строка из `.env`.

    `python-dotenv` в зависимостях нет и заводить его ради одного файла нельзя,
    поэтому разбор минимальный: `KEY=value`, пустые строки и `#`-комментарии
    пропускаются, окружающие кавычки снимаются. Окружение имеет приоритет.

    Значение не логируется и не попадает в артефакты: `.env` игнорируется git,
    и таким должно остаться.
    """
    value = os.environ.get(name)
    if value:
        return value

    if not environmentFile.exists():
        return None

    for line in environmentFile.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue

        key, _, rawValue = line.partition('=')
        if key.strip() != name:
            continue

        return rawValue.strip().strip('"').strip("'") or None

    return None


def asDate(surveyDate) -> date:
    """Дата опроса приходит и как `date`, и как `datetime`/`pd.Timestamp`.

    Время в ней всегда полуночное и в отборе не участвует: окно строится по
    календарным суткам.
    """
    if isinstance(surveyDate, datetime):
        return surveyDate.date()

    if isinstance(surveyDate, date):
        return surveyDate

    raise TypeError(f'Survey date must be date or datetime, got {type(surveyDate)}')


def moscowDate(corpusTimestamp: str) -> date:
    """Московская дата timestamp корпуса нужна для cutoff и нумерации дней.

    Корпус хранит время в UTC, а контракт окна задан календарными сутками MSK.
    """
    timestamp = datetime.fromisoformat(corpusTimestamp)
    if timestamp.tzinfo is None:
        raise NewsContextError(
            f'Отклонён timestamp {corpusTimestamp!r}: контракт корпуса требует явного смещения UTC.'
        )
    return timestamp.astimezone(moscowTimeZone).date()


def moscowDayStartUtc(moscowDay: date) -> datetime:
    """UTC-момент начала московских суток нужен как явная граница SQL-окна.

    Так день опроса исключается по правилу MSK, а не из-за сравнения форматов.
    """
    moscowMidnight = datetime.combine(moscowDay, time.min, tzinfo=moscowTimeZone)
    return moscowMidnight.astimezone(UTC)
