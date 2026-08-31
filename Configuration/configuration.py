from pathlib import Path

path = 'Configuration'

bothub_key = Path(f'{path}/bothub_key.txt').read_text(encoding="utf-8")
bothubUrl = 'https://openai.bothub.chat/v1'

mlcluster_key = Path(f'{path}/mlcluster_key.txt').read_text(encoding="utf-8")
mlclusterUrl = 'https://litellm.mlcluster.ru'

rlmsToInflationRegionsPath = Path(f'data/rlmsToInflationRegionsMapping.txt')
rlmsToInflationProductsPath = Path(f'data/rlmsToInflationProductsMapping.txt')
rlmsToAverageSalaryRegionsPath = Path(f'data/rlmsToAverageSalaryRegionsMapping.txt')

mrotStatisticsPath = Path(f'data/MROT_history.xlsx')
averageBuyingsDataPath = Path(f'data/Average Buyings Regions 1980_2026.xlsx')
#inflationDataPath = Path(f'data/Inflation weekly by regions 2015 - 2026.xlsx')
inflationDataPath = Path(f'data/Monthly Inflation for goods and services in regions_2015_2026_v1.xlsx')

inflation20092014DataPath = Path(f'data/Monthly Inflation for goods and services in regions_2009_2014_v0.xlsx')
inflation20152020DataPath = Path(f'data/Monthly Inflation for goods and services in regions_2015_2020_v0.xlsx')
inflation20212026DataPath = Path(f'data/Monthly Inflation for goods and services in regions_2021_2026_v0.xlsx')

years20092014 = set(range(2009, 2015))
years20152020 = set(range(2015, 2021))
years20212026 = set(range(2021, 2027))

regularGoods = Path(f'data/rlms_regular_goods_map.txt')
durableGoods = Path(f'data/rlms_durable_goods_map.txt')
services = Path(f'data/rlms_services_map.txt')

weeklyRegularGoods = Path(f'data/rlmsWeeklyRegularGoods.txt')
weeklyDurableGoods = Path(f'data/rlmsWeeklyDurableGoods.txt')
weeklyServices = Path(f'data/rlmsWeeklyServices.txt')

inflationSurveysDates = Path(f'data/ExpectedInflationSurveysDates.xlsx')
weeklyInflationDataPath = Path(f'data/Nedel_ipc.xlsx')
usdrubDataPath = Path(f'data/RC_F01_01_2009_T01_08_2026.xlsx')

regularMarkerGoods = ['Хлеб и булочные изделия из пшеничной муки', 'Хлеб из ржаной муки и из смеси муки ржаной и пшеничной, кг', 'Мясо птицы', 'Свинина', 'Свинина (кроме бескостного мяса), кг', 'Молоко и молочная продукция', 'Молоко питьевое цельное пастеризованное 2,5%-3,2% жирности, л', 'Рыба мороженая, неразделанная, кг', 'Рыба и морепродукты, за исключением сельди и консервов рыбных', 'Бензин автомобильный', 'Дизельное топливо, л', ]
durableMarkerGoods = ['Легковой автомобиль отечественный новый, шт.', 'Легковой автомобиль иностранной марки новый, шт.', 'Легковые автомобили', 'Мебель', 'Одежда', 'Обувь кожаная, текстильная и комбинированная']
servicesMarker = ['Ремонт жилищ', 'Жилищно-коммунальные услуги', 'Плата за жилье в домах государственного и муниципального жилищных фондов, м2 общей площади', 'Услуги образования', 'Услуги пассажирского транспорта', 'Проезд в городском автобусе, поездка', 'Проезд в трамвае, поездка', 'Проезд в троллейбусе, поездка', 'Проезд в метро, поездка', 'Обед в столовой, кафе, закусочной (кроме столовой в организации), на 1 человека', 'Общественное питание']

inflationExpectations = Path(f'data/Direct_Inflation_Estimations_12m.xlsx')