from datetime import datetime
from pathlib import Path
from unittest import TestCase

from SurveyLogic.PromptBuilders.StatisticsProviders.InflationExpectationsProvider import InflationExpectationsProvider


class TestInflationExpectationsProvider(TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path('../data/Direct_Inflation_Estimations_12m.xlsx')
        cls.inflationExpectationsProvider = InflationExpectationsProvider(path)

    def test_get_inflation_expectations(self):
        dates = ['01.01.2016', '10.03.2022', '11.03.2022', '15.03.2022', '01.08.2026', '31.03.2010']

        format = '%d.%m.%Y'
        expectedValues = [16.44344473, 13.5372, 18.3345, 18.3345, 14.7045, None]

        for i in range(len(dates)):
            inflation = self.inflationExpectationsProvider.getInflationExpectations(datetime.strptime(dates[i], format))
            print(f'Expected: {expectedValues[i]}, actual: {inflation}')
            if expectedValues[i] is not None:
                assert abs(expectedValues[i] - inflation) < 0.00001
            else:
                assert inflation is None
