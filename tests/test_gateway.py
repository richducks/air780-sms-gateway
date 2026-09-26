import hashlib
import hmac
import json
import tempfile
import unittest
from unittest.mock import patch

from sms_gateway.modem import SerialModem
from sms_gateway.store import MessageStore
from sms_gateway.webhook import deliver, deliver_feishu, deliver_dingtalk
from urllib.parse import parse_qs, urlsplit
import base64


class GatewayTests(unittest.TestCase):
    def test_bridge_dispatches_unicode_sms(self):
        modem = SerialModem("auto")
        modem._dispatch({"type": "sms_received", "phone": "+86123", "body": "你好"})
        self.assertEqual(modem._received[0].sender, "+86123")
        self.assertEqual(modem._received[0].body, "你好")

    def test_bridge_keeps_reported_signal(self):
        modem = SerialModem("auto")
        modem._dispatch({"type": "ready", "signal": {"rsrp": -101, "csq": 21}})
        self.assertEqual(modem.device_info["signal"]["rsrp"], -101)

    def test_store_deduplicates_modem_index(self):
        with tempfile.NamedTemporaryFile() as db:
            store = MessageStore(db.name)
            first = store.create("inbound", "+86123", "one", "received", 9)
            second = store.create("inbound", "+86123", "one", "received", 9)
            self.assertEqual(first, second)
            self.assertEqual(len(store.list()), 1)

    def test_store_separates_devices_and_filters(self):
        with tempfile.NamedTemporaryFile() as db:
            store = MessageStore(db.name)
            store.upsert_device("air780-a", "a", "online", "/dev/a", "1")
            store.upsert_device("air780-b", "b", "offline", None, "1")
            first = store.create("inbound", "+86123", "one", "received", 9,
                                 device_id="air780-a")
            second = store.create("inbound", "+86123", "two", "received", 9,
                                  device_id="air780-b")
            self.assertNotEqual(first, second)
            self.assertEqual(len(store.list(device_id="air780-a")), 1)
            self.assertEqual(len(store.list_devices()), 2)

    def test_contacts_persist_without_changing_sms_history(self):
        with tempfile.NamedTemporaryFile() as db:
            store = MessageStore(db.name)
            message_id = store.create("inbound", "+8613800138000", "你好", "received")
            store.upsert_contact("+8613800138000", "张先生", "客户")
            reopened = MessageStore(db.name)
            self.assertEqual(reopened.list_contacts()[0]["name"], "张先生")
            self.assertEqual(reopened.list_contacts()[0]["note"], "客户")
            reopened.upsert_contact("+8613800138000", "张经理", "重要客户")
            self.assertEqual(reopened.get(message_id)["phone"], "+8613800138000")
            reopened.delete_contact("+8613800138000")
            self.assertIsNotNone(reopened.get(message_id))

    def test_favorite_persists_and_preserves_message(self):
        with tempfile.NamedTemporaryFile() as db:
            store = MessageStore(db.name)
            message_id = store.create("inbound", "10000", "通知", "received")
            self.assertEqual(store.get(message_id)["favorite"], 0)
            store.set_favorite(message_id, True)
            reopened = MessageStore(db.name)
            self.assertEqual(reopened.get(message_id)["favorite"], 1)
            self.assertEqual(reopened.get(message_id)["body"], "通知")
            reopened.set_favorite(message_id, False)
            self.assertEqual(reopened.get(message_id)["favorite"], 0)

    @patch("sms_gateway.webhook.urllib.request.urlopen")
    def test_webhook_signature(self, urlopen):
        response = urlopen.return_value.__enter__.return_value
        response.status = 204
        event = {"event": "sms.received"}
        self.assertTrue(deliver("https://example.invalid/hook", "secret", event, 1))
        request = urlopen.call_args.args[0]
        timestamp = request.headers["X-sms-timestamp"]
        expected = hmac.new(b"secret", timestamp.encode() + b"." + request.data, hashlib.sha256).hexdigest()
        self.assertEqual(request.headers["X-sms-signature"], "sha256=" + expected)

    @patch("sms_gateway.webhook.urllib.request.urlopen")
    def test_feishu_payload(self, urlopen):
        response = urlopen.return_value.__enter__.return_value
        response.status = 200
        response.read.return_value = b'{"code":0,"msg":"success"}'
        event = {"event": "sms.received", "device_id": "air780-test",
                 "message": {"phone": "10086", "body": "你好", "created_at": "now"}}
        self.assertTrue(deliver_feishu("https://example.invalid/hook", event, 1))
        payload = json.loads(urlopen.call_args.args[0].data)
        self.assertEqual(payload["msg_type"], "text")
        self.assertIn("你好", payload["content"]["text"])

    @patch("sms_gateway.webhook.urllib.request.urlopen")
    def test_feishu_prefers_device_label(self, urlopen):
        response = urlopen.return_value.__enter__.return_value
        response.status = 200
        response.read.return_value = b'{"code":0}'
        event = {"event": "device.online", "device_id": "air780-test",
                 "device_label": "客服一号卡"}
        self.assertTrue(deliver_feishu("https://example.invalid/hook", event, 1))
        payload = json.loads(urlopen.call_args.args[0].data)
        self.assertIn("客服一号卡", payload["content"]["text"])
        self.assertNotIn("air780-test", payload["content"]["text"])

    @patch("sms_gateway.webhook.time.time", return_value=1700000000)
    @patch("sms_gateway.webhook.urllib.request.urlopen")
    def test_dingtalk_signed_payload(self, urlopen, _time):
        response = urlopen.return_value.__enter__.return_value
        response.status = 200
        response.read.return_value = b'{"errcode":0,"errmsg":"ok"}'
        event = {"event": "sms.received", "device_label": "客服卡",
                 "message": {"phone": "10086", "body": "你好", "created_at": "now"}}
        self.assertTrue(deliver_dingtalk("https://oapi.dingtalk.com/robot/send?access_token=abc",
                                         "SEC123", event, 1))
        request = urlopen.call_args.args[0]
        query = parse_qs(urlsplit(request.full_url).query)
        self.assertEqual(query["timestamp"], ["1700000000000"])
        signature = base64.b64encode(hmac.new(
            b"SEC123", b"1700000000000\nSEC123", hashlib.sha256).digest()).decode()
        self.assertEqual(query["sign"], [signature])
        payload = json.loads(request.data)
        self.assertEqual(payload["msgtype"], "text")
        self.assertIn("你好", payload["text"]["content"])


if __name__ == "__main__":
    unittest.main()
