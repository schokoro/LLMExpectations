import json
import os
import glob
from typing import Dict, List, Tuple
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path


def load_json_files(folder_path: Path, filter: str = None) -> List[Dict]:
    """
    Загружает все JSON файлы из указанной папки.

    Args:
        folder_path: Путь к папке с JSON файлами

    Returns:
        Список словарей с данными из всех файлов
    """
    json_files = glob.glob(os.path.join(folder_path, "*.json"))

    if not json_files:
        raise ValueError(f"No JSON files found in folder: {folder_path}")

    if filter is not None:
        json_files = [f for f in json_files if os.path.basename(f).startswith(filter)]

    data = []
    for file_path in json_files:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                file_data = json.load(f)
                data.append(file_data)
        except json.JSONDecodeError as e:
            print(f"Error parsing {file_path}: {e}")
            continue
        except Exception as e:
            print(f"Error reading {file_path}: {e}")
            continue

    print(f"Loaded {len(data)} files from {folder_path}")
    return data

def extract_variable_values(data: List[Dict]) -> Dict[str, List[float]]:
    """
    Извлекает значения SHAP переменных из загруженных данных.

    Args:
        data: Список словарей с данными из JSON файлов

    Returns:
        Словарь, где ключ - имя переменной, значение - список ее значений
    """
    if not data:
        raise ValueError("No data provided")

    # Проверяем, что все файлы имеют одинаковые переменные
    variable_names = None
    all_values = {}

    for idx, item in enumerate(data):
        if 'shapValues' not in item:
            print(f"Warning: Item {idx} has no 'shapValues' field, skipping")
            continue

        shap_values = item['shapValues']

        # Определяем список переменных из первого валидного файла
        if variable_names is None:
            variable_names = list(shap_values.keys())
            all_values = {name: [] for name in variable_names}

        # Проверяем, что переменные совпадают
        if set(shap_values.keys()) != set(variable_names):
            print(f"Warning: Item {idx} has different variables, skipping")
            continue

        # Добавляем значения в соответствующие списки
        for name in variable_names:
            all_values[name].append(shap_values[name])

    # Проверяем, что все переменные имеют данные
    for name, values in all_values.items():
        if not values:
            print(f"Warning: No values for variable '{name}'")

    return all_values


def extract_target_dates(data: List[Dict]) -> List[str]:
    """
    Извлекает даты из загруженных данных для использования в подписях.

    Args:
        data: Список словарей с данными из JSON файлов

    Returns:
        Список дат для каждого файла
    """
    dates = []
    for item in data:
        if 'target_date' in item:
            dates.append(item['target_date'])
        else:
            dates.append("Unknown")
    return dates


def plot_variable_distributions_normalized(
        variable_values: Dict[str, List[float]],
        output_path: Path,
        dates: List[str] = None,
        figsize: Tuple[int, int] = (15, 10),
        center_zero: bool = True,
        variablesMap: dict[str, str] = None,
        totalObjects: int = None,
        additional_desc: str = None,
        quantile_range: float = 0.99  # Диапазон квантилей (0-1)
):
    """
    Версия с нормализованными гистограммами (плотности) для лучшего сравнения форм распределений.

    Args:
        quantile_range: Диапазон квантилей для определения границ оси X (0.95 = 2.5% - 97.5%)
    """
    if not variable_values:
        raise ValueError("No variable values to plot")

    # Фильтруем None значения для каждой переменной
    filtered_variable_values = {}
    for var_name, values in variable_values.items():
        if values is not None:
            # Фильтруем None внутри списка
            filtered_values = [v for v in values if v is not None]
            if filtered_values:  # Оставляем только непустые списки
                filtered_variable_values[var_name] = filtered_values

    if not filtered_variable_values:
        raise ValueError("No valid (non-None) values found in variable_values")

    n_vars = len(filtered_variable_values)
    n_cols = 3
    n_rows = (n_vars + n_cols - 1) // n_cols

    fig, axes = plt.subplots(n_rows, n_cols, figsize=figsize)
    axes = axes.flatten()

    # Сбор всех значений для определения общего диапазона
    all_values = []
    for values in filtered_variable_values.values():
        all_values.extend(values)
    all_values = np.array(all_values)

    if len(all_values) == 0:
        raise ValueError("No values found in filtered_variable_values")

    # Вычисляем диапазон с использованием квантилей
    if center_zero:
        # Для симметричного диапазона относительно нуля используем абсолютные значения
        abs_values = np.abs(all_values)
        # Вычисляем квантиль для верхней границы
        upper_quantile = np.quantile(abs_values, quantile_range)
        # Добавляем небольшой запас (10%)
        x_max = upper_quantile * 1.1 if upper_quantile > 0 else 1.0
        x_min = -x_max
    else:
        # Для несимметричного диапазона используем квантили с обеих сторон
        lower_quantile = (1 - quantile_range) / 2  # например, 0.025 для quantile_range=0.95
        upper_quantile = 1 - lower_quantile  # например, 0.975 для quantile_range=0.95

        x_min = np.quantile(all_values, lower_quantile)
        x_max = np.quantile(all_values, upper_quantile)

        # Добавляем небольшой запас (10%)
        if x_min != x_max:
            x_range = x_max - x_min
            x_min = x_min - x_range * 0.1
            x_max = x_max + x_range * 0.1
        else:
            x_min = x_min - 1.0
            x_max = x_max + 1.0

    colors = plt.cm.Set3(np.linspace(0, 1, n_vars))

    for idx, (var_name, values) in enumerate(filtered_variable_values.items()):
        if idx >= len(axes):
            break

        ax = axes[idx]
        values = np.array(values)

        if len(values) == 0:
            ax.text(0.5, 0.5, 'No data', transform=ax.transAxes,
                    ha='center', va='center')
            continue

        # ---- ИЗМЕНЕНИЕ ЗДЕСЬ ----
        # Вычисляем количество бинов на основе диапазона
        # Чтобы получить шаг примерно 1, либо фиксированное количество бинов
        data_range = x_max - x_min

        # Вариант 1: Шаг = 1 (если диапазон позволяет)
        bin_width = 1.0
        n_bins = max(1, int(np.ceil(data_range / bin_width)))
        # Ограничиваем количество бинов, чтобы не было слишком много
        n_bins = min(n_bins, 50)  # Максимум 50 бинов

        # Вариант 2: Если хотите всегда 20 бинов (закомментируйте вариант 1 и раскомментируйте этот)
        # n_bins = 20

        # Создаем явные границы бинов с шагом bin_width
        bins = np.arange(x_min, x_max + bin_width, bin_width)
        # Если бинов получилось слишком мало, используем 20 бинов
        if len(bins) < 5:
            n_bins = 20
            bins = n_bins
        # ---- КОНЕЦ ИЗМЕНЕНИЯ ----

        # Нормализованная гистограмма (плотность) с использованием вычисленного диапазона
        ax.hist(values, bins=bins, alpha=0.7, color=colors[idx],
                edgecolor='black', linewidth=0.5,
                density=True)

        # Вычисляем и отображаем ядерную оценку плотности (KDE)
        try:
            from scipy import stats
            if len(values) > 1:
                kde = stats.gaussian_kde(values)
                x_range = np.linspace(x_min, x_max, 200)
                ax.plot(x_range, kde(x_range), 'k-', linewidth=1.5, alpha=0.7,
                        label='KDE')
        except ImportError:
            pass  # Если scipy не установлен, просто игнорируем

        # Вертикальная линия на нуле
        if center_zero:
            ax.axvline(0, color='black', linestyle='-', linewidth=1, alpha=0.5)

        # Статистика
        mean_val = np.mean(values)
        std_val = np.std(values)

        # Добавляем линии среднего и стандартного отклонения
        ax.axvline(mean_val, color='red', linestyle='--', linewidth=2,
                   label=f'μ = {mean_val:.3f}, σ = {std_val:.3f}')

        # Опционально: добавить линии для ±σ
        ax.axvline(mean_val - std_val, color='red', linestyle=':', linewidth=1, alpha=0.5)
        ax.axvline(mean_val + std_val, color='red', linestyle=':', linewidth=1, alpha=0.5,
                   label=f'±σ')

        # Получаем имя переменной из маппинга
        display_name = var_name
        if variablesMap is not None and var_name in variablesMap:
            display_name = variablesMap[var_name]

        # Подпись с датами
        if dates:
            # Берем даты только для этого набора значений
            var_dates = dates[:len(values)]
            unique_dates = sorted(set(var_dates))
            if len(unique_dates) <= 3:
                date_str = ", ".join(unique_dates)
            else:
                date_str = f"{unique_dates[0]} ... {unique_dates[-1]}"
            title_text = f"{display_name}"
        else:
            title_text = display_name
            date_str = ""

        ax.set_title(title_text, fontsize=10)
        ax.set_xlabel('SHAP Value', fontsize=8)
        ax.set_ylabel('Density', fontsize=8)
        ax.set_xlim(x_min, x_max)
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=7, loc='upper right')

        # Информация о количестве точек (учитываем только не-None значения)
        ax.text(0.95, 0.95, f'n={len(values)}', transform=ax.transAxes,
                fontsize=8, verticalalignment='top', horizontalalignment='right',
                bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))

    # Скрываем неиспользуемые подграфики
    for idx in range(n_vars, len(axes)):
        axes[idx].axis('off')

    if totalObjects is not None:
        desc = f'число смоделированных индивидов {totalObjects}'
    else:
        desc = 'число опрошенных индивидов не указано'

    # Формируем заголовок с учетом date_str
    if date_str:
        fig.suptitle(f'Плотности распределений SHAP {additional_desc} значений для опроса {date_str} ({desc})',
                     fontsize=14, y=1.02)
    else:
        fig.suptitle(f'Плотности распределений SHAP {additional_desc} значений ({desc})', fontsize=14, y=1.02)

    plt.tight_layout()

    # Сохраняем
    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    print(f"Plot saved to: {output_path}")

    return fig


def plot_variable_distributions_boxplot(
        variable_values: Dict[str, List[float]],
        output_path: Path,
        dates: List[str] = None,
        figsize: Tuple[int, int] = (15, 8),
        center_zero: bool = True
):
    """
    Альтернативная версия с boxplot для лучшего сравнения распределений.
    """
    n_vars = len(variable_values)

    fig, ax = plt.subplots(figsize=figsize)

    # Подготавливаем данные
    data_to_plot = []
    labels = []
    colors = []

    # Вычисляем общий диапазон для выравнивания
    all_values = []
    for values in variable_values.values():
        all_values.extend(values)
    all_values = np.array(all_values)

    if center_zero:
        max_abs = np.max(np.abs(all_values))
        y_min = -max_abs * 1.2
        y_max = max_abs * 1.2
    else:
        y_min = np.min(all_values) * 1.1
        y_max = np.max(all_values) * 1.1

    # Сортируем по имени переменной для стабильности
    sorted_vars = sorted(variable_values.items())

    for idx, (var_name, values) in enumerate(sorted_vars):
        data_to_plot.append(values)

        # Создаем подпись с датами
        if dates:
            unique_dates = sorted(set(dates[:len(values)]))
            if len(unique_dates) <= 2:
                date_str = ", ".join(unique_dates)
            else:
                date_str = f"{unique_dates[0]} ... {unique_dates[-1]}"
            labels.append(f"{var_name}\n{date_str}")
        else:
            labels.append(var_name)

        colors.append(plt.cm.Set3(idx / n_vars))

    # Строим boxplot
    bp = ax.boxplot(data_to_plot, labels=labels, patch_artist=True,
                    showmeans=True, meanline=True)

    # Закрашиваем боксы
    for patch, color in zip(bp['boxes'], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.7)

    # Добавляем линию на нуле
    if center_zero:
        ax.axhline(0, color='black', linestyle='-', linewidth=1.5, alpha=0.5)

    # Устанавливаем единый диапазон
    ax.set_ylim(y_min, y_max)

    ax.set_ylabel('SHAP Value', fontsize=12)
    ax.set_xlabel('Variable', fontsize=12)
    ax.grid(True, alpha=0.3, axis='y')

    # Добавляем легенду
    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor='gray', alpha=0.7, label='Box (25-75%)'),
        Patch(facecolor='gray', alpha=0.7, edgecolor='black',
              linestyle='-', label='Median'),
        Patch(facecolor='gray', alpha=0.7, edgecolor='black',
              linestyle='--', label='Mean (line)')
    ]
    ax.legend(handles=legend_elements, loc='upper right')

    if center_zero:
        ax.set_title(f'Распределения SHAP значений (центрировано по 0, диапазон: [{y_min:.2f}, {y_max:.2f}])',
                     fontsize=14)
    else:
        ax.set_title(f'Распределения SHAP значений (диапазон: [{y_min:.2f}, {y_max:.2f}])',
                     fontsize=14)

    plt.tight_layout()

    # Сохраняем
    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    print(f"Plot saved to: {output_path}")

    return fig


def plot_variable_distributions_aligned(
        variable_values: Dict[str, List[float]],
        output_path: Path,
        dates: List[str] = None,
        show_stats: bool = True,
        figsize: Tuple[int, int] = (15, 10),
        x_range: Tuple[float, float] = None,  # Если None, вычисляется автоматически
        center_zero: bool = True
):
    """
    Создает графики распределений с выравниванием по нулю и единым масштабом.

    Args:
        variable_values: Словарь с значениями переменных
        output_path: Путь для сохранения графика
        dates: Список дат для подписей
        show_stats: Показывать ли статистику
        figsize: Размер фигуры
        x_range: Фиксированный диапазон по X (мин, макс). Если None - вычисляется автоматически
        center_zero: Центрировать ли графики по нулю
    """
    if not variable_values:
        raise ValueError("No variable values to plot")

    n_vars = len(variable_values)
    n_cols = 3
    n_rows = (n_vars + n_cols - 1) // n_cols

    fig, axes = plt.subplots(n_rows, n_cols, figsize=figsize)
    axes = axes.flatten()

    # Вычисляем общий диапазон для всех графиков
    all_values = []
    for values in variable_values.values():
        all_values.extend(values)
    all_values = np.array(all_values)

    if x_range is not None:
        x_min, x_max = x_range
    else:
        if center_zero:
            # Симметричный диапазон относительно нуля
            max_abs = np.max(np.abs(all_values))
            x_min = -max_abs * 1.2  # 20% запас
            x_max = max_abs * 1.2
        else:
            x_min = np.min(all_values) * 1.1
            x_max = np.max(all_values) * 1.1

    # Вычисляем общее количество бинов для единого масштаба
    n_bins = 20

    colors = plt.cm.Set3(np.linspace(0, 1, n_vars))

    for idx, (var_name, values) in enumerate(variable_values.items()):
        if idx >= len(axes):
            break

        ax = axes[idx]
        values = np.array(values)

        # Строим гистограмму с единым диапазоном
        ax.hist(values, bins=n_bins, alpha=0.7, color=colors[idx],
                edgecolor='black', linewidth=0.5, range=(x_min, x_max))

        # Добавляем вертикальную линию на нуле
        if center_zero:
            ax.axvline(0, color='black', linestyle='-', linewidth=1, alpha=0.5)

        # Статистика
        mean_val = np.mean(values)
        std_val = np.std(values)

        # Точка для среднего
        ax.scatter(mean_val, 0, color='red', s=50, zorder=5,
                   marker='v', label=f'μ = {mean_val:.3f}')

        # Линии для стандартного отклонения
        ax.axvline(mean_val - std_val, color='orange', linestyle=':', linewidth=1.5,
                   alpha=0.7)
        ax.axvline(mean_val + std_val, color='orange', linestyle=':', linewidth=1.5,
                   alpha=0.7, label=f'μ±σ = {mean_val:.3f}±{std_val:.3f}')

        # Закрашиваем область стандартного отклонения
        if show_stats:
            y_min, y_max = ax.get_ylim()
            ax.axvspan(mean_val - std_val, mean_val + std_val,
                       alpha=0.15, color='orange', label='±σ range')

        # Подпись с датами
        if dates:
            unique_dates = sorted(set(dates[:len(values)]))
            if len(unique_dates) <= 3:
                date_str = ", ".join(unique_dates)
            else:
                date_str = f"{unique_dates[0]} ... {unique_dates[-1]}"
            title_text = f"{var_name}\n{date_str}"
        else:
            title_text = var_name

        ax.set_title(title_text, fontsize=10)
        ax.set_xlabel('SHAP Value', fontsize=8)
        ax.set_ylabel('Frequency', fontsize=8)
        ax.grid(True, alpha=0.3)

        # Устанавливаем единый диапазон
        ax.set_xlim(x_min, x_max)

        # Легенда
        if show_stats:
            ax.legend(fontsize=7, loc='upper right')

        # Количество точек
        ax.text(0.95, 0.95, f'n={len(values)}', transform=ax.transAxes,
                fontsize=8, verticalalignment='top', horizontalalignment='right',
                bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))

    # Скрываем неиспользуемые подграфики
    for idx in range(n_vars, len(axes)):
        axes[idx].axis('off')

    # Добавляем общий заголовок с информацией о диапазоне
    if center_zero:
        fig.suptitle(f'Распределения SHAP значений (диапазон: [{x_min:.2f}, {x_max:.2f}], центрировано по 0)',
                     fontsize=14, y=1.02)
    else:
        fig.suptitle(f'Распределения SHAP значений (диапазон: [{x_min:.2f}, {x_max:.2f}])',
                     fontsize=14, y=1.02)

    plt.tight_layout()

    # Сохраняем
    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    print(f"Plot saved to: {output_path}")

    return fig

def plot_variable_distributions(
        variable_values: Dict[str, List[float]],
        output_path: Path,
        dates: List[str] = None,
        show_stats: bool = True,
        figsize: Tuple[int, int] = (15, 10)
):
    """
    Создает и сохраняет графики распределений для всех переменных.

    Args:
        variable_values: Словарь с значениями переменных
        output_path: Путь для сохранения графика
        dates: Список дат для подписей (опционально)
        show_stats: Показывать ли статистику на графиках
        figsize: Размер фигуры
    """
    if not variable_values:
        raise ValueError("No variable values to plot")

    n_vars = len(variable_values)
    n_cols = 3
    n_rows = (n_vars + n_cols - 1) // n_cols

    fig, axes = plt.subplots(n_rows, n_cols, figsize=figsize)
    axes = axes.flatten()

    # Цвета для графиков
    colors = plt.cm.Set3(np.linspace(0, 1, n_vars))

    for idx, (var_name, values) in enumerate(variable_values.items()):
        if idx >= len(axes):
            break

        ax = axes[idx]
        values = np.array(values)

        # Строим гистограмму
        ax.hist(values, bins=20, alpha=0.7, color=colors[idx],
                edgecolor='black', linewidth=0.5)

        # Добавляем вертикальные линии для статистики
        mean_val = np.mean(values)
        std_val = np.std(values)

        ax.axvline(mean_val, color='red', linestyle='--', linewidth=2,
                   label=f'μ = {mean_val:.3f}')
        ax.axvline(mean_val - std_val, color='orange', linestyle=':', linewidth=1.5,
                   label=f'μ±σ = {mean_val:.3f}±{std_val:.3f}')
        ax.axvline(mean_val + std_val, color='orange', linestyle=':', linewidth=1.5)

        # Создаем подпись
        if dates:
            # Берем уникальные даты для этой переменной
            # (они должны быть одинаковыми для всех переменных)
            unique_dates = list(set(dates[:len(values)]))
            date_str = ", ".join(unique_dates[:3])
            if len(unique_dates) > 3:
                date_str += f" и {len(unique_dates) - 3} др."
            title = f"{var_name}\n{date_str}"
        else:
            title = var_name

        ax.set_title(title, fontsize=10)
        ax.set_xlabel('SHAP Value', fontsize=8)
        ax.set_ylabel('Frequency', fontsize=8)
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=7, loc='upper right')

        # Добавляем информацию о количестве точек
        ax.text(0.95, 0.95, f'n={len(values)}', transform=ax.transAxes,
                fontsize=8, verticalalignment='top', horizontalalignment='right',
                bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))

    # Скрываем неиспользуемые подграфики
    for idx in range(n_vars, len(axes)):
        axes[idx].axis('off')

    plt.tight_layout()

    # Сохраняем
    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    print(f"Plot saved to: {output_path}")

    # Показываем статистику в консоли
    print("\nСтатистика по переменным:")
    print("-" * 60)
    for var_name, values in variable_values.items():
        values = np.array(values)
        print(f"{var_name:30s}: n={len(values):4d}, "
              f"mean={np.mean(values):8.4f}, "
              f"std={np.std(values):8.4f}, "
              f"min={np.min(values):8.4f}, "
              f"max={np.max(values):8.4f}")

    return fig