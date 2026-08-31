import pandas as pd
import statsmodels.api as sm

class SurveyRegressionService:
    def __init__(self, inflationExpectations, pastYearInflation, usdrubRate):
        self.usdrubRate = usdrubRate
        self.pastYearInflation = pastYearInflation
        self.inflationExpectations = inflationExpectations

    def fit(self, survey, vars):
        df = self._createDataset(survey)
        df.to_excel('temp.xlsx')

        x = df[vars]
        y = df['Y']

        dates = df['D']

        x_const = sm.add_constant(x)
        model_sm = sm.OLS(y, x_const).fit()

        prediction = model_sm.predict(x_const)

        return y, prediction, model_sm, dates

    def _createDataset(self, survey):
        rows = []
        print(survey)

        df = self.inflationExpectations

        for i in range(1, len(df)):
            prev_date = df.index[i - 1]
            current_date = df.index[i]
            llm_survey_date = survey.index[i]

            current_value = df['expected_inflation'].iloc[i]

            Y = current_value
            X1 = df['expected_inflation'].iloc[i - 1]
            X2 = self._getInflation(llm_survey_date)
            X3 = survey['exp_mean'].iloc[i]
            X4 = self._get_usdrub(llm_survey_date)

            #print(f'Y = {Y}, X1 = {X1}, X2 = {X2}, X3 = {X3}, D = {current_date}')
            if X2 is None or X4 is None:
                continue

            if self._calcDifference(current_date, prev_date) > 1:
                #print(f'Skipping date {current_date} because of prev date = {prev_date} is older for 1 month')
                continue

            row = {
                'Y': Y,
                'X1': X1,
                'X2': X2,
                'X3': X3,
                'X4': X4,
                'D': llm_survey_date
            }
            rows.append(row)

        regression_df = pd.DataFrame(rows)
        return regression_df

    def _calcDifference(self, date1, date2):
        monthDiff = (date1.year - date2.year) * 12 + date1.month - date2.month
        return monthDiff

    def _getInflation(self, date):
        df = self.pastYearInflation
        actualValue = None
        actualValueDate = None

        for i in range(len(df)):
            current_date = df.index[i]
            current_value = df['Значение'].iloc[i]

            if current_date > date:
                if actualValueDate is None:
                    return None

                month_diff = self._calcDifference(date, actualValueDate)
                if month_diff > 1:
                    return None
                return actualValue

            actualValue = current_value
            actualValueDate = current_date

        if actualValueDate is None:
            return None

        month_diff = self._calcDifference(date, actualValueDate)
        if month_diff > 1:
            return None
        return actualValue

    def _get_usdrub(self, target_date, positions_back=10):
        """
        Всегда берет дату из прошлого (или саму дату, если есть).
        """
        # Фильтруем только даты <= target_date
        df = self.usdrubRate
        past_dates = df.index[df.index <= target_date]

        if len(past_dates) == 0:
            return None  # нет данных в прошлом

        # Берем самую позднюю дату из прошлого
        found_date = past_dates[-1]
        current_idx = df.index.get_loc(found_date)

        past_idx = current_idx - positions_back

        if past_idx < 0:
            return None

        current_value = df.iloc[current_idx, 1]
        past_value = df.iloc[past_idx, 1]

        return current_value/past_value - 1

    def _get_values_by_position(self, df, current_date, positions_back=10):
        """
        Получает значения по позиции (не по дате).
        """
        # Находим позицию текущей даты
        try:
            current_idx = df.index.get_loc(current_date)
        except KeyError:
            # Если даты нет, ищем ближайшую
            current_idx = df.index.get_indexer([current_date], method='nearest')[0]
            current_date = df.index[current_idx]

        # Получаем значение 10 позиций назад
        past_idx = current_idx - positions_back

        if past_idx < 0:
            raise ValueError(f"Недостаточно данных: нужно {positions_back} позиций назад")

        current_value = df.iloc[current_idx]
        past_value = df.iloc[past_idx]
        past_date = df.index[past_idx]

        return {
            'current_date': current_date,
            'current_value': current_value,
            'past_date': past_date,
            'past_value': past_value,
            'positions_back': positions_back
        }

