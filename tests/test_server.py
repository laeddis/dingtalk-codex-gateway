import unittest
from http import HTTPStatus
from unittest.mock import patch

from src.models import ExecutionResult
from src.server import GatewayHandler


class FakeRequest:
    def makefile(self, *_args, **_kwargs):
        raise RuntimeError("socket IO is not used by handler unit tests")


class ServerHandlerTest(unittest.TestCase):
    def make_handler(self):
        handler = GatewayHandler.__new__(GatewayHandler)
        handler.client_address = ("127.0.0.1", 12345)
        handler.server = object()
        handler.command = "POST"
        handler.path = "/local/message"
        handler.request_version = "HTTP/1.1"
        handler.close_connection = True
        handler.requestline = "POST /local/message HTTP/1.1"
        handler.responses = []
        return handler

    def test_local_message_response_shape_and_audit(self):
        handler = self.make_handler()
        payload = {"workspace": "cuticlub", "sender": "tester", "text": "广告状态"}
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


if __name__ == "__main__":
    unittest.main()
