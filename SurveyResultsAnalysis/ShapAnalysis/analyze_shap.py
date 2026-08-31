from pathlib import Path

import matplotlib.pyplot as plt

from SurveyResultsAnalysis.ShapAnalysis.shapAnalysingHelpers import load_json_files, extract_variable_values, \
    extract_target_dates, plot_variable_distributions_normalized

#caseName = 'mlcluster_qwen36_async_shap'
#additionalDescription = '(2^7)'

caseName = 'mlcluster_qwen36_async_shap_7_minus_1'
additionalDescription = '(7-1)'

#caseName = 'mlcluster_qwen36_async_shap_0_plus_1'
#additionalDescription = '(0+1)'

rootFolder = Path('../../data/Shap Results')

input_folder = rootFolder/caseName  # Путь к вашей папке
output_path = rootFolder/caseName  # Куда сохранить

dates = ['09.07.2026', '08.05.2018', '09.12.2014', '05.03.2020', '05.03.2022']
#dates = ['09.07.2026']

for d in dates:
    print(f"Loading files for date {d} from: {input_folder}")
    data = load_json_files(input_folder, d)

    if not data:
        print(f'No data for date {d} found')
        continue

    # 2. Извлекаем значения
    print("Extracting variable values...")
    variable_values = extract_variable_values(data)

    # 3. Извлекаем даты для подписей
    dates = extract_target_dates(data)

    # 4. Создаем и сохраняем график
    print(f"Creating plot and saving to: {output_path}")
    #plot_variable_distributions_boxplot
    #plot_variable_distributions_aligned
    #plot_variable_distributions_boxplot
    #plot_variable_distributions_normalized

    description = {
        'RLMSIndividual': 'RLMS индивидуальная анкета',
        'RLMSHH': 'RLMS анкета домохозяйства',
        'RLMSHHRegionalExpenses': 'Траты по RLMS (регион, точность месяц)',
        'RLMSHHStateExpenses': 'Траты по RLMS (РФ, точность неделя)',
        'Economy': 'Курс доллар/рубль',
        'RegionalInflation': 'Инфляция в регионе (точность месяц)',
        'StateInflation': 'Инфляция в РФ (точность месяц)'
    }

    vv = {}
    for k, v in variable_values.items():
        name = description[k]
        vv[name] = v

    fig = plot_variable_distributions_normalized(
        variable_values=vv,
        output_path=output_path/f'{d}_{caseName}_shap_values.png',
        dates=dates,
        #show_stats=True,
        totalObjects=len(data),
        additional_desc=additionalDescription
    )

    plt.show()  # Опционально, если хотите посмотреть график