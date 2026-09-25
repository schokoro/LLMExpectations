"""Сверка профилей и перенос сводки проверяются только на временных данных."""

import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
from zipfile import ZipFile

from checkProfilesSeed import aggregateDigest, compareProfiles, hashDirectory, verifyProfiles
from NewsLogic.RunManifest import readRespondentData


class ProfilesSeedTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.original = self.root / 'original'
        self.extracted = self.root / 'extracted'
        for folder in (self.original, self.extracted):
            folder.mkdir()
            (folder / 'a.json').write_bytes(b'{"age": 18}')
            (folder / 'b.json').write_bytes(b'{"age": 21}')

    def compare(self):
        output = io.StringIO()
        with redirect_stdout(output):
            result = compareProfiles('2020', self.original, self.extracted)
        return result, output.getvalue()

    def testIdentical(self):
        result, _ = self.compare()
        self.assertEqual(result['verdict'], 'verified')
        self.assertEqual(result['matched_count'], 2)
        self.assertEqual(result['content_different_count'], 0)
        self.assertEqual(result['profile_counts'], {'original': 2, 'extracted': 2})
        self.assertEqual(
            result['aggregate_sha256']['original'], result['aggregate_sha256']['extracted']
        )

    def testDifferentContentNamesYearAndFile(self):
        (self.extracted / 'a.json').write_bytes(b'{"age": 19}')
        result, output = self.compare()
        self.assertEqual(result['verdict'], 'failed')
        self.assertEqual(result['matched_count'], 1)
        self.assertEqual(result['content_different_count'], 1)
        self.assertEqual(result['content_different'], ['a.json'])
        self.assertEqual(result['year'], '2020')
        self.assertIn('2020: Отличается содержимое (1): a.json', output)
        self.assertNotEqual(
            result['aggregate_sha256']['original'], result['aggregate_sha256']['extracted']
        )

    def testOneSidedFiles(self):
        (self.extracted / 'a.json').unlink()
        (self.extracted / 'c.json').write_bytes(b'{}')
        result, output = self.compare()
        self.assertEqual(result['verdict'], 'failed')
        self.assertEqual(result['original_only'], ['a.json'])
        self.assertEqual(result['extracted_only'], ['c.json'])
        self.assertEqual(result['matched_count'], 1)
        self.assertEqual(result['content_different_count'], 0)
        self.assertIn('2020: Только в исходных (1): a.json', output)
        self.assertIn('2020: Только в повторных (1): c.json', output)

    def testDigestIndependentOfIterationOrder(self):
        hashes = hashDirectory(self.original)
        ordered = dict(sorted(hashes.items()))
        reversedHashes = dict(reversed(list(ordered.items())))
        self.assertEqual(aggregateDigest(ordered), aggregateDigest(reversedHashes))
        reversedHashes['a.json'] = 'changed'
        self.assertNotEqual(aggregateDigest(ordered), aggregateDigest(reversedHashes))

    def testManifestSummaryOnly(self):
        comparison, _ = self.compare()
        verification = {
            'seed': 42,
            'extractor_commit': 'commit-recorded-by-check',
            'verdict': 'verified',
            'checked_at_utc': '2026-09-22T12:00:00+00:00',
            'scope': 'selected_years',
            'years': {'2020': comparison},
        }
        path = self.root / 'verification.json'
        path.write_text(json.dumps(verification))
        result = readRespondentData(self.original, self.extracted, 100, path)
        self.assertEqual(result['extractor_seed'], 42)
        self.assertEqual(result['extractor_commit'], verification['extractor_commit'])
        self.assertEqual(
            result['seed42_verification'],
            {
                'verdict': 'verified',
                'checked_at_utc': verification['checked_at_utc'],
                'scope': 'selected_years',
                'aggregate_sha256': {'2020': comparison['aggregate_sha256']},
            },
        )
        self.assertNotIn('file_sha256', json.dumps(result))
        self.assertNotIn('file_sha256', json.dumps(result['seed42_verification']))
        verification['verdict'] = 'failed'
        path.write_text(json.dumps(verification))
        failed = readRespondentData(self.original, self.extracted, 100, path)
        self.assertEqual(failed['seed42_verification']['verdict'], 'failed')
        self.assertIn('failed', failed['provenance_status'])

    def testMissingResultIsExplicitlyUnverified(self):
        result = readRespondentData(self.original, self.extracted, 100, self.root / 'absent.json')
        self.assertEqual(result['extractor_seed'], 42)
        self.assertIsNone(result['extractor_commit'])
        self.assertIsNone(result['seed42_verification'])
        self.assertIn('не проверено', result['provenance_status'])
        self.assertIn('отсутствует', result['provenance_status'])

    def testSyntheticArchiveDefaultSeedAndCleanup(self):
        waves = self.root / 'data/RLMS waves'
        profiles = self.root / 'data/Target profiles/2020'
        waves.mkdir(parents=True)
        profiles.mkdir(parents=True)
        (self.root / 'RLMSLogic').mkdir()
        (self.root / 'RLMSLogic/RLMSProfileExtractor.py').write_text('synthetic')
        (profiles / 'a.json').write_bytes(b'{}')
        with ZipFile(waves / '2020.zip', 'w') as archive:
            archive.writestr('a.json', b'{}')
        # Конфигурация production читает ключи при импорте; фикстуре нужны только карты.
        configuration = SimpleNamespace(
            regularGoods='regular', durableGoods='durable', services='services'
        )
        configurationPatch = patch.dict(
            'sys.modules', {'Configuration.configuration': configuration}
        )
        configurationPatch.start()
        self.addCleanup(configurationPatch.stop)
        before = hashDirectory(self.root / 'data')
        temporaryPaths = []

        def generate(extractor, source, target, sample_size, adultAge, seed=42):
            self.assertEqual((sample_size, adultAge, seed), (100, 18, 42))
            self.assertEqual((source / 'a.json').read_bytes(), b'{}')
            temporaryPaths.append(source.parent.parent)
            target.mkdir()
            (target / 'a.json').write_bytes(b'{}')

        with (
            patch(
                'RLMSLogic.RLMSProfileExtractor.RLMSProfileExtractor.__init__', return_value=None
            ) as constructor,
            patch(
                'RLMSLogic.RLMSProfileExtractor.RLMSProfileExtractor.generateAndSaveProfilesFromRLMS',
                new=generate,
            ),
            patch('checkProfilesSeed.subprocess.check_output', return_value='fixture-commit\n'),
            redirect_stdout(io.StringIO()),
        ):
            result = verifyProfiles(self.root, ['2020'])
            self.assertEqual(len(constructor.call_args.args), 4)
        self.assertEqual(result['verdict'], 'verified')
        self.assertEqual(result['seed'], 42)
        self.assertEqual(result['extractor_commit'], 'fixture-commit')
        self.assertTrue(result['inputs_unchanged'])
        self.assertEqual(hashDirectory(self.root / 'data'), before)
        self.assertTrue(temporaryPaths)
        self.assertTrue(all(not path.exists() for path in temporaryPaths))

        def fail(extractor, source, target, sample_size, adultAge, seed=42):
            temporaryPaths.append(source.parent.parent)
            raise ValueError('Синтетический отказ')

        with (
            patch(
                'RLMSLogic.RLMSProfileExtractor.RLMSProfileExtractor.__init__', return_value=None
            ),
            patch(
                'RLMSLogic.RLMSProfileExtractor.RLMSProfileExtractor.generateAndSaveProfilesFromRLMS',
                new=fail,
            ),
            patch('checkProfilesSeed.subprocess.check_output', return_value='fixture-commit\n'),
        ):
            failed = verifyProfiles(self.root)
        self.assertEqual(failed['verdict'], 'failed')
        self.assertIn('Синтетический отказ', failed['error'])
        self.assertTrue(failed['inputs_unchanged'])
        self.assertTrue(all(not path.exists() for path in temporaryPaths))
