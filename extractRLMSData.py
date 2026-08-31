import re
import shutil
from pathlib import Path

from Configuration import configuration
from RLMSLogic.SimpleRLMSProfileConverter import SimpleRLMSProfileConverter
from RLMSLogic.RLMSProfileExtractor import RLMSProfileExtractor

targetDirectory = 'data/Target profiles'
dtaSources = Path('data/RLMS waves')

files = list(dtaSources.rglob("*.sav"))
files.extend(list(dtaSources.rglob("*.dta")))

adultAge = 18

start_wave = 33
end_wave = 18          # например, до 20-й волны
start_year = 2024

wavesToYearMap = {wave: start_year - (start_wave - wave) for wave in range(start_wave, end_wave - 1, -1)}
converter = SimpleRLMSProfileConverter()
extractor = RLMSProfileExtractor(converter, configuration.regularGoods, configuration.durableGoods, configuration.services)
sampleSize = 1000

folder = Path(targetDirectory)
if folder.exists():
    shutil.rmtree(folder)  # удаляем папку целиком

for iFile in files:
    match = re.search(r'r(\d+)i', iFile.name)
    if not match:
        continue

    waveNumber = int(match.group(1))
    hhFile = next((f for f in files if f'r{waveNumber}h' in f.name), None)

    print(f'Parsing file: {iFile} for wave #{waveNumber}')

    waveYear = wavesToYearMap[waveNumber]
    waveDirectory = dtaSources / f'{waveYear}'
    waveDirectory.mkdir(parents=True, exist_ok=True)

    targetProfileDirectory = Path(targetDirectory) / f'{waveYear}'
    targetProfileDirectory.mkdir(parents=True, exist_ok=True)

    extractor.extractAndSaveRLMSProfiles(iFile, hhFile, waveDirectory, 2*sampleSize)
    extractor.generateAndSaveProfilesFromRLMS(waveDirectory, targetProfileDirectory, sampleSize, adultAge)

    archive_base = dtaSources / f'{waveYear}'
    archivePath = dtaSources/f'{waveYear}.zip'

    if archivePath.exists() and archivePath.is_file():
        archivePath.unlink()  # удаляем файл

    archive_path = shutil.make_archive(str(archive_base), 'zip', str(waveDirectory))
    shutil.rmtree(waveDirectory)

#dta_file = 'data\\r33iall_84_DTA\\r33iall_84.dta'
#dta_file = 'data\\r33i_os_84_DTA\\r33i_os_84.dta'
#out_folder = 'data\\rlms2024_os_profiles'
#profiles_out_folder = 'data\\target_rlms2024_os_based_profiles'