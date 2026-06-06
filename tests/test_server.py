import unittest
from http import HTTPStatus
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from src.config import AppSettings
from src.job_store import JobStore
from src.models import ExecutionResult
from src.server import GatewayHandler


class FakeServer:
    def __init__(self, settings=None, job_store=None):
        self.settings = settings
        self.job_store = job_store


class ServerHandlerTest(unittest.TestCase):
    def make_handler(self, settings=None, job_store=None):
        handler = GatewayHandler.__new__(GatewayHandler)
        handler.client_address = ("127.0.0.1", 12345)
        handler.server = FakeServer(settings or AppSettings("127.0.0.1", 8787, "", False, "test", Path("config/workspaces.json"), "default", agent_token="agent-secret", dingtalk_callback_token="callback-secret"), job_store)
        handler.command = "POST"
        handler.path = "/local/message"
        handler.request_version = "HTTP/1.1"
        handler.close_connection = True
        handler.requestline = "POST /local/message HTTP/1.1"
        handler.headers = {}
        handler.responses = []
        return handler

    def test_local_message_response_shape_and_audit(self):
        handler = self.make_handler()
        payload = {"workspace": "default", "sender": "tester", "text": "广告状态"}
        with patch.object(GatewayHandler, "read_json", return_value=payload), \
             patch.object(GatewayHandler, "write_json", side_effect=lambda body, status=HTTPStatus.OK: handler.responses.append((status, body))), \
             patch("src.server.execute_route", return_value=ExecutionResult(True, "ad_status", "# ok")), \
             patch("src.server.append_audit") as append_audit:
            handler.do_POST()

        status, body = handler.responses[0]
        self.assertEqual(status, HTTPStatus.OK)
        self.assertTrue(body["ok"])
        self.assertEqual(body["command"], "ad_status")
        self.assertEqual(body["executor"], "ad_status")
        append_audit.assert_called_once()

    def test_local_message_rejects_empty_text(self):
        handler = self.make_handler()
        with patch.object(GatewayHandler, "read_json", return_value={"text": "   "}), \
             patch.object(GatewayHandler, "write_json", side_effect=lambda body, status=HTTPStatus.OK: handler.responses.append((status, body))):
            handler.do_POST()

        status, body = handler.responses[0]
        self.assertEqual(status, HTTPStatus.BAD_REQUEST)
        self.assertFalse(body["ok"])
        self.assertEqual(body["error"], "empty_text")

    def test_local_message_requires_bearer_token_when_configured(self):
        settings = AppSettings("127.0.0.1", 8787, "secret", True, "test", Path("config/workspaces.json"), "default")
        handler = self.make_handler(settings)
        with patch.object(GatewayHandler, "write_json", side_effect=lambda body, status=HTTPStatus.OK: handler.responses.append((status, body))):
            handler.do_POST()

        status, body = handler.responses[0]
        self.assertEqual(status, HTTPStatus.UNAUTHORIZED)
        self.assertEqual(body["error"], "unauthorized")

    def test_local_message_accepts_valid_bearer_token(self):
        settings = AppSettings("127.0.0.1", 8787, "secret", True, "test", Path("config/workspaces.json"), "default")
        handler = self.make_handler(settings)
        handler.headers = {"Authorization": "Bearer secret"}
        payload = {"workspace": "default", "sender": "tester", "text": "广告状态"}
        with patch.object(GatewayHandler, "read_json", return_value=payload), \
             patch.object(GatewayHandler, "write_json", side_effect=lambda body, status=HTTPStatus.OK: handler.responses.append((status, body))), \
             patch("src.server.execute_route", return_value=ExecutionResult(True, "ad_status", "# ok")), \
             patch("src.server.append_audit"):
            handler.do_POST()

        status, body = handler.responses[0]
        self.assertEqual(status, HTTPStatus.OK)
        self.assertTrue(body["ok"])

    def test_dingtalk_callback_creates_codex_job(self):
        with TemporaryDirectory() as tmp:
            store = JobStore(Path(tmp) / "jobs.sqlite3")
            settings = AppSettings("127.0.0.1", 8787, "", False, "test", Path("config/workspaces.json"), "default", agent_token="agent-secret", dingtalk_callback_token="callback-secret")
            handler = self.make_handler(settings, store)
            handler.path = "/dingtalk/callback?token=callback-secret"
            payload = {"text": {"content": "复杂分析 看一下昨天订单"}, "senderNick": "tester"}
            with patch.object(GatewayHandler, "read_json", return_value=payload), \
                 patch.object(GatewayHandler, "write_json", side_effect=lambda body, status=HTTPStatus.OK: handler.responses.append((status, body))), \
                 patch.object(GatewayHandler, "notify_dingtalk"), \
                 patch("src.server.append_audit"):
                handler.do_POST()

            status, body = handler.responses[0]
            self.assertEqual(status, HTTPStatus.OK)
            self.assertTrue(body["ok"])
            self.assertEqual(store.get_job(body["job_id"])["status"], "queued")

    def test_agent_poll_requires_agent_token(self):
        handler = self.make_handler()
        handler.path = "/agent/poll"
        with patch.object(GatewayHandler, "write_json", side_effect=lambda body, status=HTTPStatus.OK: handler.responses.append((status, body))):
            handler.do_POST()

        status, body = handler.responses[0]
        self.assertEqual(status, HTTPStatus.UNAUTHORIZED)
        self.assertEqual(body["error"], "unauthorized")

    def test_agent_poll_claims_job_and_complete_updates_status(self):
        with TemporaryDirectory() as tmp:
            store = JobStore(Path(tmp) / "jobs.sqlite3")
            job = store.create_job("default", "sender", "复杂分析 test", "test")
            handler = self.make_handler(job_store=store)
            handler.headers = {"Authorization": "Bearer agent-secret"}
            handler.path = "/agent/poll"
            with patch.object(GatewayHandler, "read_json", return_value={"agent_id": "pc-1"}), \
                 patch.object(GatewayHandler, "write_json", side_effect=lambda body, status=HTTPStatus.OK: handler.responses.append((status, body))), \
                 patch.object(GatewayHandler, "notify_dingtalk"):
                handler.do_POST()
            self.assertEqual(handler.responses[0][1]["job"]["id"], job["id"])

            handler = self.make_handler(job_store=store)
            handler.headers = {"Authorization": "Bearer agent-secret"}
            handler.path = f"/agent/jobs/{job['id']}/complete"
            with patch.object(GatewayHandler, "read_json", return_value={"ok": True, "markdown": "done", "returncode": 0}), \
                 patch.object(GatewayHandler, "write_json", side_effect=lambda body, status=HTTPStatus.OK: handler.responses.append((status, body))), \
                 patch.object(GatewayHandler, "notify_dingtalk"):
                handler.do_POST()
            self.assertEqual(handler.responses[0][1]["status"], "succeeded")



if __name__ == "__main__":
    unittest.main()
