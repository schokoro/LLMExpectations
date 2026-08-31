import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from experimentsConfiguration import ExperimentsConfiguration


def saveExperimentConfiguration(cfg: ExperimentsConfiguration, resultsFolder: Path):
    resultsFolder.mkdir(parents=True, exist_ok=True)

    config_dict = asdict(cfg)

    file_path = resultsFolder/'configuration.txt'

    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(config_dict, f, indent=4, ensure_ascii=False)


def loadExperimentConfig(config_path: Path) -> ExperimentsConfiguration:
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return ExperimentsConfiguration(**data)
    except FileNotFoundError:
        print(f"⚠️ Файл конфига не найден: {config_path}")
        raise
    except json.JSONDecodeError as e:
        print(f"⚠️ Ошибка парсинга JSON: {e}")
        raise
    except Exception as e:
        print(f"⚠️ Ошибка загрузки конфига: {e}")
        raise


def generate_filename_from_config(
        config: ExperimentsConfiguration,
        prefix: str = 'plot',
        variable: Optional[str] = None,  # 'observable' или 'expected'
        use_intersection: bool = False,
        include_hash: bool = False,
        max_length: int = 200,
        **kwargs
) -> str:
    """
    Генерирует имя файла на основе конфигурации эксперимента

    Args:
        config: объект конфигурации
        prefix: префикс имени файла
        variable: тип переменной ('observable' или 'expected')
        use_intersection: используется ли пересечение диапазонов
        include_hash: добавлять ли хеш для уникальности
        max_length: максимальная длина имени файла (с учетом Windows ограничений)
        **kwargs: дополнительные параметры для включения в имя

    Returns:
        str: сгенерированное имя файла
    """
    # Базовая часть имени
    parts = [prefix]

    # Добавляем информацию о переменной
    if variable:
        var_short = 'obs' if variable == 'observable' else 'exp'
        parts.append(var_short)

    # Добавляем информацию об активных фичах
    active_features = config.get_active_features()
    if active_features:
        # Создаем компактное представление фич
        feature_str = config.get_feature_abbr()
        parts.append(feature_str)
    else:
        parts.append('base')

    # Добавляем информацию о пересечении диапазонов
    if use_intersection:
        parts.append('intersect')

    # Добавляем дополнительные параметры если они есть
    if kwargs:
        for key, value in kwargs.items():
            if value is not None:
                # Преобразуем булевы значения в короткие флаги
                if isinstance(value, bool):
                    if value:
                        parts.append(key.lower())
                else:
                    # Для других значений добавляем в формате ключ=значение
                    parts.append(f"{key}={str(value)[:10]}")

    # Собираем имя
    filename = '_'.join(parts)

    # Заменяем недопустимые символы
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        filename = filename.replace(char, '')

    # Ограничиваем длину
    if len(filename) > max_length:
        # Если нужно сохранить уникальность, используем хеш
        if include_hash:
            # Берем первые (max_length - 12) символов и добавляем хеш
            hash_obj = hashlib.md5(filename.encode())
            hash_suffix = hash_obj.hexdigest()[:8]
            filename = filename[:max_length - 12] + '_' + hash_suffix
        else:
            # Просто обрезаем
            filename = filename[:max_length]

    return filename + '.png'


def generate_filename_with_dates(
        config: ExperimentsConfiguration,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        prefix: str = 'plot',
        variable: Optional[str] = None,
        use_intersection: bool = False,
        max_length: int = 200,
        **kwargs
) -> str:
    """
    Генерирует имя файла с включением дат (если они есть)

    Args:
        config: объект конфигурации
        start_date: начальная дата в формате 'YYYY-MM-DD'
        end_date: конечная дата в формате 'YYYY-MM-DD'
        prefix: префикс имени файла
        variable: тип переменной
        use_intersection: используется ли пересечение диапазонов
        max_length: максимальная длина имени файла
        **kwargs: дополнительные параметры

    Returns:
        str: сгенерированное имя файла
    """
    # Сначала генерируем базовое имя
    base_filename = generate_filename_from_config(
        config=config,
        prefix=prefix,
        variable=variable,
        use_intersection=use_intersection,
        include_hash=False,
        max_length=max_length,
        **kwargs
    )

    # Убираем расширение .png
    base_filename = base_filename.replace('.png', '')

    # Добавляем даты, если они есть
    if start_date and end_date:
        # Очищаем даты от недопустимых символов
        start_clean = start_date.replace('-', '').replace('/', '')
        end_clean = end_date.replace('-', '').replace('/', '')
        date_str = f"{start_clean}_{end_clean}"

        # Проверяем длину
        if len(base_filename) + len(date_str) + 1 > max_length - 4:  # -4 для .png
            # Если слишком длинное, обрезаем базовое имя
            available = max_length - len(date_str) - 5  # -5 для '_' и '.png'
            base_filename = base_filename[:available]

        filename = f"{base_filename}_{date_str}.png"
    else:
        filename = base_filename

    return filename