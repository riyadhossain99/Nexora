"""Offline image regressions: python -B backend/test_agent_images.py."""

import base64
import copy
import io
import json
import os
import unittest
from contextlib import redirect_stdout
from threading import Event, Thread
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import django
import requests

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nexora.settings")
django.setup()

from core import agent
from core.views import wa_webhook
from django.conf import settings
from django.core.exceptions import RequestDataTooBig
from django.test import RequestFactory


PHOTO = {
    "mime": "image/png",
    "b64": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aX1sAAAAASUVORK5CYII=",
}
OTHER_PHOTO = {
    "mime": "image/png",
    "b64": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
}


class AgentImageTests(unittest.TestCase):
    def setUp(self):
        self.config = SimpleNamespace(
            llm_base_url="https://agentrouter.org/v1", model_name="fixture-model",
            api_key="offline-placeholder", request_options="{}", system_prompt="",
        )
        self.tenant = SimpleNamespace(pk=1, id=1, business_name="Fixture Shop", settings={}, usage_stats={}, save=Mock())
        self.conversations = {}
        self.next_id = 100
        self.requests = []
        self.outputs = []
        self.product = SimpleNamespace(name="Fixture Dress", description="A dress", base_price=10, image_url="/media/fixture.png", skus=[])
        products = MagicMock()
        products.values_list.return_value = [self.product.name]
        products.first.return_value = self.product
        products.__iter__.side_effect = lambda: iter([self.product])
        tenants = Mock()
        tenants.values_list.return_value.first.return_value = {}
        for target, kwargs in (
            ("core.agent.SystemConfig.load", {"return_value": self.config}),
            ("core.agent.Conversation.objects.get_or_create", {"side_effect": self.get_conversation}),
            ("core.agent.Product.objects.filter", {"return_value": products}),
            ("core.agent.Tenant.objects.filter", {"return_value": tenants}),
            ("core.agent._make_http_session", {"return_value": SimpleNamespace(post=self.post)}),
            ("core.agent._log_error", {}),
            ("core.agent.cleanup_images", {}),
            ("requests.sessions.Session.request", {"side_effect": AssertionError("Live network disabled")}),
            ("django.db.backends.base.base.BaseDatabaseWrapper.ensure_connection", {"side_effect": AssertionError("Database access disabled")}),
        ):
            self.enterContext(patch(target, **kwargs))
        cache = getattr(agent, "_IMAGE_CONTEXT", None)
        if cache is not None:
            cache.clear()
            self.addCleanup(cache.clear)

    def get_conversation(self, tenant, customer_phone):
        key = (tenant.pk, customer_phone)
        if key not in self.conversations:
            self.conversations[key] = SimpleNamespace(pk=self.next_id, id=self.next_id, messages=[], needs_human=False, save=Mock())
            self.next_id += 1
        return self.conversations[key], False

    def post(self, url, headers, json, timeout):
        self.requests.append((url, copy.deepcopy(json)))
        responses = url.endswith("/responses")
        messages = json["input" if responses else "messages"]
        errors = []
        for message in messages:
            content = message.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                kind = part.get("type")
                allowed = ("input_text", "input_image") if responses else ("text", "image_url")
                if kind not in allowed:
                    errors.append(f"Invalid content type {kind!r}")
                if kind == "input_image" and not isinstance(part.get("image_url"), str):
                    errors.append("Responses image_url must be a string")
        response = Mock()
        if errors:
            response.raise_for_status.side_effect = requests.HTTPError("400 Bad Request: " + "; ".join(errors))
        elif self.outputs:
            response.json.return_value = self.outputs.pop(0)
        elif responses:
            response.json.return_value = {"output": [{"type": "message", "content": [{"type": "output_text", "text": "Available."}]}]}
        else:
            response.json.return_value = {"choices": [{"message": {"content": "Available."}}]}
        return response

    def ask(self, text="Is this dress available?", image=None, phone="OFFLINE", tenant=None, return_media=False):
        with redirect_stdout(io.StringIO()):
            return agent.run_agent(tenant or self.tenant, phone, text, image, return_media=return_media)

    def current_content(self):
        payload = self.requests[-1][1]
        messages = payload.get("input", payload.get("messages"))
        return next(message["content"] for message in reversed(messages) if message.get("role") == "user")

    def image_url(self):
        content = self.current_content()
        if isinstance(content, list):
            for part in content:
                if part.get("type") == "input_image":
                    return part["image_url"]
                if part.get("type") == "image_url":
                    return part["image_url"]["url"]
        return None

    def test_responses_image_and_caption_have_valid_input_types(self):
        self.assertEqual(self.ask(image=PHOTO), "Available.")
        self.assertEqual([part["type"] for part in self.current_content()], ["input_text", "input_image"])
        self.assertEqual(self.image_url(), "data:image/png;base64," + PHOTO["b64"])

    def test_explicit_responses_endpoint_is_not_duplicated(self):
        self.config.llm_base_url = "https://example.invalid/v1/responses"
        self.assertEqual(self.ask(image=PHOTO), "Available.")
        self.assertEqual(self.requests[-1][0], self.config.llm_base_url)

    def test_image_without_caption_is_understood(self):
        self.assertEqual(self.ask(text="", image=PHOTO), "Available.")
        self.assertIsNotNone(self.image_url())

    def test_chat_completions_image_format_is_unchanged(self):
        self.config.llm_base_url = "https://example.invalid/v1"
        self.assertEqual(self.ask(image=PHOTO), "Available.")
        self.assertEqual([part["type"] for part in self.current_content()], ["text", "image_url"])
        self.assertEqual(self.image_url(), "data:image/png;base64," + PHOTO["b64"])

    def test_text_only_messages_remain_text_for_both_apis(self):
        for endpoint in ("https://agentrouter.org/v1", "https://example.invalid/v1"):
            with self.subTest(endpoint=endpoint):
                self.config.llm_base_url = endpoint
                self.assertEqual(self.ask(text="What dresses do you sell?"), "Available.")
                self.assertEqual(self.current_content(), "What dresses do you sell?")

    def test_separate_question_uses_current_chat_photo(self):
        self.ask(text="", image=PHOTO)
        self.assertEqual(self.ask(), "Available.")
        self.assertEqual(self.image_url(), "data:image/png;base64," + PHOTO["b64"])

    def test_incoming_photo_is_not_saved_in_conversation_history(self):
        self.ask(image=PHOTO)
        self.ask()
        history = json.dumps(self.conversations[(1, "OFFLINE")].messages)
        self.assertNotIn(PHOTO["b64"], history)
        self.assertNotIn("data:image", history)
        self.assertEqual(self.conversations[(1, "OFFLINE")].messages[-2]["content"], "Is this dress available?")

    def test_new_photo_replaces_old_photo(self):
        self.ask(image=PHOTO)
        self.ask(image=OTHER_PHOTO)
        self.ask()
        self.assertEqual(self.image_url(), "data:image/png;base64," + OTHER_PHOTO["b64"])
        self.assertNotIn(PHOTO["b64"], json.dumps(self.requests[-1][1]))

    def test_overlapping_replacements_and_questions_keep_valid_latest_context(self):
        conv = self.get_conversation(self.tenant, "OFFLINE")[0]
        agent._chat_image(self.tenant, conv, PHOTO)
        paused, release = Event(), Event()
        results, errors = {}, []
        started = {name: Event() for name in ("older", "question", "newer")}
        finished = {name: Event() for name in started}
        decode = agent.base64.b64decode

        def slow_decode(value, **kwargs):
            if value == PHOTO["b64"]:
                paused.set()
                if not release.wait(5):
                    raise AssertionError("Replacement gate was not released")
            return decode(value, **kwargs)

        def update(name, image):
            started[name].set()
            try:
                results[name] = agent._chat_image(self.tenant, conv, image)
            except Exception as exc:
                errors.append(exc)
            finally:
                finished[name].set()

        threads = []
        with patch("core.agent.base64.b64decode", side_effect=slow_decode):
            try:
                for name, image in (("older", PHOTO), ("question", None), ("newer", OTHER_PHOTO)):
                    thread = Thread(target=update, args=(name, image), daemon=True)
                    threads.append(thread)
                    thread.start()
                    self.assertTrue(started[name].wait(2))
                    if name == "older":
                        self.assertTrue(paused.wait(2))
                    else:
                        finished[name].wait(0.25)
            finally:
                release.set()
                for thread in threads:
                    thread.join(2)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(errors, [])
        with self.subTest("question must not see a gap during replacement"):
            self.assertIsNotNone(results["question"])
        with self.subTest("older request must not overwrite the newer photo"):
            self.assertEqual(agent._chat_image(self.tenant, conv, None), OTHER_PHOTO)

    def test_context_is_isolated_between_customers_and_shops(self):
        self.ask(image=PHOTO)
        self.ask(phone="OTHER-CUSTOMER")
        self.assertIsNone(self.image_url())
        other_tenant = SimpleNamespace(pk=2, id=2, business_name="Other Shop", settings={}, usage_stats={}, save=Mock())
        self.ask(tenant=other_tenant)
        self.assertIsNone(self.image_url())

    def test_context_expires_after_ten_minutes_of_inactivity(self):
        with patch("django.core.cache.backends.locmem.time.time", return_value=1000):
            self.ask(image=PHOTO)
        with patch("django.core.cache.backends.locmem.time.time", return_value=1601):
            self.ask()
        self.assertIsNone(self.image_url())

    def test_active_chat_refreshes_temporary_context(self):
        with patch("django.core.cache.backends.locmem.time.time", return_value=1000):
            self.ask(image=PHOTO)
        with patch("django.core.cache.backends.locmem.time.time", return_value=1500):
            self.ask()
        with patch("django.core.cache.backends.locmem.time.time", return_value=2000):
            self.ask()
        self.assertEqual(self.image_url(), "data:image/png;base64," + PHOTO["b64"])

    def test_recreated_conversation_cannot_reuse_old_context(self):
        self.ask(image=PHOTO)
        del self.conversations[(1, "OFFLINE")]
        self.ask()
        self.assertIsNone(self.image_url())

    def test_context_capacity_is_bounded(self):
        for i in range(17):
            self.ask(image=PHOTO, phone=f"CHAT-{i}")
        self.ask(phone="CHAT-0")
        self.assertIsNone(self.image_url())
        self.ask(phone="CHAT-16")
        self.assertIsNotNone(self.image_url())

    def test_oversized_photo_is_not_retained_or_replaced_with_old_context(self):
        self.ask(image=PHOTO)
        large = {"mime": "image/png", "b64": "A" * (4 * 1024 * 1024 + 4)}
        self.ask(image=large)
        self.ask()
        self.assertIsNone(self.image_url())

    def test_malformed_photo_cannot_poison_followup_context(self):
        self.ask(image=PHOTO)
        self.ask(image={"mime": "image/png", "b64": "not base64"})
        self.ask()
        self.assertIsNone(self.image_url())

    def test_photo_tool_continuation_keeps_image_and_outgoing_media(self):
        self.outputs = [
            {"output": [{"type": "function_call", "call_id": "fixture-call", "name": "send_product_photo", "arguments": json.dumps({"product_name": "Fixture Dress"})}]},
            {"output": [{"type": "message", "content": [{"type": "output_text", "text": "Available."}]}]},
        ]
        reply, media = self.ask(image=PHOTO, return_media=True)
        self.assertEqual(reply, "Available.")
        self.assertEqual(media[0]["url"], self.product.image_url)
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(self.image_url(), "data:image/png;base64," + PHOTO["b64"])
        self.assertTrue(any(item.get("type") == "function_call_output" for item in self.requests[-1][1]["input"]))


class WhatsAppPhotoRequestTests(unittest.TestCase):
    def test_webhook_accepts_bridge_maximum_photo_after_base64_encoding(self):
        photo = {"mime": "image/jpeg", "b64": base64.b64encode(b"X" * (4 * 1024 * 1024)).decode()}
        payload = {"tenant_id": 1, "phone": "OFFLINE", "text": "Is this available?", "image": photo}
        request = RequestFactory().post("/api/webhook/wa/", data=json.dumps(payload), content_type="application/json")
        tenant = SimpleNamespace(id=1, is_active=True, plan_status="ACTIVE", wa_status="CONNECTED", business_name="Fixture Shop")
        with patch("django.db.backends.base.base.BaseDatabaseWrapper.ensure_connection", side_effect=AssertionError("Database disabled")), \
             patch("core.views.Tenant.objects.filter") as tenants, \
             patch("core.views._rate_limit", return_value=(False, False)), \
             patch("core.views.run_agent", return_value=("Available.", [])) as run, \
             redirect_stdout(io.StringIO()):
            tenants.return_value.first.return_value = tenant
            response = wa_webhook(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)["reply"], "Available.")
        self.assertEqual(run.call_args.args[3], photo)

    def test_request_body_limit_remains_finite_and_rejects_oversized_json(self):
        self.assertIsInstance(settings.DATA_UPLOAD_MAX_MEMORY_SIZE, int)
        self.assertLessEqual(settings.DATA_UPLOAD_MAX_MEMORY_SIZE, 6 * 1024 * 1024)
        request = RequestFactory().post("/api/webhook/wa/", data=b"X" * (6 * 1024 * 1024 + 1), content_type="application/json")
        with self.assertRaises(RequestDataTooBig):
            wa_webhook(request)


if __name__ == "__main__":
    unittest.main(verbosity=2)
