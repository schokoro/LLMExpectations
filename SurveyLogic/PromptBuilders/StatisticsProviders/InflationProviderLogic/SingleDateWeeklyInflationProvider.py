from datetime import date
from pathlib import Path
import pandas as pd

from pandas import DataFrame

from SurveyLogic.PromptBuilders.StatisticsProviders.InflationProviderLogic.BaseSingleDateInflationProvider import \
    BaseSingleDateInflationProvider
from SurveyLogic.PromptBuilders.commonHelpers import parseRosstateMonth


class SingleDateWeeklyInflationProvider(BaseSingleDateInflationProvider):
    def __init__(self, path: Path, year):
        datesMap, productsMap, df, minDate, maxDate = self._getMaps(path, year)

        self.productsMap = productsMap
        self.datesMap = datesMap
        self.df = df
        self.minDate = minDate
        self.maxDate = maxDate
        self.delta = pd.DateOffset(days=1)

    def getInflation(self, d: date, product: str):
        if product not in self.productsMap:
            return None

        rowIdx = self.productsMap[product]

        currentDate = self._getDate(d)
        if currentDate is None:
            return None

        columnIdx = self.datesMap[currentDate]
        inflation = float(self.df.iloc[rowIdx, columnIdx])

        return inflation

    def _getMaps(self, path: Path, year: int) -> (dict[str, int], dict[date, int], DataFrame):
        df = pd.read_excel(path, sheet_name=str(year), header=None, skiprows=[0, 1, 2])

        data_start_col = 1
        month_row = 0

        data_start_row = 1
        goodCategory_col = 0

        minDate = None
        maxDate = None
        dateToCol = dict()
        for col in range(data_start_col, len(df.columns)):
            val = df.iloc[month_row, col]
            dateVal = parseRosstateMonth(val, year)

            if minDate is None:
                minDate = dateVal

            if maxDate is None:
                maxDate = dateVal

            if dateVal < minDate:
                minDate = dateVal

            if dateVal > maxDate:
                maxDate = dateVal

            dateToCol[dateVal] = col

        goodToRow = {}
        for row in range(data_start_row, len(df)):
            category = df.iloc[row, goodCategory_col]
            category = str(category).strip()

            goodToRow[category] = row

        return dateToCol, goodToRow, df, minDate, maxDate

    def _getDate(self, d: date):
        if d < self.minDate:
            return None

        if d >= self.maxDate:
            return self.maxDate

        curD = d

        while True:
            if curD in self.datesMap:
                return curD

            curD = (curD - self.delta).date()