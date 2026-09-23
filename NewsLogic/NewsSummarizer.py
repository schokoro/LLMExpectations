from amnesiac import Doc
from amnesiac.summarize import (
    AxisSummariesResult,
    MetaResult,
    SummarizeConfig,
    summarize_axes,
    summarize_meta,
)
from amnesiac.summarize.prompts import RU_MACRO_V1
from openai.types.chat import ChatCompletion

from Logging.BaseLogger import BaseLogger
from NewsLogic.NewsDocument import NewsDocument
from NewsLogic.newsExceptions import NewsContextError
from NewsLogic.newsHelpers import readSecret
from NewsLogic.NewsRagConfiguration import NewsRagConfiguration
from NewsLogic.PinnedOpenRouterClient import PinnedOpenRouterClient


class NewsSummarizer:
    """Двухэтапная суммаризация отобранных новостей через `amnesiac.summarize`.

    Логика суммаризации живёт в пакете `amnesiac` и здесь не дублируется:
    этот класс отвечает только за клиента провайдера и за перевод отобранных
    документов в `Doc`.
    """

    def __init__(self, configuration: NewsRagConfiguration, logger: BaseLogger):
        self.configuration = configuration
        self.logger = logger

    async def preflight(self) -> ChatCompletion:
        """Один короткий запрос через ту же фабрику и пин, что у суммаризации."""
        client = self._createClient(maxRetries=0)
        return await client.chat.completions.create(
            model=self.configuration.summarizeModel,
            messages=[{'role': 'user', 'content': 'Ответь: OK'}],
            temperature=self.configuration.summarizeTemperature,
            max_tokens=1,
        )

    async def buildAxisSummaries(
        self, retrieved: dict[str, list[NewsDocument]]
    ) -> AxisSummariesResult:
        client = self._createClient()

        axes = {
            axis: [
                Doc(
                    text=document.text,
                    channel=document.channel,
                    day_number=document.dayNumber,
                    doc_id=document.messageId,
                )
                for document in documents
            ]
            for axis, documents in retrieved.items()
        }

        self.logger.logDebug(
            f'Summarizing {sum(len(documents) for documents in axes.values())} documents '
            f'over {len(axes)} axes with {self.configuration.summarizeModel}'
        )

        result = await summarize_axes(
            client=client,
            model=self.configuration.summarizeModel,
            axes=axes,
            prompts=RU_MACRO_V1.bind(horizon_days=self.configuration.horizonDays),
            config=SummarizeConfig(
                temperature=self.configuration.summarizeTemperature,
                concurrency=self.configuration.summarizeConcurrency,
                max_failed_axes=self.configuration.summarizeMaxFailedAxes,
            ),
        )

        if result.failed_axes:
            self.logger.logDebug(
                f'Axes failed during summarization: {", ".join(result.failed_axes)}. '
                f'Errors: {result.axis_errors}'
            )

        return result

    async def buildMetaSummary(self, axisSummaries: dict[str, str]) -> MetaResult:
        client = self._createClient()

        return await summarize_meta(
            client=client,
            model=self.configuration.summarizeModel,
            axis_summaries=axisSummaries,
            prompts=RU_MACRO_V1.bind(horizon_days=self.configuration.horizonDays),
            config=SummarizeConfig(
                temperature=self.configuration.summarizeTemperature,
                concurrency=self.configuration.summarizeConcurrency,
                max_failed_axes=self.configuration.summarizeMaxFailedAxes,
            ),
        )

    def _createClient(self, maxRetries: int = 2) -> PinnedOpenRouterClient:
        return PinnedOpenRouterClient(
            provider=self.configuration.summarizeProvider,
            base_url=self.configuration.summarizeBaseUrl,
            api_key=self._getApiKey(),
            timeout=self.configuration.summarizeTimeout,
            max_retries=maxRetries,
        )

    def _getApiKey(self) -> str:
        key = readSecret(self.configuration.summarizeApiKeyVariable)
        if not key:
            raise NewsContextError(
                f'Ключ провайдера не найден: нет ни переменной окружения '
                f'{self.configuration.summarizeApiKeyVariable}, ни строки с ней в .env. '
                f'В репозиторий ключ не попадает: .env в .gitignore.'
            )

        return key
