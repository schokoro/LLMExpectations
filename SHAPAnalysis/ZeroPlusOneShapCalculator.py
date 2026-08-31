from SHAPAnalysis.BaseSHAPCalculator import BaseSHAPCalculator


class ZeroPlusOneShapCalculator(BaseSHAPCalculator):
    def __init__(self, names: list[str]):
        self.names = names
        self.totalBits = len(names)

    def calculateShapValues(self, responds) -> dict[str, float]:
        shapValues = {}
        for i in range(self.totalBits):
            currentValue = responds[i]
            shapValues[self.names[i]] = currentValue

        return shapValues