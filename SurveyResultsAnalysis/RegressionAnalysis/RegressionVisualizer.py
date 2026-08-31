import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.patches import Rectangle
import seaborn as sns
from typing import Dict, Tuple, List, Optional
from sklearn.metrics import r2_score, mean_squared_error, mean_absolute_error
from scipy import stats
import warnings

warnings.filterwarnings('ignore')


class RegressionVisualizer:
    """
    Визуализатор результатов регрессионного анализа для множества моделей.

    Parameters:
    -----------
    figsize : tuple
        Размер фигуры для каждого графика
    dpi : int
        Качество изображения
    """

    def __init__(self, figsize: tuple = (10, 8), dpi: int = 150):
        self.figsize = figsize
        self.dpi = dpi

        # Настройка стиля
        plt.style.use('seaborn-v0_8-darkgrid')
        self.colors = sns.color_palette("husl", 8)

    def visualize(self,
                  regression_results: Dict[str, Tuple[pd.Series, pd.Series, object]],
                  n_cols: int = 2,
                  save_path: Optional[str] = None,
                  show_stats: bool = True,
                  figsize_per_plot: Optional[Tuple[float, float]] = None,
                  additional_title: str = '') -> None:
        """
        Визуализирует результаты всех регрессионных моделей.

        Parameters:
        -----------
        regression_results : Dict[str, Tuple[pd.Series, pd.Series, object]]
            Словарь с результатами регрессии:
            - ключ: название модели
            - значение: (истинные значения, предсказанные значения, обученная модель)
        n_cols : int
            Количество столбцов в сетке графиков
        save_path : str, optional
            Путь для сохранения изображения
        show_stats : bool
            Показывать ли статистику на графике
        figsize_per_plot : tuple, optional
            Размер каждого отдельного графика
        """
        n_models = len(regression_results)
        n_rows = (n_models + n_cols - 1) // n_cols

        # Размер фигуры
        if figsize_per_plot is not None:
            total_figsize = (figsize_per_plot[0] * n_cols, figsize_per_plot[1] * n_rows)
        else:
            total_figsize = (self.figsize[0] * n_cols, self.figsize[1] * n_rows)

        # Создаем фигуру с подсетками
        fig = plt.figure(figsize=total_figsize, dpi=self.dpi)

        # Используем GridSpec для лучшего контроля
        gs = gridspec.GridSpec(n_rows, n_cols, figure=fig, hspace=0.3, wspace=0.3)

        # Собираем все истинные и предсказанные значения для общего масштаба
        all_actual = []
        all_predicted = []
        for _, (actual, predicted, _) in regression_results.items():
            all_actual.extend(actual.values.flatten())
            all_predicted.extend(predicted.values.flatten())

        # Общий диапазон для осей
        global_min = min(min(all_actual), min(all_predicted))
        global_max = max(max(all_actual), max(all_predicted))
        margin = (global_max - global_min) * 0.05
        axis_limits = (global_min - margin, global_max + margin)

        # ============================================
        # СОРТИРУЕМ МОДЕЛИ ПО УБЫВАНИЮ R²
        # ============================================
        # Вычисляем R² для каждой модели
        models_with_r2 = []
        for model_name, (actual, predicted, model) in regression_results.items():
            actual_values = actual.values.flatten()
            predicted_values = predicted.values.flatten()
            r2 = r2_score(actual_values, predicted_values)
            models_with_r2.append((r2, model_name, actual, predicted, model))

        # Сортируем по убыванию R²
        sorted_models = sorted(models_with_r2, key=lambda x: x[0], reverse=True)

        # Рисуем каждый график
        for idx, (r2, model_name, actual, predicted, model) in enumerate(sorted_models):
            row = idx // n_cols
            col = idx % n_cols

            # Определяем, является ли график последним в строке
            is_last_row = (row == n_rows - 1)
            is_first_col = (col == 0)

            ax = fig.add_subplot(gs[row, col])
            self._plot_single_model(
                ax, model_name, actual, predicted, model,
                axis_limits, show_stats,
                show_xlabel=is_last_row,
                show_ylabel=is_first_col
            )

        # Скрываем пустые подграфики
        for idx in range(len(regression_results), n_rows * n_cols):
            row = idx // n_cols
            col = idx % n_cols
            if row < n_rows and col < n_cols:
                fig.add_subplot(gs[row, col]).set_visible(False)

        # Общий заголовок
        fig.suptitle(f'Сравнение регрессионных моделей инфляционных ожиданий ({additional_title})',
                     fontsize=16, fontweight='bold', y=0.98)

        plt.tight_layout()

        # Сохраняем если нужно
        if save_path:
            plt.savefig(save_path, dpi=self.dpi, bbox_inches='tight',
                        facecolor='white', edgecolor='none')
            print(f"✅ График сохранен в: {save_path}")

        plt.show()

    def _plot_single_model(self,
                           ax,
                           model_name: str,
                           actual: pd.Series,
                           predicted: pd.Series,
                           model: object,
                           axis_limits: Tuple[float, float],
                           show_stats: bool = True,
                           show_xlabel: bool = True,
                           show_ylabel: bool = True) -> None:
        """
        Рисует отдельный график для одной модели.
        """
        # Получаем значения
        actual_values = actual.values.flatten()
        predicted_values = predicted.values.flatten()

        # Основные метрики
        r2 = r2_score(actual_values, predicted_values)
        rmse = np.sqrt(mean_squared_error(actual_values, predicted_values))
        mae = mean_absolute_error(actual_values, predicted_values)

        # Scatter plot
        ax.scatter(actual_values, predicted_values, alpha=0.6, s=30,
                   color=self.colors[0], edgecolors='white', linewidth=0.5)

        # Линия y = x (блеклая)
        ax.plot(axis_limits, axis_limits, '--', color='gray', alpha=0.5,
                linewidth=1.5, label='y = x')

        # Линия регрессии (опционально, для визуализации смещения)
        z = np.polyfit(actual_values, predicted_values, 1)
        p = np.poly1d(z)
        x_line = np.linspace(axis_limits[0], axis_limits[1], 100)
        ax.plot(x_line, p(x_line), 'r-', alpha=0.3, linewidth=1,
                label=f'y = {z[0]:.2f}x + {z[1]:.2f}')

        # Настройка осей
        ax.set_xlim(axis_limits)
        ax.set_ylim(axis_limits)

        # Показываем подписи осей только для нужных графиков
        if show_xlabel:
            ax.set_xlabel('Истинные значения', fontsize=10)
        else:
            ax.set_xlabel('')
            # Убираем ticks для верхних графиков, чтобы не загромождать
            ax.tick_params(axis='x', labelsize=8)

        if show_ylabel:
            ax.set_ylabel('Прогноз', fontsize=10)
        else:
            ax.set_ylabel('')
            # Убираем ticks для правых графиков
            ax.tick_params(axis='y', labelsize=8)

        ax.grid(True, alpha=0.3)

        # Заголовок с названием модели (добавляем R² в заголовок для наглядности)
        ax.set_title(f'{model_name} R² = {r2:.4f}', fontsize=11, fontweight='bold')

        # Добавляем статистику на график
        if show_stats and model is not None:
            stats_text = self._get_model_stats(model, actual_values, predicted_values)

            # Создаем рамку со статистикой
            props = dict(boxstyle='round', facecolor='wheat', alpha=0.8)
            ax.text(0.02, 0.98, stats_text, transform=ax.transAxes,
                    fontsize=7, verticalalignment='top',
                    bbox=props, family='monospace')

        # Добавляем метрики в правом верхнем углу
        metrics_text = f'R² = {r2:.4f}\nRMSE = {rmse:.4f}\nMAE = {mae:.4f}'
        props = dict(boxstyle='round', facecolor='lightblue', alpha=0.7)
        ax.text(0.98, 0.98, metrics_text, transform=ax.transAxes,
                fontsize=8, verticalalignment='top', horizontalalignment='right',
                bbox=props, family='monospace')

    def _get_model_stats(self, model: object, actual: np.ndarray,
                         predicted: np.ndarray) -> str:
        """
        Извлекает статистическую информацию из модели.
        """
        stats_text = ""

        try:
            # Для statsmodels
            if hasattr(model, 'summary'):
                # Коэффициенты и p-values
                if hasattr(model, 'params') and hasattr(model, 'pvalues'):
                    params = model.params
                    pvalues = model.pvalues

                    # Пропускаем константу, если она есть
                    start_idx = 1 if 'const' in params.index else 0

                    for i in range(start_idx, len(params)):
                        coef = params.iloc[i]
                        pval = pvalues.iloc[i]
                        var_name = params.index[i]

                        # Звездочки для значимости
                        stars = self._get_significance_stars(pval)
                        stats_text += f'{var_name}: {coef:.4f} (p={pval:.4f}{stars})\n'

                    # Добавляем информацию о модели
                    if hasattr(model, 'rsquared_adj'):
                        stats_text += f'Adj. R² = {model.rsquared_adj:.4f}\n'
                    if hasattr(model, 'fvalue') and hasattr(model, 'f_pvalue'):
                        stats_text += f'F = {model.fvalue:.2f} (p={model.f_pvalue:.4f})'

            # Для sklearn
            elif hasattr(model, 'coef_') and hasattr(model, 'intercept_'):
                # Для sklearn нужно вычислить p-values отдельно
                stats_text += f'Intercept: {model.intercept_:.4f}\n'
                for i, coef in enumerate(model.coef_):
                    stats_text += f'X{i + 1}: {coef:.4f}\n'

                # Вычисляем приблизительные p-values для sklearn
                p_values_approx = self._calculate_sklearn_pvalues(model, actual, predicted)
                if p_values_approx is not None:
                    stats_text += '\nP-values (приблизительные):\n'
                    for i, pval in enumerate(p_values_approx):
                        stars = self._get_significance_stars(pval)
                        stats_text += f'X{i + 1}: {pval:.4f}{stars}\n'

        except Exception as e:
            stats_text = f"Статистика недоступна\n({str(e)})"

        return stats_text

    def _get_significance_stars(self, pval: float) -> str:
        """Возвращает звездочки для уровня значимости."""
        if pval < 0.001:
            return '***'
        elif pval < 0.01:
            return '**'
        elif pval < 0.05:
            return '*'
        elif pval < 0.1:
            return '.'
        else:
            return ''

    def _calculate_sklearn_pvalues(self, model, X: np.ndarray, y: np.ndarray) -> Optional[np.ndarray]:
        """
        Вычисляет приблизительные p-values для sklearn модели.
        """
        try:
            n = len(y)
            k = X.shape[1] if hasattr(X, 'shape') else len(model.coef_)

            # Предсказания и остатки
            y_pred = model.predict(X) if hasattr(model, 'predict') else y
            residuals = y - y_pred

            # Стандартная ошибка
            sigma2 = np.sum(residuals ** 2) / (n - k - 1)

            # Добавляем константу
            if hasattr(X, 'shape'):
                X_with_const = np.column_stack([np.ones(n), X])
            else:
                X_with_const = np.column_stack([np.ones(n), X.reshape(-1, 1)])

            # Ковариационная матрица
            try:
                cov = np.linalg.inv(X_with_const.T @ X_with_const) * sigma2
                se = np.sqrt(np.diag(cov))

                # t-статистика
                params = np.append(model.intercept_, model.coef_)
                t_values = params / se

                # p-values
                p_values = 2 * (1 - stats.t.cdf(np.abs(t_values), df=n - k - 1))

                return p_values[1:]  # Пропускаем intercept
            except:
                return None
        except:
            return None

    def create_detailed_report(self,
                               regression_results: Dict[str, Tuple[pd.Series, pd.Series, object]],
                               save_path: Optional[str] = None) -> pd.DataFrame:
        """
        Создает детальный отчет по всем моделям.

        Parameters:
        -----------
        regression_results : dict
            Результаты регрессий: (истинные значения, предсказанные значения, модель)
        save_path : str, optional
            Путь для сохранения отчета

        Returns:
        --------
        pd.DataFrame : Отчет с метриками всех моделей
        """
        report_data = []

        for model_name, (actual, predicted, model) in regression_results.items():
            actual_values = actual.values.flatten()
            predicted_values = predicted.values.flatten()

            # Базовые метрики
            metrics = {
                'Model': model_name,
                'R²': r2_score(actual_values, predicted_values),
                'R²_adj': self._get_adj_r2(model),
                'RMSE': np.sqrt(mean_squared_error(actual_values, predicted_values)),
                'MAE': mean_absolute_error(actual_values, predicted_values),
                'MAPE': np.mean(np.abs((actual_values - predicted_values) / actual_values)) * 100,
                'N': len(actual_values)
            }

            # Добавляем информацию о коэффициентах
            coef_info = self._get_coefficients_info(model)
            metrics.update(coef_info)

            report_data.append(metrics)

        # Создаем датафрейм
        report_df = pd.DataFrame(report_data)

        # Сортируем по R²
        report_df = report_df.sort_values('R²', ascending=False)

        # Сохраняем если нужно
        if save_path:
            report_df.to_csv(save_path, index=False)
            print(f"✅ Отчет сохранен в: {save_path}")

        return report_df

    def _get_adj_r2(self, model) -> float:
        """Получает скорректированный R² из модели."""
        try:
            if hasattr(model, 'rsquared_adj'):
                return model.rsquared_adj
            elif hasattr(model, 'score'):
                # Для sklearn - приблизительный расчет
                return model.score
        except:
            return np.nan
        return np.nan

    def _get_coefficients_info(self, model) -> Dict:
        """Извлекает информацию о коэффициентах из модели."""
        info = {}

        try:
            if hasattr(model, 'params'):
                params = model.params
                pvalues = model.pvalues if hasattr(model, 'pvalues') else None

                for i, (name, value) in enumerate(params.items()):
                    if name != 'const':
                        info[f'coef_{name}'] = value
                        if pvalues is not None:
                            info[f'p_{name}'] = pvalues[name]
        except:
            pass

        return info

    def visualize_single_model(self,
                               model_name: str,
                               actual: pd.Series,
                               predicted: pd.Series,
                               model: object,
                               save_path: Optional[str] = None,
                               show_stats: bool = True,
                               figsize: Optional[Tuple[float, float]] = None) -> None:
        """
        Визуализирует результат одной модели.

        Parameters:
        -----------
        model_name : str
            Название модели
        actual : pd.Series
            Истинные значения
        predicted : pd.Series
            Предсказанные значения
        model : object
            Обученная модель
        save_path : str, optional
            Путь для сохранения изображения
        show_stats : bool
            Показывать ли статистику на графике
        figsize : tuple, optional
            Размер фигуры
        """
        if figsize is None:
            figsize = self.figsize

        fig, ax = plt.subplots(figsize=figsize, dpi=self.dpi)

        # Общий диапазон для осей
        actual_values = actual.values.flatten()
        predicted_values = predicted.values.flatten()

        global_min = min(actual_values.min(), predicted_values.min())
        global_max = max(actual_values.max(), predicted_values.max())
        margin = (global_max - global_min) * 0.05
        axis_limits = (global_min - margin, global_max + margin)

        self._plot_single_model(
            ax, model_name, actual, predicted, model,
            axis_limits, show_stats,
            show_xlabel=True,
            show_ylabel=True
        )

        plt.tight_layout()

        if save_path:
            plt.savefig(save_path, dpi=self.dpi, bbox_inches='tight',
                        facecolor='white', edgecolor='none')
            print(f"✅ График сохранен в: {save_path}")

        plt.show()