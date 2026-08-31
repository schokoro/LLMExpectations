from Configuration import configuration
from SHAPAnalysis.AllMinusOneShapCalculator import AllMinusOneShapCalculator
from SHAPAnalysis.BruteforceSHAPCalculator import BruteforceSHAPCalculator
from SHAPAnalysis.ZeroPlusOneShapCalculator import ZeroPlusOneShapCalculator
from SHAPAnalysis.shapHelpers import getBitArray
from SurveyLogic.PromptBuilders.BasePromptBuilder import BasePromptBuilder
from SurveyLogic.PromptBuilders.CompositePromptBuilder import CompositePromptBuilder
from SurveyLogic.PromptBuilders.ContextPromptBuilders.NewsPromptBuilder import NewsPromptBuilder
from SurveyLogic.PromptBuilders.ProfileSepcificPromptBuilders.CommonProfilePromptBuilder import \
    CommonProfilePromptBuilder
from SurveyLogic.PromptBuilders.PromptBuilderFactory import PromptBuilderFactory
from SurveyLogic.PromptBuilders.Prompts import prompts
from SurveyLogic.PromptBuilders.StatisticsProviders.AverageExpensesProvider import AverageExpensesProvider
from SurveyLogic.PromptBuilders.StatisticsProviders.ConvertingAverageExpensesProvider import \
    ConvertingAverageExpensesProvider
from SurveyLogic.PromptBuilders.StatisticsProviders.MROTProvider import MROTProvider
from SurveyLogic.PromptBuilders.SystemPromptBuilder import SystemPromptBuilder
from SurveyLogic.PromptBuilders.TaskPromptBuilder import TaskPromptBuilder
from experimentsConfiguration import ExperimentsConfiguration


def createSimplePromptBuilder() -> (BasePromptBuilder, BasePromptBuilder):
    builders = []

    builders.append(CommonProfilePromptBuilder(prompts.respondentPrompt))
    builders.append(TaskPromptBuilder(prompts.taskPrompt))

    headers = ['Основные параметры опроса и респондента', 'Задача']

    return SystemPromptBuilder(prompts.systemPrompt), CompositePromptBuilder(builders, headers)

def createNewsPromptBuilder() -> (BasePromptBuilder, BasePromptBuilder):
    builders = []

    mrotProvider = MROTProvider(configuration.mrotStatisticsPath)
    averageBuyingsProvider = AverageExpensesProvider(configuration.averageBuyingsDataPath)
    averageBuyingsProvider = ConvertingAverageExpensesProvider(averageBuyingsProvider,
                                                               configuration.rlmsToInflationRegionsPath)

    builders.append(CommonProfilePromptBuilder(prompts.respondentPrompt, mrotProvider, averageBuyingsProvider))
    builders.append(NewsPromptBuilder())
    builders.append(TaskPromptBuilder(prompts.taskPrompt))

    headers = ['Основные параметры опроса и респондента', 'Новости', 'Задача']

    return SystemPromptBuilder(prompts.systemPrompt), CompositePromptBuilder(builders, headers)

def createSHAPBruteforcePromptBuilders():
    promptBuilders = createBruteforce()

    return createBuilders(promptBuilders, lambda x: BruteforceSHAPCalculator(x))

def createSHAPZeroPlusOnePromptBuilders():
    builders = createZeroPlusOne()
    return createBuilders(builders, lambda x: ZeroPlusOneShapCalculator(x))

def createSHAPAllMinusOnePromptBuilders():
    builders = createAllMinusOne()
    return createBuilders(builders, lambda x: AllMinusOneShapCalculator(x) )


def createZeroPlusOne():
    factory = PromptBuilderFactory()
    builders = []
    totalBits = 7

    for i in range(totalBits):
        arr = [False] * totalBits
        arr[i] = True

        cfg = ExperimentsConfiguration(
            useIndividualRLMSData=arr[0],
            useFamilyInformation=arr[1],
            useFamilyExpenses=arr[2],
            useStateExpenses=arr[3],
            useEconomy=arr[4],
            useRegionalInflation=arr[5],
            useStateInflation=arr[6]
        )

        pp = factory.createCustomPromptBuilder(cfg)
        builders.append(pp[1])

    return builders

def createAllMinusOne():
    factory = PromptBuilderFactory()
    builders = []
    totalBits = 7

    for i in range(totalBits + 1):
        arr = [True] * totalBits
        if i <totalBits:
            arr[i] = False

        cfg = ExperimentsConfiguration(
            useIndividualRLMSData=arr[0],
            useFamilyInformation=arr[1],
            useFamilyExpenses=arr[2],
            useStateExpenses=arr[3],
            useEconomy=arr[4],
            useRegionalInflation=arr[5],
            useStateInflation=arr[6]
        )

        pp = factory.createCustomPromptBuilder(cfg)
        builders.append(pp[1])

    return builders

def createBruteforce():
    factory = PromptBuilderFactory()
    builders = []
    totalBits = 7

    for i in range(2 ** totalBits):
        arr = getBitArray(i, totalBits)
        cfg = ExperimentsConfiguration(
            useIndividualRLMSData=arr[0],
            useFamilyInformation=arr[1],
            useFamilyExpenses=arr[2],
            useStateExpenses=arr[3],
            useEconomy=arr[4],
            useRegionalInflation=arr[5],
            useStateInflation=arr[6]
        )

        pp = factory.createCustomPromptBuilder(cfg)
        builders.append(pp[1])

    return builders

def createBuilders(builders, factory):
    names = ['RLMSIndividual', 'RLMSHH', 'RLMSHHRegionalExpenses', 'RLMSHHStateExpenses', 'Economy',
             'RegionalInflation', 'StateInflation']

    systemPromptBuilder = SystemPromptBuilder(prompts.systemPrompt)
    shapCalculator = factory(names)

    return systemPromptBuilder, builders, shapCalculator