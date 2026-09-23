-- 015: хеш конфигурации в обоих уровнях кеша саммари (D-031).
--
-- Зачем. Горизонт и модель не различают настройки отбора, порядок осей,
-- промпты и провайдера. Устаревшее осевое саммари иначе попадает во вход
-- новой меты, даже когда кеш меты очищен. Другой хеш означает промах кеша.
--
-- Формат: SHA-256 hex канонического JSON UTF-8; состав описан в SCHEMA.md.
-- Оси — упорядоченные пары, ключи объектов сортируются. NULL не является
-- актуальным хешем. Обе таблицы при применении пусты, заполнения задним
-- числом нет. Повторное применение ALTER TABLE завершится ошибкой.
--
-- Применение (с реестром в одной транзакции):
--   (echo 'BEGIN;'; cat data/newsDB/migrations/015_summaries_config_hash.sql; \
--    echo "INSERT INTO migrations (name) VALUES ('015_summaries_config_hash'); COMMIT;") \
--    | sqlite3 -bail data/newsDB/project.db

ALTER TABLE summaries ADD COLUMN config_hash TEXT;
ALTER TABLE axis_summaries ADD COLUMN config_hash TEXT;
