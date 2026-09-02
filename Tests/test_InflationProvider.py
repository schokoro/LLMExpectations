from datetime import datetime
from pathlib import Path
from unittest import TestCase

from SurveyLogic.PromptBuilders.StatisticsProviders.InflationProviderLogic.EMISSWebSingleMonthInflationProvider import \
    EMISSWebSingleMonthInflationProvider
from SurveyLogic.PromptBuilders.StatisticsProviders.InflationProviderLogic.InflationProvider import InflationProvider
from SurveyLogic.PromptBuilders.StatisticsProviders.InflationProviderLogic.MultipleEMISSFilesInflationProvider import \
    MultipleEMISSFilesInflationProvider
from SurveyLogic.PromptBuilders.StatisticsProviders.InflationProviderLogic.MultipleWeeklyInflationProvider import \
    MultipleWeeklyInflationProvider
from SurveyLogic.PromptBuilders.StatisticsProviders.InflationProviderLogic.RosstatWeeklyInflationProvider import \
    RosstatWeeklyInflationProvider


class TestInflationProvider(TestCase):
    @classmethod
    def setUpClass(cls):
        """Метод вызывается ОДИН раз перед всеми тестами"""
        #path = Path('../data/Inflation weekly by regions 2015 - 2026.xlsx')
        path1 = Path('../data/Monthly Inflation for goods and services in regions_2009_2014_v0.xlsx')
        path2 = Path('../data/Monthly Inflation for goods and services in regions_2015_2020_v0.xlsx')
        path3 = Path('../data/Monthly Inflation for goods and services in regions_2021_2026_v0.xlsx')

        weeklyPath = Path('../data/Nedel_ipc.xlsx')

        files = [path1, path2, path3]
        yearsSets = [set(range(2009, 2015)), set(range(2015, 2021)), set(range(2021, 2027))]
        providers = [EMISSWebSingleMonthInflationProvider(x) for x in files]

        singleMonthInflationProvider = MultipleEMISSFilesInflationProvider(providers, yearsSets)
        weeklyInflationProvider = RosstatWeeklyInflationProvider(
            MultipleWeeklyInflationProvider(weeklyPath, list(range(2022, 2027))))

        cls.inflationProvider = InflationProvider(singleMonthInflationProvider, weeklyInflationProvider)

    def test_get_average_common_year_inflation_last_nmonth(self):
        format = '%d.%m.%Y'
        dates = ['01.01.2016', '01.01.2017', '01.09.2021', '01.07.2026', '01.06.2020']
        expectedValues = [(1 + 0.0077) ** 12 - 1, (1 + 0.004) ** 12 - 1, (1 + 0.0017) ** 12 - 1,
                          (1 + 0.0087) ** 12 - 1, (1 + 0.0027) ** 12 - 1]

        for i in range(len(dates)):
            inflation = self.inflationProvider.getAverageCommonYearInflationLastNMonth(
                datetime.strptime(dates[i], format), lastMonth=1)
            print(f'Expected: {expectedValues[i]}, actual: {inflation}')
            if expectedValues[i] is not None:
                assert abs(expectedValues[i] - inflation) < 0.00001
            else:
                assert inflation is None

    def test_get_average_regional_year_inflation_last_nmonth(self):
        format = '%d.%m.%Y'
        dates = ['01.01.2016', '01.01.2017', '01.09.2021', '01.07.2026']
        expectedValues = [(1 + 0.0107) ** 12 - 1, (1 + 0.0022) ** 12 - 1, (1 + 0.0044) ** 12 - 1,
                          (1 + 0.0114) ** 12 - 1]

        for i in range(len(dates)):
            inflation = self.inflationProvider.getAverageRegionalYearInflationLastNMonth(datetime.strptime(dates[i], format),
                                                                                    'Липецкая область', lastMonth=1)
            print(f'Expected: {expectedValues[i]}, actual: {inflation}')
            if expectedValues[i] is not None:
                assert abs(expectedValues[i] - inflation) < 0.00001
            else:
                assert inflation is None


    def test_get_average_regional_year_inflation_last_n_3_month(self):

        format = '%d.%m.%Y'
        dates = ['01.01.2016', '01.01.2017', '01.07.2026', '01.06.2020']
        expectedValues = [((1 + 0.0082) * (1 + 0.007) * (1 + 0.0107)) ** 4 - 1, ((1 + 0.0064) * (1+0.0031) * (1 + 0.0022)) ** 4 - 1,
                          ((1 + 0.0007) * (1 + 0.0006) * (1 + 0.0114)) ** 4 - 1, ((1 + 0.0053) * (1 + 0.0104) * (1 + 0.0024)) ** 4 - 1]

        for i in range(len(dates)):
            inflation = self.inflationProvider.getAverageRegionalYearInflationLastNMonth(datetime.strptime(dates[i], format),
                                                                                    'Липецкая область', lastMonth=3)
            print(f'Expected: {expectedValues[i]}, actual: {inflation}')
            if expectedValues[i] is not None:
                assert abs(expectedValues[i] - inflation) < 0.00001
            else:
                assert inflation is None

    def test_get_products_common_year_inflation_last_nmonth(self):
        format = '%d.%m.%Y'
        dates = ['01.08.2016', '01.02.2016', '01.11.2016']
        expectedValues1 = [None, (1 + 0.0100) ** 12 - 1, (1 + 0.0027)**12 - 1]
        expectedValues2 = [(1 + 0.0018) ** 12 - 1, None, (1 + 0.009)**12 - 1]
        products = ['Электротовары и другие бытовые приборы', 'Одежда']

        for i in range(len(dates)):
            inflation = self.inflationProvider.getProductsCommonYearInflationLastNMonth(
                datetime.strptime(dates[i], format), products, lastMonth=1)

            print(f'Expected: {expectedValues1[i]}, {expectedValues2[i]}, actual: {inflation}')
            if expectedValues1[i] is not None:
                assert abs(expectedValues1[i] - inflation[0]) < 0.00001
            else:
                assert inflation[0] is None

            if expectedValues2[i] is not None:
                assert abs(expectedValues2[i] - inflation[1]) < 0.00001
            else:
                assert inflation[1] is None

    def test_get_products_regional_year_inflation_last_nmonth(self):
        format = '%d.%m.%Y'
        dates = ['01.03.2016', '01.07.2026', '01.06.2020', '01.05.2016']
        expectedValues1 = [None, (100.31 * 115.75/10000) ** 6 - 1, (101.1*100.96/10000)**6-1, None]
        expectedValues2 = [None, (100*100/10000) ** 6 - 1, 0, 0]
        products = ['Беспроводная радиосвязь', 'Услуги телевещания']
        region = 'Республика Татарстан (Татарстан)'

        for i in range(len(dates)):
            inflation = self.inflationProvider.getProductsRegionalYearInflationLastNMonth(
                datetime.strptime(dates[i], format), region, products, lastMonth=2)

            print(f'Expected: {expectedValues1[i]}, {expectedValues2[i]}, actual: {inflation}')
            if expectedValues1[i] is not None:
                assert abs(expectedValues1[i] - inflation[0]) < 0.00001
            else:
                assert inflation[0] is None

            if expectedValues2[i] is not None:
                assert abs(expectedValues2[i] - inflation[1]) < 0.00001
            else:
                assert inflation[1] is None

    def test_get_products_regional_year_inflation_last_nmonth_on_boarder(self):
        format = '%d.%m.%Y'
        dates = ['01.02.2015', '01.02.2021']
        expectedValues1 = [(99.69 * 100/10000) ** 6 - 1, (100*100/10000)**6-1, None]
        products = ['Беспроводная радиосвязь']
        region = 'Республика Татарстан (Татарстан)'

        for i in range(len(dates)):
            inflation = self.inflationProvider.getProductsRegionalYearInflationLastNMonth(
                datetime.strptime(dates[i], format), region, products, lastMonth=2)

            print(f'Expected: {expectedValues1[i]}, actual: {inflation}')
            if expectedValues1[i] is not None:
                assert abs(expectedValues1[i] - inflation[0]) < 0.00001
            else:
                assert inflation[0] is None
