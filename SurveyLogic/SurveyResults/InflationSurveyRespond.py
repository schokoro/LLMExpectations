from datetime import date
from dataclasses import dataclass
from typing import Optional


@dataclass
class InflationSurveyRespond:
    respondent_id: str
    target_date: Optional[str] = None

    expected_inflation_1m_category: Optional[str] = None
    observable_inflation_last_1m_category: Optional[str] = None
    expected_inflation_12m_pct: Optional[float] = None
    observable_inflation_last_12m_pct: Optional[float] = None

    certainty_0_100: Optional[int] = None
    perceived_personal_price_pressure: Optional[str] = None
    attention_to_inflation: Optional[str] = None
    main_anchor: Optional[str] = None
    secondary_anchors: Optional[str] = None
    short_explanation: Optional[str] = None

    hasCredit: Optional[bool] = None
    hasSavings: Optional[bool] = None


