import hashlib
import hmac
import json
import tempfile
import unittest
import threading
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

from sms_gateway.modem import ModemWorker, SerialModem
from sms_gateway.store import MessageStore
from sms_gateway.app import Gateway, handler_factory
from sms_gateway.admin import AdminAccess
from sms_gateway.modem import ReceivedSms
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

    def test_portal_summary_is_read_only_and_privacy_safe(self):
        with tempfile.NamedTemporaryFile() as db:
            gateway = Gateway.__new__(Gateway)
            gateway.store = MessageStore(db.name)
            gateway.store.upsert_device("air780-secret-id", "867530900000001", "online", "/dev/ttyACM0", "1.2.1")
            gateway.store.update_device_label("air780-secret-id", "客服一号")
            gateway.store.create("inbound", "+8613800138000", "敏感短信正文", "received", device_id="air780-secret-id")
            gateway.store.create("outbound", "+8613900139000", "另一条敏感正文", "sent", device_id="air780-secret-id")
            gateway.store.set_setting("feishu_webhooks", json.dumps([{"id":"f1","label":"飞书","url":"https://example.invalid/secret","enabled":True}]))
            gateway.store.set_setting("dingtalk_webhooks", json.dumps([{"id":"d1","label":"钉钉","url":"https://example.invalid/token","secret":"SEC-secret","enabled":True}]))

            summary = gateway.portal_summary()
            encoded = json.dumps(summary, ensure_ascii=False)

            self.assertEqual(summary["online_devices"], 1)
            self.assertEqual(summary["messages"]["inbound"], 1)
            self.assertEqual(summary["messages"]["outbound"], 1)
            self.assertEqual(summary["integrations"], {"feishu": 1, "dingtalk": 1})
            self.assertIn("客服一号", encoded)
            for secret in ["13800138000", "13900139000", "敏感短信正文", "另一条敏感正文",
                           "867530900000001", "/dev/ttyACM0", "example.invalid", "SEC-secret"]:
                self.assertNotIn(secret, encoded)

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

    def test_blacklist_archives_messages_and_persists(self):
        with tempfile.NamedTemporaryFile() as db:
            store = MessageStore(db.name)
            store.upsert_blacklist("10086", "广告", "不通知")
            self.assertTrue(store.is_blacklisted("10086"))
            message_id = store.create("inbound", "10086", "促销", "blacklisted",
                                      device_id="air780-a", blacklisted=True)
            reopened = MessageStore(db.name)
            self.assertEqual(reopened.get(message_id)["blacklisted"], 1)
            self.assertEqual(reopened.list_blacklist()[0]["message_count"], 1)
            reopened.delete_blacklist("10086")
            self.assertFalse(reopened.is_blacklisted("10086"))
            self.assertEqual(reopened.get(message_id)["body"], "促销")

    def test_blacklist_supports_contains_regex_search_and_validation(self):
        with tempfile.NamedTemporaryFile() as db:
            store = MessageStore(db.name)
            contains = store.upsert_blacklist("1069", "营销号段", "包含匹配", "contains")
            regex = store.upsert_blacklist(r"^95\d{3}$", "服务短号", "正则匹配", "regex")
            self.assertEqual(contains["match_type"], "contains")
            self.assertEqual(regex["match_type"], "regex")
            self.assertTrue(store.is_blacklisted("1069123456"))
            self.assertTrue(store.is_blacklisted("95555"))
            self.assertFalse(store.is_blacklisted("10086"))
            store.create("inbound", "1069123456", "推广", "blacklisted", blacklisted=True)
            store.create("inbound", "95555", "通知", "blacklisted", blacklisted=True)
            items = store.list_blacklist(search="服务", match_type="regex")
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["phone"], r"^95\d{3}$")
            self.assertEqual(items[0]["message_count"], 1)
            self.assertEqual(items[0]["matched_phones"], ["95555"])
            with self.assertRaisesRegex(ValueError, "正则表达式无效"):
                store.upsert_blacklist("([", "坏规则", "", "regex")
            with self.assertRaisesRegex(ValueError, "匹配方式"):
                store.list_blacklist(match_type="wildcard")

    def test_password_accounts_support_admin_managed_users(self):
        with tempfile.NamedTemporaryFile() as db:
            store = MessageStore(db.name)
            access = AdminAccess(store, "Bootstrap123!")
            admin_session = access.login("admin", "Bootstrap123!")
            self.assertIsNotNone(admin_session)
            self.assertEqual(access.session_user(admin_session)["role"], "admin")

            created = access.create_user("operator1", "Password123")
            self.assertEqual(created["role"], "user")
            user_session = access.login("operator1", "Password123")
            self.assertIsNotNone(user_session)
            self.assertFalse(access.is_admin(user_session))

            access.update_user("operator1", False)
            self.assertIsNone(access.session_user(user_session))
            self.assertIsNone(access.login("operator1", "Password123"))
            access.update_user("operator1", True)
            access.reset_user_password("operator1", "Changed123")
            self.assertIsNone(access.login("operator1", "Password123"))
            self.assertIsNotNone(access.login("operator1", "Changed123"))
            with self.assertRaisesRegex(ValueError, "不能禁用"):
                access.update_user("admin", False)
            self.assertTrue(access.delete_user("operator1"))
            self.assertIsNone(access.login("operator1", "Changed123"))

    def test_delete_device_only_removes_offline_registry_and_keeps_history(self):
        with tempfile.NamedTemporaryFile() as db:
            store = MessageStore(db.name)
            store.upsert_device("air780-old", "old-imei", "offline", None, "1")
            message_id = store.create("inbound", "10086", "历史短信", "received",
                                      device_id="air780-old")
            self.assertEqual(store.delete_device("air780-old"), "deleted")
            self.assertFalse(any(item["device_id"] == "air780-old" for item in store.list_devices()))
            self.assertEqual(store.get(message_id)["body"], "历史短信")
            store.upsert_device("air780-live", "live-imei", "online", "/dev/ttyACM2", "1")
            self.assertEqual(store.delete_device("air780-live"), "online")
            self.assertTrue(any(item["device_id"] == "air780-live" for item in store.list_devices()))

    def test_advertisement_rules_seed_match_and_validate(self):
        with tempfile.NamedTemporaryFile() as db:
            store = MessageStore(db.name)
            defaults = store.list_ad_rules()
            self.assertTrue(all(item["match_type"] == "regex" for item in defaults))
            self.assertIsNone(store.match_advertisement("10000", "这是正常的退订业务说明，不是广告"))
            self.assertIsNotNone(store.match_advertisement("10690000", "新品促销，回复TD退订"))
            rule = store.create_ad_rule(r"限时.*优惠", "regex", "body", "限时优惠")
            self.assertEqual(rule["match_type"], "regex")
            self.assertEqual(store.match_advertisement("10000", "限时会员优惠")["id"], rule["id"])
            with self.assertRaisesRegex(ValueError, "正则表达式无效"):
                store.create_ad_rule("([", "regex", "body", "坏规则")

    @patch("sms_gateway.app.threading.Thread")
    def test_advertisement_inbound_is_archived_without_notifications(self, thread):
        with tempfile.NamedTemporaryFile() as db:
            gateway = Gateway.__new__(Gateway)
            gateway.store = MessageStore(db.name)
            gateway._device_label = lambda _device_id: "测试设备"
            gateway._received("air780-a", ReceivedSms(8, "10690000", "活动通知，回复TD退订"))
            thread.assert_not_called()
            message = gateway.store.list()[0]
            self.assertEqual(message["status"], "advertisement")
            self.assertEqual(message["advertisement"], 1)
            self.assertEqual(message["blacklisted"], 0)

    def test_http_account_permissions_and_admin_device_delete(self):
        with tempfile.NamedTemporaryFile() as db:
            gateway = Gateway.__new__(Gateway)
            gateway.settings = SimpleNamespace(api_token="")
            gateway.store = MessageStore(db.name)
            gateway.admin = AdminAccess(gateway.store, "AdminPass123")
            gateway.store.upsert_device("air780-stale", "stale-imei", "offline", None, "1")
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler_factory(gateway))
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            base = f"http://127.0.0.1:{server.server_port}"

            def call(path, method="GET", body=None, session=None):
                data = json.dumps(body).encode() if body is not None else None
                headers = {"Content-Type": "application/json"} if body is not None else {}
                if session:
                    headers["X-User-Session"] = session
                request = Request(base + path, data=data, headers=headers, method=method)
                try:
                    with urlopen(request, timeout=3) as response:
                        return response.status, json.loads(response.read())
                except HTTPError as exc:
                    try:
                        return exc.code, json.loads(exc.read())
                    finally:
                        exc.close()

            try:
                status, login = call("/api/v1/auth/login", "POST",
                                     {"username": "admin", "password": "AdminPass123"})
                self.assertEqual(status, 200)
                admin_session = login["session"]
                self.assertEqual(login["user"]["role"], "admin")

                status, created = call("/api/v1/admin/users", "POST",
                                       {"username": "worker1", "password": "WorkerPass123"},
                                       admin_session)
                self.assertEqual(status, 201)
                self.assertTrue(any(item["username"] == "worker1" for item in created["users"]))

                status, login = call("/api/v1/auth/login", "POST",
                                     {"username": "worker1", "password": "WorkerPass123"})
                self.assertEqual(status, 200)
                user_session = login["session"]

                status, _ = call("/api/v1/devices/air780-stale", "DELETE", session=user_session)
                self.assertEqual(status, 403)
                status, _ = call("/api/v1/network/4g", "PUT", {"enabled": True}, user_session)
                self.assertEqual(status, 403)

                status, rule = call("/api/v1/ad-rules", "POST", {
                    "pattern": "领券", "match_type": "contains", "field": "body",
                    "label": "优惠券", "enabled": True,
                }, user_session)
                self.assertEqual(status, 201)
                self.assertEqual(rule["pattern"], "领券")

                status, _ = call("/api/v1/devices/air780-stale", "DELETE", session=admin_session)
                self.assertEqual(status, 200)
                self.assertFalse(any(item["device_id"] == "air780-stale"
                                     for item in gateway.store.list_devices()))
            finally:
                server.shutdown()
                server.server_close()
                worker.join(timeout=2)

    @patch("sms_gateway.app.threading.Thread")
    def test_blacklisted_inbound_sms_skips_all_notifications(self, thread):
        with tempfile.NamedTemporaryFile() as db:
            gateway = Gateway.__new__(Gateway)
            gateway.store = MessageStore(db.name)
            gateway.store.upsert_blacklist("10010", "广告")
            gateway._device_label = lambda _device_id: "测试设备"
            gateway._received("air780-a", ReceivedSms(3, "10010", "推广活动，回复TD退订"))
            thread.assert_not_called()
            message = gateway.store.list()[0]
            self.assertEqual(message["status"], "blacklisted")
            self.assertEqual(message["blacklisted"], 1)
            self.assertEqual(message["advertisement"], 0)

    def test_modem_worker_retries_transient_send_failure(self):
        class FlakyModem:
            serial = type("SerialState", (), {"is_open": True})()

            def __init__(self):
                self.calls = 0

            def send_sms(self, phone, body):
                self.calls += 1
                if self.calls < 3:
                    raise RuntimeError("temporary modem failure")
                return "sent"

        modem = FlakyModem()
        worker = ModemWorker(modem, 1, lambda _sms: None, False,
                             reconnect=False, send_attempts=3)
        results = []
        worker.enqueue(42, "10086", "test", lambda *args: results.append(args))
        with patch.object(worker.stop_event, "wait", return_value=False):
            worker._send_pending()
        self.assertEqual(modem.calls, 3)
        self.assertEqual(results, [(42, True, None)])

    def test_modem_worker_reports_failure_after_retry_limit(self):
        class BrokenModem:
            serial = type("SerialState", (), {"is_open": True})()

            def __init__(self):
                self.calls = 0

            def send_sms(self, phone, body):
                self.calls += 1
                raise RuntimeError("permanent modem failure")

        modem = BrokenModem()
        worker = ModemWorker(modem, 1, lambda _sms: None, False,
                             reconnect=False, send_attempts=2)
        results = []
        worker.enqueue(43, "10010", "test", lambda *args: results.append(args))
        with patch.object(worker.stop_event, "wait", return_value=False):
            worker._send_pending()
        self.assertEqual(modem.calls, 2)
        self.assertEqual(results, [(43, False, "permanent modem failure")])

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
