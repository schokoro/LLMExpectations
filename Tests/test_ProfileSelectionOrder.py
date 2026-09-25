"""Детерминизм и безопасная перегенерация на синтетических данных."""

import hashlib
import io
import json
import os
import unittest
from contextlib import redirect_stdout
from dataclasses import fields
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
from zipfile import ZipFile

import checkProfilesSeed
import extractProfilesFromJSONs
from NewsLogic.RunManifest import readRespondentData
from RLMSLogic.ProfileHashes import hashDirectory
from RLMSLogic.RLMSProfileData import RLMSProfileData
from RLMSLogic.RLMSProfileExtractor import RLMSProfileExtractor
from RLMSLogic.SimpleRLMSProfileConverter import SimpleRLMSProfileConverter


class ProfileSelectionOrderTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.configuration = SimpleNamespace(
            regularGoods='regular', durableGoods='durable', services='services'
        )

    def testSelectionIgnoresGlobOrder(self):
        source = self.root / 'source'
        source.mkdir()
        names = []
        for index in range(30):
            profile = {}
            for field in fields(RLMSProfileData):
                profile[field.name] = {} if field.type == dict[str, float] else field.type()
            profile.update(respondentId=f'p{index:02}', age=15 if index % 3 == 0 else 30)
            path = source / f'p{index:02}.json'
            path.write_text(json.dumps(profile))
            names.append(str(path))
        extractor = object.__new__(RLMSProfileExtractor)
        extractor.converter = SimpleRLMSProfileConverter()
        outputs = []
        for index, order in enumerate((names, names[::-1], names[::2] + names[1::2])):
            target = self.root / f'output{index}'
            output = io.StringIO()
            with (
                patch('RLMSLogic.RLMSProfileExtractor.glob.glob', return_value=order),
                redirect_stdout(output),
            ):
                extractor.generateAndSaveProfilesFromRLMS(source, target, 8, 18)
            self.assertIn('Skipping profile', output.getvalue())
            files = {path.name: path.read_bytes() for path in target.iterdir()}
            self.assertEqual(len(files), 8)
            self.assertTrue(all(json.loads(data)['age'] >= 18 for data in files.values()))
            outputs.append(files)
        for output in outputs[1:]:
            self.assertEqual(set(output), set(outputs[0]))
            self.assertEqual(output, outputs[0])

    def testRegenerationRefusesNonemptyTarget(self):
        target = self.root / 'data/Target profiles'
        target.mkdir(parents=True)
        (target / 'keep.json').write_bytes(b'keep exactly\x00\xff')
        before = hashDirectory(target)
        previous = Path.cwd()
        self.addCleanup(os.chdir, previous)
        os.chdir(self.root)
        output = io.StringIO()
        with (
            patch.dict('sys.modules', {'Configuration.configuration': self.configuration}),
            patch('extractProfilesFromJSONs.RLMSProfileExtractor') as constructor,
            redirect_stdout(output),
        ):
            self.assertNotEqual(extractProfilesFromJSONs.main(), 0)
        self.assertEqual(hashDirectory(target), before)
        self.assertIn('архивируйте и переместите', output.getvalue())
        constructor.assert_not_called()

    def testRegenerationWiringTemporaryExtractionAndSortedYears(self):
        waves = self.root / 'data/RLMS waves'
        waves.mkdir(parents=True)
        for year in ('2021', '2020'):
            with ZipFile(waves / f'{year}.zip', 'w') as archive:
                archive.writestr('a.json', b'{}')
        before = hashDirectory(waves)
        previous = Path.cwd()
        self.addCleanup(os.chdir, previous)
        os.chdir(self.root)
        sources = []
        years = []

        def generate(source, target, sampleSize, adultAge):
            self.assertEqual((sampleSize, adultAge), (100, 18))
            self.assertFalse(source.is_relative_to(waves))
            self.assertEqual((source / 'a.json').read_bytes(), b'{}')
            target.mkdir(parents=True)
            (target / 'a.json').write_bytes(b'{}')
            sources.append(source)
            years.append(target.name)

        with (
            patch.dict('sys.modules', {'Configuration.configuration': self.configuration}),
            patch('extractProfilesFromJSONs.RLMSProfileExtractor') as constructor,
            redirect_stdout(io.StringIO()),
        ):
            constructor.return_value.generateAndSaveProfilesFromRLMS.side_effect = generate
            self.assertEqual(extractProfilesFromJSONs.main(), 0)
        args = constructor.call_args.args
        self.assertEqual(len(args), 4)
        self.assertIsInstance(args[0], SimpleRLMSProfileConverter)
        self.assertEqual(args[1:], ('regular', 'durable', 'services'))
        self.assertEqual(years, ['2020', '2021'])
        self.assertEqual(hashDirectory(waves), before)
        self.assertEqual({p.name for p in waves.iterdir()}, {'2020.zip', '2021.zip'})
        self.assertTrue(all(not path.exists() for path in sources))

    def testManifestHashesAndByteChange(self):
        waves = self.root / 'waves'
        profiles = self.root / 'profiles'
        waves.mkdir()
        contents = {'2020/b.json': b'B', '2020/a.json': b'A', '2021/c.json': b'C'}
        for name, data in contents.items():
            path = profiles / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

        def digest(files):
            pairs = ''.join(
                f'{name}:{hashlib.sha256(data).hexdigest()}\n'
                for name, data in sorted(files.items())
            )
            return hashlib.sha256(pairs.encode()).hexdigest()

        result = readRespondentData(waves, profiles, 100)
        self.assertEqual(result['profiles_sha256'], digest(contents))
        self.assertEqual(
            result['profiles_sha256_by_year'],
            {
                year: digest({Path(n).name: b for n, b in contents.items() if n.startswith(year)})
                for year in ('2020', '2021')
            },
        )
        self.assertIsNone(result['seed42_verification'])
        self.assertIsNone(result['extractor_commit'])
        self.assertIn('вне репозитория', result['provenance_status'])
        self.assertIn('profiles_sha256_by_year', result['provenance_status'])
        originalRglob = Path.rglob
        with patch.object(
            Path,
            'rglob',
            lambda folder, pattern: iter(reversed(list(originalRglob(folder, pattern)))),
        ):
            reordered = readRespondentData(waves, profiles, 100)
        self.assertEqual(reordered['profiles_sha256'], result['profiles_sha256'])
        self.assertEqual(reordered['profiles_sha256_by_year'], result['profiles_sha256_by_year'])
        (profiles / '2020/a.json').write_bytes(b'Z')
        changed = readRespondentData(waves, profiles, 100)
        self.assertNotEqual(changed['profiles_sha256'], result['profiles_sha256'])
        self.assertNotEqual(
            changed['profiles_sha256_by_year']['2020'], result['profiles_sha256_by_year']['2020']
        )
        self.assertEqual(
            changed['profiles_sha256_by_year']['2021'], result['profiles_sha256_by_year']['2021']
        )

    def testVerificationOutputRequiredAndManifestDirectoryRefused(self):
        forbidden = Path(checkProfilesSeed.__file__).parent / 'data/run_manifests/check.json'
        for arguments in ([], ['--output', str(forbidden)]):
            with (
                patch('sys.argv', ['checkProfilesSeed.py', *arguments]),
                patch('checkProfilesSeed.verifyProfiles') as verify,
                patch('sys.stderr', new_callable=io.StringIO),
                self.assertRaises(SystemExit) as error,
            ):
                checkProfilesSeed.main()
            self.assertEqual(error.exception.code, 2)
            verify.assert_not_called()

    def testVerificationWritesRequestedOutputAndExitCode(self):
        output = self.root / 'verification.json'
        for verdict, code in (('verified', 0), ('failed', 1)):
            result = {'verdict': verdict, 'inputs_unchanged': True}
            with (
                patch('sys.argv', ['checkProfilesSeed.py', '--output', str(output)]),
                patch('checkProfilesSeed.verifyProfiles', return_value=result),
                redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(checkProfilesSeed.main(), code)
            self.assertEqual(json.loads(output.read_text()), result)

    def testIndependentExtractionsOrderAndFailure(self):
        waves = self.root / 'data/RLMS waves'
        profiles = self.root / 'data/Target profiles/2020'
        waves.mkdir(parents=True)
        profiles.mkdir(parents=True)
        (profiles / 'a.json').write_bytes(b'A')
        (self.root / 'RLMSLogic').mkdir()
        (self.root / 'RLMSLogic/RLMSProfileExtractor.py').write_bytes(b'fixture')
        with ZipFile(waves / '2020.zip', 'w') as archive:
            archive.writestr('a.json', b'A')
            archive.writestr('b.json', b'B')
        for defect in ('none', 'content', 'name', 'input'):
            extractionOrders = []
            sources = []
            originalExtract = ZipFile.extractall

            def extract(archive, path, members, orders=extractionOrders, original=originalExtract):
                orders.append([member.filename for member in members])
                return original(archive, path, members)

            def generate(
                extractor,
                source,
                target,
                sample_size,
                adultAge,
                seed=42,
                sourcePaths=sources,
                failure=defect,
            ):
                sourcePaths.append(source)
                target.mkdir()
                second = len(sourcePaths) == 2
                name = 'other.json' if second and failure == 'name' else 'a.json'
                data = b'Z' if second and failure == 'content' else b'A'
                (target / name).write_bytes(data)
                if second and failure == 'input':
                    (profiles / 'a.json').write_bytes(b'changed input')

            with (
                patch.dict('sys.modules', {'Configuration.configuration': self.configuration}),
                patch.object(RLMSProfileExtractor, '__init__', return_value=None),
                patch.object(RLMSProfileExtractor, 'generateAndSaveProfilesFromRLMS', generate),
                patch('checkProfilesSeed.subprocess.check_output', return_value='fixture-commit'),
                patch.object(ZipFile, 'extractall', extract),
                redirect_stdout(io.StringIO()),
            ):
                result = checkProfilesSeed.verifyProfiles(self.root, ['2020'])
            self.assertEqual(extractionOrders, [['a.json', 'b.json'], ['b.json', 'a.json']])
            self.assertEqual(len(set(sources)), 2)
            self.assertTrue(all(not source.exists() for source in sources))
            expected = 'verified' if defect == 'none' else 'failed'
            self.assertEqual(result['verdict'], expected)
            year = result['years']['2020']
            self.assertEqual(year['verdict'], expected)
            self.assertEqual(
                year['independent_extractions']['verdict'],
                'failed' if defect in ('content', 'name') else 'verified',
            )
            self.assertEqual(result['inputs_unchanged'], defect != 'input')
