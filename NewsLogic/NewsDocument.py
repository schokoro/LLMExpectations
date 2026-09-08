from dataclasses import dataclass


@dataclass(frozen=True)
class NewsDocument:
    """Отобранное новостное сообщение в терминах одной оси.

    dayNumber отсчитывается от начала окна: 1 — самый ранний день окна.
    position — позиция в выдаче оси после дедупликации и сортировки по дню.
    """

    messageId: int
    channel: str
    publishedAt: str
    dayNumber: int
    text: str
    axis: str
    position: int
    score: float

    def toDictionary(self) -> dict:
        return {
            'message_id': self.messageId,
            'channel': self.channel,
            'published_at': self.publishedAt,
            'day_number': self.dayNumber,
            'axis': self.axis,
            'position': self.position,
            'score': self.score,
        }
