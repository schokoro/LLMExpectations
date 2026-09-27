# Манифесты серий

`runMySeriesWithNews.py` автоматически записывает `<experiment>_<UTC start>.json`
при завершении или прерывании запуска. Время UTC включает микросекунды; совпадение
имени вызывает ошибку, а не перезапись. Манифесты предназначены для хранения в git.
Файл `run_manifest_<run_id>.json` возле ответов содержит run id и абсолютный путь
к манифесту. При переносе репозитория файл находится также здесь по run id.

`dates_computed` означает подготовленные контексты; завершённые опросы записаны
отдельно в `surveys_completed`. `usage` учитывает суммаризацию, включая доступную
стоимость неудачных стадий. При транспортном отказе библиотека может не вернуть
usage: тогда `usage_complete=false`, сумма является только известной частью.
`summaryFromCache=null` означает, что контекст даты не был получен.

`configured_provider` фиксирует настройку, а не доказательство применения пина.
`provider_pin_verification` содержит исходное значение `provider` из ответа preflight:
отображаемое имя OpenRouter (например, `DeepInfra`), не slug; `null`, если отсутствует.
`provider_pin_verification_status`: `not_checked` — ответа ещё нет,
`not_reported` — ответ не содержит provider,
`provider_name_verified` — имя точно равно части пина до `/` без учёта регистра
и пробелов по краям; `mismatch` — несовпадение, прерывающее запуск.
Полный slug в ответе или иное различие в имени после такой нормализации — `mismatch`.
`configured_quantization` — часть пина после `/` (`null`, если её нет).
`quantization_verification_status`: `not_checked` — до preflight,
`not_reported` — после успешного preflight: ответ не сообщает квантизацию.
Она задаётся только маршрутизацией (`provider.order` + `allow_fallbacks: false`
в `PinnedOpenRouterClient`); манифест её не подтверждает.
`preflight.attempts` — число попыток; `preflight.transient_errors` — только имена
типов временных ошибок, никогда не их сообщения. `RateLimitError`,
`InternalServerError`, `APIConnectionError` (включая таймауты) повторяются:
не более 3 попыток с паузами 5 и 15 с; остальные ошибки завершают preflight
при первой попытке. Любая неудачная попытка запроса делает `preflight.usage_complete`
и `totals.usage_complete` равными `false`, даже если preflight затем успешен.
Пустой content при успешном preflight допустим: запрос ограничен одним токеном.
В totals `degraded_dates_count` считает подготовленные даты с непустым
failed_axes, `unknown_degradation_dates_count` — с failed_axes=null.
Прогон без подготовленных дат сохраняется, если записан хотя бы один пропуск. `extractor_seed` всегда содержит default seed из сигнатуры экстрактора текущего кода.
`profiles_sha256` — SHA256 отсортированных строк `год/файл:хеш\n` всего набора;
`profiles_sha256_by_year` — такие же агрегаты внутри каждого года (имена без года).
Они напрямую сопоставимы с `aggregate_sha256` результата `checkProfilesSeed.py`.
Проверка запускается с обязательным `--output PATH` вне `data/run_manifests/`:
результат содержит идентификаторы RLMS и хранится в артефактах вне основного репозитория.
По умолчанию `extractor_commit` и `seed42_verification` равны null, а
`provenance_status` указывает на внешнюю проверку через `profiles_sha256_by_year`.
При явно переданном `verificationPath` манифест сохраняет сводку проверки без имён файлов.
Хеши волн и профилей относятся к файлам на момент запуска.
