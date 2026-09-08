from NewsLogic import NewsRagConfiguration as newsRagConfiguration
from NewsLogic.NewsContext import NewsContext
from NewsLogic.newsExceptions import NewsContextError

# Текст секции — данные под регресс-тестом: он сравнивается с фикстурой
# побайтно. Менять формулировки можно только вместе с фикстурой.
summaryHeader = ('Новостной фон за {horizonDays} дней, предшествовавших опросу. '
                 'Дни пронумерованы от начала периода: день 1 — самый ранний, '
                 'день {horizonDays} — накануне опроса.')

rawHeader = ('Новостные сообщения за {horizonDays} дней, предшествовавших опросу, '
             'сгруппированные по темам. Дни пронумерованы от начала периода: '
             'день 1 — самый ранний, день {horizonDays} — накануне опроса.')

axisHeaderTemplate = '--- Тема: {axis} ---'
documentTemplate = '[день {dayNumber} | {channel}] {text}'
emptyAxisText = '(нет сообщений по теме)'


def renderNewsSection(context: NewsContext) -> str:
    if context.mode == newsRagConfiguration.twoStageMode:
        return _renderTwoStage(context)

    if context.mode == newsRagConfiguration.rawMode:
        return _renderRaw(context)

    raise NewsContextError(f'Неизвестный режим новостной секции: {context.mode!r}')


def _renderTwoStage(context: NewsContext) -> str:
    if not context.summary:
        raise NewsContextError(
            f'Саммари на {context.runDate} пустое. Пустая секция «Новости» превратила бы '
            f'эксперимент news в no-news, поэтому это отказ, а не пропуск.'
        )

    header = summaryHeader.format(horizonDays=context.horizonDays)

    return f'{header}\n\n{context.summary}'


def _renderRaw(context: NewsContext) -> str:
    blocks = [rawHeader.format(horizonDays=context.horizonDays)]

    for axis, documents in context.documents.items():
        lines = [axisHeaderTemplate.format(axis=axis)]

        if documents:
            lines.extend(
                documentTemplate.format(
                    dayNumber=document.dayNumber,
                    channel=document.channel,
                    text=document.text,
                )
                for document in documents
            )
        else:
            lines.append(emptyAxisText)

        blocks.append('\n'.join(lines))

    return '\n\n'.join(blocks)
