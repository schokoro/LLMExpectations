"""Общие хеши файлов профилей для проверки и манифеста."""

import hashlib
from pathlib import Path


def hashDirectory(folder: Path) -> dict[str, str]:
    """Снять хеши байтов всех файлов с относительными именами."""
    if not folder.is_dir():
        raise FileNotFoundError(f'Нет каталога: {folder}')
    hashes = {}
    for path in folder.rglob('*'):
        if path.is_file():
            with path.open('rb') as source:
                hashes[path.relative_to(folder).as_posix()] = hashlib.file_digest(
                    source, 'sha256'
                ).hexdigest()
    return hashes


def aggregateDigest(hashes: dict[str, str]) -> str:
    """SHA256 от отсортированных строк name:hash, каждая заканчивается LF."""
    pairs = ''.join(f'{name}:{hashes[name]}\n' for name in sorted(hashes))
    return hashlib.sha256(pairs.encode('utf-8')).hexdigest()
