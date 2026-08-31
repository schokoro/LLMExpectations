import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats

from SurveyResultsAnalysis.visualizationHelpers import calculate_statistics, plot_time_series, plot_comparison, \
    plot_log_returns


class InflationComparisonAnalyzer:
    """
    Класс для сравнения инфляционных данных
    """

    def __init__(self, monthly_df, quarterly_agg_df):
        self.monthly_df = monthly_df.copy()
        self.quarterly_agg_df = quarterly_agg_df.copy()
        self.fill_value = 0

        self.monthly_df = self._add_missing_dates()
        print(self.monthly_df)

        self.comparison_df = self._prepare_data()
        self.stats = {}

    def _add_missing_dates(self):
        # Убеждаемся, что индекс — datetime
        if not pd.api.types.is_datetime64_any_dtype(self.quarterly_agg_df.index):
            self.quarterly_agg_df.index = pd.to_datetime(self.quarterly_agg_df.index)

        # Создаем полный диапазон дат
        full_index = pd.date_range(
            start=self.quarterly_agg_df.index.min(),
            end=self.quarterly_agg_df.index.max(),
            freq='D'
        )

        # Переиндексируем
        monthly_df = self.quarterly_agg_df.reindex(full_index)

        # Интерполируем (если нужно)
        monthly_df = monthly_df.interpolate(method='linear', limit_area='inside')

        return monthly_df

    def _prepare_data(self):
        """Подготавливает данные с расчетом средних и стандартных отклонений"""
        # Создаем копию с date как колонкой для удобства
        quarterly_df = self.quarterly_agg_df.copy()
        quarterly_df['date'] = quarterly_df.index  # Добавляем колонку из индекса

        # Получаем квартальные даты
        quarterly_dates = quarterly_df['date'].values

        # Получаем данные для квартальных дат
        monthly_quarterly = self.monthly_df.loc[quarterly_dates]

        print(monthly_quarterly.columns)

        # Формируем базовый DataFrame
        result_df = pd.DataFrame({
            'date': quarterly_dates,
            'monthly_observable': monthly_quarterly['observable_inflation'].values,
            'monthly_expected': monthly_quarterly['expected_inflation'].values,
            'quarterly_observable_mean': quarterly_df['obs_mean'].values,
            'quarterly_expected_mean': quarterly_df['exp_mean'].values
        })

        # Добавляем стандартные отклонения
        std_columns = ['obs_std', 'exp_std']
        for col in std_columns:
            if col in quarterly_df.columns:
                result_df[f'quarterly_{col}'] = quarterly_df[col].values
            else:
                result_df[f'quarterly_{col}'] = np.nan
                print(f"⚠️ '{col}' не найден в quarterly_agg_df. Доверительные интервалы не будут отображены.")

        return result_df

    def analyze(self):
        """Проводит полный анализ"""
        # Observable
        self.stats['observable'] = calculate_statistics(
            self.comparison_df['quarterly_observable_mean'].values,
            self.comparison_df['monthly_observable'].values
        )

        # Expected
        self.stats['expected'] = calculate_statistics(
            self.comparison_df['quarterly_expected_mean'].values,
            self.comparison_df['monthly_expected'].values
        )

        return self.stats

    def plot_all(self, save_prefix='inflation_comparison'):
        # 2. Time series
        plot_time_series(self.comparison_df,
                         save_path=f'{save_prefix}_timeseries.png')

        #plot_log_returns(self.comparison_df,
        #                 save_path=f'{save_prefix}_timeseries_log_returns.png')

        # 3. Residuals plot (дополнительно)
        #self._plot_residuals(save_path=f'{save_prefix}_residuals.png')

        """Создает все графики"""
        # 1. Scatter plots
        plot_comparison(self.comparison_df,
                        self.stats['observable'],
                        self.stats['expected'],
                        save_path=f'{save_prefix}_scatter.png')

    def _plot_residuals(self, save_path=None):
        """График остатков"""
        fig, axes = plt.subplots(1, 2, figsize=(14, 5))

        # Observable
        X_obs = sm.add_constant(self.comparison_df['quarterly_observable_mean'])
        y_obs = self.comparison_df['monthly_observable']
        model_obs = sm.OLS(y_obs, X_obs).fit()
        residuals_obs = model_obs.resid

        axes[0].scatter(model_obs.fittedvalues, residuals_obs, alpha=0.7)
        axes[0].axhline(y=0, color='r', linestyle='--')
        axes[0].set_title('Остатки: Observable Inflation', fontsize=12)
        axes[0].set_xlabel('Fitted values')
        axes[0].set_ylabel('Residuals')
        axes[0].grid(True, alpha=0.3)

        # Expected
        X_exp = sm.add_constant(self.comparison_df['quarterly_expected_mean'])
        y_exp = self.comparison_df['monthly_expected']
        model_exp = sm.OLS(y_exp, X_exp).fit()
        residuals_exp = model_exp.resid

        axes[1].scatter(model_exp.fittedvalues, residuals_exp, alpha=0.7)
        axes[1].axhline(y=0, color='r', linestyle='--')
        axes[1].set_title('Остатки: Expected Inflation', fontsize=12)
        axes[1].set_xlabel('Fitted values')
        axes[1].set_ylabel('Residuals')
        axes[1].grid(True, alpha=0.3)

        plt.tight_layout()

        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')

        plt.show()

    def export_results(self, file_prefix='analysis_results'):
        """Экспортирует результаты"""
        # 1. Сохраняем comparison DataFrame
        self.comparison_df.to_csv(f'{file_prefix}_data.csv', index=False)

        # 2. Сохраняем статистики
        stats_df = pd.DataFrame({
            'metric': list(self.stats['observable'].keys()),
            'observable': list(self.stats['observable'].values()),
            'expected': list(self.stats['expected'].values())
        })
        stats_df.to_csv(f'{file_prefix}_stats.csv', index=False)

        print(f"✅ Результаты сохранены с префиксом '{file_prefix}'")

    def print_summary(self):
        """Выводит краткую сводку"""
        print("\n" + "=" * 80)
        print("📊 СВОДКА РЕЗУЛЬТАТОВ АНАЛИЗА")
        print("=" * 80)

        for var, stats in self.stats.items():
            print(f"\n{var.upper()}:")
            print(f"  R²     = {stats['r_squared']:.4f}")
            print(f"  Corr   = {stats['correlation']:.4f}")
            print(f"  Slope  = {stats['slope']:.4f} {stats['significance']}")
            print(f"  Intercept = {stats['intercept']:.4f}")
            print(f"  p-value = {stats['p_value']:.4f}")
            print(f"  n_obs  = {stats['n_obs']}")