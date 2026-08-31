from dataclasses import dataclass

@dataclass
class ExperimentsConfiguration:
    useEconomy: bool = False
    usePolitics: bool = False
    useInflation: bool = False
    useFamilyInformation: bool = False
    useFamilyExpenses: bool = False
    useStateExpenses: bool = False
    usePreviousInflationExpectations: bool = False
    useIndividualRLMSData: bool = False

    def get_active_features(self) -> list:
        """Возвращает список активных фич"""
        features = []
        if self.useEconomy:
            features.append('economy')
        if self.usePolitics:
            features.append('politics')
        if self.useInflation:
            features.append('inf')
        if self.useFamilyInformation:
            features.append('family_info')
        if self.useFamilyExpenses:
            features.append('family_exp')
        if self.useStateExpenses:
            features.append('state_exp')
        if self.useIndividualRLMSData:
            features.append('individual_info')
        if self.usePreviousInflationExpectations:
            features.append('previous_exp')
        return features

    def get_feature_names_en(self) -> list[str]:
        """Возвращает английские названия активных фич"""
        names_map = {
            'economy': 'Economy',
            'politics': 'Politics',
            'inf': 'Inflation info',
            'family_info': 'Family Information',
            'family_exp': 'Family Expenses',
            'state_exp': 'State Expenses',
            'individual_info': 'Individual Information',
            'previous_exp': 'Previous Inflation Expectations'
        }
        active = self.get_active_features()
        return [names_map[f] for f in active]

    def get_feature_abbr(self) -> str:
        """Возвращает краткое сокращение для активных фич"""
        abbr_map = {
            'economy': 'Econ',
            'politics': 'Pol',
            'inf': 'Inf',
            'family_info': 'FamInf',
            'family_exp': 'FamExp',
            'state_exp': 'StExp',
            'individual_info': 'IndInfo',
            'previous_exp': 'PrevInfExp'
        }
        active = self.get_active_features()
        if not active:
            return 'Base'
        return '_'.join(abbr_map[f] for f in active)
