import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

from SurveyLogic.SurveyResults.InflationSurveyRespond import InflationSurveyRespond
from experimentsConfiguration import ExperimentsConfiguration


def load_from_official_statistics_1m(fileName):
    directEstimations = pd.read_excel(fileName, index_col=0)
    directEstimations = directEstimations.T
    directEstimations.index = pd.to_datetime(directEstimations.index)

    return directEstimations

def load_respond_from_json(file_path: str) -> InflationSurveyRespond:
    """Загружает объект InflationSurveyRespond из JSON-файла"""
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # Создаем объект, распаковывая словарь
    return InflationSurveyRespond(**data)

def getCategory(answeredCategory: str, type: str):
    if answeredCategory == 'вырастут очень сильно' or answeredCategory == 'high_growth' or answeredCategory == 'вырастут сильно' or answeredCategory=='выросли сильно':
        return 'вырастут очень сильно' if type == 'expected' else 'выросли очень сильно'

    if answeredCategory == 'вырастут умеренно' or answeredCategory == 'medium_growth':
        return 'вырастут умеренно' if type == 'expected' else 'выросли умеренно'

    if answeredCategory == 'снизился незначительно' or answeredCategory == 'снизилась незначительно':
        return 'снизились незначительно'

    if answeredCategory == 'вырастут незначительно' or answeredCategory == 'little_growth':
        return 'вырастут незначительно' if type == 'expected' else 'выросли незначительно'

    if answeredCategory == 'не изменятся' or answeredCategory == 'no_change':
        return 'не изменятся' if type == 'expected' else 'не изменились'

    if answeredCategory == 'снизились' or answeredCategory == 'снизятся':
        return 'снизятся' if type == 'expected' else 'снизились'

    if answeredCategory == 'no_answer':
        return 'затрудняюсь ответить'

    if answeredCategory == 'выросли умеренно' or answeredCategory == 'выросли очень сильно' or answeredCategory == 'выросли незначительно' or answeredCategory == 'не изменились' or answeredCategory == 'затрудняюсь ответить' or answeredCategory == 'снизятся':
        return answeredCategory

    if answeredCategory == 'снизились' or answeredCategory == 'снизлись' or answeredCategory == 'снизился' or answeredCategory == 'снизилась':
        return 'снизились'

    if answeredCategory == 'снизился незначительно':
        return 'снизились незначительно'

    if answeredCategory is None:
        return None

    raise ValueError(f'Unknown answer category: {answeredCategory}')

def load_pdtable(folder: Path):
    files = os.listdir(folder)
    files = [f for f in files if os.path.isfile(os.path.join(folder, f))]
    files = [f for f in files if f.endswith('.json')]

    rows = []
    for file in files:
        respond = load_respond_from_json(f'{folder}/{file}')

        expectedCategory = getCategory(respond.expected_inflation_1m_category, 'expected')
        observableCategory = getCategory(respond.observable_inflation_last_1m_category, 'observable')

        if expectedCategory is None or observableCategory is None:
            continue

        if respond.expected_inflation_12m_pct is None or respond.observable_inflation_last_12m_pct is None:
            continue

        rows.append({
            'date': datetime.strptime(respond.target_date, "%d.%m.%Y"),
            'expected_12m': float(respond.expected_inflation_12m_pct),
            'observable_12m': float(respond.observable_inflation_last_12m_pct),
            'expected_1m': expectedCategory,
            'observable_1m': observableCategory
        })

    return pd.DataFrame(rows)

def load_pdtable_with_repeats(folder: str):
    dates = pd.date_range(start='2016-01-01', end='2026-01-01', freq='QS', inclusive='both').tolist()
    files = os.listdir(folder)
    files = [f for f in files if os.path.isfile(os.path.join(folder, f))]

    rows = []
    for file in files:
        respond = load_respond_from_json(f'{folder}/{file}')

        expectedCategory = getCategory(respond.expected_inflation_1m_category, 'expected')
        observableCategory = getCategory(respond.observable_inflation_last_1m_category, 'observable')

        if expectedCategory is None or observableCategory is None:
            continue

        if respond.expected_inflation_12m_pct is None or respond.observable_inflation_last_12m_pct is None:
            continue

        for d in dates:
            rows.append({
                'date': d,
                'expected_12m': float(respond.expected_inflation_12m_pct),
                'observable_12m': float(respond.observable_inflation_last_12m_pct),
                'expected_1m': expectedCategory,
                'observable_1m': observableCategory
            })

    return pd.DataFrame(rows)

def transform_date(date_str: str) -> datetime:
    # Парсим строку в формате MM.YYYY
    month, year = map(int, date_str.split('.'))
    # Создаем дату 01 числа следующего месяца
    if month == 12:
        # Если декабрь, то переходим на январь следующего года
        new_date = datetime(year + 1, 1, 1)
    else:
        new_date = datetime(year, month + 1, 1)
    return new_date

def transform_value(value: str) -> float:
    # Парсим строку в формате MM.YYYY
    a, b = map(int, value.split(','))

    return a + b / 10000

def load_official_inflation(path: Path):
    df = pd.read_excel(path, header=0, dtype={'Дата': str})

    # Применяем преобразование к столбцу 'Дата'
    df['Дата'] = df['Дата'].apply(transform_date)

    # Устанавливаем индекс по датам
    df = df.set_index('Дата')
    df = df.rename(columns={'Инфляция, % г/г': 'Значение'})

    # Сортируем по индексу (по датам) для удобства
    df = df.sort_index()

    return df

def load_usdrub(path: Path):
    df = pd.read_excel(path, header=0, decimal=',')

    # Устанавливаем индекс по датам
    df = df.set_index('data')

    # Сортируем по индексу (по датам) для удобства
    df = df.sort_index()

    return df

def parse_dates_from_file(file_path: Path) -> dict:
    """
    Парсит файл с датами и возвращает словарь.

    Формат файла: "Месяц Год — ДД.ММ.ГГГГ"
    Ключ: 01.месяц.год (первое число указанного месяца)
    Значение: распознанная дата + 1 день (datetime)

    Args:
        file_path: путь к файлу

    Returns:
        dict: {ключ_дата: значение_datetime}

    Example:
        "Май 2021 — 01.06.2021" -> {datetime(2021, 5, 1): datetime(2021, 6, 2)}
    """
    # Словарь для перевода названий месяцев на русском в номер месяца
    months_ru = {
        'январь': 1, 'января': 1,
        'февраль': 2, 'февраля': 2,
        'март': 3, 'марта': 3,
        'апрель': 4, 'апреля': 4,
        'май': 5, 'мая': 5,
        'июнь': 6, 'июня': 6,
        'июль': 7, 'июля': 7,
        'август': 8, 'августа': 8,
        'сентябрь': 9, 'сентября': 9,
        'октябрь': 10, 'октября': 10,
        'ноябрь': 11, 'ноября': 11,
        'декабрь': 12, 'декабря': 12
    }

    result = {}

    # Читаем файл
    with open(file_path, 'r', encoding='utf-8') as file:
        lines = file.readlines()

    for line in lines:
        line = line.strip()
        if not line:  # Пропускаем пустые строки
            continue

        # Разделяем на префикс (месяц год) и дату
        parts = line.split('—')
        if len(parts) != 2:
            print(f"⚠️ Неверный формат строки: {line}")
            continue

        prefix = parts[0].strip()  # "Май 2021"
        date_part = parts[1].strip()  # "01.06.2021"

        # Извлекаем месяц и год из префикса
        prefix_parts = prefix.split()
        if len(prefix_parts) != 2:
            print(f"⚠️ Неверный формат префикса: {prefix}")
            continue

        month_name = prefix_parts[0].lower()  # "май"
        year = int(prefix_parts[1])  # 2021

        # Получаем номер месяца
        if month_name not in months_ru:
            print(f"⚠️ Неизвестный месяц: <{month_name}>")
            continue

        month = months_ru[month_name]

        # Создаем ключ: 01.месяц.год
        key_date = pd.Timestamp(year=year, month=month, day=1)

        # Извлекаем дату из правой части
        date_pattern = r'\d{2}\.\d{2}\.\d{4}'
        match = re.search(date_pattern, date_part)

        if not match:
            print(f"⚠️ Не найдена дата в: {date_part}")
            continue

        date_str = match.group()
        parsed_date = datetime.strptime(date_str, '%d.%m.%Y')

        # Добавляем в словарь
        result[key_date] = parsed_date

    return result

def load_official_analytics_expectation(path: Path, datesMapPath: Path):
    df = pd.read_excel(path, sheet_name='1', skiprows=range(5), header=None)

    data_col_idx = 4
    date_row_idx = 0
    value_row_idx = 11

    datesMap = parse_dates_from_file(datesMapPath)

    resultDf = pd.DataFrame(columns=['Дата', 'Значение'])

    for col in range(data_col_idx, len(df.columns)):
        date_str = df.iloc[date_row_idx, col]
        value = df.iloc[value_row_idx, col]

        if value=='-':
            value_row_idx += 1
            value = df.iloc[value_row_idx, col]

        new_date = pd.to_datetime(date_str, format='%d.%m.%Y')

        correctDate = datesMap[new_date]
        correctDate = correctDate + timedelta(days=1)#на следующий день мы знаем эту инфо

        new_row = pd.DataFrame({'Дата': [correctDate], 'Значение': [value]})
        resultDf = pd.concat([resultDf, new_row], ignore_index=True)

    resultDf = resultDf.set_index('Дата')
    resultDf = resultDf.sort_index()

    return resultDf

def load_from_official_statistics(fileName, offsetDays=0):
    """
    Загружает данные из файла официальной статистики

    Args:
        fileName (str): путь к файлу Excel
        offsetDays (int): количество дней для сдвига дат (по умолчанию 0)

    Returns:
        pd.DataFrame: DataFrame с датами в индексе, сдвинутыми на offsetDays
    """
    directEstimations = pd.read_excel(fileName, index_col=0)
    directEstimations.rename(
        index={
            'наблюдаемая инфляция (в %)': 'observable_inflation',
            'ожидаемая инфляция (в %)': 'expected_inflation'
        },
        inplace=True
    )
    directEstimations = directEstimations.T
    directEstimations.index = pd.to_datetime(directEstimations.index)

    # Добавляем сдвиг в днях, если указан
    if offsetDays != 0:
        directEstimations.index = directEstimations.index + pd.Timedelta(days=offsetDays)
        print(f"📅 Даты сдвинуты на {offsetDays} дней")

    # Удаляем только первую строку, если в ней есть NaN
    if not directEstimations.empty:
        first_row = directEstimations.iloc[0]
        if first_row.isna().any():
            directEstimations = directEstimations.iloc[1:]
            print(f"🗑️ Удалена первая строка с NaN (дата: {first_row.name})")

    print(f"✅ Загружено {len(directEstimations)} записей")

    return directEstimations


def aggregate_survey(surveys):
    """
    Агрегирует данные по датам

    Returns:
        DataFrame с индексом из дат и колонками 'obs_mean', 'obs_std', 'obs_count',
        'exp_mean', 'exp_std', 'exp_count'
    """
    surveys['date'] = pd.to_datetime(surveys['date'])

    quarterly_agg_df = surveys.groupby('date').agg({
        'observable_12m': ['mean', 'std', 'count'],
        'expected_12m': ['mean', 'std', 'count']
    })

    # Переименовываем колонки
    quarterly_agg_df.columns = ['obs_mean', 'obs_std', 'obs_count',
                                'exp_mean', 'exp_std', 'exp_count']

    print(quarterly_agg_df.head())

    return quarterly_agg_df

def aggregate_survey1(surveys):
    quarterly_agg_df = surveys.groupby('date').agg({
        'observable_12m': ['mean', 'std', 'count'],
        'expected_12m': ['mean', 'std', 'count']
    }).reset_index()

    # Переименовываем колонки
    quarterly_agg_df.columns = ['date', 'obs_mean', 'obs_std', 'obs_count',
                                'exp_mean', 'exp_std', 'exp_count']

    return quarterly_agg_df


def aggregate_to_percentages(df, date_col='date', response_col='response', categories=None):
    """
    Агрегирует неагрегированные данные в формат процентов

    Args:
        df: DataFrame с колонками date и response
        date_col: название колонки с датами
        response_col: название колонки с ответами
        categories: список категорий (если None, определяется автоматически)

    Returns:
        DataFrame с датами в индексе и категориями в колонках
    """
    # Если категории не указаны, определяем автоматически
    if categories is None:
        categories = sorted(df[response_col].unique())

    # Группируем по дате и ответу
    grouped = df.groupby([date_col, response_col]).size().reset_index(name='count')

    # Получаем общее количество для каждой даты
    total_per_date = grouped.groupby(date_col)['count'].sum().reset_index(name='total')

    # Объединяем
    grouped = grouped.merge(total_per_date, on=date_col)

    # Вычисляем проценты
    grouped['pct'] = (grouped['count'] / grouped['total']) * 100

    # Создаем сводную таблицу
    pivot = grouped.pivot(index=date_col, columns=response_col, values='pct').fillna(0)

    # Убеждаемся, что все категории присутствуют
    for cat in categories:
        if cat not in pivot.columns:
            pivot[cat] = 0

    # Приводим к целым числам
    pivot = pivot.round().astype(int)

    # Корректируем сумму до 100
    for idx in pivot.index:
        diff = 100 - pivot.loc[idx].sum()
        if diff != 0:
            # Добавляем разницу к первой категории
            pivot.loc[idx, pivot.columns[0]] += diff

    return pivot


from scipy.stats import chi2_contingency, wasserstein_distance
import numpy as np


def safe_chi2_contingency(obs, correction=True):
    """
    Безопасная версия chi2_contingency с обработкой нулевых ожидаемых частот

    Args:
        obs: таблица сопряженности (2 x n_categories)
        correction: использовать ли поправку Йейтса

    Returns:
        chi2_stat, p_value, dof, expected
    """
    # Проверяем, есть ли категории с нулями в обоих распределениях
    obs = np.array(obs)

    # Находим категории, где сумма по строке равна 0
    zero_categories = np.where(obs.sum(axis=0) == 0)[0]

    if len(zero_categories) > 0:
        print(f"⚠️ Найдены категории с нулевыми значениями: {zero_categories}")
        # Удаляем нулевые категории
        obs_filtered = np.delete(obs, zero_categories, axis=1)

        if obs_filtered.shape[1] < 2:
            print("⚠️ Слишком мало категорий для теста")
            return np.nan, np.nan, 0, None

        # Пробуем снова с отфильтрованными данными
        try:
            return chi2_contingency(obs_filtered, correction=correction)
        except ValueError:
            # Если все еще ошибка, используем альтернативный подход
            print("⚠️ Использую альтернативный подход...")
            return alternative_chi2_test(obs)
    else:
        try:
            return chi2_contingency(obs, correction=correction)
        except ValueError as e:
            if "zero element" in str(e):
                print("⚠️ Ошибка с нулевыми ожидаемыми частотами, использую альтернативный подход...")
                return alternative_chi2_test(obs)
            else:
                raise


def alternative_chi2_test(obs):
    """
    Альтернативный тест для таблиц с нулевыми значениями
    Использует G-тест (отношение правдоподобия) вместо хи-квадрат
    """
    obs = np.array(obs)

    # Удаляем категории с нулевыми суммами
    valid_cols = obs.sum(axis=0) > 0
    obs = obs[:, valid_cols]

    if obs.shape[1] < 2:
        return np.nan, np.nan, 0, None

    # Рассчитываем ожидаемые частоты
    row_totals = obs.sum(axis=1, keepdims=True)
    col_totals = obs.sum(axis=0, keepdims=True)
    total = obs.sum()

    expected = (row_totals * col_totals) / total

    # Заменяем нулевые ожидаемые частоты на очень маленькое число
    expected = np.maximum(expected, 1e-10)

    # G-тест (отношение правдоподобия)
    # G = 2 * sum(obs * log(obs / expected))
    with np.errstate(divide='ignore', invalid='ignore'):
        ratio = obs / expected
        ratio = np.where(ratio == 0, 1e-10, ratio)  # Заменяем нули
        g_stat = 2 * np.sum(obs * np.log(ratio))

    # p-value из хи-квадрат распределения
    dof = (obs.shape[0] - 1) * (obs.shape[1] - 1)
    from scipy.stats import chi2
    p_value = 1 - chi2.cdf(g_stat, dof)

    return g_stat, p_value, dof, expected


def compare_distributions_robust(monthly, quarterly, categories):
    """
    Сравнивает два распределения с робастной обработкой нулей
    """
    # Проверяем, есть ли категории с нулями
    monthly = np.array(monthly)
    quarterly = np.array(quarterly)

    # Находим категории с нулевыми значениями
    zero_mask = (monthly == 0) | (quarterly == 0)

    if zero_mask.any():
        print(f"⚠️ Найдены нулевые значения в категориях:")
        for i, cat in enumerate(categories):
            if monthly[i] == 0:
                print(f"  - {cat}: monthly = 0")
            if quarterly[i] == 0:
                print(f"  - {cat}: quarterly = 0")

        # Вариант 1: Добавляем небольшое значение (0.5) к нулям
        monthly_adj = monthly.copy()
        quarterly_adj = quarterly.copy()

        for i in range(len(categories)):
            if monthly_adj[i] == 0:
                monthly_adj[i] = 0.5
            if quarterly_adj[i] == 0:
                quarterly_adj[i] = 0.5

        # Нормализуем сумму до 100
        monthly_adj = monthly_adj / monthly_adj.sum() * 100
        quarterly_adj = quarterly_adj / quarterly_adj.sum() * 100

        print("✅ Применена коррекция нулевых значений")
        return compare_distributions_core(monthly_adj, quarterly_adj, categories)
    else:
        return compare_distributions_core(monthly, quarterly, categories)


def compare_distributions_core(monthly, quarterly, categories):
    """
    Основная функция сравнения распределений
    """
    monthly = np.array(monthly)
    quarterly = np.array(quarterly)

    # Используем безопасную версию chi2_contingency
    chi2_stat, p_value, dof, expected = safe_chi2_contingency([monthly, quarterly])

    wasserstein_dist = wasserstein_distance(monthly, quarterly)
    mean_abs_diff = np.mean(np.abs(monthly - quarterly))
    max_diff = np.max(np.abs(monthly - quarterly))

    return {
        'chi2_stat': chi2_stat,
        'chi2_p_value': p_value,
        'wasserstein_dist': wasserstein_dist,
        'mean_abs_diff': mean_abs_diff,
        'max_diff': max_diff,
        'is_significant': p_value < 0.05 if not np.isnan(p_value) else False,
        'has_zero_categories': (monthly == 0).any() or (quarterly == 0).any()
    }


def generate_title_from_config(
        config: ExperimentsConfiguration,
        variable: Optional[str] = None,  # 'observable' или 'expected'
        include_date_range: bool = False,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        language: str = 'ru',  # 'ru' или 'en'
        use_intersection: bool = False,
        additional_info: Optional[str] = None,
        max_length: int = 100
) -> str:
    """
    Генерирует говорящий заголовок для графика на основе конфигурации

    Args:
        config: объект конфигурации
        variable: тип переменной ('observable' или 'expected')
        include_date_range: включать ли диапазон дат в заголовок
        start_date: начальная дата
        end_date: конечная дата
        language: язык заголовка ('ru' или 'en')
        use_intersection: используется ли пересечение диапазонов
        additional_info: дополнительная информация для заголовка
        max_length: максимальная длина заголовка

    Returns:
        str: сгенерированный заголовок
    """
    # Получаем активные фичи
    active_features = config.get_active_features()

    # Определяем названия на нужном языке
    if language == 'ru':
        feature_names = config.get_feature_names_ru()
        variable_names = {
            'observable': 'Наблюдаемая инфляция',
            'expected': 'Ожидаемая инфляция'
        }
        intersection_text = ' (пересечение диапазонов)' if use_intersection else ''
        of_text = 'с использованием'
        and_text = ' и '
        period_text = 'Период'
        features_text = 'Фичи'

        # Базовая конструкция для списка фич
        if active_features:
            if len(active_features) == 1:
                features_str = feature_names[0]
            elif len(active_features) == 2:
                features_str = f"{feature_names[0]}{and_text}{feature_names[1]}"
            else:
                features_str = ', '.join(feature_names[:-1]) + f"{and_text}{feature_names[-1]}"
        else:
            features_str = 'Базовый набор'

        # Формируем заголовок
        if variable:
            var_name = variable_names.get(variable, variable)
            title = f"{var_name}: {features_str}"
        else:
            title = f"{features_str}"

        # Добавляем информацию о пересечении
        if use_intersection:
            title += intersection_text

        # Добавляем диапазон дат
        if include_date_range and start_date and end_date:
            date_str = f"{start_date} - {end_date}"
            title = f"{title} ({date_str})"

        # Добавляем дополнительную информацию
        if additional_info:
            title = f"{title} - {additional_info}"

    else:  # English
        feature_names = config.get_feature_names_en()
        variable_names = {
            'observable': 'Observable Inflation',
            'expected': 'Expected Inflation'
        }
        intersection_text = ' (Range Intersection)' if use_intersection else ''
        of_text = 'with'
        and_text = ' and '
        period_text = 'Period'
        features_text = 'Features'

        if active_features:
            if len(active_features) == 1:
                features_str = feature_names[0]
            elif len(active_features) == 2:
                features_str = f"{feature_names[0]}{and_text}{feature_names[1]}"
            else:
                features_str = ', '.join(feature_names[:-1]) + f"{and_text}{feature_names[-1]}"
        else:
            features_str = 'Base Configuration'

        if variable:
            var_name = variable_names.get(variable, variable)
            title = f"{var_name}: {features_str}"
        else:
            title = f"{features_str}"

        if use_intersection:
            title += intersection_text

        if include_date_range and start_date and end_date:
            date_str = f"{start_date} - {end_date}"
            title = f"{title} ({date_str})"

        if additional_info:
            title = f"{title} - {additional_info}"

    # Ограничиваем длину заголовка
    if len(title) > max_length:
        # Обрезаем с многоточием
        title = title[:max_length - 3] + '...'

    return title