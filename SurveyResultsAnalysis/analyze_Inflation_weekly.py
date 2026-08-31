from pathlib import Path

from Configuration import visualizationConfiguration
from SurveyResultsAnalysis.TimeSeriesVisualizer import TimeSeriesVisualizer
from SurveyResultsAnalysis.helpers import load_from_official_statistics, load_pdtable, aggregate_survey, \
        load_official_inflation, load_official_analytics_expectation

rootFolder = Path('../data/SurveyResults/')

modellingResults = [
        ('mlcluster_qwen36_async_all_time', 'QWEN 3.6 (все данные, в день Инфом)'),
        ('mlcluster_qwen36_async_all_time_week_before', 'QWEN 3.6 (все данные, -7d от Инфом)'),
        ('mlcluster_qwen36_async_all_two_weekbefore', 'QWEN 3.6 (все данные, -2w от Инфом)'),
        ('mlcluster_qwen36_async_nousdrub_time_week_before', 'QWEN 3.6 (без usdrub, -7d от Инфом)'),
        ('mlcluster_qwen36_async_nousdrub_time', 'QWEN 3.6 (без usdrub, в день Инфом)'),
        ('mlcluster_qwen36_async_norlms_weekbefore', 'QWEN 3.6 (без RLMS, -7d от Инфом)')
]

officialInflation = load_official_inflation(visualizationConfiguration.officialInflationPath)
analytics = load_official_analytics_expectation(visualizationConfiguration.analyticsForecastPath, visualizationConfiguration.analyticsDatesMapPath)

models = {}
for folder, name in modellingResults:
        f = rootFolder/folder
        s = load_pdtable(f)
        s = aggregate_survey(s)

        models[name] = s

directEstimationsFileName = visualizationConfiguration.directInflationEstimationsPath
directEstimations = load_from_official_statistics(directEstimationsFileName, 1)
keyDates = {'15.12.2014': 'Черный понедельник', '31.01.2020': 'COVID-19 в РФ', '24.02.2022': 'Начало СВО', '18.06.2026': 'НПЗ в Московской области', '01.05.2018': 'Топливный кризис в РФ'}

# Создаем визуализатор
viz = TimeSeriesVisualizer(
        true_series=directEstimations,
        model_series=models,
        additional_series={'Инфляция Росстат (г/г)': officialInflation, 'Опрос аналитиков (на дек.)':analytics},
        vertical_lines=keyDates
    )

# Строим график с кастомными цветами
colors = {
        'true': '#1F77B4',
        'Model A': '#FF6B6B',
        'Model B': '#4ECDC4',
        'Model C': '#FFE66D'
}

viz.plot_timeseries(
        variable='expected',
        colors=colors,
        xlabel='Дата',
        ylabel='Инфляция, %',
        show_date_labels=True,
        date_labels_for='true',
        title='Ожидаемая на год вперед инфляция: моделирование vs реальный опрос',
        figsize=(16, 8),
        label_offset_y=-0.1,
        label_offset_x=0,
        save_path=Path('timeseries.png')
    )

cutDates = ['2009-01-01', '2013-05-01', '2024-07-01']

for d in cutDates:
        viz.plot_correlation(
                variable='expected',
                cut_date=d,
                save_path=Path(f'{d}_correlation_expected.png'),
                use_intersection=True,
        )