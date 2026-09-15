#!/usr/bin/env python3
"""Pinned text-document pipeline remains tracked through cancelled ASGI work."""
import ast
import asyncio
import builtins
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

SOURCE = Path(sys.argv.pop(1))
sys.path.insert(0, str(SOURCE))
from lifecycle.middleware import ActivityMiddleware
from lifecycle.tracking import Tracker, install_thread_hooks


class DocumentTests(unittest.IsolatedAsyncioTestCase):
    async def test_pinned_document_processing_survives_request_cancellation(self):
        module = ast.parse((SOURCE / 'src/document_processor.py').read_text())
        # The text-document path requires no model. Leave all actual processing
        # functions intact; replace only the unused external model dependency.
        module.body = [node for node in module.body if not (
            isinstance(node, ast.ImportFrom) and node.module == 'src.llm_core')]
        scope = {'__name__': 'pinned_document_processor'}
        exec(compile(module, str(SOURCE / 'src/document_processor.py'), 'exec'), scope)
        calls = []
        tracker = Tracker('fixture', 'fixture', 'fixture', transport=lambda operation, data: calls.append(operation))
        install_thread_hooks()
        entered, release = threading.Event(), threading.Event()
        result = []
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'proof.txt'
            source.write_text('The acceptance canary is cobalt heron 731.\n')
            original_open = builtins.open
            def blocked_open(path, *args, **kwargs):
                if str(path) == str(source):
                    entered.set()
                    if not release.wait(5):
                        raise TimeoutError('fixture was not released')
                return original_open(path, *args, **kwargs)
            scope['open'] = blocked_open
            handler = Mock()
            handler.resolve_upload.return_value = {'path': str(source), 'mime': 'text/plain', 'name': 'proof.txt'}
            handler._inside_upload_dir.return_value = True
            handler.is_image_file.return_value = False
            handler.is_audio_file.return_value = False
            handler.is_document_file.return_value = True
            def process():
                result.append(scope['build_user_content']('Read the attached proof.', ['fixture'], directory, handler))
            async def app(scope, receive, send):
                await asyncio.to_thread(process)
            middleware = ActivityMiddleware(app, tracker)
            with patch.dict(sys.modules, {'src.personal_docs': None}):
                task = asyncio.create_task(middleware({'type': 'http', 'path': '/api/chat_stream', 'method': 'POST'}, None, None))
                for _ in range(100):
                    if entered.is_set():
                        break
                    await asyncio.sleep(.01)
                self.assertTrue(entered.is_set())
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                tracker.report()
                self.assertEqual(len(tracker.tickets), 1)
                self.assertNotIn('finish', calls)
                release.set()
                for _ in range(100):
                    tracker.report()
                    if not tracker.tickets:
                        break
                    await asyncio.sleep(.01)
                self.assertFalse(tracker.tickets)
                self.assertEqual(calls.count('begin'), 1)
                self.assertEqual(calls.count('finish'), 1)
                self.assertIn('cobalt heron 731', result[0])
                self.assertIn('proof.txt', result[0])


if __name__ == '__main__':
    unittest.main()
