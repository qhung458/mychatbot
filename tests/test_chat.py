import asyncio
from pathlib import Path
import tempfile
import threading
import unittest

from fastapi.testclient import TestClient

from app.config import Settings
from app.gemini import Chunk, Gemini
from app.main import create_app
from app.store import ChatError, Store


class ProviderError(Exception):
    code = 429


class FakeGemini:
    """Test double only. Production never substitutes this for Gemini."""
    def __init__(self, mode='normal'):
        self.mode = mode
        self.calls = []
        self.closed_stream = False
        self.started = threading.Event()

    async def count(self, text):
        return len(text)  # Predictable units, not a claimed real Gemini tokenizer.

    async def stream(self, history, text, allowance, prompt):
        self.calls.append(dict(history=history, allowance=allowance, prompt=prompt, text=text))
        self.started.set()
        try:
            if self.mode == 'quota':
                raise ProviderError('A_SECRET_KEY_MUST_NOT_LEAK')
            if self.mode == 'network':
                raise TimeoutError('unknown upstream usage')
            if self.mode == 'slow':
                await asyncio.sleep(60)
            if self.mode == 'limit':
                yield Chunk(text='x' * allowance, output_tokens=allowance, finish='MAX_TOKENS')
                raise AssertionError('Consumer continued after cap')
            if self.mode == 'no_usage':
                yield Chunk(text='partial')
                return
            yield Chunk(text='ok', output_tokens=2)
            yield Chunk(text='!', output_tokens=3, finish='STOP')
        finally:
            self.closed_stream = True

    async def close(self):
        pass


class ChatTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.settings = Settings(database=Path(self.temp.name) / 'chat.db', system_prompt='test prompt')
        self.provider = FakeGemini()
        self.client = TestClient(create_app(self.settings, self.provider))
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def new(self):
        response = self.client.post('/api/chats')
        self.assertEqual(response.status_code, 201)
        return response.json()

    def get(self, chat):
        return self.client.get(f"/api/chats/{chat['id']}").json()

    def send(self, chat, text):
        return self.client.post(f"/api/chats/{chat['id']}/messages", json={'text': text})

    def test_chat_isolation_and_budget_not_recharged_for_history(self):
        a, b = self.new(), self.new()
        self.assertEqual(a['remaining'], 1500)
        self.assertEqual(a['messages'], [])
        self.assertNotIn('system_prompt', a)
        response = self.send(a, 'hello')
        self.assertIn('event: delta', response.text)
        self.assertIn('event: done', response.text)
        self.assertEqual(self.get(a)['remaining'], 1492)  # 1500 - 5 - 3
        self.send(a, 'next')
        self.assertEqual(self.get(a)['remaining'], 1485)  # only new 4 + 3
        self.assertEqual(len(self.provider.calls[1]['history']), 2)
        self.send(b, 'new')
        self.assertEqual(self.provider.calls[2]['history'], [])
        self.assertEqual(self.get(b)['remaining'], 1494)

    def test_output_cap_is_remaining_after_input_and_stops_iterator(self):
        self.provider.mode = 'limit'
        chat = self.new()
        response = self.send(chat, 'a' * 1490)
        self.assertEqual(self.provider.calls[0]['allowance'], 10)
        self.assertEqual(self.get(chat)['remaining'], 0)
        self.assertEqual(self.get(chat)['messages'][-1]['status'], 'budget')
        self.assertTrue(self.provider.closed_stream)
        self.assertNotIn('event: error', response.text)
        self.assertEqual(self.send(chat, 'more').status_code, 409)
        self.assertEqual(len(self.provider.calls), 1)

    def test_input_can_exhaust_budget_without_calling_generation(self):
        chat = self.new()
        self.send(chat, 'a' * 1500)
        self.assertEqual(self.get(chat)['remaining'], 0)
        self.assertEqual(self.provider.calls, [])

    def test_reject_oversized_input_without_consuming_budget(self):
        chat = self.new()
        response = self.send(chat, 'a' * 1501)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.get(chat)['remaining'], 1500)
        self.assertEqual(self.get(chat)['messages'], [])

    def test_draft_count_does_not_consume_tokens(self):
        chat = self.new()
        count = self.client.post('/api/tokens', json={'text': 'example'}).json()
        self.assertEqual(count, {'tokens': 7, 'exact': True})
        self.assertEqual(self.get(chat)['remaining'], 1500)

    def test_quota_error_refunds_and_hides_provider_error(self):
        self.provider.mode = 'quota'
        chat = self.new()
        response = self.send(chat, 'hello')
        self.assertIn('event: error', response.text)
        self.assertNotIn('A_SECRET_KEY', response.text)
        self.assertEqual(self.get(chat)['remaining'], 1500)
        self.assertFalse(self.get(chat)['active'])
        self.assertEqual(self.get(chat)['messages'], [])

    def test_missing_usage_does_not_refund_uncertain_output(self):
        self.provider.mode = 'no_usage'
        chat = self.new()
        response = self.send(chat, 'hi')
        self.assertEqual(self.get(chat)['remaining'], 0)
        self.assertIn('"uncertain": true', response.text)

    def test_network_timeout_before_first_chunk_keeps_reservation(self):
        self.provider.mode = 'network'
        chat = self.new()
        response = self.send(chat, 'hi')
        self.assertEqual(self.get(chat)['remaining'], 0)
        self.assertFalse(self.get(chat)['active'])
        self.assertIn('"uncertain": true', response.text)

    def test_stop_cancels_pending_upstream_read_and_duplicate_send_rejected(self):
        self.provider.mode = 'slow'
        chat = self.new()
        results = []
        sender = threading.Thread(target=lambda: results.append(self.send(chat, 'hi')))
        sender.start()
        self.assertTrue(self.provider.started.wait(timeout=3))
        self.assertEqual(self.send(chat, 'duplicate').status_code, 409)
        stop = self.client.post(f"/api/chats/{chat['id']}/stop")
        self.assertEqual(stop.status_code, 200)
        sender.join(timeout=4)
        self.assertFalse(sender.is_alive(), 'Stop did not interrupt upstream read')
        self.assertTrue(self.provider.closed_stream)
        self.assertEqual(self.get(chat)['messages'][-1]['status'], 'stopped')
        self.assertEqual(self.get(chat)['remaining'], 0)
        self.assertEqual(len(self.provider.calls), 1)

    def test_cross_origin_mutations_blocked(self):
        response = self.client.post('/api/chats', headers={'Origin': 'https://untrusted.example'})
        self.assertEqual(response.status_code, 403)

    def test_local_html_static_and_security_headers(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Olympic AI Chatbot', response.text)
        self.assertIn("default-src 'self'", response.headers['content-security-policy'])
        self.assertEqual(self.client.get('/static/app.js').status_code, 200)
        self.assertEqual(self.client.get('/.env').status_code, 404)

    def test_unconfigured_and_no_billing_confirmation_block_generation(self):
        settings = Settings(database=Path(self.temp.name) / 'disabled.db', api_key='not-real', free_tier_confirmed=False)
        with TestClient(create_app(settings)) as client:
            self.assertFalse(client.get('/api/config').json()['ready'])
            self.assertNotIn('not-real', client.get('/api/config').text)
            chat = client.post('/api/chats').json()
            self.assertEqual(client.post(f"/api/chats/{chat['id']}/messages", json={'text': 'hi'}).status_code, 503)
            draft = client.post('/api/tokens', json={'text': 'tiếng Việt'}).json()
            self.assertFalse(draft['exact'])

    def test_sdk_config_applies_limit_and_minimal_thinking(self):
        # Construct without credentials or network to inspect actual SDK types.
        gemini = Gemini.__new__(Gemini)
        config = gemini.generation_config(17, 'system')
        self.assertEqual(config.max_output_tokens, 17)
        self.assertEqual(config.thinking_config.thinking_level.value, 'MINIMAL')
        self.assertIsNone(config.tools)

    def test_restart_retains_balances_and_recovers_pending_reservation(self):
        chat = self.new()
        self.send(chat, 'hello')
        store = Store(self.settings.database)
        self.assertEqual(store.get(chat['id'])['remaining'], 1492)
        turn = store.reserve(chat['id'], 'pending', 7)
        with self.assertRaises(ChatError):
            store.reserve(chat['id'], 'duplicate', 9)
        recovered = Store(self.settings.database).get(chat['id'])
        self.assertEqual(recovered['remaining'], 0)
        self.assertFalse(recovered['active'])
        self.assertEqual(recovered['messages'][-1]['status'], 'interrupted')


if __name__ == '__main__':
    unittest.main()
