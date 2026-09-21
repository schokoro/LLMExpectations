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
corpusDatePattern = (
    '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]+00:00'
)
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
