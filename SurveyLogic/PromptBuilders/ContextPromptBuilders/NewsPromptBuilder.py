from datetime import date

from NewsLogic.NewsContextProvider import NewsContextProvider
from NewsLogic.newsSectionRenderer import renderNewsSection
from SurveyLogic.PromptBuilders.BasePromptBuilder import BasePromptBuilder
from SurveyLogic.PromptBuilders.Profiles.ProfileData import ProfileData


class NewsPromptBuilder(BasePromptBuilder):
    """Секция «Новости»: медийный фон, актуальный на дату опроса.

    Builder только рендерит готовый контекст. Отбор и суммаризация выполняются
    до запуска опроса (`NewsContextProvider.prepare`): `buildPrompt()`
    синхронный, вызывается внутри async-исполнителя и на каждого респондента,
    поэтому любая тяжёлая работа здесь заблокировала бы event loop и повторилась
    бы сто раз на одну и ту же дату.
    """

    def __init__(self, newsContextProvider: NewsContextProvider):
        self.newsContextProvider = newsContextProvider

    def buildPrompt(self, surveyDate: date, profile: ProfileData) -> str:
        context = self.newsContextProvider.getContext(surveyDate)

        return renderNewsSection(context)
