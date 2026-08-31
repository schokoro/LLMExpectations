from pathlib import Path

import pandas as pd
from SurveyResultsAnalysis.InflationComparisonAnalyzer import InflationComparisonAnalyzer
from SurveyResultsAnalysis.helpers import load_from_official_statistics, load_pdtable, aggregate_survey, \
    load_pdtable_with_repeats

folder = '../data/SurveyResults/mlcluster_qwen36_async_all_time'

directEstimationsFileName = '../data/Direct_Inflation_Estimations_12m.xlsx'
directEstimations = load_from_official_statistics(directEstimationsFileName)
print(directEstimations.head())

surveys = load_pdtable(Path(folder))
print(surveys)
#surveys = load_pdtable_with_repeats(folder)

surveys = aggregate_survey(surveys)
print(surveys)

analyzer = InflationComparisonAnalyzer(directEstimations, surveys)
analyzer.analyze()
analyzer.print_summary()
analyzer.plot_all()
analyzer.export_results()