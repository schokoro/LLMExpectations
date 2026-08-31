from SHAPAnalysis.BaseSHAPCalculator import BaseSHAPCalculator


class AllMinusOneShapCalculator(BaseSHAPCalculator):
    def __init__(self, names: list[str]):
        self.names = names
        self.totalBits = len(names)

    def calculateShapValues(self, responds) -> dict[str, float]:
        shapValues = {}
        lastRespond = responds[self.totalBits]

        for i in range(self.totalBits):
            currentValue = lastRespond - responds[i]
            shapValues[self.names[i]] = currentValue

        return shapValues