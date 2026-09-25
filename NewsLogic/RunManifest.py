"""Провенанс и итоги серии; сборка не требует запуска опроса."""

import hashlib
import inspect
import json
import re
import subprocess
from datetime import UTC, date, datetime
from importlib.metadata import distribution
from pathlib import Path
from typing import Self

from amnesiac.summarize import SummarizeConfig, Usage
from openai.types.chat import ChatCompletion

from NewsLogic import NewsRagConfiguration as newsRagConfiguration
from NewsLogic.NewsContext import NewsContext
from NewsLogic.NewsContextProvider import NewsContextProvider
from NewsLogic.NewsCorpusReader import NewsCorpusReader, queryListHash
from NewsLogic.NewsRagConfiguration import NewsRagConfiguration
from RLMSLogic.ProfileHashes import aggregateDigest, hashDirectory
from RLMSLogic.RLMSProfileExtractor import RLMSProfileExtractor
from SurveyLogic.PromptBuilders.BasePromptBuilder import BasePromptBuilder
from SurveyLogic.PromptBuilders.CompositePromptBuilder import CompositePromptBuilder


def readCodeEnvironment(repository: Path) -> dict:
    """Читать идентификаторы кода, не включая URL установки и секреты окружения."""

    def gitOutput(*arguments: str) -> str:
        return subprocess.check_output(
            ['git', '-C', str(repository), *arguments], text=True
        ).strip()

    installed = json.loads(distribution('amnesiac').read_text('direct_url.json'))
    vcs = installed['vcs_info']
    return {
        'commit': gitOutput('rev-parse', 'HEAD'),
        'branch': gitOutput('rev-parse', '--abbrev-ref', 'HEAD'),
        'dirty': bool(gitOutput('status', '--porcelain')),
        'amnesiac': {'tag': vcs['requested_revision'], 'commit': vcs['commit_id']},
    }


def readRespondentData(
    wavesFolder: Path,
    profilesFolder: Path,
    profilesCount: int,
    verificationPath: Path | None = None,
) -> dict:
    """Хешировать имеющиеся волны; происхождение старых профилей не угадывать."""
    waveHashes = {}
    for path in sorted(wavesFolder.rglob('*')):
        if path.is_file():
            with path.open('rb') as source:
                waveHashes[str(path)] = hashlib.file_digest(source, 'sha256').hexdigest()
    respondentData = {
        'extractor_seed': (
            inspect.signature(RLMSProfileExtractor.generateAndSaveProfilesFromRLMS)
            .parameters['seed']
            .default
        ),
        'profiles_sha256': (
            aggregateDigest(hashDirectory(profilesFolder)) if profilesFolder.is_dir() else None
        ),
        'profiles_sha256_by_year': {
            folder.name: aggregateDigest(hashDirectory(folder))
            for folder in sorted(profilesFolder.iterdir())
            if folder.is_dir()
        }
        if profilesFolder.is_dir()
        else {},
        'extractor_commit': None,
        'seed42_verification': None,
        'provenance_status': 'Происхождение не проверено: файл seed42_verification.json отсутствует',
        'wave_sha256': waveHashes,
        'profiles_per_date': profilesCount,
        'profile_files_available': sum(1 for _ in profilesFolder.rglob('*.json')),
    }

    if verificationPath is None:
        respondentData['provenance_status'] = (
            'Происхождение не проверено: результат проверки хранится вне репозитория; '
            'сравнение через profiles_sha256_by_year'
        )
    elif verificationPath.is_file():
        verification = json.loads(verificationPath.read_text(encoding='utf-8'))
        respondentData.update(
            extractor_commit=verification['extractor_commit'],
            seed42_verification={
                'verdict': verification['verdict'],
                'checked_at_utc': verification['checked_at_utc'],
                'scope': verification.get('scope'),
                'aggregate_sha256': {
                    year: entry['aggregate_sha256'] for year, entry in verification['years'].items()
                },
            },
            provenance_status=(
                'Повторное извлечение: '
                + verification['verdict']
                + '; область проверки: '
                + verification.get('scope', 'не указана')
                + '; исходный коммит старых профилей неизвестен'
            ),
        )
    return respondentData


class RunManifest:
    """Один запуск, отдельный файл и ссылка возле результатов; запись в finally."""

    def __init__(
        self,
        experiment: str,
        configuration: NewsRagConfiguration,
        respondentModel: str,
        respondentEndpoint: str,
        resultsFolder: Path,
        manifestFolder: Path = Path('data/run_manifests'),
        startedAt: datetime | None = None,
    ):
        startedAt = startedAt or datetime.now(UTC)
        if startedAt.tzinfo is None:
            raise ValueError('Время старта должно содержать часовой пояс')
        startedAt = startedAt.astimezone(UTC)
        safeExperiment = re.sub(r'[^\w.-]', '_', experiment)
        self.runId = f'{safeExperiment}_{startedAt:%Y%m%dT%H%M%S%fZ}'
        self.path = manifestFolder / f'{self.runId}.json'
        self.resultsFolder = resultsFolder
        self.data = {
            'run_id': self.runId,
            'experiment': experiment,
            'code_environment': {'started_at_utc': startedAt.isoformat()},
            'corpus': None,
            'news_rag': {
                **configuration.toDictionary(),
                'config_hash': configuration.configHash(),
                'axis_order': list(configuration.axes),
                'query_hash': {
                    axis: queryListHash(queries) for axis, queries in configuration.axes.items()
                },
                'timezone_rule': newsRagConfiguration.windowRule,
                'utc_offset_hours': newsRagConfiguration.moscowUtcOffsetHours,
            },
            'models': {
                'summarization': {
                    'model': configuration.summarizeModel,
                    'endpoint': configuration.summarizeBaseUrl,
                    'configured_provider': configuration.summarizeProvider,
                    'provider_pin_verification': None,
                    'provider_pin_verification_status': 'not_checked',
                    'api_key_variable': configuration.summarizeApiKeyVariable,
                    'timeout': configuration.summarizeTimeout,
                    'SummarizeConfig': SummarizeConfig(
                        temperature=configuration.summarizeTemperature,
                        concurrency=configuration.summarizeConcurrency,
                        max_failed_axes=configuration.summarizeMaxFailedAxes,
                    ).model_dump(mode='json'),
                },
                'respondent': {'model': respondentModel, 'endpoint': respondentEndpoint},
            },
            # D-018: семь бит ExperimentsConfiguration не управляют news-фабрикой.
            'prompt': {
                'factory': 'createNewsPromptBuilder',
                'composition': None,
                'section_headers': None,
                'experiments_configuration_note': 'D-018: news-фабрика имеет фиксированный состав, без семи бит',
            },
            'respondent_data': None,
            'preflight': None,
            'totals': {
                'status': 'aborted',
                'dates_requested': [],
                'dates_computed': [],
                'dates_skipped': [],
                'skipped_count': 0,
                'degraded_dates_count': 0,
                'unknown_degradation_dates_count': 0,
                'surveys_completed': [],
                'surveys_already_saved': [],
                'per_date': {},
                'usage': Usage().model_dump(),
                'usage_scope': 'Суммаризация и preflight; только возвращённый usage',
                'usage_complete': True,
            },
        }

    def collectInputs(
        self, configuration: NewsRagConfiguration, profilesFolder: Path, profilesCount: int
    ) -> None:
        """Заполнять внутри защиты finally, до первого вызова провайдера."""
        self.data['code_environment'].update(readCodeEnvironment(Path.cwd()))
        with NewsCorpusReader(configuration.corpusPath) as reader:
            self.data['corpus'] = reader.getCorpusManifest()
        self.data['respondent_data'] = readRespondentData(
            Path('data/RLMS waves'), profilesFolder, profilesCount
        )

    def recordPrompt(
        self, systemBuilder: BasePromptBuilder, promptBuilder: CompositePromptBuilder
    ) -> None:
        """Снять состав с фактического результата фабрики."""
        self.data['prompt'].update(
            {
                'system_builder': type(systemBuilder).__name__,
                'composition': [type(builder).__name__ for builder in promptBuilder.builders],
                'section_headers': list(promptBuilder.headers),
            }
        )

    def recordSkipped(self, surveyDate: date, reason: str) -> None:
        self.data['totals']['dates_skipped'].append(
            {
                'date': surveyDate.isoformat(),
                'reason': reason,
            }
        )
        self.data['totals']['skipped_count'] += 1

    def recordUsage(
        self, surveyDate: date, provider: NewsContextProvider, context: NewsContext | None = None
    ) -> None:
        """Обновить срез даты без двойного учёта идемпотентного prepare()."""
        totals = self.data['totals']
        totals['per_date'][surveyDate.isoformat()] = {
            'usage': provider.usageByDate.get(surveyDate, Usage()).model_dump(),
            'summaryFromCache': context.summaryFromCache if context is not None else None,
            'failed_axes': (
                list(context.failedAxes)
                if context is not None and context.failedAxes is not None
                else None
            ),
            'documents_count': context.documentsCount if context is not None else None,
            'usage_complete': provider.usageCompleteByDate.get(surveyDate, True),
        }
        self._updateUsage()

    def recordPreflight(self, response: ChatCompletion) -> None:
        """Сохранить расход отдельного запроса, включая сообщённую стоимость."""
        providerUsage = response.usage
        usage = Usage(calls=1)
        if providerUsage is not None:
            usage = Usage(
                calls=1,
                prompt_tokens=providerUsage.prompt_tokens or 0,
                completion_tokens=providerUsage.completion_tokens or 0,
                total_tokens=providerUsage.total_tokens or 0,
            )
        self.data['preflight'] = {
            'outcome': 'succeeded',
            'usage': usage.model_dump(),
            'usage_complete': providerUsage is not None,
            'usage_note': None if providerUsage is not None else 'Провайдер не вернул usage',
            'reported_cost': getattr(providerUsage, 'cost', None),
        }
        self._updateUsage()
        summarization = self.data['models']['summarization']
        servedProvider = getattr(response, 'provider', None)
        summarization['provider_pin_verification'] = servedProvider
        if servedProvider is None:
            summarization['provider_pin_verification_status'] = 'not_reported'
        elif servedProvider == summarization['configured_provider']:
            summarization['provider_pin_verification_status'] = 'verified'
        else:
            summarization['provider_pin_verification_status'] = 'mismatch'
            raise ValueError('Провайдер preflight отличается от закреплённого')

    def recordPreflightFailure(self, errorType: str) -> None:
        """Не сохранять текст ошибки; расход без ответа неизвестен."""
        if self.data['preflight'] is None:
            self.data['preflight'] = {
                'usage': Usage().model_dump(),
                'usage_complete': False,
                'usage_note': 'Нет ответа с usage; расход неизвестен',
                'reported_cost': None,
            }
        self.data['preflight'].update(outcome='failed', error_type=errorType)
        self._updateUsage()

    def _updateUsage(self) -> None:
        totals = self.data['totals']
        preflight = self.data['preflight']
        usage = Usage(**preflight['usage']) if preflight else Usage()
        totals['preflight_reported_cost'] = preflight['reported_cost'] if preflight else None
        for entry in totals['per_date'].values():
            usage += Usage(**entry['usage'])
        totals['usage'] = usage.model_dump()
        totals['usage_complete'] = (preflight is None or preflight['usage_complete']) and all(
            entry['usage_complete'] for entry in totals['per_date'].values()
        )

    def write(self) -> None:
        """Не перезаписывать даже запуск с совпавшей микросекундой старта."""
        totals = self.data['totals']
        if (
            totals['status'] != 'aborted'
            and not totals['dates_computed']
            and not totals['dates_skipped']
        ):
            raise ValueError('Ошибка сборки манифеста: dates_computed и dates_skipped пусты')
        computedEntries = [totals['per_date'][day] for day in totals['dates_computed']]
        totals['degraded_dates_count'] = sum(
            bool(entry['failed_axes']) for entry in computedEntries
        )
        totals['unknown_degradation_dates_count'] = sum(
            entry['failed_axes'] is None for entry in computedEntries
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.resultsFolder.mkdir(parents=True, exist_ok=True)
        with self.path.open('x', encoding='utf-8') as target:
            json.dump(self.data, target, ensure_ascii=False, indent=2)
            target.write('\n')
        reference = {'run_id': self.runId, 'manifest_path': str(self.path.resolve())}
        referencePath = self.resultsFolder / f'run_manifest_{self.runId}.json'
        with referencePath.open('x', encoding='utf-8') as target:
            json.dump(reference, target, ensure_ascii=False, indent=2)
            target.write('\n')

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exceptionType, exception, traceback) -> bool:
        try:
            # Текст произвольного исключения может содержать ключ или URL с токеном.
            if exceptionType is not None:
                self.data['totals']['status'] = 'aborted'
                self.data['totals']['abort_type'] = exceptionType.__name__
            else:
                self.data['totals']['status'] = (
                    'completed_with_skips' if self.data['totals']['dates_skipped'] else 'completed'
                )
        finally:
            try:
                self.write()
            except Exception as writeError:
                if exception is None:
                    raise
                # Не заменять исходный отказ ошибкой записи и не раскрывать её текст.
                exception.add_note(f'Манифест не записан: {type(writeError).__name__}')
        return False
