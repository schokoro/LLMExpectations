from datetime import datetime
from pathlib import Path
from unittest import TestCase

from SurveyLogic.PromptBuilders.StatisticsProviders.InflationProviderLogic.MultipleWeeklyInflationProvider import \
    MultipleWeeklyInflationProvider
from SurveyLogic.PromptBuilders.StatisticsProviders.InflationProviderLogic.RosstatWeeklyInflationProvider import \
    RosstatWeeklyInflationProvider


class TestRosstatWeeklyInflationProvider(TestCase):
    @classmethod
    def setUpClass(cls):
        """Метод вызывается ОДИН раз перед всеми тестами"""
        # path = Path('../data/Inflation weekly by regions 2015 - 2026.xlsx')
        path1 = Path('../data/Nedel_ipc.xlsx')

        weeklyInflationProvider = RosstatWeeklyInflationProvider(MultipleWeeklyInflationProvider(path1, list(range(2022, 2027))))
        cls.inflationProvider = weeklyInflationProvider
    def test_get_weekly_inflation(self):
        format = '%d.%m.%Y'
        dates = ['09.01.2022', '05.03.2022', '27.12.2022', '21.07.2026']
        expectedValues = [None, (99.82 * 99.94/10000) ** (365/14) - 1, (100.27*99.63/10000) ** (365/14) - 1, (101.99*101.90/10000)**(365/14) - 1]

        product = 'Куры охлажденные и мороженые, кг'
        for i in range(len(dates)):
            inflation = self.inflationProvider.getWeeklyInflation(datetime.strptime(dates[i], format), [product], 2)

            print(f'Expected: {expectedValues[i]}, actual: {inflation[0]}')
            if expectedValues[i] is not None:
                assert abs(expectedValues[i] - inflation[0]) < 0.00001
            else:
                assert inflation[0] is None

    def test_get_weekly_inflation_with_nonround_dates(self):
        format = '%d.%m.%Y'
        dates = ['07.03.2022', '30.12.2022']
        expectedValues = [(99.82 * 99.94/10000) ** (365/14) - 1, (100.27*99.63/10000) ** (365/14) - 1]

        product = 'Куры охлажденные и мороженые, кг'
        for i in range(len(dates)):
            inflation = self.inflationProvider.getWeeklyInflation(datetime.strptime(dates[i], format), [product], 2)

            print(f'Expected: {expectedValues[i]}, actual: {inflation[0]}')
            if expectedValues[i] is not None:
                assert abs(expectedValues[i] - inflation[0]) < 0.00001
            else:
                assert inflation[0] is None

    def test_get_weekly_inflation_with_overlap(self):
        format = '%d.%m.%Y'
        dates = ['14.01.2026']
        expectedValues = [(100.26*100.14/10000)**(365/21) - 1]

        product = 'Куры охлажденные и мороженые, кг'
        for i in range(len(dates)):
            inflation = self.inflationProvider.getWeeklyInflation(datetime.strptime(dates[i], format), [product], 3)

            print(f'Expected: {expectedValues[i]}, actual: {inflation[0]}')
            if expectedValues[i] is not None:
                assert abs(expectedValues[i] - inflation[0]) < 0.00001
            else:
                assert inflation[0] is None
