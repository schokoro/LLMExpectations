"""Проверка повторного извлечения профилей без изменения исходных данных.

.venv/bin/python -B -u checkProfilesSeed.py --output PATH [--years 2020 2021]
"""

import argparse
import hashlib
import inspect
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import BadZipFile, ZipFile

from RLMSLogic.ProfileHashes import aggregateDigest, hashDirectory

# Импорт экстрактора не должен создавать __pycache__ вне временного каталога.
sys.dont_write_bytecode = True


def compareProfiles(year: str, originalFolder: Path, extractedFolder: Path) -> dict:
    """Сравнить имена и байты, сохранив обе стороны для разбора расхождений."""
    original = hashDirectory(originalFolder)
    extracted = hashDirectory(extractedFolder)
    common = original.keys() & extracted.keys()
    changed = sorted(name for name in common if original[name] != extracted[name])
    originalOnly = sorted(original.keys() - extracted.keys())
    extractedOnly = sorted(extracted.keys() - original.keys())
    passed = bool(original) and not (changed or originalOnly or extractedOnly)
    result = {
        'year': year,
        'verdict': 'verified' if passed else 'failed',
        'matched_count': len(common) - len(changed),
        'content_different_count': len(changed),
        'content_different': changed,
        'original_only': originalOnly,
        'extracted_only': extractedOnly,
        'profile_counts': {'original': len(original), 'extracted': len(extracted)},
        'aggregate_sha256': {
            'original': aggregateDigest(original),
            'extracted': aggregateDigest(extracted),
        },
        'file_sha256': {'original': original, 'extracted': extracted},
    }
    print(
        f'{year}: совпало {result["matched_count"]}, содержимое отличается '
        f'{len(changed)}; исходных {len(original)}, повторных {len(extracted)}'
    )
    for label, names in (
        ('Отличается содержимое', changed),
        ('Только в исходных', originalOnly),
        ('Только в повторных', extractedOnly),
    ):
        print(f'{year}: {label} ({len(names)}): {", ".join(names) or "—"}')
    print(f'{year}: SHA256 {result["aggregate_sha256"]}')
    return result


def verifyProfiles(repository: Path, years: list[str] | None = None) -> dict:
    """Распаковать во временное место и проверить неизменность входов в finally."""
    from RLMSLogic.RLMSProfileExtractor import RLMSProfileExtractor
    from RLMSLogic.SimpleRLMSProfileConverter import SimpleRLMSProfileConverter

    wavesFolder = repository / 'data/RLMS waves'
    profilesFolder = repository / 'data/Target profiles'
    # Параметры исходного запуска взяты из extractProfilesFromJSONs.py.
    sampleSize, adultAge = 100, 18
    seed = (
        inspect.signature(RLMSProfileExtractor.generateAndSaveProfilesFromRLMS)
        .parameters['seed']
        .default
    )
    result = {
        'verdict': 'failed',
        'checked_at_utc': datetime.now(UTC).isoformat(),
        'extractor_commit': None,
        'seed': seed,
        'sample_size': sampleSize,
        'adultAge': adultAge,
        'years': {},
        'inputs_unchanged': None,
    }
    before = None
    try:
        from Configuration import configuration

        before = (hashDirectory(wavesFolder), hashDirectory(profilesFolder))
        result['wave_sha256'] = before[0]
        result['extractor_commit'] = subprocess.check_output(
            [
                'git',
                '-C',
                str(repository),
                'log',
                '-1',
                '--format=%H',
                '--',
                'RLMSLogic/RLMSProfileExtractor.py',
            ],
            text=True,
        ).strip()
        if not result['extractor_commit'] or seed != 42:
            raise ValueError('Не найден коммит экстрактора или изменён default seed=42')
        result['extractor_sha256'] = hashlib.sha256(
            (repository / 'RLMSLogic/RLMSProfileExtractor.py').read_bytes()
        ).hexdigest()
        available = {path.stem for path in wavesFolder.glob('*.zip')}
        selected = sorted(set(years) if years is not None else available)
        if not selected or set(selected) - available:
            raise ValueError(f'Нет архивов для выбранных лет: {selected}')
        result['scope'] = 'all' if set(selected) == available else 'selected_years'
        extractor = RLMSProfileExtractor(
            SimpleRLMSProfileConverter(),
            configuration.regularGoods,
            configuration.durableGoods,
            configuration.services,
        )
        with TemporaryDirectory(prefix='profiles-seed42-') as temporary:
            for year in selected:
                targets = []
                for attempt in range(2):
                    source = Path(temporary) / year / str(attempt) / 'wave'
                    target = source.parent / 'profiles'
                    source.mkdir(parents=True)
                    with ZipFile(wavesFolder / f'{year}.zip') as archive:
                        members = archive.infolist()
                        if attempt == 1:
                            members = list(reversed(members))
                        for member in members:
                            if (
                                not (source / member.filename)
                                .resolve()
                                .is_relative_to(source.resolve())
                            ):
                                raise ValueError('Путь в архиве выходит из временного каталога')
                        archive.extractall(source, members=members)
                    # Seed намеренно не передаётся: проверяется default экстрактора.
                    extractor.generateAndSaveProfilesFromRLMS(source, target, sampleSize, adultAge)
                    targets.append(target)
                comparison = compareProfiles(year, profilesFolder / year, targets[0])
                comparison['independent_extractions'] = compareProfiles(year, *targets)
                if comparison['independent_extractions']['verdict'] != 'verified':
                    comparison['verdict'] = 'failed'
                result['years'][year] = comparison
        result['verdict'] = (
            'verified'
            if all(item['verdict'] == 'verified' for item in result['years'].values())
            else 'failed'
        )
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        BadZipFile,
        subprocess.SubprocessError,
    ) as error:
        result['error'] = f'{type(error).__name__}: {error}'
        result['verdict'] = 'failed'
    finally:
        if before is not None:
            try:
                result['inputs_unchanged'] = before == (
                    hashDirectory(wavesFolder),
                    hashDirectory(profilesFolder),
                )
            except OSError:
                result['inputs_unchanged'] = False
            if not result['inputs_unchanged']:
                result['verdict'] = 'failed'
    return result


def main() -> int:
    """Записать результат отдельно от запусков опроса; красный результат даёт exit 1."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--years', nargs='+', help='Годы архивов, например 2020 2021')
    parser.add_argument('--output', type=Path, required=True, help='Путь результата вне манифестов')
    arguments = parser.parse_args()
    repository = Path(__file__).resolve().parent
    resultPath = arguments.output.resolve()
    if resultPath.is_relative_to((repository / 'data/run_manifests').resolve()):
        parser.error('Результат проверки нельзя сохранять в data/run_manifests/')
    result = verifyProfiles(repository, arguments.years)
    resultPath.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'Исходные данные неизменны: {result["inputs_unchanged"]}')
    if 'error' in result:
        print(result['error'])
    print(f'Результат: {resultPath}')
    print('ЗЕЛЁНЫЙ' if result['verdict'] == 'verified' else 'КРАСНЫЙ')
    return 0 if result['verdict'] == 'verified' else 1


if __name__ == '__main__':
    sys.exit(main())
