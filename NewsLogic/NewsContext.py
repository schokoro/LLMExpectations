from dataclasses import dataclass, field
from datetime import date

from NewsLogic.NewsDocument import NewsDocument


@dataclass(frozen=True)
class NewsContext:
    """Новостной контекст на одну дату опроса.

    Контекст один на дату и не зависит от респондента: retrieval по полям
    профиля — отдельное решение, а не побочный эффект интеграции.
    """

    runDate: date
    windowFrom: date
    windowToExclusive: date
    horizonDays: int
    mode: str

    documents: dict[str, list[NewsDocument]]
    summary: str | None = None
    summaryModel: str | None = None
    # None — статус отказавших осей неизвестен: саммари поднято из строки кеша,
    # записанной до появления колонки failed_axes. Пустой кортеж означает
    # проверенное «не отвалилось ничего», и смешивать эти два случая нельзя.
    failedAxes: tuple[str, ...] | None = ()
    summaryFromCache: bool = False
    corpusManifest: dict = field(default_factory=dict)

    @property
    def documentsCount(self) -> int:
        return sum(len(documents) for documents in self.documents.values())

    def toArtefact(self, configuration: dict) -> dict:
        return {
            'run_date': self.runDate.isoformat(),
            'window_from': self.windowFrom.isoformat(),
            'window_to_exclusive': self.windowToExclusive.isoformat(),
            'horizon_days': self.horizonDays,
            'mode': self.mode,
            'doc_count': self.documentsCount,
            'summary_model': self.summaryModel,
            'summary_from_cache': self.summaryFromCache,
            'failed_axes': None if self.failedAxes is None else list(self.failedAxes),
            'config': configuration,
            'corpus_manifest': self.corpusManifest,
            'documents': {
                axis: [document.toDictionary() for document in documents]
                for axis, documents in self.documents.items()
            },
            'summary': self.summary,
        }
