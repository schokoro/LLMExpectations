import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call

import pytest
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    InternalServerError,
    PermissionDeniedError,
    RateLimitError,
)
from openai.types.chat import ChatCompletion

from NewsLogic.NewsRagConfiguration import NewsRagConfiguration
from NewsLogic.RunManifest import RunManifest, providerNameMatchesPin
from runMySeriesWithNews import preflightRetryDelays, runPreflight


@pytest.fixture
def responseData():
    path = Path(__file__).parent / 'fixtures' / 'openrouter_preflight_response.json'
    return json.loads(path.read_text(encoding='utf-8'))


@pytest.fixture
def setupPreflight(tmp_path, responseData):
    configuration = replace(NewsRagConfiguration(), summarizeProvider='deepinfra/fp8')
    manifest = RunManifest(
        'fixture',
        configuration,
        'fixture',
        'https://invalid',
        tmp_path / 'results',
        manifestFolder=tmp_path / 'manifests',
    )
    response = ChatCompletion(**responseData, id='fixture', created=0)
    provider = SimpleNamespace(
        configuration=configuration,
        summarizer=SimpleNamespace(preflight=AsyncMock(return_value=response)),
        prepare=Mock(),
    )
    return provider, manifest, Mock()


@pytest.mark.parametrize(
    'served,pin,expected',
    [
        ('DeepInfra', 'deepinfra/fp8', True),
        (' dEePiNfRa ', ' DeepInfra /fp8', True),
        ('DeepInfra', 'deepinfra', True),
        ('STRASSE', 'straße/fp8', True),
        ('Together', 'deepinfra/fp8', False),
        ('DeepInfra Turbo', 'deepinfra/fp8', False),
        ('deepinfra/bf16', 'deepinfra/fp8', False),
        ('deepinfra/fp8', 'deepinfra/fp8', False),
        ('Deep', 'deepinfra/fp8', False),
        ('', 'deepinfra/fp8', False),
        (42, 'deepinfra/fp8', False),
        (None, 'deepinfra/fp8', False),
    ],
)
def test_provider_name_match(served, pin, expected):
    assert providerNameMatchesPin(served, pin) is expected


def test_preflight_real_fixture(setupPreflight):
    provider, manifest, sleep = setupPreflight
    summary = manifest.data['models']['summarization']
    assert summary['provider_pin_verification_status'] == 'not_checked'
    assert summary['quantization_verification_status'] == 'not_checked'
    assert summary['configured_quantization'] == 'fp8'
    runPreflight(provider, manifest, sleep=sleep)
    provider.prepare()
    provider.prepare.assert_called_once()
    provider.summarizer.preflight.assert_awaited_once()
    sleep.assert_not_called()
    assert summary['provider_pin_verification'] == 'DeepInfra'
    assert summary['provider_pin_verification_status'] == 'provider_name_verified'
    assert summary['quantization_verification_status'] == 'not_reported'
    assert manifest.data['preflight']['attempts'] == 1
    assert manifest.data['preflight']['transient_errors'] == []
    assert manifest.data['preflight']['usage_complete'] is True
    assert manifest.data['preflight']['usage_note'] is None


def test_preflight_pin_without_quantization(tmp_path, responseData):
    configuration = replace(NewsRagConfiguration(), summarizeProvider='deepinfra')
    manifest = RunManifest('fixture', configuration, 'fixture', '', tmp_path)
    assert manifest.data['models']['summarization']['configured_quantization'] is None
    manifest.recordPreflight(ChatCompletion(**responseData, id='fixture', created=0))
    assert (
        manifest.data['models']['summarization']['quantization_verification_status']
        == 'not_reported'
    )


@pytest.mark.parametrize(
    'served',
    [
        'Together',
        'DeepInfra Turbo',
        'deepinfra/bf16',
        'deepinfra/fp8',
        '',
        42,
    ],
)
def test_preflight_mismatch_no_retry(setupPreflight, responseData, served):
    provider, manifest, sleep = setupPreflight
    responseData['provider'] = served
    provider.summarizer.preflight.return_value = ChatCompletion(
        **responseData,
        id='fixture',
        created=0,
    )
    with pytest.raises(RuntimeError, match='несовпадение'), manifest:
        runPreflight(provider, manifest, sleep=sleep)
        provider.prepare()
    provider.prepare.assert_not_called()
    provider.summarizer.preflight.assert_awaited_once()
    sleep.assert_not_called()
    summary = manifest.data['models']['summarization']
    assert summary['provider_pin_verification_status'] == 'mismatch'
    assert summary['provider_pin_verification'] == served
    assert manifest.data['preflight']['attempts'] == 1
    assert manifest.data['preflight']['transient_errors'] == []


def makeError(errorType):
    if issubclass(errorType, APIConnectionError):
        return errorType(request=Mock())
    status = 503 if errorType is InternalServerError else errorType.status_code
    return errorType('SECRET', response=Mock(status_code=status), body='SECRET')


@pytest.mark.parametrize(
    'errorType',
    [
        RateLimitError,
        InternalServerError,
        APIConnectionError,
        APITimeoutError,
    ],
)
def test_preflight_transient_then_success(setupPreflight, errorType):
    provider, manifest, sleep = setupPreflight
    response = provider.summarizer.preflight.return_value
    provider.summarizer.preflight.side_effect = [makeError(errorType), response]
    runPreflight(provider, manifest, sleep=sleep)
    provider.prepare()
    provider.prepare.assert_called_once()
    assert provider.summarizer.preflight.await_count == 2
    sleep.assert_called_once_with(preflightRetryDelays[0])
    assert manifest.data['preflight']['attempts'] == 2
    assert manifest.data['preflight']['transient_errors'] == [errorType.__name__]
    assert manifest.data['preflight']['outcome'] == 'succeeded'
    assert manifest.data['preflight']['usage_complete'] is False
    assert 'неудачные попытки без usage' in manifest.data['preflight']['usage_note']
    assert manifest.data['preflight']['usage']['total_tokens'] == response.usage.total_tokens
    assert manifest.data['totals']['usage_complete'] is False
    manifest._updateUsage()
    assert manifest.data['totals']['usage_complete'] is False
    assert 'SECRET' not in json.dumps(manifest.data)


def test_preflight_transient_exhaustion(setupPreflight):
    provider, manifest, sleep = setupPreflight
    errorTypes = [RateLimitError, InternalServerError, APIConnectionError]
    provider.summarizer.preflight.side_effect = [makeError(kind) for kind in errorTypes]
    with pytest.raises(RuntimeError, match='Временные.*3'), manifest:
        runPreflight(provider, manifest, sleep=sleep)
        provider.prepare()
    provider.prepare.assert_not_called()
    assert provider.summarizer.preflight.await_count == 3
    assert sleep.call_args_list == [call(delay) for delay in preflightRetryDelays]
    preflight = manifest.data['preflight']
    assert preflight['attempts'] == 3
    assert preflight['transient_errors'] == [kind.__name__ for kind in errorTypes]
    assert preflight['error_type'] == 'APIConnectionError'
    assert preflight['outcome'] == 'failed'
    assert preflight['usage_complete'] is False
    assert 'неудачные попытки без usage' in preflight['usage_note']
    assert manifest.data['totals']['usage_complete'] is False
    assert 'SECRET' not in manifest.path.read_text()


@pytest.mark.parametrize(
    'error',
    [
        makeError(AuthenticationError),
        makeError(PermissionDeniedError),
        APIStatusError('SECRET', response=Mock(status_code=400), body='SECRET'),
        ValueError('SECRET'),
        KeyboardInterrupt(),
        SystemExit(),
    ],
)
def test_preflight_permanent_no_retry(setupPreflight, error):
    provider, manifest, sleep = setupPreflight
    provider.summarizer.preflight.side_effect = error
    expected = RuntimeError if isinstance(error, Exception) else type(error)
    with pytest.raises(expected) as caught, manifest:
        runPreflight(provider, manifest, sleep=sleep)
        provider.prepare()
    if not isinstance(error, Exception):
        assert caught.value is error
    provider.prepare.assert_not_called()
    provider.summarizer.preflight.assert_awaited_once()
    sleep.assert_not_called()
    assert manifest.data['preflight']['attempts'] == 1
    assert manifest.data['preflight']['transient_errors'] == []
    assert manifest.data['preflight']['error_type'] == type(error).__name__
    assert manifest.data['preflight']['usage_complete'] is False
    assert 'SECRET' not in manifest.path.read_text()
