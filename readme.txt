1. Создать папку RLMS Waves в папке data проекта.
2. Скопировать туда данные RLMS анкет (индивидуальные и по домохозяйствам) - доступны по ссылке: https://disk.yandex.ru/d/05Ll1JA1fQkC9Q
3. Запустить файл ExtractRLMSData.py (находится в корне проекта). Этот файл сгенерирует профили опрашиваемых и сохранит их на диск в json формате (каждый).
4. Запустить файл runMultipleSurveyesWithNews.py
5. Для просмотра визуальных результатов запустить файл analyze_Inflation_weekly.py (предварительно в нем указать путь в переменной modellingResults как пару (x, y), где x - это то же значение, что и значение experimentUniqueName из файла runMultipleSurveyesWithNews.py, а y - это подпись на графике для этого ряда).