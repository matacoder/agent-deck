import json
import tempfile
import time
import unittest
from pathlib import Path
from integrations.lmstudio import LMStudio
from integrations.relay import Measurements, private_write


class LocalActivityTests(unittest.TestCase):
    def test_stream_phases_and_chunks_do_not_invent_token_counts(self):
        sample = Measurements(time.monotonic())
        self.assertEqual(sample.phase, 'waiting')
        sample.feed(b'data: {"type":"content_block_delta","delta":{"thinking":"private reasoning"}}\n')
        self.assertEqual(sample.phase, 'thinking')
        self.assertEqual(sample.chunks, 1)
        self.assertNotIn('output_tokens', sample.result())
        self.assertNotIn('tokens_per_second', sample.result())
        sample.feed(b'data: {"type":"content_block_delta","delta":{"partial_json":"{"}}\n')
        self.assertEqual(sample.phase, 'tool')
        sample.feed(b'data: {"type":"content_block_delta","delta":{"text":"answer"}}\n')
        self.assertEqual(sample.phase, 'generating')
        self.assertEqual(sample.chunks, 3)
        self.assertNotIn('private reasoning', json.dumps(sample.result()))

    def test_status_reads_other_process_metrics_and_expires_stale_activity(self):
        with tempfile.TemporaryDirectory() as directory:
            service = LMStudio(directory)
            profile = service.save({'name': 'Local', 'url': 'http://localhost:1234'})
            writer = LMStudio(directory)
            writer.record(profile['id'], 'model', {'output_tokens': 20})
            path = Path(directory) / 'live-requests' / 'request.json'
            private_write(path, {'profile': profile['id'], 'phase': 'waiting', 'request_time_seconds': 2, 'updated_at': time.time() - 5})
            status = service.status()['profiles'][0]
            self.assertEqual(status['performance']['output_tokens'], 20)
            self.assertGreaterEqual(status['activity'][0]['request_time_seconds'], 7)
            private_write(path, {'profile': profile['id'], 'updated_at': time.time() - 700})
            self.assertEqual(service.status()['profiles'][0]['activity'], [])
