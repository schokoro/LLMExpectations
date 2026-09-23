from types import SimpleNamespace
from typing import Any

from openai import AsyncOpenAI


class PinnedOpenRouterClient:
    """Клиент суммаризации с обязательным пином провайдера OpenRouter."""

    # Временный мост до сквозных параметров роутинга в amnesiac; затем удалить.
    # Черновик issue: artefacts/E01_news_rag/S08_ablation_run/
    # issue_amnesiac_provider_routing.md — публикует человек.
    def __init__(self, provider: str, **kwargs: Any) -> None:
        if not isinstance(provider, str) or not provider.strip():
            raise ValueError('Провайдер OpenRouter должен быть явно задан')
        self._provider = provider
        self._client = AsyncOpenAI(**kwargs)
        self.chat = SimpleNamespace(completions=self)

    async def create(self, **kwargs: Any) -> Any:
        """Сохраняет дополнительные поля; попытка передать provider — ошибка."""
        extraBody = dict(kwargs.pop('extra_body', None) or {})
        if 'provider' in extraBody:
            raise ValueError('Поле provider нельзя переопределять поверх пина OpenRouter')
        extraBody['provider'] = {'order': [self._provider], 'allow_fallbacks': False}
        return await self._client.chat.completions.create(**kwargs, extra_body=extraBody)
