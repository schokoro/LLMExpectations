import pandas as pd
from datetime import date
from pathlib import Path

from SurveyLogic.PromptBuilders.StatisticsProviders.BaseInflationExpectationsProvider import \
    BaseInflationExpectationsProvider


class InflationExpectationsProvider(BaseInflationExpectationsProvider):
    def __init__(self, path: Path):
        self.df = self._load_expectations(path)

    def getInflationExpectations(self, d: date):
        mask = self.df.index <= pd.Timestamp(d)
        valid_dates = self.df.index[mask]

        if len(valid_dates) == 0:
            return None

        closest_date = valid_dates[-1]
        # Исправление: обращаемся к строке по индексу, а не к столбцу
        return self.df.loc[closest_date, 'expected_inflation']

    def _load_expectations(self, path: Path):
        directEstimations = pd.read_excel(path, index_col=0)
        directEstimations.rename(
            index={
                'наблюдаемая инфляция (в %)': 'observable_inflation',
                'ожидаемая инфляция (в %)': 'expected_inflation'
            },
            inplace=True
        )
        directEstimations = directEstimations.T
        directEstimations.index = pd.to_datetime(directEstimations.index)

        directEstimations.index = directEstimations.index + pd.Timedelta(days=1)
        if not directEstimations.empty:
            first_row = directEstimations.iloc[0]
            if first_row.isna().any():
                directEstimations = directEstimations.iloc[1:]
                print(f"🗑️ Удалена первая строка с NaN (дата: {first_row.name})")


        return directEstimations