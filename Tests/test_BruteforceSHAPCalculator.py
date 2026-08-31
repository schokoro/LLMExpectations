from unittest import TestCase

from SHAPAnalysis.BruteforceSHAPCalculator import BruteforceSHAPCalculator


class TestBruteforceSHAPCalculator(TestCase):
    def test_calculate_shap_values(self):
        bf = BruteforceSHAPCalculator(2, ['1', '2'])

        responds = [1, 2, 3, 4]
        expected = {'1': 1.0, '2': 0.5}
        result = bf.calculateShapValues(responds)

        assert len(expected) == len(result)

        for k,v in result.items():
            print(f'Expected: {expected[k]}, actual: {result[k]}')
            assert expected[k] == result[k]
