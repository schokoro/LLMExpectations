import asyncio
import json
import os
from dataclasses import fields
from unittest import TestCase
from unittest.mock import Mock, patch

import httpx
from openai import AsyncOpenAI, InternalServerError, PermissionDeniedError

from NewsLogic.NewsDocument import NewsDocument
from NewsLogic.NewsRagConfiguration import (
    NewsRagConfiguration,
    configHashExcludedFields,
    configHashFields,
    defaultAxisOrder,
    defaultAxisQueries,
)
from NewsLogic.NewsSummarizer import NewsSummarizer
from NewsLogic.PinnedOpenRouterClient import PinnedOpenRouterClient


class TestPinnedOpenRouterClient(TestCase):
    def setUp(self):
        self.configuration = NewsRagConfiguration()
        self.bodies = []
        self.clients = []
        environment = patch.dict(os.environ, {'OPENROUTER_API_KEY': 'dummy-for-test'})
        environment.start()
        self.addCleanup(environment.stop)
        constructor = patch(
            'NewsLogic.PinnedOpenRouterClient.AsyncOpenAI', side_effect=self.createClient
        )
        constructor.start()
        self.addCleanup(constructor.stop)

    def captureRequest(self, request: httpx.Request) -> httpx.Response:
        self.bodies.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                'id': 'test-completion',
                'object': 'chat.completion',
                'created': 0,
                'model': self.configuration.summarizeModel,
                'choices': [
                    {
                        'index': 0,
                        'message': {'role': 'assistant', 'content': 'Тестовое саммари'},
                        'finish_reason': 'stop',
                    }
                ],
                'usage': {'prompt_tokens': 5, 'completion_tokens': 3, 'total_tokens': 8},
            },
        )

    def createClient(self, **kwargs) -> AsyncOpenAI:
        client = AsyncOpenAI(
            **kwargs,
            http_client=httpx.AsyncClient(
                transport=httpx.MockTransport(self.captureRequest), trust_env=False
            ),
        )
        # SDK иначе определяет платформу в потоке, зависающем в песочнице.
        # На сериализацию тела и транспорт это не влияет.
        client._platform = 'Linux'
        self.clients.append(client)
        return client

    def runAsync(self, action):
        async def run():
            try:
                return await action()
            finally:
                for client in self.clients:
                    await client.close()

        return asyncio.run(run())

    def assertPinnedBody(self, body):
        self.assertEqual([self.configuration.summarizeProvider], body['provider']['order'])
        self.assertIs(False, body['provider']['allow_fallbacks'])
        self.assertEqual(self.configuration.summarizeModel, body['model'])
        self.assertEqual(self.configuration.summarizeTemperature, body['temperature'])

    def test_both_stages_send_pinned_http_bodies(self):
        summarizer = NewsSummarizer(self.configuration, Mock())
        retrieved = {
            axis: [
                NewsDocument(
                    1, 'test', '2022-03-20T12:00:00+00:00', 1, 'Цены растут.', axis, 1, 0.9
                )
            ]
            for axis in self.configuration.axes
        }

        async def run():
            axes = await summarizer.buildAxisSummaries(retrieved)
            self.assertEqual([], axes.failed_axes)
            self.assertEqual(len(retrieved), len(self.bodies))
            for body in self.bodies:
                self.assertPinnedBody(body)
            result = await summarizer.buildMetaSummary(axes.axis_summaries)
            self.assertEqual(len(retrieved) + 1, len(self.bodies))
            self.assertPinnedBody(self.bodies[-1])
            self.assertEqual('Тестовое саммари', result.meta)

        self.runAsync(run)

    def test_preflight_sends_one_minimal_pinned_request(self):
        summarizer = NewsSummarizer(self.configuration, Mock())
        response = self.runAsync(summarizer.preflight)
        self.assertEqual(1, len(self.bodies))
        self.assertPinnedBody(self.bodies[0])
        self.assertEqual(1, self.bodies[0]['max_tokens'])
        self.assertEqual([{'role': 'user', 'content': 'Ответь: OK'}], self.bodies[0]['messages'])
        self.assertEqual(8, response.usage.total_tokens)
        self.assertEqual(0, self.clients[0].max_retries)

    def test_failed_preflight_does_not_retry_or_drop_pin(self):
        for status, errorType in ((403, PermissionDeniedError), (503, InternalServerError)):

            def rejectRequest(request, responseStatus=status):
                self.bodies.append(json.loads(request.content))
                return httpx.Response(
                    responseStatus, json={'error': {'message': 'fixture failure'}}
                )

            self.bodies.clear()
            with patch.object(self, 'captureRequest', side_effect=rejectRequest):
                summarizer = NewsSummarizer(self.configuration, Mock())
                with self.assertRaises(errorType):
                    self.runAsync(summarizer.preflight)
            self.assertEqual(1, len(self.bodies))
            self.assertPinnedBody(self.bodies[0])

    def test_extra_body_is_preserved_without_mutating_the_caller(self):
        extraBody = {'usage': {'include': True}}

        async def run():
            client = PinnedOpenRouterClient(
                self.configuration.summarizeProvider, api_key='dummy-for-test'
            )
            await client.chat.completions.create(
                model=self.configuration.summarizeModel,
                messages=[{'role': 'user', 'content': 'Тест'}],
                temperature=self.configuration.summarizeTemperature,
                extra_body=extraBody,
            )

        self.runAsync(run)
        self.assertEqual(1, len(self.bodies))
        self.assertPinnedBody(self.bodies[0])
        self.assertEqual({'include': True}, self.bodies[0]['usage'])
        self.assertEqual({'usage': {'include': True}}, extraBody)

    def test_caller_cannot_override_provider(self):
        async def run():
            client = PinnedOpenRouterClient(
                self.configuration.summarizeProvider, api_key='dummy-for-test'
            )
            with self.assertRaisesRegex(ValueError, 'provider'):
                await client.chat.completions.create(
                    extra_body={'provider': {'order': ['other'], 'allow_fallbacks': True}}
                )

        self.runAsync(run)
        self.assertEqual([], self.bodies)

    def test_empty_or_missing_provider_fails_before_client_creation(self):
        for provider in ('', '   ', None):
            with self.assertRaisesRegex(ValueError, 'Провайдер'):
                PinnedOpenRouterClient(provider, api_key='dummy-for-test')
        with self.assertRaises(TypeError):
            PinnedOpenRouterClient(api_key='dummy-for-test')
        self.assertEqual([], self.clients)

    def test_hash_field_partition_covers_configuration_without_overlap(self):
        included = set(configHashFields)
        excluded = set(configHashExcludedFields)
        self.assertEqual(set(), included & excluded)
        self.assertEqual(
            {item.name for item in fields(NewsRagConfiguration)},
            included | excluded,
            'Новое поле требует решения: включить в config_hash или явно исключить',
        )

    def test_axis_order_covers_all_queries(self):
        self.assertEqual(set(defaultAxisQueries), set(defaultAxisOrder))
