"""Проверка провайдера суммаризации из той оболочки, где запускается прогон.

Печатает, откуда взялся ключ и его отпечаток (не сам ключ), затем делает один
настоящий осевой запрос — тот же, что шлёт прогон.

    .venv/bin/python -u checkNewsProvider.py
"""

import asyncio
import hashlib
import os
from datetime import date
from pathlib import Path

from amnesiac import Doc
from amnesiac.summarize.prompts import RU_MACRO_V1
from openai import AsyncOpenAI, OpenAIError

from Logging.SimpleLogger import SimpleLogger
from NewsLogic.newsHelpers import readSecret
from NewsLogic.NewsRagConfiguration import NewsRagConfiguration
from NewsLogic.NewsRetriever import NewsRetriever

probeDate = date(2019, 11, 8)
probeAxis = 'дкп'


class Quiet(SimpleLogger):
    def logDebug(self, obj):
        pass


def fingerprint(value: str | None) -> str:
    if not value or not value.strip():
        return 'нет'
    return f'длина {len(value.strip())}, отпечаток {hashlib.sha256(value.strip().encode()).hexdigest()[:12]}'


configuration = NewsRagConfiguration()

print('=== откуда берётся ключ ===')
print(f'переменная окружения OPENROUTER_API_KEY: {fingerprint(os.environ.get("OPENROUTER_API_KEY"))}')

envPath = Path('.env')
fromFile = None
if envPath.exists():
    for line in envPath.read_text(encoding='utf-8').splitlines():
        if line.strip().startswith('OPENROUTER_API_KEY'):
            fromFile = line.split('=', 1)[1].strip().strip('"').strip("'")
print(f'.env: {fingerprint(fromFile)}')
print(f'фактически используется: {fingerprint(readSecret("OPENROUTER_API_KEY"))}')
print('  (окружение приоритетнее .env — если отпечатки разные, прогон шлёт запросы другим ключом)')

print()
print('=== живой осевой запрос ===')
print(f'дата {probeDate}, ось {probeAxis}, модель {configuration.summarizeModel}')

prompts = RU_MACRO_V1.bind(horizon_days=configuration.horizonDays)
documents = NewsRetriever(configuration, Quiet()).retrieve(probeDate)[probeAxis]
docs = [Doc(text=x.text, channel=x.channel, day_number=x.dayNumber, doc_id=x.messageId)
        for x in documents]
messages = [
    {'role': 'system', 'content': prompts._render_axis_system(axis=probeAxis)},
    {'role': 'user', 'content': prompts._render_axis_user(axis=probeAxis, docs=prompts._render_docs(docs))},
]


async def main() -> None:
    client = AsyncOpenAI(
        base_url=configuration.summarizeBaseUrl,
        api_key=readSecret('OPENROUTER_API_KEY'),
        timeout=configuration.summarizeTimeout,
    )
    try:
        response = await client.chat.completions.create(
            model=configuration.summarizeModel,
            messages=messages,
            temperature=configuration.summarizeTemperature,
        )
        content = response.choices[0].message.content
        print(f'OK: {len(documents)} документов, ответ {len(content) if content else 0} символов')
    except OpenAIError as error:
        # Диагностика: нужен именно текст отказа провайдера, каким бы он ни был.
        # OpenAIError — общий предок и для 403, и для сетевых ошибок SDK.
        print(f'FAIL: {type(error).__name__}: {error}')


asyncio.run(main())
