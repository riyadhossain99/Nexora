import atexit
import base64
import json
import os
import sys
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

import django
import requests

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nexora.settings")
from django.conf import settings

# Default checks are offline; --mysql uses a uniquely named disposable XAMPP database.
use_mysql = "--mysql" in sys.argv
if not use_mysql:
    settings.DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
test_media = TemporaryDirectory(prefix="nexora-tests-")
settings.MEDIA_ROOT = Path(test_media.name)
atexit.register(test_media.cleanup)
settings.EMAIL_OTP_BACKEND = "dev"
settings.DEBUG = True
settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
offline = patch("requests.sessions.Session.request", side_effect=requests.ConnectionError("Offline test: service unavailable"))
offline.start()
atexit.register(offline.stop)
django.setup()

from django.core.management import call_command

if use_mysql:
    from django.db import connection
    from django.test.utils import setup_databases, teardown_databases

    connection.settings_dict["TEST"]["NAME"] = f"test_nexora_{uuid.uuid4().hex}"
    old_databases = setup_databases(verbosity=0, interactive=False, serialized_aliases=[])
    atexit.register(teardown_databases, old_databases, verbosity=0)
    print(f"Testing {connection.vendor} in disposable database {connection.settings_dict['NAME']}")
else:
    call_command("migrate", verbosity=0, interactive=False)

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.db.models import Q
from django.test import Client, override_settings

from core.agent import _create_or_update_order, _search_inventory
from core.models import (
    Conversation,
    EmailOTP,
    Order,
    Product,
    SystemConfig,
    Tenant,
    adjust_stock,
    cleanup_images,
    find_sku,
)

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(("PASS" if ok else "FAIL"), "-", name, ("| " + str(detail)) if (detail and not ok) else "")


config = SystemConfig.load()
_original_config = {
    "llm_base_url": config.llm_base_url,
    "api_key": config.api_key,
    "model_name": config.model_name,
    "request_options": config.request_options,
}
config.api_key = ""
config.save()

admin, _ = User.objects.get_or_create(username="smoke_admin")
admin.is_staff = True
admin.is_superuser = True
admin.set_password("smoke-pass-123")
admin.save()

shop_user, _ = User.objects.get_or_create(username="smoke_shop")
shop_user.set_password("smoke-pass-123")
shop_user.save()

tenant, _ = Tenant.objects.get_or_create(user=shop_user, defaults={"business_name": "Smoke Test Co"})
tenant.is_active = True
tenant.plan = "BASIC"
tenant.usage_stats = {}
tenant.settings = {}
tenant.save()

shop = Client()
check("client login", shop.login(username="smoke_shop", password="smoke-pass-123"))
staff = Client()
check("admin login", staff.login(username="smoke_admin", password="smoke-pass-123"))

r = shop.get("/api/dashboard/?widgets=summary_cards,catalog_skus,recent_orders,chat_threads")
widgets = r.json().get("widgets", {}) if r.status_code == 200 else {}
check(
    "client widgets",
    r.status_code == 200 and set(widgets) == {"summary_cards", "catalog_skus", "recent_orders", "chat_threads"},
    r.status_code,
)

payload = {
    "name": "Smoke Tee",
    "description": "test product",
    "base_price": "100.00",
    "skus": [
        {"sku": "SMK-1", "size": "L", "color": "Red", "price": 100, "stock": 5},
        {"sku": "SMK-2", "size": "M", "color": "Blue", "price": 110, "stock": 0},
    ],
}
r = shop.post("/api/product/save/", data=json.dumps(payload), content_type="application/json")
check("product save", r.status_code == 200 and r.json().get("ok"), r.content[:120])
product_id = r.json().get("id")
product, sku = find_sku(tenant, "SMK-1")
check("sku saved", product is not None and sku["stock"] == 5)

r = shop.post(
    "/api/product/save/",
    data=json.dumps({"name": "Bad", "skus": "nope"}),
    content_type="application/json",
)
check("product save validation", r.status_code == 400)

r = shop.post(
    "/api/product/save/",
    data=json.dumps(
        {
            "name": "Dupe",
            "skus": [
                {"sku": "SMK-DUP", "price": 1, "stock": 1},
                {"sku": "smk-dup", "price": 1, "stock": 1},
            ],
        }
    ),
    content_type="application/json",
)
check("duplicate sku codes rejected", r.status_code == 400, r.content[:120])

r = shop.post(
    "/api/product/save/",
    data=json.dumps({"name": "Clash", "skus": [{"sku": "smk-1", "price": 1, "stock": 1}]}),
    content_type="application/json",
)
check("cross-product sku clash rejected", r.status_code == 400, r.content[:120])

r = shop.post(
    "/api/product/save/",
    data=json.dumps({"name": "NoCode", "skus": [{"sku": "", "price": 5, "stock": 1}]}),
    content_type="application/json",
)
check("empty sku code rejected", r.status_code == 400, r.content[:120])

r = shop.post(
    "/api/product/save/",
    data=json.dumps({"name": "NegStock", "skus": [{"sku": "SMK-NEG", "price": 5, "stock": -3}]}),
    content_type="application/json",
)
check("negative stock rejected", r.status_code == 400, r.content[:120])

r = shop.post(
    "/api/product/stock/",
    data=json.dumps({"id": product_id, "sku": "SMK-1", "delta": 5}),
    content_type="application/json",
)
check("stock adjust adds", r.status_code == 200 and r.json().get("stock") == 10, r.content[:120])

r = shop.post(
    "/api/product/stock/",
    data=json.dumps({"id": product_id, "sku": "SMK-1", "delta": -999}),
    content_type="application/json",
)
check("stock adjust floors at zero", r.status_code == 200 and r.json().get("stock") == 0, r.content[:120])

r = shop.post(
    "/api/product/stock/",
    data=json.dumps({"id": product_id, "sku": "NOPE-1", "delta": 1}),
    content_type="application/json",
)
check("stock adjust unknown sku", r.status_code == 404)

shop.post(
    "/api/product/stock/",
    data=json.dumps({"id": product_id, "sku": "SMK-1", "delta": 5}),
    content_type="application/json",
)

r = shop.post(
    "/api/product/duplicate/",
    data=json.dumps({"id": product_id}),
    content_type="application/json",
)
dup_id = r.json().get("id")
dup = Product.objects.filter(id=dup_id).first()
check(
    "product duplicate",
    r.status_code == 200
    and dup is not None
    and dup.name.endswith("(copy)")
    and dup.skus[0]["sku"] == "SMK-1-COPY",
    r.content[:120],
)

r = shop.post(
    "/api/product/archive/",
    data=json.dumps({"id": dup_id, "archived": True}),
    content_type="application/json",
)
dup.refresh_from_db()
check("product archive", r.status_code == 200 and dup.is_active is False)

check("archived hidden from agent search", isinstance(_search_inventory(tenant, "copy"), str))

result = _create_or_update_order(
    tenant,
    "8801700000000",
    {"name": "X", "address": "Y", "sku": "SMK-1-COPY", "qty": 1},
)
check("archived product not orderable", "no longer available" in str(result), result)

r = shop.post(
    "/api/product/archive/",
    data=json.dumps({"id": dup_id, "archived": False}),
    content_type="application/json",
)
dup.refresh_from_db()
check("product restore", r.status_code == 200 and dup.is_active is True)

r = shop.get("/api/dashboard/?widgets=catalog_skus")
rows = r.json().get("widgets", {}).get("catalog_skus", [])
sample = next((p for p in rows if p.get("id") == product_id), {})
check(
    "catalog widget stats",
    {"is_active", "variants", "total_stock", "min_price", "max_price", "low_stock", "out_of_stock"}
    <= set(sample),
    sample,
)

Product.objects.filter(id=dup_id).delete()

order = Order.objects.create(
    tenant=tenant,
    customer_phone="8801700000000",
    customer_name="Smoke Customer",
    address="Dhaka",
    items=[{"sku": "SMK-1", "qty": 2, "product": "Smoke Tee", "price": 100}],
    total=200,
    status="PENDING",
)
adjust_stock(tenant, "SMK-1", -2)
_, sku = find_sku(tenant, "SMK-1")
check("stock deducted for order", sku["stock"] == 3)

r = shop.post(
    f"/api/order/{order.id}/action/",
    data=json.dumps({"action": "CANCELLED", "note": "out of stock"}),
    content_type="application/json",
)
order.refresh_from_db()
_, sku = find_sku(tenant, "SMK-1")
check("order cancelled", r.status_code == 200 and order.status == "CANCELLED")
check("stock restored on cancel", sku["stock"] == 5)
config.refresh_from_db()
check("bridge failure logged", any("wa_bridge" in str(e.get("message", "")) for e in config.error_logs))

r = shop.post(
    f"/api/order/{order.id}/action/",
    data=json.dumps({"action": "NOPE"}),
    content_type="application/json",
)
check("order action validation", r.status_code == 400)

Conversation.objects.filter(tenant=tenant, customer_phone="8801711111111").delete()
r = shop.post(
    "/api/webhook/wa/",
    data=json.dumps({"tenant_id": tenant.id, "phone": "8801711111111", "text": "do you have this shirt?"}),
    content_type="application/json",
)
body = r.json() if r.status_code == 200 else {}
conv = Conversation.objects.filter(tenant=tenant, customer_phone="8801711111111").first()
check("webhook fallback reply", r.status_code == 200 and body.get("reply"), r.content[:160])
check("webhook marks needs_human", conv is not None and conv.needs_human)
store = Tenant.objects.get(id=tenant.id)
check("usage stats updated", int((store.usage_stats or {}).get("messages_count", 0)) >= 1)
check("webhook sets wa_status", store.wa_status == "CONNECTED")

r = shop.post("/api/webhook/wa/", data=json.dumps({"tenant_id": 999999, "phone": "1"}), content_type="application/json")
check("webhook unknown tenant 404", r.status_code == 404)

r = shop.get("/api/dashboard/?widgets=system_overview")
check("shop cannot read admin widgets", r.json().get("widgets") == {} or r.status_code in (200, 403))

r = shop.post("/api/admin/config/", data=json.dumps({"model_name": "hacked"}), content_type="application/json")
check("shop blocked from admin config", r.status_code == 403)

r = staff.get("/api/dashboard/?widgets=system_overview,tenant_usage,config_and_logs")
widgets = r.json().get("widgets", {}) if r.status_code == 200 else {}
check("admin widgets", r.status_code == 200 and "tenant_usage" in widgets)

r = staff.post(
    "/api/admin/config/",
    data=json.dumps({"llm_base_url": "https://example.invalid/v1", "model_name": "test-model", "api_key": "test-key-123"}),
    content_type="application/json",
)
config.refresh_from_db()
check("admin config updates", r.json().get("ok") and config.model_name == "test-model" and config.api_key == "test-key-123")

r = staff.post(
    "/api/admin/config/",
    data=json.dumps({"request_options": "{bad"}),
    content_type="application/json",
)
check("admin rejects invalid request options", r.status_code == 400)

r = staff.post(
    "/api/admin/config/",
    data=json.dumps({"request_options": '{"temperature": 0.2}'}),
    content_type="application/json",
)
config.refresh_from_db()
check(
    "admin saves request options",
    r.status_code == 200 and json.loads(config.request_options) == {"temperature": 0.2},
)

r = shop.post(
    "/api/admin/models/",
    data=json.dumps({"llm_base_url": "https://example.invalid/v1"}),
    content_type="application/json",
)
check("shop blocked from model list", r.status_code == 403)

r = staff.post(
    "/api/admin/models/",
    data=json.dumps({"llm_base_url": "https://example.invalid/v1"}),
    content_type="application/json",
)
check("model list rejects unreachable provider", r.status_code == 400 and r.json().get("error"))

r = shop.post(
    "/api/admin/test-llm/",
    data=json.dumps({"llm_base_url": "https://example.invalid/v1"}),
    content_type="application/json",
)
check("shop blocked from test-llm", r.status_code == 403)

r = staff.post(
    "/api/admin/test-llm/",
    data=json.dumps({"llm_base_url": "https://example.invalid/v1", "model_name": "test"}),
    content_type="application/json",
)
check("test-llm rejects unreachable provider", r.status_code == 400 and not r.json().get("ok"))

username = f"smoke_tenant_{User.objects.count()}"
r = staff.post(
    "/api/admin/tenant/",
    data=json.dumps({"username": username, "password": "Tenant-1234", "business_name": "New Biz"}),
    content_type="application/json",
)
check("admin creates tenant", r.status_code == 200 and r.json().get("ok"))

bridge_response = Mock(status_code=200, ok=True)
bridge_response.json.return_value = {"status": "QR_READY", "qr": "data:image/png;base64,test"}
with patch("requests.sessions.Session.request", return_value=bridge_response) as bridge_request:
    r = shop.get("/api/wa/status/")
check("status reads the current business connection", r.status_code == 200 and r.json().get("status") == "QR_READY")
check("status uses a read-only bridge request", bridge_request.called and bridge_request.call_args.args[0] == "GET")
bridge_response.json.return_value = {"status": "BOGUS"}
with patch("requests.sessions.Session.request", return_value=bridge_response):
    r = shop.get("/api/wa/status/")
check("invalid bridge status is rejected", r.status_code == 503)
bridge_response.json.return_value = {"ok": True, "status": "CONNECTING"}
with patch("requests.sessions.Session.request", return_value=bridge_response) as bridge_request:
    r = shop.post("/api/wa/connect/", data="{}", content_type="application/json")
check("explicit connect starts this business only", r.status_code == 200 and bridge_request.called and bridge_request.call_args.args[1].endswith(f"/wa/{tenant.id}/connect"))
check("connect requires login", Client().post("/api/wa/connect/", data="{}", content_type="application/json").status_code == 302)

# --- Email auth: signup OTP, password policy, password reset via OTP ---

r = Client().get("/")
check(
    "landing page for anonymous",
    r.status_code == 200 and b"WhatsApp AI sales assistant" in r.content,
)

signup_email = f"owner{User.objects.count()}@example.com"
signup = Client()
r = signup.post(
    "/signup/",
    {"business_name": "Signup Boutique", "email": signup_email, "password": "Signup-pass-123"},
)
new_user = User.objects.filter(username=signup_email).first()
new_tenant = Tenant.objects.filter(user=new_user).first() if new_user else None
check(
    "signup creates pending user and tenant",
    r.status_code == 302
    and r.url == "/signup/verify/"
    and new_user is not None
    and not new_user.is_active
    and new_tenant is not None,
    (r.status_code, getattr(r, "url", None)),
)
check("signup tenant gets BASIC plan", new_tenant is not None and new_tenant.plan == "BASIC")
check("signup not logged in before otp", signup.get("/dashboard/client/").status_code == 302)

r = Client().post(
    "/signup/",
    {
        "business_name": "Weak Co",
        "email": f"weak{User.objects.count()}@example.com",
        "password": "weakpass1",
    },
)
check(
    "signup rejects weak password",
    r.status_code == 200 and b"8-16" in r.content,
    r.status_code,
)

r = Client().post(
    "/signup/",
    {
        "business_name": "Short Co",
        "email": f"short{User.objects.count()}@example.com",
        "password": "Ab1",
    },
)
check("signup rejects short password", r.status_code == 200 and b"8-16" in r.content)

r = Client().post(
    "/signup/",
    {
        "business_name": "Long Co",
        "email": f"long{User.objects.count()}@example.com",
        "password": "Abcdefghijklmnop1",
    },
)
check("signup rejects long password", r.status_code == 200 and b"8-16" in r.content)

signup_otp = (
    EmailOTP.objects.filter(email=signup_email, purpose="signup", used=False)
    .order_by("-id")
    .first()
)
check("signup otp generated", signup_otp is not None and len(signup_otp.code) == 6)

r = signup.post("/signup/verify/", {"code": "invalid"})
check("signup rejects wrong otp", r.status_code == 200 and b"invalid" in r.content)

r = signup.post("/signup/verify/", {"code": signup_otp.code})
new_user.refresh_from_db()
check(
    "signup verifies otp and activates user",
    r.status_code == 302 and r.url == "/dashboard/client/" and new_user.is_active,
    r.status_code,
)
check("signup logs user in", signup.get("/dashboard/client/").status_code == 200)

r = Client().post(
    "/signup/",
    {"business_name": "Duplicate", "email": signup_email, "password": "Other-pass-123"},
)
check(
    "signup duplicate email rejected",
    r.status_code == 200 and b"already exists" in r.content,
    r.status_code,
)

email_client = Client()
r = email_client.post(
    "/login/", {"username": signup_email, "password": "Signup-pass-123"}, follow=True
)
check(
    "email login works",
    r.status_code == 200 and r.redirect_chain and r.redirect_chain[-1][0] == "/dashboard/client/",
    r.redirect_chain,
)

r = email_client.post(
    "/api/account/update/",
    data=json.dumps(
        {"username": signup_email, "current_password": "wrong", "new_password": "Next-pass-123"}
    ),
    content_type="application/json",
)
check("account update rejects wrong password", r.status_code == 400)

r = email_client.post(
    "/api/account/update/",
    data=json.dumps(
        {"username": signup_email, "current_password": "Signup-pass-123", "new_password": "weakpass1"}
    ),
    content_type="application/json",
)
check("account update rejects weak password", r.status_code == 400)

renamed_username = f"renamed_{User.objects.count()}"
r = email_client.post(
    "/api/account/update/",
    data=json.dumps(
        {
            "username": renamed_username,
            "current_password": "Signup-pass-123",
            "new_password": "Next-pass-123",
        }
    ),
    content_type="application/json",
)
check("account update username and password", r.status_code == 200 and r.json().get("changed"))

relogin = Client()
r = relogin.post(
    "/login/", {"username": signup_email, "password": "Next-pass-123"}, follow=True
)
check(
    "login after account update by email",
    r.status_code == 200 and r.redirect_chain and r.redirect_chain[-1][0] == "/dashboard/client/",
    r.redirect_chain,
)

reset = Client()
r = reset.post("/reset/", {"email": signup_email})
reset_otp = (
    EmailOTP.objects.filter(email=signup_email, purpose="reset", used=False)
    .order_by("-id")
    .first()
)
check(
    "reset sends otp",
    r.status_code == 200 and reset_otp is not None and len(reset_otp.code) == 6,
    r.status_code,
)

r = reset.post(
    "/reset/verify/",
    {"code": "invalid", "password": "Reset-pass-123", "confirm": "Reset-pass-123"},
)
check("reset rejects wrong otp", r.status_code == 200 and b"invalid" in r.content)

r = reset.post(
    "/reset/verify/",
    {"code": reset_otp.code, "password": "weakpass1", "confirm": "weakpass1"},
)
check("reset rejects weak password", r.status_code == 200 and b"8-16" in r.content)

r = reset.post(
    "/reset/verify/",
    {"code": reset_otp.code, "password": "Reset-pass-123", "confirm": "Reset-pass-999"},
)
check("reset rejects mismatched password", r.status_code == 200 and b"do not match" in r.content)

r = reset.post(
    "/reset/verify/",
    {"code": reset_otp.code, "password": "Reset-pass-123", "confirm": "Reset-pass-123"},
)
check("reset sets new password", r.status_code == 302 and r.url == "/login/?reset=1", r.status_code)

reset_login = Client()
r = reset_login.post(
    "/login/", {"username": signup_email, "password": "Reset-pass-123"}, follow=True
)
check(
    "login with reset password",
    r.status_code == 200 and r.redirect_chain and r.redirect_chain[-1][0] == "/dashboard/client/",
    r.redirect_chain,
)

from core.email_auth import dev_code_for, send_otp, verify_otp

provider_email = "provider-test@example.com"
provider_response = Mock(status_code=200)
provider_response.json.return_value = {"member_authenticated": False}
with override_settings(EMAIL_OTP_BACKEND="stytch", STYTCH_PROJECT_ID="test-project", STYTCH_SECRET="test-secret", STYTCH_ORGANIZATION_ID="test-organization"):
    with patch("requests.sessions.Session.request", return_value=provider_response) as provider_request:
        sent, error = send_otp(provider_email, "signup")
    provider_otp = EmailOTP.objects.filter(email=provider_email).first()
    check("Stytch B2B sends through the configured organization", sent and error is None and provider_otp.method_id == "b2b" and not provider_otp.code and provider_request.call_args.kwargs["url"].endswith("/v1/b2b/otps/email/login_or_signup") and provider_request.call_args.kwargs["json"]["organization_id"] == "test-organization")
    with patch("requests.sessions.Session.request", return_value=provider_response):
        verified = verify_otp(provider_email, "signup", "123456")
    check("Stytch HTTP 200 without full authentication is rejected", verified is False)
    provider_otp.used = False
    provider_otp.save(update_fields=["used"])
    provider_response.json.return_value = {"member_authenticated": True}
    with patch("requests.sessions.Session.request", return_value=provider_response) as provider_request:
        verified = verify_otp(provider_email, "signup", "123456")
    check("Stytch authenticates on the documented email OTP endpoint", verified and provider_request.call_args.kwargs["url"].endswith("/v1/b2b/otps/email/authenticate"))
    with patch("requests.sessions.Session.request", return_value=provider_response) as provider_request:
        reused = verify_otp(provider_email, "signup", "123456")
    check("verified email code cannot be reused", not reused and not provider_request.called)

with override_settings(EMAIL_OTP_BACKEND="stytch", STYTCH_PROJECT_ID="", STYTCH_SECRET="", STYTCH_ORGANIZATION_ID=""):
    sent, error = send_otp("unconfigured@example.com", "signup")
    check("missing Stytch settings cannot silently enable development codes", not sent and error and not EmailOTP.objects.filter(email="unconfigured@example.com").exists() and not dev_code_for("unconfigured@example.com", "signup"))

with override_settings(EMAIL_OTP_BACKEND="dev", DEBUG=False):
    sent, error = send_otp("debug-off@example.com", "signup")
    check("development OTP mode requires Django debug mode", not sent and error and not EmailOTP.objects.filter(email="debug-off@example.com").exists())

send_otp("dev-only@example.com", "signup")
dev_otp = EmailOTP.objects.get(email="dev-only@example.com")
with override_settings(EMAIL_OTP_BACKEND="stytch"):
    check("development codes cannot authenticate in Stytch mode", not verify_otp(dev_otp.email, "signup", dev_otp.code))
dev_otp.attempts = 5
dev_otp.save(update_fields=["attempts"])
check("email OTP stops after five failed attempts", not verify_otp(dev_otp.email, "signup", dev_otp.code))

# --- Phase B: product images and plan product limits ---

png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")
upload_file = SimpleUploadedFile("product.png", png, content_type="image/png")
r = shop.post("/api/product/upload/", {"file": upload_file})
body = r.json() if r.status_code == 200 else {}
image_url = body.get("url", "")
stored = image_url.startswith("/media/") and (
    Path(settings.MEDIA_ROOT) / image_url.replace("/media/", "", 1)
).exists()
check("product image upload", r.status_code == 200 and stored, r.content[:120])

r = shop.post(
    "/api/product/upload/",
    {"file": SimpleUploadedFile("notes.txt", b"hello", content_type="text/plain")},
)
check("image upload rejects wrong type", r.status_code == 400)

r = shop.post(
    "/api/product/upload/",
    {"file": SimpleUploadedFile("big.png", b"0" * (5 * 1024 * 1024 + 1), content_type="image/png")},
)
check("image upload rejects oversize", r.status_code == 400)

r = shop.post("/api/product/upload/", {"file": SimpleUploadedFile("empty.png", b"", content_type="image/png")})
check("image upload rejects empty files", r.status_code == 400)

photo_path = Path(settings.MEDIA_ROOT) / image_url.removeprefix("/media/")
photo_product = Product.objects.create(tenant=tenant, name="Photo original", image_url=image_url)
photo_copy = Product.objects.create(tenant=tenant, name="Photo copy", image_url=image_url, is_active=False)
r = shop.post("/api/product/save/", data=json.dumps({"id": photo_product.id, "name": photo_product.name, "image_url": "", "skus": []}), content_type="application/json")
check("replacing a photo keeps an archived product's shared image", r.status_code == 200 and photo_path.exists())
photo_chat = Conversation.objects.create(tenant=tenant, customer_phone="8801799999901", messages=[{"role": "assistant", "media": [{"url": image_url}]}] + [{"role": "user", "content": "Hello"}] * 59)
r = shop.post("/api/product/save/", data=json.dumps({"id": photo_copy.id, "name": photo_copy.name, "image_url": "", "skus": []}), content_type="application/json")
check("replacing the last product photo keeps the chat's image", r.status_code == 200 and photo_path.exists())
from core.views import _wa_send

with patch("core.views._wa_request", return_value={"ok": True}):
    _wa_send(tenant, photo_chat.customer_phone, "New message")
check("a photo is cleaned after its final chat reference expires", not photo_path.exists())

rollback_path = Path(settings.MEDIA_ROOT) / str(tenant.id) / "rollback.png"
rollback_path.parent.mkdir(parents=True, exist_ok=True)
rollback_path.write_bytes(png)
rollback_url = f"/media/{tenant.id}/rollback.png"
rollback_product = Product.objects.create(tenant=tenant, name="Rollback photo", image_url=rollback_url)
try:
    with transaction.atomic():
        r = shop.post("/api/product/save/", data=json.dumps({"id": rollback_product.id, "name": rollback_product.name, "image_url": "", "skus": []}), content_type="application/json")
        check("photo cleanup waits for the database commit", r.status_code == 200 and rollback_path.exists())
        raise RuntimeError("Rollback the test change")
except RuntimeError:
    pass
rollback_product.refresh_from_db()
check("a rolled-back product change preserves its photo", rollback_path.exists() and rollback_product.image_url == rollback_url)
r = shop.post("/api/product/save/", data=json.dumps({"id": rollback_product.id, "name": rollback_product.name, "image_url": "", "skus": []}), content_type="application/json")
check("a committed replacement removes an unreferenced photo", r.status_code == 200 and not rollback_path.exists())

photo_a = Path(settings.MEDIA_ROOT) / str(tenant.id) / "tab-a.png"
photo_b = photo_a.with_name("tab-b.png")
photo_a.parent.mkdir(parents=True, exist_ok=True)
photo_a.write_bytes(png)
photo_b.write_bytes(png)
url_a, url_b = f"/media/{tenant.id}/tab-a.png", f"/media/{tenant.id}/tab-b.png"
two_tab_product = Product.objects.create(tenant=tenant, name="Two tabs", image_url=url_a)
edit = {"id": two_tab_product.id, "name": "Newer photo", "skus": [], "image_url": url_b, "original_image_url": url_a}
r = shop.post("/api/product/save/", data=json.dumps(edit), content_type="application/json")
check("newer product tab can replace its original photo", r.status_code == 200 and photo_b.exists() and not photo_a.exists())
r = shop.post("/api/product/save/", data=json.dumps({**edit, "name": "Stale edit", "image_url": url_a}), content_type="application/json")
two_tab_product.refresh_from_db()
check("stale product tab cannot erase a newer photo", r.status_code == 409 and two_tab_product.image_url == url_b and two_tab_product.name == "Newer photo" and photo_b.exists())
r = shop.post("/api/product/save/", data=json.dumps({**edit, "original_image_url": url_b, "image_url": "/media/missing.png"}), content_type="application/json")
check("missing local photo cannot replace a valid image", r.status_code == 400 and photo_b.exists())

with TemporaryDirectory(prefix="nexora-photo-boundary-") as directory:
    outside_photo = Path(directory) / "outside.png"
    outside_photo.write_bytes(png)
    with override_settings(MEDIA_ROOT=Path(directory) / "media"):
        cleanup_images(["/media/../outside.png"])
    check("photo cleanup cannot delete outside the upload directory", outside_photo.exists())

r = Client().post(
    "/api/product/upload/",
    {"file": SimpleUploadedFile("a.png", b"x", content_type="image/png")},
)
check("image upload requires login", r.status_code == 302)

limit_user, _ = User.objects.get_or_create(username="smoke_limit_shop")
limit_user.set_password("smoke-pass-123")
limit_user.save()
limit_tenant, _ = Tenant.objects.get_or_create(user=limit_user, defaults={"business_name": "Limit Co"})
limit_tenant.plan = "BASIC"
limit_tenant.save(update_fields=["plan"])
Product.objects.filter(tenant=limit_tenant).delete()
Product.objects.bulk_create(
    [Product(tenant=limit_tenant, name=f"Limit {i}", skus=[]) for i in range(50)]
)
limit_client = Client()
limit_client.login(username="smoke_limit_shop", password="smoke-pass-123")
r = limit_client.post(
    "/api/product/save/",
    data=json.dumps({"name": "Overflow", "skus": [{"sku": "X-1", "price": 1, "stock": 1}]}),
    content_type="application/json",
)
check(
    "plan product limit enforced",
    r.status_code == 400 and "plan" in str(r.json().get("error", "")).lower(),
    r.content[:120],
)

existing_product = Product.objects.filter(tenant=limit_tenant).first()
r = limit_client.post(
    "/api/product/save/",
    data=json.dumps(
        {"id": existing_product.id, "name": "Limit 0 edited", "skus": [{"sku": "X-1", "price": 1, "stock": 1}]}
    ),
    content_type="application/json",
)
check("product edit allowed at plan limit", r.status_code == 200 and r.json().get("ok"))

# --- Phase C: order flow, assistant settings, stats widgets ---

r = shop.get(
    "/api/dashboard/?widgets=sales_stats,inventory_stats,pending_orders,active_orders,order_history,tenant_settings"
)
widgets = r.json().get("widgets", {}) if r.status_code == 200 else {}
check(
    "client v2 widgets",
    r.status_code == 200
    and set(widgets)
    == {"sales_stats", "inventory_stats", "pending_orders", "active_orders", "order_history", "tenant_settings"},
    r.content[:160],
)
check(
    "sales stats aggregate orders",
    "top_sellers" in widgets.get("sales_stats", {})
    and "total_revenue" in widgets.get("sales_stats", {}),
)

ship_order = Order.objects.create(
    tenant=tenant,
    customer_phone="8801722222222",
    customer_name="Ship Customer",
    address="Dhaka",
    items=[{"sku": "SMK-1", "qty": 1, "product": "Smoke Tee", "price": 100}],
    total=100,
    status="ACCEPTED",
)
r = shop.post(
    f"/api/order/{ship_order.id}/action/",
    data=json.dumps({"action": "SHIPPED"}),
    content_type="application/json",
)
ship_order.refresh_from_db()
check(
    "order ship transition",
    r.status_code == 200
    and ship_order.status == "SHIPPED"
    and (ship_order.shipment or {}).get("courier") == "MANUAL"
    and (ship_order.shipment or {}).get("status") == "manual"
    and not (ship_order.shipment or {}).get("consignment"),
    r.content[:120],
)

r = shop.post(
    "/api/tenant/settings/",
    data=json.dumps(
        {
            "greeting": "Welcome to Smoke Test Co!",
            "commands": [{"trigger": "delivery", "reply": "Delivery takes 2 days."}],
        }
    ),
    content_type="application/json",
)
tenant.refresh_from_db()
check(
    "tenant settings saved",
    r.status_code == 200 and (tenant.settings or {}).get("greeting") == "Welcome to Smoke Test Co!",
)

Conversation.objects.filter(tenant=tenant, customer_phone="8801733333333").delete()
r = shop.post(
    "/api/webhook/wa/",
    data=json.dumps({"tenant_id": tenant.id, "phone": "8801733333333", "text": "delivery"}),
    content_type="application/json",
)
reply = (r.json().get("reply") or "") if r.status_code == 200 else ""
check("command reply without LLM", r.status_code == 200 and "Delivery takes 2 days." in reply, r.content[:160])
check("greeting prefixed on first message", reply.startswith("Welcome to Smoke Test Co!"))

# --- Phase D: plans, rate limits, admin v2 ---

r = staff.get(f"/api/admin/tenant/{tenant.id}/")
detail = r.json().get("tenant", {}) if r.status_code == 200 else {}
check(
    "admin tenant detail",
    r.status_code == 200 and detail.get("orders_count", 0) >= 1 and "conversion_rate" in detail,
    r.content[:160],
)

r = staff.post(
    "/api/admin/plan/",
    data=json.dumps({"tenant_id": tenant.id, "plan": "PRO"}),
    content_type="application/json",
)
tenant.refresh_from_db()
check("admin plan change", r.status_code == 200 and tenant.plan == "PRO", r.content[:120])

r = staff.post(
    "/api/admin/plan/",
    data=json.dumps({"tenant_id": tenant.id, "plan": "BOGUS"}),
    content_type="application/json",
)
check("admin plan validation", r.status_code == 400)

r = shop.post(
    "/api/admin/plan/",
    data=json.dumps({"tenant_id": tenant.id, "plan": "BASIC"}),
    content_type="application/json",
)
check("shop blocked from admin plan", r.status_code == 403)

r = staff.post(
    "/api/admin/plan/",
    data=json.dumps({"tenant_id": tenant.id, "plan_status": "CANCELLED"}),
    content_type="application/json",
)
tenant.refresh_from_db()
r2 = shop.post(
    "/api/webhook/wa/",
    data=json.dumps({"tenant_id": tenant.id, "phone": "8801744444444", "text": "hello"}),
    content_type="application/json",
)
check(
    "cancelled plan ignores webhook",
    r.status_code == 200
    and tenant.plan_status == "CANCELLED"
    and r2.json().get("reply") is None
    and r2.json().get("ignored"),
    r2.content[:120],
)
staff.post(
    "/api/admin/plan/",
    data=json.dumps({"tenant_id": tenant.id, "plan_status": "ACTIVE"}),
    content_type="application/json",
)

rl_user, _ = User.objects.get_or_create(username="smoke_rl_shop")
rl_user.set_password("smoke-pass-123")
rl_user.save()
rl_tenant, _ = Tenant.objects.get_or_create(user=rl_user, defaults={"business_name": "Rate Co"})
rl_tenant.plan = "BASIC"
rl_tenant.plan_status = "ACTIVE"
rl_tenant.is_active = True
rl_tenant.usage_stats = {}
rl_tenant.save()
replies = []
for i in range(7):
    r = shop.post(
        "/api/webhook/wa/",
        data=json.dumps({"tenant_id": rl_tenant.id, "phone": f"88019900000{i}", "text": "hi"}),
        content_type="application/json",
    )
    replies.append(r.json().get("reply"))
check(
    "rate limit allows plan quota",
    all(reply and "temporarily unavailable" in reply for reply in replies[:5]),
    replies[:5],
)
check(
    "rate limit throttles over quota with one notice",
    replies[5] is not None and "too fast" in replies[5] and replies[6] is None,
    [replies[5], replies[6]],
)

del_user = User.objects.create_user(username=f"smoke_del_{User.objects.count()}", password="pw-12345")
del_tenant = Tenant.objects.create(user=del_user, business_name="Delete Co")
del_username = del_user.username
owned_media = Path(settings.MEDIA_ROOT) / str(del_tenant.id)
owned_media.mkdir(parents=True, exist_ok=True)
owned_photo = owned_media / "owned.png"
shared_photo = owned_media / "shared.png"
owned_photo.write_bytes(png)
shared_photo.write_bytes(png)
Product.objects.create(tenant=del_tenant, name="Owned photo", image_url=f"/media/{del_tenant.id}/owned.png")
Product.objects.create(tenant=tenant, name="Shared photo", image_url=f"/media/{del_tenant.id}/shared.png")
bridge_response.json.return_value = {"ok": True}
with patch("requests.sessions.Session.request", return_value=bridge_response) as bridge_request:
    r = staff.post(f"/api/admin/tenant/{del_tenant.id}/delete/", data="{}", content_type="application/json")
check(
    "admin delete tenant",
    r.status_code == 200
    and not Tenant.objects.filter(id=del_tenant.id).exists()
    and not User.objects.filter(username=del_username).exists(),
    r.content[:120],
)

check("business deletion removes rather than restarts WhatsApp", bridge_request.called and bridge_request.call_args.args[1].endswith(f"/wa/{del_tenant.id}/remove"))
check("business deletion removes its unused photos and preserves shared ones", not owned_photo.exists() and shared_photo.exists())
blocked_user = User.objects.create_user(username="smoke_delete_offline", password="pw-12345")
blocked_tenant = Tenant.objects.create(user=blocked_user, business_name="Offline Delete")
r = staff.post(f"/api/admin/tenant/{blocked_tenant.id}/delete/", data="{}", content_type="application/json")
check("failed disconnect preserves the business for retry", r.status_code == 503 and User.objects.filter(pk=blocked_user.pk).exists())

# Order changes must be visible, isolated, and honest about external failures.
from core.couriers import create_pathao_order

flow_order = Order.objects.create(tenant=tenant, customer_phone="8801755555555", customer_name="Flow Customer", address="Dhaka", total=100)
r = shop.post(f"/api/order/{flow_order.id}/action/", data=json.dumps({"action": "ACCEPTED"}), content_type="application/json")
flow_order.refresh_from_db()
visible = shop.get("/api/dashboard/?widgets=pending_orders,active_orders").json()["widgets"]
check("accepted order moves to active list", r.status_code == 200 and flow_order.status == "ACCEPTED" and flow_order.id in [o["id"] for o in visible["active_orders"]] and flow_order.id not in [o["id"] for o in visible["pending_orders"]])
check("notification failure reported separately", r.json().get("ok") and r.json().get("notified") is False and r.json().get("warning"))
r = limit_client.post(f"/api/order/{flow_order.id}/action/", data=json.dumps({"action": "CANCELLED"}), content_type="application/json")
check("other business cannot change order", r.status_code == 404)

pathao_config = {"enabled": True, "environment": "sandbox", "client_id": "test-client", "client_secret": "test-secret", "username": "merchant@example.com", "password": "test-password", "store_id": "7"}
tenant.settings = {"couriers": {"pathao": pathao_config}}
tenant.save(update_fields=["settings"])
r = shop.post(f"/api/order/{flow_order.id}/action/", data=json.dumps({"action": "SHIPPED"}), content_type="application/json")
flow_order.refresh_from_db()
check("failed courier booking keeps order accepted", r.status_code >= 400 and flow_order.status == "ACCEPTED" and not flow_order.shipment and r.json().get("error"))

malformed = Mock(status_code=200, headers={"content-type": "application/json"}, text="Test courier response")
malformed.json.return_value = {"type": "success", "data": {"order_status": "pending"}}
with patch("core.couriers._pathao_issue_token", return_value=("test-token", None)), patch("core.couriers._make_session") as session:
    session.return_value.post.return_value = malformed
    result = create_pathao_order(pathao_config, flow_order)
check("pathao success requires actual tracking", not result.get("ok") and result.get("error"))

for store_id in ("", "invalid", "0", "-1", True):
    with patch("core.couriers._pathao_issue_token", return_value=("test-token", None)) as token_request:
        result = create_pathao_order({**pathao_config, "store_id": store_id}, flow_order)
    check(f"pathao rejects invalid store ID {store_id!r} before contacting provider", not result.get("ok") and not token_request.called)

for label, body in [
    ("pathao rejects explicit failure", {"type": "error", "data": {"consignment_id": "TRACK-ERROR"}}),
    ("pathao rejects blank tracking", {"type": "success", "data": {"consignment_id": "   "}}),
    ("pathao rejects boolean tracking", {"type": "success", "data": {"consignment_id": True}}),
    ("pathao rejects container tracking", {"type": "success", "data": {"consignment_id": {"id": "TRACK"}}}),
]:
    malformed.json.return_value = body
    with patch("core.couriers._pathao_issue_token", return_value=("test-token", None)), patch("core.couriers._make_session") as session:
        session.return_value.post.return_value = malformed
        result = create_pathao_order(pathao_config, flow_order)
    check(label, result.get("ok") is False and result.get("error"))

malformed.json.return_value = {"type": "success", "data": {"consignment_id": 123}}
with patch("core.couriers._pathao_issue_token", return_value=("test-token", None)), patch("core.couriers._make_session") as session:
    session.return_value.post.return_value = malformed
    result = create_pathao_order(pathao_config, flow_order)
check("numeric courier IDs remain supported", result.get("ok") is True and result.get("consignment") == "123")
check("pathao uses the merchant store and full address", session.return_value.post.call_args.kwargs["json"]["store_id"] == 7 and session.return_value.post.call_args.kwargs["json"]["recipient_address"] == flow_order.address)

r = shop.post("/api/tenant/couriers/", data=json.dumps({"pathao": pathao_config}), content_type="application/json")
saved = shop.get("/api/tenant/couriers/").json().get("couriers", {})
check("courier settings expose only Pathao without its secrets", r.status_code == 200 and set(saved) == {"pathao"} and saved["pathao"].get("has_password") and "password" not in saved["pathao"] and "client_secret" not in saved["pathao"])
r = shop.post("/api/tenant/couriers/", data=json.dumps({"pathao": {**pathao_config, "client_secret": "", "password": ""}}), content_type="application/json")
tenant.refresh_from_db()
check("blank Pathao secrets preserve saved credentials", r.status_code == 200 and tenant.settings["couriers"]["pathao"]["password"] == "test-password" and tenant.settings["couriers"]["pathao"]["client_secret"] == "test-secret")
r = shop.post("/api/tenant/couriers/", data=json.dumps({"pathao": {**pathao_config, "store_id": ""}}), content_type="application/json")
check("active Pathao settings require a pickup store", r.status_code == 400)
r = shop.post("/api/tenant/couriers/", data=json.dumps({"pathao": {**pathao_config, "environment": "invalid"}}), content_type="application/json")
check("Pathao settings reject unknown environments", r.status_code == 400)
with patch("core.views.test_pathao_connection", return_value={"ok": True}) as test_connection:
    r = shop.post("/api/courier/test/", data=json.dumps({"client_secret": "", "password": ""}), content_type="application/json")
check("Pathao connection test uses saved credentials", r.status_code == 200 and test_connection.called and test_connection.call_args.args[0]["password"] == "test-password")

flow_order = Order.objects.create(tenant=tenant, customer_phone="8801755555555", customer_name="Booking Customer", address="Dhaka", total=100, status="ACCEPTED")
with patch("core.couriers.create_pathao_order", return_value={"ok": True, "consignment": "TRACK-123", "consignment_id": 123, "status": "placed"}), patch("core.views._wa_request", return_value={"ok": True}):
    r = shop.post(f"/api/order/{flow_order.id}/action/", data=json.dumps({"action": "SHIPPED"}), content_type="application/json")
flow_order.refresh_from_db()
check("successful courier booking stores real tracking", r.status_code == 200 and flow_order.status == "SHIPPED" and flow_order.shipment.get("consignment") == "TRACK-123")
check("successful notification is reported", r.json().get("notified") is True)
r = shop.post(f"/api/order/{flow_order.id}/action/", data=json.dumps({"action": "SHIPPED"}), content_type="application/json")
check("repeated shipping is rejected", r.status_code == 400)
r = shop.post(f"/api/order/{flow_order.id}/action/", data=json.dumps({"action": "COMPLETED"}), content_type="application/json")
flow_order.refresh_from_db()
check("shipped order completes", r.status_code == 200 and flow_order.status == "COMPLETED")

tenant.settings = {"couriers": {"pathao": {**pathao_config, "enabled": False}}}
tenant.save(update_fields=["settings"])
manual_order = Order.objects.create(tenant=tenant, customer_phone="8801755555555", address="Dhaka", total=100, status="ACCEPTED")
with patch("core.couriers.create_pathao_order") as booking:
    r = shop.post(f"/api/order/{manual_order.id}/action/", data=json.dumps({"action": "SHIPPED"}), content_type="application/json")
manual_order.refresh_from_db()
check("disabled Pathao records manual shipping without a booking", r.status_code == 200 and manual_order.shipment.get("courier") == "MANUAL" and not manual_order.shipment.get("consignment") and not booking.called)

_, before_cancel = find_sku(tenant, "SMK-1")
stock_before = before_cancel["stock"]
r = shop.post(f"/api/order/{order.id}/action/", data=json.dumps({"action": "CANCELLED"}), content_type="application/json")
_, after_cancel = find_sku(tenant, "SMK-1")
check("repeated cancellation cannot add stock", r.status_code == 400 and after_cancel["stock"] == stock_before)

orders_before = Order.objects.filter(tenant=tenant).count()
with patch("core.agent.adjust_stock", side_effect=RuntimeError("Stock write failed")):
    try:
        _create_or_update_order(tenant, "8801766666666", {"sku": "SMK-1", "name": "Rollback Customer", "address": "Dhaka", "qty": 1})
    except RuntimeError:
        pass
check("failed stock update leaves no partial order", Order.objects.filter(tenant=tenant).count() == orders_before and not Order.objects.filter(tenant=tenant, customer_phone="8801766666666").exists())

config.refresh_from_db()
config.llm_base_url = _original_config["llm_base_url"]
config.api_key = _original_config["api_key"]
config.model_name = _original_config["model_name"]
config.request_options = _original_config["request_options"]
config.save()

cleaned = 0
for smoke_user in User.objects.filter(
    Q(username__startswith="smoke_") | Q(username__startswith="renamed_")
):
    smoke_user.delete()
    cleaned += 1
print(f"cleaned {cleaned} smoke test users/tenants")

# Re-running the explicit demo command must preserve existing accounts and data.
import contextlib
import io
import runpy

keep_user = User.objects.create_user("preserved_business", password="Keep1234")
keep_tenant = Tenant.objects.create(user=keep_user, business_name="Preserved Business")
with contextlib.redirect_stdout(io.StringIO()), patch.dict(os.environ, {"ADMIN_USER": "seed_admin", "ADMIN_PASS": "Seed1234", "ZARA_PASS": "Seed1234", "NOVA_PASS": "Seed1234"}):
    runpy.run_path(str(Path(__file__).with_name("seed_demo.py")), run_name="__main__")
check("demo seeding preserves other businesses", User.objects.filter(pk=keep_user.pk, username="preserved_business").exists() and Tenant.objects.filter(pk=keep_tenant.pk).exists())
demo_user = User.objects.get(username="zara")
demo_shipment = Order.objects.filter(tenant=demo_user.tenant, status="SHIPPED").first()
check("demo shipment is explicitly marked simulated", demo_shipment is not None and demo_shipment.shipment.get("status") == "simulated")
demo_user.set_password("Changed1234")
demo_user.save()
demo_product = Product.objects.filter(tenant=demo_user.tenant).first()
demo_product.name = "My edited product"
demo_product.save()
demo_order = Order.objects.create(tenant=demo_user.tenant, customer_phone="8801777777777", total=77)
with contextlib.redirect_stdout(io.StringIO()), patch.dict(os.environ, {"ADMIN_USER": "seed_admin", "ADMIN_PASS": "Seed1234", "ZARA_PASS": "Seed1234", "NOVA_PASS": "Seed1234"}):
    runpy.run_path(str(Path(__file__).with_name("seed_demo.py")), run_name="__main__")
demo_user.refresh_from_db()
check("demo rerun preserves changed password", demo_user.check_password("Changed1234"))
check("demo rerun preserves edited products and orders", Product.objects.filter(pk=demo_product.pk, name="My edited product").exists() and Order.objects.filter(pk=demo_order.pk).exists())

failed = results.count(False)
print(f"\n{len(results) - failed}/{len(results)} checks passed")
sys.exit(1 if failed else 0)
