class NewsContextError(Exception):
    """Базовая ошибка новостного контекста."""


class NewsContextUnavailableError(NewsContextError):
    """Окно новостей не покрыто корпусом: дата опроса вне диапазона сбора."""


class NewsContextNotPreparedError(NewsContextError):
    """Контекст на дату не посчитан. Retrieval внутри builder'а запрещён."""
