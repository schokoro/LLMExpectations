from dataclasses import dataclass
from typing import Optional


@dataclass
class SHAPSurveyRespond:
    respondent_id: str
    target_date: Optional[str] = None

    shapValues: dict[str, float] = None