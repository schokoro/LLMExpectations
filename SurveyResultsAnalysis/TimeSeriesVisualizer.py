from pathlib import Path
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd
import numpy as np
from typing import Optional, Tuple, Union, List, Dict, Any
from datetime import datetime

from scipy.stats import stats


class TimeSeriesVisualizer:
    """
    Класс для визуализации временных рядов с несинхронизированными датами
    Поддерживает один истинный ряд и несколько модельных рядов
    """

    def __init__(self,
                 true_series: pd.DataFrame,
                 model_series: Dict[str, pd.DataFrame],
                 additional_series: Optional[Dict[str, pd.DataFrame]] = None,
                 vertical_lines: Optional[Dict[str, str]] = None):
        """
        Args:
            true_series: DataFrame с колонками 'observable_inflation', 'expected_inflation'
                        Индекс - даты (истинный ряд)
            model_series: Словарь {имя_модели: DataFrame с колонками 'obs_mean', 'exp_mean'}
                         Индекс - даты (модельные ряды)
            additional_series: Словарь {имя_ряда: DataFrame с колонками 'Дата', 'Значение'}
                              Индекс - даты (дополнительные ряды для отображения)
            vertical_lines: Словарь {дата в формате 'dd.mm.yyyy': текст подписи}
                           Вертикальные прерывистые линии для отображения на графике
        """
        self.true_series = true_series.copy()
        self.model_series = {}
        self.additional_series = {}
        self.vertical_lines = {}

        # Приводим даты к datetime для истинного ряда
        if not pd.api.types.is_datetime64_any_dtype(self.true_series.index):
            self.true_series.index = pd.to_datetime(self.true_series.index)
        self.true_series = self.true_series.sort_index()

        # Приводим даты к datetime для каждого модельного ряда
        for name, df in model_series.items():
            self.model_series[name] = df.copy()
            if not pd.api.types.is_datetime64_any_dtype(self.model_series[name].index):
                self.model_series[name].index = pd.to_datetime(self.model_series[name].index)
            self.model_series[name] = self.model_series[name].sort_index()

        # Приводим даты к datetime для каждого дополнительного ряда
        if additional_series:
            for name, df in additional_series.items():
                self.additional_series[name] = df.copy()
                # Проверяем, есть ли колонка 'Дата'
                if 'Дата' in self.additional_series[name].columns:
                    if not pd.api.types.is_datetime64_any_dtype(self.additional_series[name]['Дата']):
                        self.additional_series[name]['Дата'] = pd.to_datetime(
                            self.additional_series[name]['Дата']
                        )
                    # Устанавливаем 'Дата' как индекс, если её там нет
                    if self.additional_series[name].index.name != 'Дата':
                        self.additional_series[name] = self.additional_series[name].set_index('Дата')
                elif not pd.api.types.is_datetime64_any_dtype(self.additional_series[name].index):
                    # Если 'Дата' не колонка, а индекс
                    self.additional_series[name].index = pd.to_datetime(
                        self.additional_series[name].index
                    )
                self.additional_series[name] = self.additional_series[name].sort_index()

        # Обрабатываем вертикальные линии
        if vertical_lines:
            for date_str, label in vertical_lines.items():
                try:
                    # Парсим дату в формате dd.mm.yyyy
                    date = datetime.strptime(date_str, '%d.%m.%Y')
                    self.vertical_lines[date] = label
                except ValueError:
                    print(f"⚠️ Неверный формат даты: {date_str}. Ожидается dd.mm.yyyy")

    def _get_date_range(self,
                        start_date: Optional[Union[str, datetime]] = None,
                        end_date: Optional[Union[str, datetime]] = None,
                        use_intersection: bool = False) -> Tuple[datetime, datetime]:
        """
        Определяет диапазон дат для отображения.
        Более широкий ряд расширяется на одну свою точку с каждой стороны
        относительно более узкого ряда.

        Args:
            start_date: начальная дата (опционально)
            end_date: конечная дата (опционально)
            use_intersection: если True, использует пересечение диапазонов

        Returns:
            (start, end) кортеж с датами
        """
        # Получаем все даты из всех рядов
        all_dates = [self.true_series.index]
        for df in self.model_series.values():
            all_dates.append(df.index)

        # Проверяем, что данные не пустые
        if not all_dates:
            print("⚠️ Нет данных")
            return datetime.now(), datetime.now()

        # Находим глобальные минимумы и максимумы
        all_min = min(dates.min() for dates in all_dates if len(dates) > 0)
        all_max = max(dates.max() for dates in all_dates if len(dates) > 0)

        if use_intersection:
            # Находим пересечение всех диапазонов
            raw_start = max(dates.min() for dates in all_dates if len(dates) > 0)
            raw_end = min(dates.max() for dates in all_dates if len(dates) > 0)

            if raw_start > raw_end:
                print("⚠️ Ряды данных не пересекаются во времени")
                mid_point = all_min + (all_max - all_min) / 2
                return mid_point - pd.Timedelta(days=30), mid_point + pd.Timedelta(days=30)

            # Определяем самый широкий ряд
            max_range = -1
            widest_dates = None
            for dates in all_dates:
                if len(dates) > 0:
                    date_range = (dates.max() - dates.min()).days
                    if date_range > max_range:
                        max_range = date_range
                        widest_dates = dates

            if widest_dates is not None:
                # Расширяем самый широкий ряд на одну точку с каждой стороны
                left_dates = widest_dates[widest_dates < raw_start]
                if len(left_dates) > 0:
                    start = left_dates[-1]
                else:
                    start = raw_start

                right_dates = widest_dates[widest_dates > raw_end]
                if len(right_dates) > 0:
                    end = right_dates[0]
                else:
                    end = raw_end
            else:
                start = raw_start
                end = raw_end

        else:
            # Используем объединение всех диапазонов
            start = all_min
            end = all_max

        # Применяем пользовательские ограничения
        if start_date is not None:
            start_date = pd.to_datetime(start_date)
            start = max(start, start_date)

        if end_date is not None:
            end_date = pd.to_datetime(end_date)
            end = min(end, end_date)

        if start > end:
            print(f"⚠️ Начальная дата ({start}) позже конечной ({end}). Меняем местами.")
            start, end = end, start

        return start, end

    def _determine_date_format(self, start_date: datetime, end_date: datetime) -> str:
        """Определяет формат отображения дат в зависимости от длины периода"""
        date_range = (end_date - start_date).days
        if date_range <= 60:
            return '%Y-%m-%d'
        elif date_range <= 365:
            return '%Y-%m-%d'
        elif date_range <= 1825:
            return '%Y-%m-%d'
        elif date_range <= 3650:
            return '%Y-%m-%d'
        else:
            return '%Y-%m-%d'

    def _determine_tick_interval(self, start_date: datetime, end_date: datetime) -> int:
        """Определяет интервал между метками на оси X"""
        date_range = (end_date - start_date).days
        if date_range <= 60:
            return 3
        elif date_range <= 180:
            return 7
        elif date_range <= 365:
            return 14
        elif date_range <= 730:
            return 30
        elif date_range <= 1825:
            return 60
        elif date_range <= 3650:
            return 90
        else:
            return 180

    def _filter_data_by_date(self,
                             start_date: datetime,
                             end_date: datetime):
        """
        Фильтрует данные по диапазону дат
        """
        true_filtered = self.true_series[
            (self.true_series.index >= start_date) &
            (self.true_series.index <= end_date)
            ]

        model_filtered = {}
        for name, df in self.model_series.items():
            model_filtered[name] = df[
                (df.index >= start_date) &
                (df.index <= end_date)
                ]

        return true_filtered, model_filtered

    def _add_date_labels(self, ax, dates, values, color, offset_x=0.02, offset_y=0.02, fontsize=8):
        """Добавляет подписи дат справа от каждой точки"""
        if len(dates) == 0:
            return

        xlim = ax.get_xlim()
        ylim = ax.get_ylim()
        x_range = xlim[1] - xlim[0]
        y_range = ylim[1] - ylim[0]

        for date, value in zip(dates, values):
            date_str = pd.Timestamp(date).strftime('%Y-%m-%d')
            x_pos = date + pd.Timedelta(days=x_range * offset_x)
            y_pos = value + y_range * offset_y

            ax.annotate(date_str,
                        xy=(date, value),
                        xytext=(x_pos, y_pos),
                        color=color,
                        fontsize=fontsize,
                        alpha=0.8,
                        weight='bold',
                        bbox=dict(boxstyle='round,pad=0.3',
                                  facecolor='white',
                                  edgecolor=color,
                                  alpha=0.7),
                        arrowprops=dict(arrowstyle='->',
                                        connectionstyle='arc3,rad=0.1',
                                        color=color,
                                        alpha=0.5,
                                        lw=0.5))

    def _add_vertical_lines(self, ax, y_min, y_max):
        """
        Добавляет вертикальные прерывистые линии для отмеченных дат
        """
        # Получаем текущие границы X в числовом формате (matplotlib dates)
        xlim = ax.get_xlim()

        # Преобразуем даты в числовой формат matplotlib для сравнения
        # matplotlib.dates.date2num преобразует datetime в числовой формат
        x_min_num = xlim[0]
        x_max_num = xlim[1]

        for date, label in self.vertical_lines.items():
            # Преобразуем datetime в числовой формат matplotlib
            date_num = mdates.date2num(date)

            # Проверяем, что дата в пределах текущего графика
            if x_min_num <= date_num <= x_max_num:
                # Рисуем вертикальную прерывистую линию черного цвета
                ax.axvline(x=date, color='black', linestyle='--', linewidth=1.5, alpha=0.7)

                # Добавляем подпись рядом с линией
                # Позиционируем подпись в верхней части графика
                y_pos = y_max * 0.95  # 95% от максимума

                # Форматируем дату для отображения
                date_str = date.strftime('%d.%m.%Y')

                # Текст подписи: дата + описание
                label_text = f"{date_str}\n{label}" if label else date_str

                ax.annotate(label_text,
                            xy=(date, y_pos),
                            xytext=(10, 0),  # Смещение вправо
                            textcoords='offset points',
                            fontsize=9,
                            color='black',
                            weight='bold',
                            ha='left',
                            va='top',
                            bbox=dict(boxstyle='round,pad=0.3',
                                      facecolor='white',
                                      edgecolor='black',
                                      alpha=0.8,
                                      linewidth=1))

    def plot_timeseries(self,
                        variable: str = 'observable',
                        figsize: Tuple[int, int] = (16, 8),
                        title: Optional[str] = None,
                        xlabel: str = 'Date',
                        ylabel: str = 'Inflation',
                        colors: Optional[Dict[str, str]] = None,
                        markers: Optional[Dict[str, str]] = None,
                        linestyles: Optional[Dict[str, str]] = None,
                        markersize: int = 8,
                        linewidth: int = 2,
                        alpha: float = 0.7,
                        show_ci: bool = True,
                        ci_alpha: float = 0.2,
                        grid: bool = True,
                        legend_loc: str = 'best',
                        legend_fontsize: int = 8,  # НОВЫЙ ПАРАМЕТР
                        show_ci_legend: bool = False,  # НОВЫЙ ПАРАМЕТР
                        save_path: Optional[Path] = None,
                        show: bool = True,
                        start_date: Optional[Union[str, datetime]] = None,
                        end_date: Optional[Union[str, datetime]] = None,
                        auto_format_dates: bool = True,
                        show_date_labels: bool = False,
                        date_labels_for: str = 'all',  # 'true', 'models', 'all'
                        label_fontsize: int = 8,
                        label_offset_x: float = 0.02,
                        label_offset_y: float = 0.02,
                        model_order: Optional[List[str]] = None,
                        additional_order: Optional[List[str]] = None,
                        show_vertical_lines: bool = True,
                        additional_alpha: float = 0.9,  # НОВЫЙ ПАРАМЕТР: прозрачность дополнительных рядов
                        additional_linewidth: float = 2.5,  # НОВЫЙ ПАРАМЕТР: толщина линий дополнительных рядов
                        additional_markersize: int = 4  # НОВЫЙ ПАРАМЕТР: размер маркеров дополнительных рядов
                        ):
        """
        Строит график временных рядов для observable или expected инфляции,
        включая дополнительные ряды, переданные в конструктор.

        Args:
            variable: 'observable' или 'expected'
            figsize: размер фигуры
            title: заголовок
            xlabel: подпись оси X
            ylabel: подпись оси Y
            colors: словарь цветов для рядов {'true': '#color', 'model1': '#color', 'additional1': '#color', ...}
            markers: словарь маркеров для рядов
            linestyles: словарь стилей линий для рядов
            markersize: размер маркеров
            linewidth: толщина линии
            alpha: прозрачность
            show_ci: показывать доверительные интервалы
            ci_alpha: прозрачность доверительных интервалов
            grid: показывать сетку
            legend_loc: позиция легенды
            save_path: путь для сохранения
            show: показывать график
            start_date: начальная дата для отображения
            end_date: конечная дата для отображения
            auto_format_dates: автоматически форматировать даты
            show_date_labels: показывать подписи дат справа от точек
            date_labels_for: для каких рядов показывать подписи ('true', 'models', 'all')
            label_fontsize: размер шрифта подписей
            label_offset_x: смещение подписей по X
            label_offset_y: смещение подписей по Y
            model_order: порядок отображения моделей в легенде
            additional_order: порядок отображения дополнительных рядов в легенде
            show_vertical_lines: показывать вертикальные линии для отмеченных дат
        """
        # Определяем колонки
        if variable == 'observable':
            true_col = 'observable_inflation'
            model_col = 'obs_mean'
            model_std_col = 'obs_std'
            default_title = f'Observable Inflation: True vs Models'
        else:
            true_col = 'expected_inflation'
            model_col = 'exp_mean'
            model_std_col = 'exp_std'
            default_title = f'Expected Inflation: True vs Models'

        if title is None:
            title = default_title

        # Настройки по умолчанию для цветов и маркеров
        default_colors = {
            'true': '#2E86C1',  # синий
        }

        # Цвета для моделей из палитры
        model_colors = [
            '#E74C3C',  # красный
            '#2ECC71',  # зеленый
            '#F39C12',  # оранжевый
            '#9B59B6',  # фиолетовый
            '#1ABC9C',  # бирюзовый
            '#E67E22',  # темно-оранжевый
            '#3498DB',  # голубой
            '#E74C3C',  # розовый
        ]

        # Цвета для дополнительных рядов (другие оттенки)
        additional_colors = [
            '#FF6B6B',  # светло-красный
            '#4ECDC4',  # мятный
            '#45B7D1',  # голубой
            '#96CEB4',  # салатовый
            '#FFEAA7',  # желтый
            '#DDA0DD',  # сливовый
            '#FF8C94',  # розовый
            '#A8E6CF',  # светло-зеленый
        ]

        for i, name in enumerate(self.model_series.keys()):
            default_colors[name] = model_colors[i % len(model_colors)]

        for i, name in enumerate(self.additional_series.keys()):
            default_colors[name] = additional_colors[i % len(additional_colors)]

        default_markers = {
            'true': 'o',
        }

        model_markers = ['s', '^', 'D', '*', 'p', 'X', 'h', 'v']
        for i, name in enumerate(self.model_series.keys()):
            default_markers[name] = model_markers[i % len(model_markers)]

        additional_markers = ['s', '^', 'D', '*', 'p', 'X', 'h', 'v']
        for i, name in enumerate(self.additional_series.keys()):
            default_markers[name] = additional_markers[i % len(additional_markers)]

        default_linestyles = {
            'true': '-',
        }

        model_linestyles = ['-', '--', '-.', ':', '-', '--', '-.', ':']
        for i, name in enumerate(self.model_series.keys()):
            default_linestyles[name] = model_linestyles[i % len(model_linestyles)]

        additional_linestyles = ['-', '--', '-.', ':', '-', '--', '-.', ':']
        for i, name in enumerate(self.additional_series.keys()):
            default_linestyles[name] = additional_linestyles[i % len(additional_linestyles)]

        # Применяем пользовательские настройки
        colors = colors or {}
        markers = markers or {}
        linestyles = linestyles or {}

        all_colors = {**default_colors, **colors}
        all_markers = {**default_markers, **markers}
        all_linestyles = {**default_linestyles, **linestyles}

        # Определяем диапазон дат (без use_intersection)
        start, end = self._get_date_range(start_date, end_date, use_intersection=False)

        # Фильтруем данные
        true_filtered, model_filtered = self._filter_data_by_date(start, end)

        # Фильтруем дополнительные ряды
        additional_filtered = {}
        for name, df in self.additional_series.items():
            additional_filtered[name] = df[
                (df.index >= start) &
                (df.index <= end)
                ]

        # Проверяем, остались ли данные после фильтрации
        if true_filtered.empty and all(df.empty for df in model_filtered.values()) and all(
                df.empty for df in additional_filtered.values()):
            print("⚠️ Нет данных в выбранном диапазоне дат")
            return None, None

        # Создаем график
        fig, ax = plt.subplots(figsize=figsize)

        # Определяем порядок отображения моделей
        if model_order is None:
            model_names = list(model_filtered.keys())
        else:
            model_names = [name for name in model_order if name in model_filtered]

        # Определяем порядок отображения дополнительных рядов
        if additional_order is None:
            additional_names = list(additional_filtered.keys())
        else:
            additional_names = [name for name in additional_order if name in additional_filtered]

        # Рисуем истинный ряд
        if not true_filtered.empty:
            ax.plot(true_filtered.index,
                    true_filtered[true_col],
                    marker=all_markers.get('true', 'o'),
                    linestyle=all_linestyles.get('true', '-'),
                    color=all_colors.get('true', '#2E86C1'),
                    linewidth=linewidth,
                    markersize=markersize,
                    alpha=alpha,
                    label='Опрос Инфом (след день после опроса)')

        # Рисуем модельные ряды
        for name in model_names:
            df = model_filtered[name]
            if not df.empty:
                ax.plot(df.index,
                        df[model_col],
                        marker=all_markers.get(name, 's'),
                        linestyle='--',  # all_linestyles.get(name, '-'),
                        color=all_colors.get(name, '#E74C3C'),
                        linewidth=linewidth,
                        markersize=markersize,
                        alpha=alpha,
                        label=name)

                # Доверительные интервалы для моделей
                if show_ci and model_std_col in df.columns:
                    ax.fill_between(df.index,
                                    df[model_col] - df[model_std_col],
                                    df[model_col] + df[model_std_col],
                                    alpha=ci_alpha,
                                    color=all_colors.get(name, '#E74C3C'),
                                    label=f'{name} CI' if show_ci_legend else None)

        # Рисуем дополнительные ряды
        for name in additional_names:
            df = additional_filtered[name]
            if not df.empty:
                # Проверяем, есть ли колонка 'Значение'
                if 'Значение' in df.columns:
                    values = df['Значение']
                else:
                    # Если нет 'Значение', берем первую колонку
                    values = df.iloc[:, 0]

                ax.plot(df.index,
                        values,
                        marker=all_markers.get(name, 's'),
                        linestyle=all_linestyles.get(name, '-'),
                        color=all_colors.get(name, '#FF6B6B'),
                        linewidth=additional_linewidth,  # Более толстая линия
                        markersize=additional_markersize,  # Более крупные маркеры
                        alpha=additional_alpha,  # Более насыщенный (меньше прозрачности)
                        label=name)

        # Добавляем вертикальные линии
        if show_vertical_lines and self.vertical_lines:
            # Получаем y-границы для размещения подписей
            y_min, y_max = ax.get_ylim()
            self._add_vertical_lines(ax, y_min, y_max)

        # Добавляем подписи дат
        if show_date_labels:
            # Для истинного ряда
            if date_labels_for in ['true', 'all'] and not true_filtered.empty:
                self._add_date_labels(
                    ax,
                    true_filtered.index,
                    true_filtered[true_col],
                    all_colors.get('true', '#2E86C1'),
                    offset_x=label_offset_x,
                    offset_y=label_offset_y,
                    fontsize=label_fontsize
                )

            # Для модельных рядов
            if date_labels_for in ['models', 'all']:
                for name in model_names:
                    df = model_filtered[name]
                    if not df.empty:
                        self._add_date_labels(
                            ax,
                            df.index,
                            df[model_col],
                            all_colors.get(name, '#E74C3C'),
                            offset_x=label_offset_x,
                            offset_y=label_offset_y,
                            fontsize=label_fontsize
                        )

            # Для дополнительных рядов
            if date_labels_for in ['all']:
                for name in additional_names:
                    df = additional_filtered[name]
                    if not df.empty:
                        if 'Значение' in df.columns:
                            values = df['Значение']
                        else:
                            values = df.iloc[:, 0]
                        self._add_date_labels(
                            ax,
                            df.index,
                            values,
                            all_colors.get(name, '#FF6B6B'),
                            offset_x=label_offset_x,
                            offset_y=label_offset_y,
                            fontsize=label_fontsize
                        )

        # Настройки графика
        ax.set_title(title, fontsize=14, fontweight='bold')
        ax.set_xlabel(xlabel, fontsize=12)
        ax.set_ylabel(ylabel, fontsize=12)

        if grid:
            ax.grid(True, alpha=0.3)

        legend = ax.legend(loc=legend_loc, fontsize=legend_fontsize)

        # Автоматическое форматирование дат
        if auto_format_dates:
            date_format = self._determine_date_format(start, end)
            tick_interval = self._determine_tick_interval(start, end)

            ax.xaxis.set_major_formatter(mdates.DateFormatter(date_format))
            ax.xaxis.set_major_locator(mdates.DayLocator(interval=tick_interval))

            if show_date_labels:
                x_range = (end - start).days
                padding = x_range * 0.1
                ax.set_xlim(start - pd.Timedelta(days=padding),
                            end + pd.Timedelta(days=padding))
            else:
                ax.set_xlim(start, end)

        fig.autofmt_xdate()
        plt.tight_layout()

        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            print(f"✅ График сохранен: {save_path}")

        if show:
            plt.show()
        else:
            plt.close()

        return fig, ax

    def plot_both(self,
                  figsize: Tuple[int, int] = (14, 12),
                  save_prefix: Optional[str] = None,
                  start_date: Optional[Union[str, datetime]] = None,
                  end_date: Optional[Union[str, datetime]] = None,
                  use_intersection: bool = False,
                  show_date_labels: bool = False,
                  date_labels_for: str = 'all',
                  show_vertical_lines: bool = True,
                  **kwargs):
        """
        Строит два графика: для observable и expected инфляции
        """
        fig, axes = plt.subplots(2, 1, figsize=figsize)

        # Observable
        self._plot_on_axes(axes[0], 'observable',
                           start_date=start_date,
                           end_date=end_date,
                           use_intersection=use_intersection,
                           show_date_labels=show_date_labels,
                           date_labels_for=date_labels_for,
                           show_vertical_lines=show_vertical_lines,
                           **kwargs)

        # Expected
        self._plot_on_axes(axes[1], 'expected',
                           start_date=start_date,
                           end_date=end_date,
                           use_intersection=use_intersection,
                           show_date_labels=show_date_labels,
                           date_labels_for=date_labels_for,
                           show_vertical_lines=show_vertical_lines,
                           **kwargs)

        plt.tight_layout()

        if save_prefix:
            start, end = self._get_date_range(start_date, end_date, use_intersection)
            filename = f'{save_prefix}_both_{start.strftime("%Y%m%d")}_{end.strftime("%Y%m%d")}.png'
            plt.savefig(filename, dpi=300, bbox_inches='tight')
            print(f"✅ График сохранен: {filename}")

        plt.show()
        return fig, axes

    def _plot_on_axes(self, ax, variable, **kwargs):
        """Вспомогательный метод для рисования на переданной оси"""
        if variable == 'observable':
            true_col = 'observable_inflation'
            model_col = 'obs_mean'
            model_std_col = 'obs_std'
            title = 'Observable Inflation'
        else:
            true_col = 'expected_inflation'
            model_col = 'exp_mean'
            model_std_col = 'exp_std'
            title = 'Expected Inflation'

        start_date = kwargs.get('start_date', None)
        end_date = kwargs.get('end_date', None)
        use_intersection = kwargs.get('use_intersection', False)
        show_date_labels = kwargs.get('show_date_labels', False)
        date_labels_for = kwargs.get('date_labels_for', 'all')
        label_fontsize = kwargs.get('label_fontsize', 8)
        label_offset_x = kwargs.get('label_offset_x', 0.02)
        label_offset_y = kwargs.get('label_offset_y', 0.02)
        grid = kwargs.get('grid', True)
        legend_loc = kwargs.get('legend_loc', 'best')
        show_ci = kwargs.get('show_ci', True)
        ci_alpha = kwargs.get('ci_alpha', 0.2)
        alpha = kwargs.get('alpha', 0.7)
        show_vertical_lines = kwargs.get('show_vertical_lines', True)

        # Настройки цветов
        colors = kwargs.get('colors', {})
        markers = kwargs.get('markers', {})
        linestyles = kwargs.get('linestyles', {})

        default_colors = {'true': '#2E86C1'}
        model_colors = ['#E74C3C', '#2ECC71', '#F39C12', '#9B59B6', '#1ABC9C', '#E67E22', '#3498DB']
        for i, name in enumerate(self.model_series.keys()):
            default_colors[name] = model_colors[i % len(model_colors)]

        all_colors = {**default_colors, **colors}

        start, end = self._get_date_range(start_date, end_date, use_intersection)
        true_filtered, model_filtered = self._filter_data_by_date(start, end)

        # Истинный ряд
        if not true_filtered.empty:
            ax.plot(true_filtered.index,
                    true_filtered[true_col],
                    marker='o',
                    linestyle='-',
                    color=all_colors.get('true', '#2E86C1'),
                    linewidth=2,
                    markersize=6,
                    alpha=alpha,
                    label='True Series')

        # Модельные ряды
        for name, df in model_filtered.items():
            if not df.empty:
                ax.plot(df.index,
                        df[model_col],
                        marker='s',
                        linestyle='-',
                        color=all_colors.get(name, '#E74C3C'),
                        linewidth=2,
                        markersize=6,
                        alpha=alpha,
                        label=name)

                if show_ci and model_std_col in df.columns:
                    ax.fill_between(df.index,
                                    df[model_col] - df[model_std_col],
                                    df[model_col] + df[model_std_col],
                                    alpha=ci_alpha,
                                    color=all_colors.get(name, '#E74C3C'),
                                    label=f'{name} CI')

        # Добавляем вертикальные линии
        if show_vertical_lines and self.vertical_lines:
            y_min, y_max = ax.get_ylim()
            self._add_vertical_lines(ax, y_min, y_max)

        # Подписи дат
        if show_date_labels:
            if date_labels_for in ['true', 'all'] and not true_filtered.empty:
                self._add_date_labels(
                    ax,
                    true_filtered.index,
                    true_filtered[true_col],
                    all_colors.get('true', '#2E86C1'),
                    offset_x=label_offset_x,
                    offset_y=label_offset_y,
                    fontsize=label_fontsize
                )

            if date_labels_for in ['models', 'all']:
                for name, df in model_filtered.items():
                    if not df.empty:
                        self._add_date_labels(
                            ax,
                            df.index,
                            df[model_col],
                            all_colors.get(name, '#E74C3C'),
                            offset_x=label_offset_x,
                            offset_y=label_offset_y,
                            fontsize=label_fontsize
                        )

        ax.set_title(title, fontsize=12, fontweight='bold')
        ax.set_xlabel('Date', fontsize=10)
        ax.set_ylabel('Inflation', fontsize=10)

        if grid:
            ax.grid(True, alpha=0.3)

        ax.legend(loc=legend_loc)

        date_format = self._determine_date_format(start, end)
        tick_interval = self._determine_tick_interval(start, end)

        ax.xaxis.set_major_formatter(mdates.DateFormatter(date_format))
        ax.xaxis.set_major_locator(mdates.DayLocator(interval=tick_interval))

        if show_date_labels:
            x_range = (end - start).days
            padding = x_range * 0.1
            ax.set_xlim(start - pd.Timedelta(days=padding),
                        end + pd.Timedelta(days=padding))
        else:
            ax.set_xlim(start, end)

        fig = ax.get_figure()
        fig.autofmt_xdate()

    def _plot_on_axes(self, ax, variable, **kwargs):
        """Вспомогательный метод для рисования на переданной оси"""
        if variable == 'observable':
            true_col = 'observable_inflation'
            model_col = 'obs_mean'
            model_std_col = 'obs_std'
            title = 'Observable Inflation'
        else:
            true_col = 'expected_inflation'
            model_col = 'exp_mean'
            model_std_col = 'exp_std'
            title = 'Expected Inflation'

        start_date = kwargs.get('start_date', None)
        end_date = kwargs.get('end_date', None)
        use_intersection = kwargs.get('use_intersection', False)
        show_date_labels = kwargs.get('show_date_labels', False)
        date_labels_for = kwargs.get('date_labels_for', 'all')
        label_fontsize = kwargs.get('label_fontsize', 8)
        label_offset_x = kwargs.get('label_offset_x', 0.02)
        label_offset_y = kwargs.get('label_offset_y', 0.02)
        grid = kwargs.get('grid', True)
        legend_loc = kwargs.get('legend_loc', 'best')
        show_ci = kwargs.get('show_ci', True)
        ci_alpha = kwargs.get('ci_alpha', 0.2)
        alpha = kwargs.get('alpha', 0.7)

        # Настройки цветов
        colors = kwargs.get('colors', {})
        markers = kwargs.get('markers', {})
        linestyles = kwargs.get('linestyles', {})

        default_colors = {'true': '#2E86C1'}
        model_colors = ['#E74C3C', '#2ECC71', '#F39C12', '#9B59B6', '#1ABC9C', '#E67E22', '#3498DB']
        for i, name in enumerate(self.model_series.keys()):
            default_colors[name] = model_colors[i % len(model_colors)]

        all_colors = {**default_colors, **colors}

        start, end = self._get_date_range(start_date, end_date, use_intersection)
        true_filtered, model_filtered = self._filter_data_by_date(start, end)

        # Истинный ряд
        if not true_filtered.empty:
            ax.plot(true_filtered.index,
                    true_filtered[true_col],
                    marker='o',
                    linestyle='-',
                    color=all_colors.get('true', '#2E86C1'),
                    linewidth=2,
                    markersize=6,
                    alpha=alpha,
                    label='True Series')

        # Модельные ряды
        for name, df in model_filtered.items():
            if not df.empty:
                ax.plot(df.index,
                        df[model_col],
                        marker='s',
                        linestyle='-',
                        color=all_colors.get(name, '#E74C3C'),
                        linewidth=2,
                        markersize=6,
                        alpha=alpha,
                        label=name)

                if show_ci and model_std_col in df.columns:
                    ax.fill_between(df.index,
                                    df[model_col] - df[model_std_col],
                                    df[model_col] + df[model_std_col],
                                    alpha=ci_alpha,
                                    color=all_colors.get(name, '#E74C3C'),
                                    label=f'{name} CI')

        # Подписи дат
        if show_date_labels:
            if date_labels_for in ['true', 'all'] and not true_filtered.empty:
                self._add_date_labels(
                    ax,
                    true_filtered.index,
                    true_filtered[true_col],
                    all_colors.get('true', '#2E86C1'),
                    offset_x=label_offset_x,
                    offset_y=label_offset_y,
                    fontsize=label_fontsize
                )

            if date_labels_for in ['models', 'all']:
                for name, df in model_filtered.items():
                    if not df.empty:
                        self._add_date_labels(
                            ax,
                            df.index,
                            df[model_col],
                            all_colors.get(name, '#E74C3C'),
                            offset_x=label_offset_x,
                            offset_y=label_offset_y,
                            fontsize=label_fontsize
                        )

        ax.set_title(title, fontsize=12, fontweight='bold')
        ax.set_xlabel('Date', fontsize=10)
        ax.set_ylabel('Inflation', fontsize=10)

        if grid:
            ax.grid(True, alpha=0.3)

        ax.legend(loc=legend_loc)


        date_format = self._determine_date_format(start, end)
        tick_interval = self._determine_tick_interval(start, end)

        ax.xaxis.set_major_formatter(mdates.DateFormatter(date_format))
        ax.xaxis.set_major_locator(mdates.DayLocator(interval=tick_interval))

        if show_date_labels:
            x_range = (end - start).days
            padding = x_range * 0.1
            ax.set_xlim(start - pd.Timedelta(days=padding),
                        end + pd.Timedelta(days=padding))
        else:
            ax.set_xlim(start, end)

        fig = ax.get_figure()
        fig.autofmt_xdate()

    def plot_correlation(self,
                         variable: str = 'observable',
                         figsize: Tuple[int, int] = (15, 10),
                         title: Optional[str] = None,
                         colors: Optional[Dict[str, str]] = None,
                         markersize: int = 30,
                         alpha: float = 0.7,
                         grid: bool = True,
                         save_path: Optional[Path] = None,
                         show: bool = True,
                         start_date: Optional[Union[str, datetime]] = None,
                         end_date: Optional[Union[str, datetime]] = None,
                         use_intersection: bool = False,
                         model_order: Optional[List[str]] = None,
                         ncols: int = 2,
                         cut_date: Optional[Union[str, datetime]] = None):
        """
        Строит графики корреляции между истинным рядом и каждым модельным рядом.
        Каждая модель отображается на отдельном subplot.
        Сопоставление происходит по ПОРЯДКОВОМУ НОМЕРУ.

        Args:
            ncols: количество колонок в сетке subplots
            cut_date: дата, до которой отсекаются точки (удаляются все точки до этой даты)
        """
        from scipy import stats

        # Определяем колонки
        if variable == 'observable':
            true_col = 'observable_inflation'
            model_col = 'obs_mean'
            default_title = f'Correlation: Observable Inflation - Models vs True'
        else:
            true_col = 'expected_inflation'
            model_col = 'exp_mean'
            default_title = f'Correlation: Expected Inflation - Models vs True'

        # Настройки цветов
        default_colors = {}
        model_colors = ['#E74C3C', '#2ECC71', '#F39C12', '#9B59B6', '#1ABC9C', '#E67E22', '#3498DB', '#E74C3C']
        for i, name in enumerate(self.model_series.keys()):
            default_colors[name] = model_colors[i % len(model_colors)]

        colors = colors or {}
        all_colors = {**default_colors, **colors}

        # Определяем диапазон дат
        start, end = self._get_date_range(start_date, end_date, use_intersection)

        # Фильтруем данные
        true_filtered, model_filtered = self._filter_data_by_date(start, end)

        if true_filtered.empty:
            print("⚠️ Нет данных для истинного ряда")
            return None, None

        # Применяем cut_date для отсечения первых точек
        cut_idx = 0
        if cut_date is not None:
            cut_date = pd.to_datetime(cut_date)

            # Находим индекс первой даты после cut_date
            true_dates = true_filtered.index
            cut_idx = np.searchsorted(true_dates, cut_date, side='left')

            # Если есть даты после cut_date
            if cut_idx < len(true_dates):
                # Обрезаем true_filtered
                true_filtered = true_filtered.iloc[cut_idx:]

                # Обрезаем все модели на то же количество точек с начала
                for name in model_filtered:
                    if not model_filtered[name].empty:
                        model_filtered[name] = model_filtered[name].iloc[cut_idx:]

                print(f"✂️ Отсечено {cut_idx} точек до даты {cut_date}")
            else:
                print(f"⚠️ Нет точек после даты {cut_date}")
                return None, None

        # Формируем заголовок с информацией о cut_date
        if title is None:
            if cut_date is not None:
                title = f'{default_title} (cut-off: {cut_date.strftime("%Y-%m-%d")}, removed {cut_idx} points)'
            else:
                title = default_title

        # Определяем порядок отображения
        if model_order is None:
            model_names = list(model_filtered.keys())
        else:
            model_names = [name for name in model_order if name in model_filtered]

        # Убираем пустые модели
        model_names = [name for name in model_names if not model_filtered[name].empty]

        if not model_names:
            print("⚠️ Нет моделей с данными")
            return None, None

        # Определяем количество subplots
        n_models = len(model_names)
        nrows = (n_models + ncols - 1) // ncols

        # Создаем фигуру с subplots
        fig, axes = plt.subplots(nrows, ncols, figsize=figsize)

        # Если只有一个 subplot, преобразуем в список
        if n_models == 1:
            axes = np.array([axes])
        else:
            axes = axes.flatten()

        # Получаем значения истинного ряда
        true_values = true_filtered[true_col].values

        # Для каждой модели строим отдельный subplot
        for idx, name in enumerate(model_names):
            ax = axes[idx]
            df = model_filtered[name]

            # Получаем значения модели
            model_values = df[model_col].values

            # Сопоставляем по порядковому номеру
            min_len = min(len(true_values), len(model_values))
            true_aligned = true_values[:min_len]
            model_aligned = model_values[:min_len]

            # Строим scatter plot
            ax.scatter(model_aligned, true_aligned,
                       color=all_colors.get(name, '#E74C3C'),
                       s=markersize,
                       alpha=alpha,
                       label='Data points')

            # Вычисляем статистику
            if len(model_aligned) > 2:
                # Проверяем, есть ли вариация в данных
                if np.std(model_aligned) > 1e-10 and np.std(true_aligned) > 1e-10:
                    # Корреляция Пирсона
                    correlation, p_value = stats.pearsonr(model_aligned, true_aligned)
                    r_squared = correlation ** 2

                    # Коэффициент зависимости (наклон линейной регрессии)
                    slope, intercept, r_value, p_value_reg, std_err = stats.linregress(model_aligned, true_aligned)

                    # Определяем звездочки для p-value
                    if p_value < 0.001:
                        stars = '***'
                    elif p_value < 0.01:
                        stars = '**'
                    elif p_value < 0.05:
                        stars = '*'
                    else:
                        stars = 'ns'

                    # Добавляем линию регрессии
                    x_line = np.array([model_aligned.min(), model_aligned.max()])
                    y_line = slope * x_line + intercept
                    ax.plot(x_line, y_line,
                            color=all_colors.get(name, '#E74C3C'),
                            linestyle='--',
                            alpha=0.7,
                            linewidth=2,
                            label=f'Regression (slope={slope:.3f})')

                    # Добавляем текст с статистикой в правый верхний угол
                    stats_text = (f'r = {correlation:.4f}{stars}\n'
                                  f'R² = {r_squared:.4f}\n'
                                  f'p = {p_value:.4e}\n'
                                  f'n = {len(model_aligned)}')

                    ax.text(0.95, 0.95, stats_text,
                            transform=ax.transAxes,
                            fontsize=10,
                            verticalalignment='top',
                            horizontalalignment='right',
                            bbox=dict(boxstyle='round,pad=0.5',
                                      facecolor='white',
                                      edgecolor=all_colors.get(name, '#E74C3C'),
                                      alpha=0.9))
                else:
                    ax.text(0.5, 0.5, 'No variation in data',
                            transform=ax.transAxes,
                            fontsize=12,
                            ha='center', va='center',
                            bbox=dict(boxstyle='round,pad=0.5',
                                      facecolor='yellow',
                                      alpha=0.5))
            else:
                ax.text(0.5, 0.5, f'Not enough points (n={len(model_aligned)})',
                        transform=ax.transAxes,
                        fontsize=12,
                        ha='center', va='center',
                        bbox=dict(boxstyle='round,pad=0.5',
                                  facecolor='yellow',
                                  alpha=0.5))

            # Линия y=x для справки
            min_val = min(ax.get_xlim()[0], ax.get_ylim()[0])
            max_val = max(ax.get_xlim()[1], ax.get_ylim()[1])
            ax.plot([min_val, max_val], [min_val, max_val],
                    'k--', alpha=0.2, linewidth=1, label='y = x')

            # Настройки subplot
            ax.set_title(f'{name}', fontsize=12, fontweight='bold')
            ax.set_xlabel('Model Values', fontsize=10)
            ax.set_ylabel('True Values', fontsize=10)
            ax.legend(loc='lower right', fontsize=8)

            if grid:
                ax.grid(True, alpha=0.3)

            ax.axis('equal')

        # Скрываем неиспользуемые subplots
        for idx in range(len(model_names), len(axes)):
            axes[idx].set_visible(False)

        # Общий заголовок с информацией о cut_date
        fig.suptitle(title, fontsize=14, fontweight='bold', y=0.98)

        plt.tight_layout()

        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            print(f"✅ График корреляции сохранен: {save_path}")

        if show:
            plt.show()
        else:
            plt.close()

        return fig, axes

    def plot_correlation_diff(self,
                              variable: str = 'observable',
                              figsize: Tuple[int, int] = (15, 10),
                              title: Optional[str] = None,
                              colors: Optional[Dict[str, str]] = None,
                              markersize: int = 30,
                              alpha: float = 0.7,
                              grid: bool = True,
                              save_path: Optional[Path] = None,
                              show: bool = True,
                              start_date: Optional[Union[str, datetime]] = None,
                              end_date: Optional[Union[str, datetime]] = None,
                              use_intersection: bool = False,
                              model_order: Optional[List[str]] = None,
                              ncols: int = 2,
                              cut_date: Optional[Union[str, datetime]] = None):
        """
        Строит графики корреляции между приростами истинного ряда и каждого модельного ряда.
        Каждая модель отображается на отдельном subplot.
        Сопоставление происходит по ПОРЯДКОВОМУ НОМЕРУ.

        Args:
            ncols: количество колонок в сетке subplots
            cut_date: дата, до которой отсекаются точки (удаляются все точки до этой даты)
        """
        from scipy import stats

        # Определяем колонки
        if variable == 'observable':
            true_col = 'observable_inflation'
            model_col = 'obs_mean'
            default_title = f'Correlation of Differences: Observable Inflation - Models vs True'
        else:
            true_col = 'expected_inflation'
            model_col = 'exp_mean'
            default_title = f'Correlation of Differences: Expected Inflation - Models vs True'

        # Настройки цветов
        default_colors = {}
        model_colors = ['#E74C3C', '#2ECC71', '#F39C12', '#9B59B6', '#1ABC9C', '#E67E22', '#3498DB', '#E74C3C']
        for i, name in enumerate(self.model_series.keys()):
            default_colors[name] = model_colors[i % len(model_colors)]

        colors = colors or {}
        all_colors = {**default_colors, **colors}

        # Определяем диапазон дат
        start, end = self._get_date_range(start_date, end_date, use_intersection)

        # Фильтруем данные
        true_filtered, model_filtered = self._filter_data_by_date(start, end)

        if true_filtered.empty:
            print("⚠️ Нет данных для истинного ряда")
            return None, None

        # Применяем cut_date для отсечения первых точек
        cut_idx = 0
        if cut_date is not None:
            cut_date = pd.to_datetime(cut_date)

            # Находим индекс первой даты после cut_date
            true_dates = true_filtered.index
            cut_idx = np.searchsorted(true_dates, cut_date, side='left')

            # Если есть даты после cut_date
            if cut_idx < len(true_dates):
                # Обрезаем true_filtered
                true_filtered = true_filtered.iloc[cut_idx:]

                # Обрезаем все модели на то же количество точек с начала
                for name in model_filtered:
                    if not model_filtered[name].empty:
                        model_filtered[name] = model_filtered[name].iloc[cut_idx:]

                print(f"✂️ Отсечено {cut_idx} точек до даты {cut_date}")
            else:
                print(f"⚠️ Нет точек после даты {cut_date}")
                return None, None

        # Формируем заголовок с информацией о cut_date
        if title is None:
            if cut_date is not None:
                title = f'{default_title} (cut-off: {cut_date.strftime("%Y-%m-%d")}, removed {cut_idx} points)'
            else:
                title = default_title

        # Вычисляем приросты для истинного ряда
        true_values = true_filtered[true_col].values
        true_diff = np.diff(true_values)

        # Определяем порядок отображения
        if model_order is None:
            model_names = list(model_filtered.keys())
        else:
            model_names = [name for name in model_order if name in model_filtered]

        # Убираем пустые модели
        model_names = [name for name in model_names if not model_filtered[name].empty]

        if not model_names:
            print("⚠️ Нет моделей с данными")
            return None, None

        # Определяем количество subplots
        n_models = len(model_names)
        nrows = (n_models + ncols - 1) // ncols

        # Создаем фигуру с subplots
        fig, axes = plt.subplots(nrows, ncols, figsize=figsize)

        # Если只有一个 subplot, преобразуем в список
        if n_models == 1:
            axes = np.array([axes])
        else:
            axes = axes.flatten()

        # Для каждой модели строим отдельный subplot
        for idx, name in enumerate(model_names):
            ax = axes[idx]
            df = model_filtered[name]

            # Вычисляем приросты для модели
            model_values = df[model_col].values
            model_diff = np.diff(model_values)

            # Сопоставляем по порядковому номеру
            min_len = min(len(true_diff), len(model_diff))
            true_diff_aligned = true_diff[:min_len]
            model_diff_aligned = model_diff[:min_len]

            # Строим scatter plot
            ax.scatter(model_diff_aligned, true_diff_aligned,
                       color=all_colors.get(name, '#E74C3C'),
                       s=markersize,
                       alpha=alpha,
                       label='Data points')

            # Вычисляем статистику
            if len(model_diff_aligned) > 2:
                # Проверяем, есть ли вариация в данных
                if np.std(model_diff_aligned) > 1e-10 and np.std(true_diff_aligned) > 1e-10:
                    # Корреляция Пирсона
                    correlation, p_value = stats.pearsonr(model_diff_aligned, true_diff_aligned)
                    r_squared = correlation ** 2

                    # Коэффициент зависимости
                    slope, intercept, r_value, p_value_reg, std_err = stats.linregress(model_diff_aligned,
                                                                                       true_diff_aligned)

                    # Определяем звездочки для p-value
                    if p_value < 0.001:
                        stars = '***'
                    elif p_value < 0.01:
                        stars = '**'
                    elif p_value < 0.05:
                        stars = '*'
                    else:
                        stars = 'ns'

                    # Добавляем линию регрессии
                    x_line = np.array([model_diff_aligned.min(), model_diff_aligned.max()])
                    y_line = slope * x_line + intercept
                    ax.plot(x_line, y_line,
                            color=all_colors.get(name, '#E74C3C'),
                            linestyle='--',
                            alpha=0.7,
                            linewidth=2,
                            label=f'Regression (slope={slope:.3f})')

                    # Добавляем текст с статистикой
                    stats_text = (f'r = {correlation:.4f}{stars}\n'
                                  f'R² = {r_squared:.4f}\n'
                                  f'p = {p_value:.4e}\n'
                                  f'n = {len(model_diff_aligned)}')

                    ax.text(0.95, 0.95, stats_text,
                            transform=ax.transAxes,
                            fontsize=10,
                            verticalalignment='top',
                            horizontalalignment='right',
                            bbox=dict(boxstyle='round,pad=0.5',
                                      facecolor='white',
                                      edgecolor=all_colors.get(name, '#E74C3C'),
                                      alpha=0.9))
                else:
                    ax.text(0.5, 0.5, 'No variation in differences',
                            transform=ax.transAxes,
                            fontsize=12,
                            ha='center', va='center',
                            bbox=dict(boxstyle='round,pad=0.5',
                                      facecolor='yellow',
                                      alpha=0.5))
            else:
                ax.text(0.5, 0.5, f'Not enough points (n={len(model_diff_aligned)})',
                        transform=ax.transAxes,
                        fontsize=12,
                        ha='center', va='center',
                        bbox=dict(boxstyle='round,pad=0.5',
                                  facecolor='yellow',
                                  alpha=0.5))

            # Линия y=x для справки
            min_val = min(ax.get_xlim()[0], ax.get_ylim()[0])
            max_val = max(ax.get_xlim()[1], ax.get_ylim()[1])
            ax.plot([min_val, max_val], [min_val, max_val],
                    'k--', alpha=0.2, linewidth=1, label='y = x')

            # Настройки subplot
            ax.set_title(f'{name} (differences)', fontsize=12, fontweight='bold')
            ax.set_xlabel('Model Differences', fontsize=10)
            ax.set_ylabel('True Differences', fontsize=10)
            ax.legend(loc='lower right', fontsize=8)

            if grid:
                ax.grid(True, alpha=0.3)

            ax.axis('equal')

        # Скрываем неиспользуемые subplots
        for idx in range(len(model_names), len(axes)):
            axes[idx].set_visible(False)

        # Общий заголовок с информацией о cut_date
        fig.suptitle(title, fontsize=14, fontweight='bold', y=0.98)

        plt.tight_layout()

        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            print(f"✅ График корреляции приростов сохранен: {save_path}")

        if show:
            plt.show()
        else:
            plt.close()

        return fig, axes