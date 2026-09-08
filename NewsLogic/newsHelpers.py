import os
from datetime import date, datetime
from pathlib import Path

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
