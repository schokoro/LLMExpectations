import numpy as np

from SHAPAnalysis.BaseSHAPCalculator import BaseSHAPCalculator


class BruteforceSHAPCalculator(BaseSHAPCalculator):
    def __init__(self, names: list[str]):
        self.names = names
        self.totalBits = len(names)

        self.indexes, self.oppositeIndexes = self._getIndexes_numpy(self.totalBits)

    def calculateShapValues(self, responds: list[float]) -> dict[str, float]:
        shapValues = {}
        for i in range(self.totalBits):
            currentValue = self._getShapValue(i, responds)
            shapValues[self.names[i]] = currentValue

        return shapValues

    def _getIndexes_numpy(self, totalBits: int) -> (list[np.ndarray], list[np.ndarray]):
        """
        Использует NumPy для быстрого создания индексов.
        Возвращает массивы numpy для эффективной индексации.
        """
        total_rows = 1 << totalBits

        # Создаем матрицу битов (эффективно)
        # Генерируем все числа от 0 до 2^totalBits - 1
        numbers = np.arange(total_rows, dtype=np.uint32)

        ones_indices = []
        zeros_indices = []

        for col in range(totalBits):
            # Создаем маску для текущего столбца (от старшего бита)
            bit_mask = 1 << (totalBits - 1 - col)

            # Получаем булеву маску для бита = 1
            ones_mask = (numbers & bit_mask) != 0

            # Получаем индексы
            ones_indices.append(np.where(ones_mask)[0])
            zeros_indices.append(np.where(~ones_mask)[0])

        return ones_indices, zeros_indices

    def _getShapValue(self, i, responds):
        idxes = self.indexes[i]
        oidxes = self.oppositeIndexes[i]

        directData = 0
        oppositeData = 0
        count_direct = 0
        count_opposite = 0

        # Суммируем только не-None значения для прямых индексов
        for idx in idxes:
            val = responds[idx]
            if val is not None:  # или if val is not None and not math.isnan(val) если есть NaN
                directData += val
                count_direct += 1

        # Суммируем только не-None значения для противоположных индексов
        for idx in oidxes:
            val = responds[idx]
            if val is not None:
                oppositeData += val
                count_opposite += 1

        # Общее количество учтенных элементов
        total_count = count_direct + count_opposite

        # Защита от деления на ноль
        if total_count == 0:
            return 0.0

        # Нормализуем на количество учтенных элементов
        return (directData - oppositeData) / total_count
