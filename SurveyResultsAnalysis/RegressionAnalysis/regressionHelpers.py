import pandas as pd
from pathlib import Path

from SurveyResultsAnalysis.helpers import load_pdtable, aggregate_survey


def loadSurveyResults(rootFolder: Path, surveyResults):
    models = {}
    for folder, name in surveyResults:
        f = rootFolder / folder
        s = load_pdtable(f)
        s = aggregate_survey(s)

        models[name] = s

    return models

def getSurveyVisualization(predictions, dates):
    result_df = pd.DataFrame({
        'exp_mean': predictions.values
    }, index=dates)

    # Переименовываем индекс в 'date' для ясности (опционально)
    result_df.index.name = 'date'
    return result_df