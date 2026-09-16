from dataclasses import dataclass, field, replace
from datetime import timedelta, timezone
from pathlib import Path

# Контракт корпуса. Несовпадение любого из этих значений означает, что векторы
# документов и векторы осей посчитаны разными моделями, а внешне это никак не
# проявляется (data/newsDB/README.md, «Три ловушки»).
corpusSchemaVersion = 1
corpusEmbeddingModel = 'ai-forever/FRIDA'
corpusEmbeddingDimension = 1536
corpusEmbeddingDtype = '<f4'
corpusEmbeddingInput = 'lead'
moscowUtcOffsetHours = 3
moscowTimeZone = timezone(timedelta(hours=moscowUtcOffsetHours))

twoStageMode = 'two_stage'
rawMode = 'raw'
supportedModes = (twoStageMode, rawMode)

# Оси и тексты запросов, по которым посчитаны векторы в query_vectors.
# Порядок значим: он задаёт порядок осевых блоков в мета-промпте и в секции raw.
# Тексты менять нельзя — от них берётся query_hash, входящий в ключ вектора.
defaultAxes: dict[str, list[str]] = {
    'дкп': ['решение по ключевой ставке', 'денежно-кредитная политика Банка России'],
    'инфляция': ['рост потребительских цен', 'инфляция в России'],
    'продовольствие': ['цены на продукты питания'],
    'курс': ['курс рубля к доллару', 'ослабление рубля'],
    'тарифы': ['повышение тарифов ЖКХ', 'цены на бензин'],
    'зарплаты': ['рост зарплат', 'реальные доходы населения'],
    'труд': ['дефицит кадров в России', 'безработица в России'],
    'кризис': [
        'экономический кризис в России',
        'экономическая неопределённость',
        'санкции против России',
    ],
    'бюджет': ['бюджетные расходы', 'дефицит бюджета'],
}


@dataclass(frozen=True)
class NewsRagConfiguration:
    """Конфигурация новостного RAG: отбор, суммаризация, пути к базам."""

    axes: dict[str, list[str]] = field(default_factory=lambda: dict(defaultAxes))
    horizonDays: int = 14
    topKPerAxis: int = 50
    dedupThreshold: float = 0.9
    excludeChannels: tuple[str, ...] = ('prime1',)

    mode: str = twoStageMode

    summarizeModel: str = 'deepseek/deepseek-v4-flash'
    summarizeBaseUrl: str = 'https://openrouter.ai/api/v1'
    summarizeApiKeyVariable: str = 'OPENROUTER_API_KEY'
    summarizeTemperature: float = 0.3
    summarizeConcurrency: int = 5
    summarizeMaxFailedAxes: int = 2
    summarizeTimeout: float = 600.0
    # Повтор всей даты при сбое суммаризации. С `amnesiac` 0.2 пустой ответ модели
    # ретраится уже внутри пакета (D-028), а вот превышение лимита отказавших осей
    # транзиентным отказом не считается и уходит наверх с первой попытки. Одна такая
    # ошибка роняет прогон целиком, поэтому повтор живёт здесь.
    # Попытки перемножаются: неудачная дата стоит до summarizeAttempts × max_attempts
    # обращений на вызов и выдерживает паузы обоих уровней.
    summarizeAttempts: int = 3
    summarizeRetryDelaySeconds: float = 30.0

    corpusPath: Path = Path('data/newsDB/corpus.db')
    projectDbPath: Path = Path('data/newsDB/project.db')
    artefactsFolder: Path | None = None

    def __post_init__(self):
        if self.mode not in supportedModes:
            raise ValueError(f'Unknown news mode {self.mode!r}, expected one of {supportedModes}')
        if self.horizonDays <= 0:
            raise ValueError(f'horizonDays must be positive, got {self.horizonDays}')
        if self.topKPerAxis <= 0:
            raise ValueError(f'topKPerAxis must be positive, got {self.topKPerAxis}')
        if not self.axes:
            raise ValueError('axes cannot be empty')
        if self.summarizeAttempts < 1:
            raise ValueError(f'summarizeAttempts must be at least 1, got {self.summarizeAttempts}')
        if self.summarizeRetryDelaySeconds < 0:
            raise ValueError(
                f'summarizeRetryDelaySeconds cannot be negative, got {self.summarizeRetryDelaySeconds}'
            )

    def withArtefactsFolder(self, artefactsFolder: Path) -> 'NewsRagConfiguration':
        return replace(self, artefactsFolder=artefactsFolder)

    def toDictionary(self) -> dict:
        return {
            'axes': {axis: list(queries) for axis, queries in self.axes.items()},
            'horizon_days': self.horizonDays,
            'top_k_per_axis': self.topKPerAxis,
            'dedup_threshold': self.dedupThreshold,
            'exclude_channels': list(self.excludeChannels),
            'mode': self.mode,
            'summarize_model': self.summarizeModel,
            'summarize_base_url': self.summarizeBaseUrl,
            'summarize_temperature': self.summarizeTemperature,
        }
