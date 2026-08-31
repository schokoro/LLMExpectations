from Configuration import configuration
from SurveyLogic.PromptBuilders.CompositePromptBuilder import CompositePromptBuilder
from SurveyLogic.PromptBuilders.ConstantPromptBuilder import ConstantPromptBuilder
from SurveyLogic.PromptBuilders.ContextPromptBuilders.StatePromptBuilders.MarkerGoodsInflationPromptBuilder import \
    MarkerGoodsInflationPromptBuilder
from SurveyLogic.PromptBuilders.ContextPromptBuilders.StatePromptBuilders.PrevoiusInflationExpectationsPromptBuilder import \
    PrevoiusInflationExpectationsPromptBuilder
from SurveyLogic.PromptBuilders.ContextPromptBuilders.StatePromptBuilders.RegionalInflationContextPromptBuilder import \
    RegionalInflationContextPromptBuilder
from SurveyLogic.PromptBuilders.ContextPromptBuilders.StatePromptBuilders.StateEconomyContextPromptBuilder import \
    StateEconomyContextPromptBuilder
from SurveyLogic.PromptBuilders.ContextPromptBuilders.StatePromptBuilders.StateInflationContextPromptBuilder import \
    StateInflationContextPromptBuilder
from SurveyLogic.PromptBuilders.MonthlyFromFilePromptBuilder import MonthlyFromFilePromptBuilder
from SurveyLogic.PromptBuilders.ProfileSepcificPromptBuilders.CommonProfilePromptBuilder import \
    CommonProfilePromptBuilder
from SurveyLogic.PromptBuilders.ProfileSepcificPromptBuilders.ExpensesProfilePromptBuilder import \
    ExpensesProfilePromptBuilder
from SurveyLogic.PromptBuilders.ProfileSepcificPromptBuilders.HouseholdProfilePromptBuilder import \
    HouseholdProfilePromptBuilder
from SurveyLogic.PromptBuilders.ProfileSepcificPromptBuilders.StateExpensesProfilePromptBuilder import \
    StateExpensesProfilePromptBuilder
from SurveyLogic.PromptBuilders.Prompts import prompts
from SurveyLogic.PromptBuilders.StatisticsProviders.AverageExpensesProvider import AverageExpensesProvider
from SurveyLogic.PromptBuilders.StatisticsProviders.ConvertingAverageExpensesProvider import \
    ConvertingAverageExpensesProvider
from SurveyLogic.PromptBuilders.StatisticsProviders.InflationExpectationsProvider import InflationExpectationsProvider
from SurveyLogic.PromptBuilders.StatisticsProviders.InflationProviderLogic.BaseSingleMonthInflationProvider import \
    BaseSingleMonthInflationProvider
from SurveyLogic.PromptBuilders.StatisticsProviders.InflationProviderLogic.ConvertingInflationProvider import \
    ConvertingInflationProvider
from SurveyLogic.PromptBuilders.StatisticsProviders.InflationProviderLogic.DateRoundingSingleMonthInflationProvider import \
    DateRoundingSingleMonthInflationProvider
from SurveyLogic.PromptBuilders.StatisticsProviders.InflationProviderLogic.EMISSWebSingleMonthInflationProvider import \
    EMISSWebSingleMonthInflationProvider
from SurveyLogic.PromptBuilders.StatisticsProviders.InflationProviderLogic.InflationProvider import InflationProvider
from SurveyLogic.PromptBuilders.StatisticsProviders.InflationProviderLogic.MultipleEMISSFilesInflationProvider import \
    MultipleEMISSFilesInflationProvider
from SurveyLogic.PromptBuilders.StatisticsProviders.InflationProviderLogic.MultipleWeeklyInflationProvider import \
    MultipleWeeklyInflationProvider
from SurveyLogic.PromptBuilders.StatisticsProviders.InflationProviderLogic.RosstatWeeklyInflationProvider import \
    RosstatWeeklyInflationProvider
from SurveyLogic.PromptBuilders.StatisticsProviders.MROTProvider import MROTProvider
from SurveyLogic.PromptBuilders.StatisticsProviders.USDRUBRateProvider import USDRUBRateProvider
from SurveyLogic.PromptBuilders.SystemPromptBuilder import SystemPromptBuilder
from SurveyLogic.PromptBuilders.TaskPromptBuilder import TaskPromptBuilder

from experimentsConfiguration import ExperimentsConfiguration


class PromptBuilderFactory:
    def __init__(self):
        self.noInformationPromptBuilder = ConstantPromptBuilder('Нет информации')
        mrotProvider = MROTProvider(configuration.mrotStatisticsPath)
        averageBuyingsProvider = AverageExpensesProvider(configuration.averageBuyingsDataPath)
        averageBuyingsProvider = ConvertingAverageExpensesProvider(averageBuyingsProvider,
                                                                   configuration.rlmsToInflationRegionsPath)

        self.commonProfilePromptBuilder = CommonProfilePromptBuilder(prompts.respondentPrompt, mrotProvider, averageBuyingsProvider)

        multipleWeeklyProvider = MultipleWeeklyInflationProvider(configuration.weeklyInflationDataPath,
                                                                 list(range(2022, 2027)))
        weeklyInflationProvider = RosstatWeeklyInflationProvider(multipleWeeklyProvider)

        singleMonthInflationProvider = self._createSingleMonthInflationProvider()
        singleMonthInflationProvider = DateRoundingSingleMonthInflationProvider(singleMonthInflationProvider)

        inflationProvider = InflationProvider(singleMonthInflationProvider, weeklyInflationProvider)
        inflationProvider = ConvertingInflationProvider(inflationProvider, configuration.rlmsToInflationRegionsPath)

        self.householdInformationBuilder = HouseholdProfilePromptBuilder(prompts.househouldCommonPrompt,
                                                                        averageBuyingsProvider)
        self.expensesProfilePromptBuilder = ExpensesProfilePromptBuilder(prompts.expensesPrompt, inflationProvider,
                                                                        [configuration.regularGoods,
                                                                         configuration.durableGoods,
                                                                         configuration.services])
        paths = [configuration.weeklyRegularGoods, configuration.weeklyDurableGoods, configuration.weeklyServices]
        self.stateExpensesPromptBuilder = StateExpensesProfilePromptBuilder(prompts.stateWeeklyExpensesPrompt,
                                                                           inflationProvider, paths)
        self.stateInflationProvider = StateInflationContextPromptBuilder(prompts.stateInflationPrompt, inflationProvider)
        self.regionInflationProvider = RegionalInflationContextPromptBuilder(prompts.regionInflationPrompt,
                                                                            inflationProvider)
        currencyProvider = USDRUBRateProvider(configuration.usdrubDataPath)
        self.stateEconomyContextPromptBuilder = StateEconomyContextPromptBuilder(prompts.stateEconomyPrompt, currencyProvider)

        self.politicsProvider = MonthlyFromFilePromptBuilder(prompts.politicsPath)
        self.taskPromptBuilder = TaskPromptBuilder(prompts.taskPrompt)

        self.markerGoodsInflationProvider = MarkerGoodsInflationPromptBuilder(inflationProvider, configuration.regularMarkerGoods, configuration.durableMarkerGoods, configuration.servicesMarker)
        inflationExpectationsProvider = InflationExpectationsProvider(configuration.inflationExpectations)
        self.previousInflationExpectationsPromptBuilder = PrevoiusInflationExpectationsPromptBuilder(inflationExpectationsProvider)

    def _createSingleMonthInflationProvider(self) -> BaseSingleMonthInflationProvider:
        files = [configuration.inflation20092014DataPath, configuration.inflation20152020DataPath,
                 configuration.inflation20212026DataPath]
        yearsSets = [configuration.years20092014, configuration.years20152020, configuration.years20212026]
        providers = [EMISSWebSingleMonthInflationProvider(x) for x in files]

        singleMonthInflationProvider = MultipleEMISSFilesInflationProvider(providers, yearsSets)
        return singleMonthInflationProvider

    def createCustomPromptBuilder(self, cfg: ExperimentsConfiguration):
        builders = []
        headers = []

        if cfg.useIndividualRLMSData:
            builders.append(self.commonProfilePromptBuilder)
        else:
            builders.append(self.noInformationPromptBuilder)
        headers.append('Основные параметры опроса и респондента')

        if cfg.useFamilyInformation:
            builders.append(self.householdInformationBuilder)
        else:
            builders.append(self.noInformationPromptBuilder)
        headers.append('Детальная информация о домохозяйстве, членом которого является индивид')

        if cfg.useFamilyExpenses:
            builders.append(self.expensesProfilePromptBuilder)
        else:
            builders.append(self.noInformationPromptBuilder)
        headers.append(
            'Детальная информация об инфляции на уровне региона на товары в топ-расходах семьи индивида (регулярные траты, товары длительного использования, услуги)')

        if cfg.useStateExpenses:
            builders.append(self.stateExpensesPromptBuilder)
        else:
            builders.append(self.noInformationPromptBuilder)
        headers.append(
            'Детальная наиболее свежая информация об инфляции на уровне Российской Федерации в целом на товары, покупаемые домохозяйством')

        if cfg.useInflation:
            inflationBuilders = [self.stateInflationProvider, self.regionInflationProvider, self.markerGoodsInflationProvider]
            inflationPromptBuilder = CompositePromptBuilder(inflationBuilders, ['Инфляция по РФ в целом', 'Инфляция по региону проживания', 'Инфляция по товарам-маркерам в РФ и регионе проживания'])
            builders.append(inflationPromptBuilder)
        else:
            builders.append(self.noInformationPromptBuilder)
        headers.append('Официальная государственная статистика по инфляции')

        if cfg.useEconomy:
            builders.append(self.stateEconomyContextPromptBuilder)
        else:
            builders.append(self.noInformationPromptBuilder)
        headers.append('Основная информация об экономических показателях РФ в целом в мире')

        if cfg.usePreviousInflationExpectations:
            builders.append(self.previousInflationExpectationsPromptBuilder)
        else:
            builders.append(self.noInformationPromptBuilder)
        headers.append('Предыдущие агрегированные инфляционные ожидания')

        if cfg.usePolitics:
            builders.append(self.politicsProvider)
        else:
            builders.append(self.noInformationPromptBuilder)
        headers.append('Основная политико-экономическая информация по РФ в целом')

        builders.append(self.taskPromptBuilder)
        headers.append('Задача')

        return SystemPromptBuilder(prompts.systemPrompt), CompositePromptBuilder(builders, headers)
