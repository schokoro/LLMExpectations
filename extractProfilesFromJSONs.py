import shutil
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from RLMSLogic.RLMSProfileExtractor import RLMSProfileExtractor
from RLMSLogic.SimpleRLMSProfileConverter import SimpleRLMSProfileConverter


def main() -> int:
    targetDirectory = Path('data/Target profiles')
    if targetDirectory.exists() and any(targetDirectory.iterdir()):
        print('Сначала архивируйте и переместите текущие профили из data/Target profiles.')
        return 1

    from Configuration import configuration

    jsonSources = Path('data/RLMS waves')
    files = sorted(jsonSources.rglob('*.zip'))
    converter = SimpleRLMSProfileConverter()
    extractor = RLMSProfileExtractor(
        converter,
        configuration.regularGoods,
        configuration.durableGoods,
        configuration.services,
    )
    sampleSize = 100
    adultAge = 18
    targetDirectory.mkdir(parents=True, exist_ok=True)

    for f in files:
        waveYear = f.stem
        print(f'Parsing file: {f}, year = {waveYear}')
        targetProfileDirectory = targetDirectory / waveYear
        with TemporaryDirectory(prefix='rlms-wave-') as temporary:
            extractDirectory = Path(temporary)
            shutil.unpack_archive(str(f), str(extractDirectory), 'zip')
            extractor.generateAndSaveProfilesFromRLMS(
                extractDirectory, targetProfileDirectory, sampleSize, adultAge
            )
    return 0


if __name__ == '__main__':
    sys.exit(main())
