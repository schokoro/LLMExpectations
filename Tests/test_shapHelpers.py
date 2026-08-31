from unittest import TestCase

from SHAPAnalysis.shapHelpers import getBitArray


class Test(TestCase):
    def test_get_bit_array(self):
        bitArray = getBitArray(1, 7)
        expected = [False, False, False, False, False, False, True]

        for i in range(len(expected)):
            assert expected[i] == bitArray[i]

    def test_get_bit_array_2(self):
        bitArray = getBitArray(0, 7)
        expected = [False, False, False, False, False, False, False]

        for i in range(len(expected)):
            assert expected[i] == bitArray[i]

    def test_get_bit_array_1(self):
        bitArray = getBitArray(127, 7)
        expected = [True, True, True, True, True, True, True]

        for i in range(len(expected)):
            assert expected[i] == bitArray[i]
