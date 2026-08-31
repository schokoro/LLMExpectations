import numpy as np
import pandas as pd
from scipy import stats
import matplotlib.pyplot as plt

print("="*70)
print("АНАЛИЗ: ЯВЛЯЕТСЯ ЛИ ПРИРОСТ R² = 0.0293 ШУМОМ?")
print("="*70)

# Ваши данные
r2_without_model = 0.7807
r2_with_model = 0.8100
r2_increase = 0.0293
n_obs = 140  # предположим (замените на реальное число)

print(f"""
📊 Исходные данные:
  - R² без модели: {r2_without_model:.4f}
  - R² с моделью: {r2_with_model:.4f}
  - Прирост: {r2_increase:.4f} ({r2_increase/r2_without_model*100:.2f}% относительного улучшения)
  - Количество наблюдений: {n_obs}

🔍 Ключевые аргументы против "шума":
""")

def compare_models_f_test(r2_full, r2_reduced, n, k_full, k_reduced):
    """
    F-тест для сравнения вложенных моделей.
    """
    k_diff = k_full - k_reduced
    f_stat = ((r2_full - r2_reduced) / k_diff) / ((1 - r2_full) / (n - k_full - 1))
    p_value = 1 - stats.f.cdf(f_stat, k_diff, n - k_full - 1)
    return f_stat, p_value

# Для вашего случая (добавление 1 переменной)
k_full = 3  # X1, X2, X3
k_reduced = 2  # X1, X2
k_diff = 1

f_stat, p_value = compare_models_f_test(
    r2_full=r2_with_model,
    r2_reduced=r2_without_model,
    n=n_obs,
    k_full=k_full,
    k_reduced=k_reduced
)

print(f"""
📊 F-тест для сравнения моделей:
  - F-статистика: {f_stat:.4f}
  - p-value: {p_value:.6f}
  - Критическое значение F(0.05): {stats.f.ppf(0.95, k_diff, n_obs - k_full - 1):.4f}

{'✅' if p_value < 0.05 else '❌'} Вывод: {'Прирост НЕ ЯВЛЯЕТСЯ шумом' if p_value < 0.05 else 'Прирост может быть шумом'}
""")