import re
from datetime import datetime, date
from pathlib import Path

months = {
        'января': 1, 'февраля': 2, 'марта': 3, 'апреля': 4,
        'мая': 5, 'июня': 6, 'июля': 7, 'августа': 8,
        'сентября': 9, 'октября': 10, 'ноября': 11, 'декабря': 12
    }

months_ru = {
    1: 'январь',
    2: 'февраль',
    3: 'март',
    4: 'апрель',
    5: 'май',
    6: 'июнь',
    7: 'июль',
    8: 'август',
    9: 'сентябрь',
    10: 'октябрь',
    11: 'ноябрь',
    0: 'декабрь'
}


def processIfNone(data):
    if data is None or data == 'None' or data == '':
        return 'нет информации'

    return str(data)

def processYesNo(data):
    if data == '1':
        return True

    return False

def processBoolToYesNo(data: bool):
    if data:
        return 'Да'

    return 'Нет'

def checkNoAnswer(value):
    noAnswerSet = {99999997, 99999998, 99999999}
    if value in noAnswerSet or value is None or value == '':
        return True

    return False

def getNoAnswerDescription(value):
    if value == 99999997:
        return 'затрудняюсь ответить'
    elif value == 99999998:
        return 'отказ от ответа'
    elif value == 99999999:
        return 'нет ответа'
    elif value is None or value == '':
        return 'нет информации'

    raise ValueError(f'Incorrect value: {value}')

def getSafeDescription(value):
    if checkNoAnswer(value):
        return getNoAnswerDescription(value)

    return value

def getDirection(inflation: float, isInflation: bool):

    if inflation > 0.0:
        return "подорожал" if not isInflation else 'повысилась'

    if inflation < 0.0:
        return "подешевел" if not isInflation else 'понизилась'

    return "цена не изменилась" if not isInflation else 'не изменилась'

def getDescriptionMonth(inflation: float, month: int, isInflation: bool = False):

    description = getDeltaDescription(month)
    if inflation is None:
        return f'за {description} нет информации'

    direction = getDirection(inflation, isInflation)
    if abs(inflation) < 0.00001:
        return f"за {description} не изменилась"

    clearInflation = (inflation + 1)**(month/12) - 1
    return f'за {description} {direction} на {showInflation(abs(clearInflation))}%'

def getDescriptionWeeks(inflation: float, weeks: int, isInflation: bool = False):
    description = getDescriptionNumberWeeks(weeks)
    if inflation is None:
        return f'за {description} нет информации'

    direction = getDirection(inflation, isInflation)
    if abs(inflation) < 0.00001:
        return f"{description} не изменилась"

    clearInflation = (inflation + 1) ** (weeks*7 / 365) - 1
    return f'{description} {direction} на {showInflation(abs(clearInflation))}%'

def getDescriptionNumberWeeks(weeks: int):
    if weeks == 1:
        return 'за последнюю 1 неделю'

    if weeks in {2, 3, 4}:
        return f'за последние {weeks} недели'

    return f'за последние {weeks} недель'

def getTop5(map, goods: dict[str, float]):
    rosstatGoods = dict[str, float]()

    for k, v in goods.items():
        if k not in map:
            continue

        g = map[k]
        if g == ('нет соответствующей категории'):
            continue

        if g in rosstatGoods:
            rosstatGoods[g] += v
        else:
            rosstatGoods[g] = v

    top_5 = sorted(rosstatGoods.items(), key=lambda x: x[1], reverse=True)[:min(5, len(rosstatGoods))]
    return [item[0] for item in top_5]


def parseRosstateMonth(value: str, year: int) -> date:
    # Извлекаем день и месяц
    parts = value.replace('на ', '').replace('*', '').strip().split()
    day = int(parts[0])
    month_name = parts[1].lower()
    month = months[month_name]

    return datetime(year, month, day).date()

def showInflation(inflation: float)->str:
    if inflation is None:
        return 'нет данных'

    return f'{inflation*100:.1f}'

def getDeltaDescription(offsetMonth: int):
    if offsetMonth == 1:
        return '1 полный календарный месяц'

    if offsetMonth in {2, 3, 4}:
        return f'{offsetMonth} полных календарных месяца'

    return f'{offsetMonth} полных календарных месяцев'

def getUsdRubDirection(rate):
    if rate == None:
        return None

    if rate > 0:
        return 'обесценился'

    if rate < 0:
        return 'укрепился'

    return 'стабилен'

def loadRlmsGoodsToRosstatGoodsMap(pathes: list[Path]) -> dict[str, str]:

    result = dict[str, str]()
    pattern = r'^[^\s]+'
    for path in pathes:
        with open(path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            for line in lines:
                key = re.match(pattern, line).group().replace('.', '_').strip()
                value = line.split(';')[1].strip()
                result[key] = value

    return result
