import json
from dataclasses import asdict
from datetime import date
from pathlib import Path

from SurveyLogic.SurveyResults.InflationSurveyRespond import InflationSurveyRespond
from SurveyLogic.SurveyResultsSerialization.BaseSurveySerializer import BaseSurveySerializer


class SurveySerializer(BaseSurveySerializer):
    def __init__(self, resultFolder: Path):
        self.resultFolder = resultFolder

    def saveSurvey(self, surveys, surveyDate: date):
        dir_path = self.resultFolder
        dir_path.mkdir(parents=True, exist_ok=True)

        for survey in surveys:
            survey.target_date = surveyDate.strftime('%d.%m.%Y')
            self.__saveSingleSurvey(survey, self.resultFolder)

        return

    @staticmethod
    def __saveSingleSurvey(survey, targetFolder: Path):
        filename = f'{survey.target_date}_{survey.respondent_id}.json'
        file_path = targetFolder / filename

        # Преобразуем датакласс в словарь и записываем в JSON
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(asdict(survey), f, ensure_ascii=False, indent=2)
