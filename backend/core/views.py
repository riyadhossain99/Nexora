import json
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import requests
from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .agent import run_agent
from .agent import _log_error as log_error
from .couriers import dispatch, pathao_config_error, test_pathao_connection
from .email_auth import CODE_ERROR, dev_code_for, password_error, send_otp, verify_otp
from .models import Conversation, Order, Product, SystemConfig, Tenant, adjust_stock, cleanup_images, conversation_images, local_image_path, messages_per_min, product_limit
from .widgets import ADMIN_WIDGETS, CLIENT_WIDGETS

IMAGE_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024


def _make_http_session():
    session = requests.Session()
    session.trust_env = False
    session.proxies = {"http": None, "https": None}
    return session


def _json(request):
    try:
        return json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return {}


def _wa_request(path, payload=None, method="POST"):
    try:
        session = _make_http_session()
        response = session.request(method, f"{settings.WA_BRIDGE_URL}{path}", json=(payload or {}) if method == "POST" else None, timeout=20)
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict):
            raise ValueError("WhatsApp bridge returned an invalid response")
        return result
    except Exception as exc:
        log_error(SystemConfig.load(), f"wa_bridge {method} {path}: {exc}")
        return {"error": str(exc)}


def _wa_send(tenant, phone, text, image=None, caption=None):
    payload = {"phone": phone, "text": text}
    if image:
        payload["image"] = image
        if caption:
            payload["caption"] = caption
    result = _wa_request(f"/wa/{tenant.id}/send", payload)
    if result.get("error") or result.get("ok") is not True:
        log_error(SystemConfig.load(), f"wa_bridge send tenant={tenant.id}: {result}")
        return False
    try:
        conv, _ = Conversation.objects.get_or_create(tenant=tenant, customer_phone=phone)
        history = list(conv.messages or [])
        old_images = conversation_images(history)
        msg_entry = {"role": "assistant", "content": text}
        if image:
            msg_entry["media"] = [{"url": image, "caption": caption or ""}]
        history.append(msg_entry)
        conv.messages = history[-60:]
        conv.save(update_fields=["messages", "updated_at"])
        cleanup_images(old_images)
    except Exception:
        pass
    return True


def _start_otp_flow(request, email, purpose):
    request.session["otp_flow"] = {"email": email, "purpose": purpose}


def _otp_flow(request, purpose):
    flow = request.session.get("otp_flow") or {}
    return flow if flow.get("purpose") == purpose else {}


def login_view(request):
    if request.user.is_authenticated:
        return redirect("/")
    error = None
    if request.method == "POST":
        identifier = str(request.POST.get("username") or "").strip()
        password = str(request.POST.get("password") or "")
        username = identifier
        if "@" in identifier:
            match = User.objects.filter(email__iexact=identifier).first()
            if match:
                username = match.username
        user = authenticate(request, username=username, password=password)
        if user:
            login(request, user)
            return redirect("/")
        candidate = User.objects.filter(
            Q(username__iexact=username) | Q(email__iexact=identifier)
        ).first()
        if candidate and not candidate.is_active and candidate.check_password(password):
            _start_otp_flow(request, candidate.email or candidate.username, "signup")
            return redirect("/signup/verify/")
        error = "Invalid email/username or password."
    return render(request, "auth.html", {"screen": "login", "title": "Sign in", "error": error, "reset_ok": request.GET.get("reset")})


def signup_view(request):
    if request.user.is_authenticated:
        return redirect("/")
    error = None
    values = {"business_name": "", "email": ""}
    if request.method == "POST":
        business_name = str(request.POST.get("business_name") or "").strip()
        email = str(request.POST.get("email") or "").strip().lower()
        password = str(request.POST.get("password") or "")
        values = {"business_name": business_name, "email": email}
        existing = User.objects.filter(
            Q(username__iexact=email) | Q(email__iexact=email)
        ).first()
        rule_error = password_error(password)
        if not business_name or not email or not password:
            error = "Business name, email and password are required."
        elif rule_error:
            error = rule_error
        elif existing and existing.is_active:
            error = "An account with this email already exists. Try signing in instead."
        else:
            sent, send_error = send_otp(email, "signup")
            if not sent:
                error = send_error
            else:
                if existing:
                    existing.email = email
                    existing.set_password(password)
                    existing.save()
                    tenant = getattr(existing, "tenant", None)
                    if tenant:
                        tenant.business_name = business_name
                        tenant.save(update_fields=["business_name"])
                else:
                    user = User.objects.create_user(username=email, email=email, password=password)
                    user.is_active = False
                    user.save(update_fields=["is_active"])
                    Tenant.objects.create(user=user, business_name=business_name, plan="BASIC")
                _start_otp_flow(request, email, "signup")
                return redirect("/signup/verify/")
    return render(request, "auth.html", {"screen": "signup", "title": "Create account", "error": error, "values": values})


def signup_verify_view(request):
    flow = _otp_flow(request, "signup")
    if not flow:
        return redirect("/signup/")
    error = None
    notice = None
    if request.method == "POST":
        if "resend" in request.POST:
            sent, send_error = send_otp(flow["email"], "signup")
            notice = "A new code was sent." if sent else None
            error = send_error
        else:
            code = str(request.POST.get("code") or "").strip()
            if verify_otp(flow["email"], "signup", code):
                user = User.objects.filter(
                    Q(username__iexact=flow["email"]) | Q(email__iexact=flow["email"])
                ).first()
                if user:
                    user.is_active = True
                    user.save(update_fields=["is_active"])
                    login(request, user)
                    request.session.pop("otp_flow", None)
                    return redirect("/dashboard/client/")
                error = "Account not found. Please sign up again."
            else:
                error = CODE_ERROR
    return render(
        request,
        "auth.html",
        {
            "screen": "verify",
            "title": "Verify email",
            "email": flow["email"],
            "purpose": "signup",
            "error": error,
            "notice": notice,
            "dev_code": dev_code_for(flow["email"], "signup"),
        },
    )


def reset_request_view(request):
    if request.user.is_authenticated:
        return redirect("/")
    sent = False
    error = None
    values = {"email": ""}
    if request.method == "POST":
        email = str(request.POST.get("email") or "").strip()
        values = {"email": email}
        user = (
            User.objects.filter(
                Q(email__iexact=email) | Q(username__iexact=email), is_active=True
            ).first()
            if email
            else None
        )
        if user and user.email:
            sent, error = send_otp(user.email, "reset")
            if sent:
                _start_otp_flow(request, user.email, "reset")
        else:
            sent = True
    return render(request, "auth.html", {"screen": "reset", "title": "Reset password", "sent": sent, "error": error, "values": values})


def reset_verify_view(request):
    flow = _otp_flow(request, "reset")
    if not flow:
        return redirect("/reset/")
    error = None
    notice = None
    if request.method == "POST":
        if "resend" in request.POST:
            sent, send_error = send_otp(flow["email"], "reset")
            notice = "A new code was sent." if sent else None
            error = send_error
        else:
            code = str(request.POST.get("code") or "").strip()
            password = str(request.POST.get("password") or "")
            confirm = str(request.POST.get("confirm") or "")
            rule_error = password_error(password)
            if rule_error:
                error = rule_error
            elif password != confirm:
                error = "Passwords do not match."
            elif not verify_otp(flow["email"], "reset", code):
                error = CODE_ERROR
            else:
                user = User.objects.filter(email__iexact=flow["email"], is_active=True).first()
                if not user:
                    error = "Account not found. Please try again."
                else:
                    user.set_password(password)
                    user.save()
                    request.session.pop("otp_flow", None)
                    return redirect("/login/?reset=1")
    return render(
        request,
        "auth.html",
        {
            "screen": "verify",
            "title": "Reset password",
            "email": flow["email"],
            "purpose": "reset",
            "error": error,
            "notice": notice,
            "dev_code": dev_code_for(flow["email"], "reset"),
        },
    )


def logout_view(request):
    logout(request)
    return redirect("/login/")


def home(request):
    if not request.user.is_authenticated:
        return render(request, "landing.html")
    if request.user.is_staff:
        return redirect("/dashboard/admin/")
    return redirect("/dashboard/client/")


@login_required(login_url="/login/")
def client_dashboard(request):
    if request.user.is_staff:
        return redirect("/dashboard/admin/")
    tenant = getattr(request.user, "tenant", None)
    if not tenant:
        return HttpResponseForbidden("No business account linked to this user.")
    return render(
        request,
        "client.html",
        {"tenant": tenant, "debug": settings.DEBUG},
    )


@login_required(login_url="/login/")
def admin_dashboard(request):
    if not request.user.is_staff:
        return redirect("/dashboard/client/")
    return render(request, "admin.html", {"debug": settings.DEBUG})


@login_required(login_url="/login/")
def api_dashboard(request):
    keys = [key.strip() for key in request.GET.get("widgets", "").split(",") if key.strip()]
    data = {}
    if request.user.is_staff:
        registry, tenant = ADMIN_WIDGETS, None
    else:
        tenant = getattr(request.user, "tenant", None)
        if not tenant:
            return JsonResponse({"error": "no tenant linked"}, status=403)
        registry = CLIENT_WIDGETS
    for key in keys:
        fn = registry.get(key)
        if not fn:
            continue
        data[key] = fn(tenant) if tenant is not None else fn()
    return JsonResponse({"widgets": data}, encoder=DjangoJSONEncoder)


def _rate_limit(tenant):
    now = time.time()
    stats = dict(tenant.usage_stats or {})
    recent = [float(t) for t in stats.get("recent_msgs", []) if now - float(t) <= 60]
    if len(recent) >= messages_per_min(tenant):
        notify = (now - float(stats.get("rl_notice_at") or 0)) > 60
        if notify:
            stats["rl_notice_at"] = now
        stats["recent_msgs"] = recent
        tenant.usage_stats = stats
        tenant.save(update_fields=["usage_stats"])
        return True, notify
    recent.append(now)
    stats["recent_msgs"] = recent
    tenant.usage_stats = stats
    tenant.save(update_fields=["usage_stats"])
    return False, False


@csrf_exempt
@require_POST
def wa_webhook(request):
    payload = _json(request)
    tid = payload.get("tenant_id")
    tenant = Tenant.objects.filter(id=tid).first()
    if not tenant:
        print(f"[wa_webhook WARN] Tenant id '{tid}' not found in database! Known tenant IDs: {list(Tenant.objects.values_list('id', flat=True))}")
        return JsonResponse({"reply": None, "error": "unknown tenant"}, status=404)
    if not tenant.is_active or tenant.plan_status == "CANCELLED":
        print(f"[wa_webhook INFO] Tenant {tenant.id} ({tenant.business_name}) is inactive or cancelled. Message ignored.")
        return JsonResponse({"reply": None, "ignored": "tenant inactive"})
    phone = str(payload.get("phone") or "").strip()
    if not phone:
        return JsonResponse({"reply": None, "error": "missing phone"}, status=400)
    image = payload.get("image")
    if image is not None and (not isinstance(image, dict) or not image.get("b64")):
        return JsonResponse({"reply": None, "error": "invalid image payload"}, status=400)
    limited, notify = _rate_limit(tenant)
    if limited:
        log_error(SystemConfig.load(), f"rate limit tenant={tenant.id} phone={phone}")
        reply = "You're sending messages too fast, one moment please." if notify else None
        return JsonResponse({"reply": reply, "throttled": True})
    if tenant.wa_status != "CONNECTED":
        Tenant.objects.filter(id=tenant.id).update(wa_status="CONNECTED")
    print(f"[wa_webhook] Running AI agent for '{tenant.business_name}' (phone={phone})...")
    reply, media = run_agent(tenant, phone, payload.get("text") or "", image, return_media=True)
    print(f"[wa_webhook] AI agent finished. Reply: '{reply[:60] if reply else None}' (media count: {len(media) if media else 0})")
    return JsonResponse({"reply": reply, "media": media})


@login_required(login_url="/login/")
@require_GET
def wa_status(request):
    tenant = getattr(request.user, "tenant", None)
    if not tenant:
        return JsonResponse({"error": "no tenant linked"}, status=403)
    result = _wa_request(f"/wa/{tenant.id}/status", method="GET")
    status = result.get("status")
    if status not in dict(Tenant.WA_CHOICES):
        return JsonResponse({"error": "WhatsApp bridge is unavailable.", "status": "DISCONNECTED"}, status=503)
    if tenant.wa_status != status:
        Tenant.objects.filter(id=tenant.id).update(wa_status=status)
    return JsonResponse({"status": status, "qr": result.get("qr")})


@login_required(login_url="/login/")
@require_POST
def wa_connect(request):
    tenant = getattr(request.user, "tenant", None)
    if not tenant:
        return JsonResponse({"error": "no tenant linked"}, status=403)
    result = _wa_request(f"/wa/{tenant.id}/connect")
    return JsonResponse(result, status=200 if result.get("ok") else 503)


def _order_message(tenant, order, note=""):
    items_lines = []
    for item in (order.items or []):
        name = str(item.get("product") or "Item").strip()
        sku = str(item.get("sku") or "").strip()
        qty = item.get("qty", 1)
        price = item.get("price")
        line = f"- {qty}x {name}"
        if sku and sku != name:
            line += f" [SKU: {sku}]"
        if price:
            try:
                line += f" ({float(price):.2f})"
            except (TypeError, ValueError):
                pass
        item_note = str(item.get("notes") or "").strip()
        if item_note:
            line += f" (Note: {item_note})"
        items_lines.append(line)
    items_block = "\n".join(items_lines) if items_lines else "Order items"

    if order.status == "ACCEPTED":
        lines = [
            f"Your order #{order.id} has been accepted and confirmed by {tenant.business_name}.",
            "",
            "Items ordered:",
            items_block,
            f"Total: {order.total}",
        ]
        if order.address:
            lines.append(f"Delivery address: {order.address}")
        lines.append("")
        lines.append("We are preparing your package and will notify you as soon as it ships.")
        base = "\n".join(lines)
    elif order.status == "SHIPPED":
        shipment = order.shipment or {}
        courier = shipment.get("courier", "courier service")
        consignment = shipment.get("consignment")
        lines = [
            f"Your order #{order.id} has been shipped!",
            "Delivery arranged directly by the store." if courier == "MANUAL" else f"Courier: {courier}",
        ]
        if consignment:
            lines.append(f"Consignment / Tracking ID: {consignment}")
        lines += [
            "",
            "Items:",
            items_block,
        ]
        if order.address:
            lines.append(f"Delivering to: {order.address}")
        lines.append("")
        lines.append("Please keep your phone reachable for delivery updates.")
        base = "\n".join(lines)
    elif order.status == "CANCELLED":
        base = f"Your order #{order.id} was cancelled and the reserved stock released."
    else:
        base = f"Your order #{order.id} is complete. Thank you for shopping with {tenant.business_name}!"

    if note:
        base = f"{base}\n\nNote from store: {note}"
    return base.strip()


@login_required(login_url="/login/")
def order_detail(request, order_id):
    if request.user.is_staff:
        tenant = None
        order = Order.objects.filter(id=order_id).first()
        if order:
            tenant = order.tenant
    else:
        tenant = getattr(request.user, "tenant", None)
        if not tenant:
            return JsonResponse({"error": "no tenant linked"}, status=403)
        order = Order.objects.filter(id=order_id, tenant=tenant).first()
    if not order:
        return JsonResponse({"error": "order not found"}, status=404)
    conv = (
        Conversation.objects.filter(tenant=tenant, customer_phone=order.customer_phone).first()
        if tenant
        else None
    )
    latest_customer_note = ""
    if conv and conv.messages:
        for m in reversed(conv.messages):
            if m.get("role") == "user":
                latest_customer_note = str(m.get("content") or "").strip()
                break
    item_notes = [
        str(itm.get("notes") or "").strip()
        for itm in (order.items or [])
        if str(itm.get("notes") or "").strip()
    ]
    return JsonResponse({
        "ok": True,
        "order": {
            "id": order.id,
            "customer_name": order.customer_name,
            "customer_phone": order.customer_phone,
            "address": order.address,
            "items": order.items or [],
            "total": float(order.total),
            "status": order.status,
            "shipment": order.shipment or {},
            "created_at": order.created_at.isoformat(),
            "latest_customer_note": latest_customer_note,
            "item_notes": item_notes,
        }
    })


@login_required(login_url="/login/")
@require_POST
def order_action(request, order_id):
    tenant = getattr(request.user, "tenant", None)
    if not tenant:
        return JsonResponse({"error": "no tenant linked"}, status=403)
    payload = _json(request)
    action = str(payload.get("action") or "").upper()
    if action not in ("ACCEPTED", "SHIPPED", "CANCELLED", "COMPLETED"):
        return JsonResponse({"error": "invalid action"}, status=400)
    order = Order.objects.filter(id=order_id, tenant=tenant).first()
    if not order:
        return JsonResponse({"error": "order not found"}, status=404)
    allowed = {
        "PENDING": ("ACCEPTED", "CANCELLED"),
        "ACCEPTED": ("SHIPPED", "CANCELLED"),
        "SHIPPED": ("COMPLETED",),
        "CANCELLED": (),
        "COMPLETED": (),
    }
    if action not in allowed.get(order.status, ()):
        return JsonResponse({"error": f"cannot change a {order.status} order to {action}"}, status=400)
    with transaction.atomic():
        # Claim the transition once, including when two dashboard tabs submit it.
        changed = Order.objects.filter(id=order.id, status=order.status).update(status=action)
        if not changed:
            return JsonResponse({"error": "This order has already changed. Refresh and try again."}, status=400)
        if action == "SHIPPED":
            shipment = dispatch(order)
            if shipment.get("error"):
                transaction.set_rollback(True)
                return JsonResponse({"error": shipment["error"]}, status=400)
            order.shipment = shipment
        order.status = action
        order.save(update_fields=["status", "shipment"])
        if action == "CANCELLED":
            for item in order.items or []:
                try:
                    adjust_stock(tenant, item.get("sku"), int(item.get("qty", 1) or 1))
                except (TypeError, ValueError):
                    continue
    notified = _wa_send(tenant, order.customer_phone, _order_message(tenant, order, payload.get("note") or ""))
    result = {"ok": True, "status": order.status, "notified": notified}
    if not notified:
        result["warning"] = "Order updated, but the WhatsApp notification could not be sent. Check the WhatsApp connection."
    return JsonResponse(result)


def _clean_skus(tenant, skus, product_id=None):
    if not isinstance(skus, list):
        return None, "skus must be a list"
    if len(skus) > 60:
        return None, "up to 60 variants per product"
    clean = []
    seen = set()
    for sku in skus:
        if not isinstance(sku, dict):
            return None, "each variant must be an object"
        code = str(sku.get("sku") or "").strip()
        if not code:
            return None, "every variant needs a SKU code"
        lowered = code.lower()
        if lowered in seen:
            return None, f"duplicate SKU code in this product: {code}"
        seen.add(lowered)
        try:
            price = float(sku.get("price") or 0)
            stock = int(float(sku.get("stock") or 0))
        except (TypeError, ValueError):
            return None, f"price/stock must be numeric ({code})"
        if price < 0 or stock < 0:
            return None, f"price/stock cannot be negative ({code})"
        clean.append(
            {
                "sku": code,
                "size": str(sku.get("size") or "").strip()[:40],
                "color": str(sku.get("color") or "").strip()[:40],
                "price": price,
                "stock": stock,
            }
        )
    others = Product.objects.filter(tenant=tenant)
    if product_id:
        others = others.exclude(id=product_id)
    for other in others:
        for sku in other.skus or []:
            code = str(sku.get("sku", "")).strip().lower()
            if code and code in seen:
                return None, f"SKU code '{sku.get('sku')}' is already used by '{other.name}'"
    return clean, None


@login_required(login_url="/login/")
@require_POST
@transaction.atomic
def product_save(request):
    tenant = getattr(request.user, "tenant", None)
    if not tenant:
        return JsonResponse({"error": "no tenant linked"}, status=403)
    payload = _json(request)
    name = str(payload.get("name") or "").strip()
    if not name:
        return JsonResponse({"error": "product name is required"}, status=400)
    product = None
    if payload.get("id"):
        product = Product.objects.select_for_update().filter(id=payload["id"], tenant=tenant).first()
        if not product:
            return JsonResponse({"error": "product not found"}, status=404)
        if "original_image_url" in payload and payload["original_image_url"] != product.image_url:
            return JsonResponse({"error": "This product's photo changed in another tab. Refresh and edit the product again."}, status=409)
    clean_skus, error = _clean_skus(tenant, payload.get("skus"), product.id if product else None)
    if error:
        return JsonResponse({"error": error}, status=400)
    if not product:
        limit = product_limit(tenant)
        if Product.objects.filter(tenant=tenant, is_active=True).count() >= limit:
            return JsonResponse(
                {"error": f"Your {tenant.get_plan_display()} plan allows up to {limit} products. Upgrade to add more."},
                status=400,
            )
        product = Product(tenant=tenant)
    old_image = product.image_url
    image_url = str(payload.get("image_url", old_image) or "")
    if image_url != old_image and image_url.startswith(settings.MEDIA_URL):
        image_path = local_image_path(image_url)
        if not image_path or not image_path.is_file():
            return JsonResponse({"error": "This uploaded photo is no longer available. Upload it again before saving."}, status=400)
    product.name = name
    product.description = str(payload.get("description") or "")
    product.image_url = image_url
    try:
        product.base_price = float(payload.get("base_price") or 0)
    except (TypeError, ValueError):
        product.base_price = 0
    product.skus = clean_skus
    if "is_active" in payload:
        product.is_active = bool(payload.get("is_active"))
    product.save()
    if old_image != product.image_url:
        cleanup_images([old_image])
    return JsonResponse({"ok": True, "id": product.id})


@login_required(login_url="/login/")
@require_POST
def product_archive(request):
    tenant = getattr(request.user, "tenant", None)
    if not tenant:
        return JsonResponse({"error": "no tenant linked"}, status=403)
    payload = _json(request)
    product = Product.objects.filter(id=payload.get("id"), tenant=tenant).first()
    if not product:
        return JsonResponse({"error": "product not found"}, status=404)
    product.is_active = not bool(payload.get("archived", True))
    product.save(update_fields=["is_active"])
    return JsonResponse({"ok": True, "is_active": product.is_active})


@login_required(login_url="/login/")
@require_POST
def product_duplicate(request):
    tenant = getattr(request.user, "tenant", None)
    if not tenant:
        return JsonResponse({"error": "no tenant linked"}, status=403)
    payload = _json(request)
    source = Product.objects.filter(id=payload.get("id"), tenant=tenant).first()
    if not source:
        return JsonResponse({"error": "product not found"}, status=404)
    limit = product_limit(tenant)
    if Product.objects.filter(tenant=tenant, is_active=True).count() >= limit:
        return JsonResponse(
            {"error": f"Your {tenant.get_plan_display()} plan allows up to {limit} products. Upgrade to add more."},
            status=400,
        )
    used = set()
    for product in Product.objects.filter(tenant=tenant):
        for sku in product.skus or []:
            code = str(sku.get("sku", "")).strip().lower()
            if code:
                used.add(code)
    skus = []
    for sku in source.skus or []:
        base_code = str(sku.get("sku", "")).strip() or "SKU"
        code = f"{base_code}-COPY"
        counter = 2
        while code.lower() in used:
            code = f"{base_code}-COPY{counter}"
            counter += 1
        used.add(code.lower())
        skus.append({**sku, "sku": code})
    copy = Product.objects.create(
        tenant=tenant,
        name=f"{source.name} (copy)"[:200],
        description=source.description,
        base_price=source.base_price,
        image_url=source.image_url,
        skus=skus,
        is_active=True,
    )
    return JsonResponse({"ok": True, "id": copy.id})


@login_required(login_url="/login/")
@require_POST
def product_stock(request):
    tenant = getattr(request.user, "tenant", None)
    if not tenant:
        return JsonResponse({"error": "no tenant linked"}, status=403)
    payload = _json(request)
    product = Product.objects.filter(id=payload.get("id"), tenant=tenant).first()
    if not product:
        return JsonResponse({"error": "product not found"}, status=404)
    code = str(payload.get("sku") or "").strip()
    try:
        delta = int(float(payload.get("delta") or 0))
    except (TypeError, ValueError):
        return JsonResponse({"error": "delta must be numeric"}, status=400)
    delta = max(-999, min(999, delta))
    skus = list(product.skus or [])
    for sku in skus:
        if str(sku.get("sku", "")).strip().lower() == code.lower():
            sku["stock"] = max(0, int(sku.get("stock", 0) or 0) + delta)
            product.skus = skus
            product.save(update_fields=["skus"])
            return JsonResponse({"ok": True, "sku": sku["sku"], "stock": sku["stock"]})
    return JsonResponse({"error": "sku not found"}, status=404)


@login_required(login_url="/login/")
@require_POST
def product_upload(request):
    tenant = getattr(request.user, "tenant", None)
    if not tenant:
        return JsonResponse({"error": "no tenant linked"}, status=403)
    file = request.FILES.get("file")
    if not file:
        return JsonResponse({"error": "file is required"}, status=400)
    ext = IMAGE_TYPES.get(file.content_type)
    if not ext:
        return JsonResponse({"error": "only jpeg, png or webp images are allowed"}, status=400)
    if not file.size:
        return JsonResponse({"error": "image file is empty"}, status=400)
    if file.size > MAX_IMAGE_BYTES:
        return JsonResponse({"error": "image must be 5MB or smaller"}, status=400)
    rel = f"{tenant.id}/{uuid.uuid4().hex}{ext}"
    dest = Path(settings.MEDIA_ROOT) / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "wb") as handle:
        for chunk in file.chunks():
            handle.write(chunk)
    return JsonResponse({"ok": True, "url": f"{settings.MEDIA_URL}{rel}"})


@login_required(login_url="/login/")
@require_POST
def tenant_settings(request):
    tenant = getattr(request.user, "tenant", None)
    if not tenant:
        return JsonResponse({"error": "no tenant linked"}, status=403)
    payload = _json(request)
    data = dict(tenant.settings or {})
    changed = []
    if "business_name" in payload:
        business_name = str(payload["business_name"] or "").strip()
        if not business_name:
            return JsonResponse({"error": "business name cannot be empty"}, status=400)
        tenant.business_name = business_name
        changed.append("business_name")
    if "greeting" in payload:
        data["greeting"] = str(payload["greeting"] or "").strip()
        changed.append("greeting")
    if "commands" in payload:
        commands = payload["commands"]
        if not isinstance(commands, list):
            return JsonResponse({"error": "commands must be a list"}, status=400)
        clean = []
        for command in commands:
            if not isinstance(command, dict):
                continue
            trigger = str(command.get("trigger") or "").strip()
            reply = str(command.get("reply") or "").strip()
            if trigger and reply:
                clean.append({"trigger": trigger, "reply": reply})
        data["commands"] = clean
        changed.append("commands")
    tenant.settings = data
    tenant.save(update_fields=["settings", "business_name"])
    return JsonResponse({"ok": True, "changed": changed})


def _pathao_config(payload, saved):
    config = {
        key: str(payload.get(key, saved.get(key, "")) or "").strip()
        for key in ("client_id", "client_secret", "username", "password", "store_id")
    }
    for key in ("client_secret", "password"):
        config[key] = config[key] or saved.get(key, "")
    config["enabled"] = payload.get("enabled", saved.get("enabled", False)) is True
    config["environment"] = str(payload.get("environment") or saved.get("environment") or "sandbox").lower()
    return config


@login_required(login_url="/login/")
def tenant_couriers(request):
    tenant = getattr(request.user, "tenant", None)
    if not tenant:
        return JsonResponse({"error": "no tenant linked"}, status=403)
    data = dict(tenant.settings or {})
    saved_couriers = dict(data.get("couriers") or {})

    if request.method == "POST":
        payload = _json(request)
        if not isinstance(payload, dict) or not isinstance(payload.get("pathao"), dict):
            return JsonResponse({"error": "Pathao settings must be an object."}, status=400)
        config = _pathao_config(payload["pathao"], saved_couriers.get("pathao") or {})
        if config["environment"] not in ("sandbox", "production"):
            return JsonResponse({"error": "Choose sandbox or production."}, status=400)
        error = pathao_config_error(config, require_store=True) if config["enabled"] else ""
        if error:
            return JsonResponse({"error": error}, status=400)
        data["couriers"] = {"pathao": config}
        tenant.settings = data
        tenant.save(update_fields=["settings"])
        return JsonResponse({"ok": True, "message": "Shipping settings saved."})

    pt = saved_couriers.get("pathao") or {}
    safe_data = {
        "pathao": {
            "enabled": bool(pt.get("enabled", False)),
            "environment": pt.get("environment", "sandbox"),
            "client_id": pt.get("client_id", ""),
            "has_client_secret": bool(pt.get("client_secret")),
            "username": pt.get("username", ""),
            "has_password": bool(pt.get("password")),
            "store_id": pt.get("store_id", ""),
        },
    }
    return JsonResponse({"ok": True, "couriers": safe_data})


@login_required(login_url="/login/")
@require_POST
def courier_test(request):
    tenant = getattr(request.user, "tenant", None)
    if not tenant:
        return JsonResponse({"error": "no tenant linked"}, status=403)
    payload = _json(request)
    if not isinstance(payload, dict):
        return JsonResponse({"error": "Pathao settings must be an object."}, status=400)
    saved = (tenant.settings or {}).get("couriers", {}).get("pathao") or {}
    res = test_pathao_connection(_pathao_config(payload, saved))
    return JsonResponse(res, status=200 if res.get("ok") else 400)


@login_required(login_url="/login/")
@require_POST
def conversation_resolve(request, conv_id):
    tenant = getattr(request.user, "tenant", None)
    if not tenant:
        return JsonResponse({"error": "no tenant linked"}, status=403)
    conversation = Conversation.objects.filter(id=conv_id, tenant=tenant).first()
    if not conversation:
        return JsonResponse({"error": "conversation not found"}, status=404)
    conversation.needs_human = False
    conversation.save(update_fields=["needs_human"])
    return JsonResponse({"ok": True})


@login_required(login_url="/login/")
@require_POST
def account_update(request):
    payload = _json(request)
    user = request.user
    if not user.check_password(str(payload.get("current_password") or "")):
        return JsonResponse({"error": "Current password is incorrect."}, status=400)
    username = str(payload.get("username") or "").strip()
    new_password = str(payload.get("new_password") or "")
    changed = False
    if username and username != user.username:
        if User.objects.filter(username__iexact=username).exclude(id=user.id).exists():
            return JsonResponse({"error": "That username is already taken."}, status=400)
        user.username = username
        changed = True
    if new_password:
        rule_error = password_error(new_password)
        if rule_error:
            return JsonResponse({"error": rule_error}, status=400)
        user.set_password(new_password)
        changed = True
    if changed:
        user.save()
        login(request, user)
    return JsonResponse({"ok": True, "changed": changed, "username": user.username})


@login_required(login_url="/login/")
@require_POST
def admin_tenant_create(request):
    if not request.user.is_staff:
        return JsonResponse({"error": "forbidden"}, status=403)
    payload = _json(request)
    username = str(payload.get("username") or "").strip()
    password = str(payload.get("password") or "")
    business_name = str(payload.get("business_name") or username).strip()
    if not username or not password:
        return JsonResponse({"error": "username and password are required"}, status=400)
    rule_error = password_error(password)
    if rule_error:
        return JsonResponse({"error": rule_error}, status=400)
    if User.objects.filter(username=username).exists():
        return JsonResponse({"error": "username already taken"}, status=400)
    user = User.objects.create_user(username=username, password=password)
    tenant = Tenant.objects.create(user=user, business_name=business_name)
    return JsonResponse({"ok": True, "tenant_id": tenant.id})


def _tenant_detail_payload(tenant):
    orders = tenant.order_set.all()
    orders_count = orders.count()
    converted = orders.exclude(status="CANCELLED").count()
    messages = int((tenant.usage_stats or {}).get("messages_count", 0))
    conversion = round(converted / messages * 100, 1) if messages else 0.0
    return {
        "id": tenant.id,
        "business_name": tenant.business_name,
        "username": tenant.user.username,
        "email": tenant.user.email,
        "plan": tenant.plan,
        "plan_status": tenant.plan_status,
        "wa_status": tenant.wa_status,
        "is_active": tenant.is_active,
        "usage_stats": tenant.usage_stats or {},
        "messages": messages,
        "orders_count": orders_count,
        "converted_orders": converted,
        "conversion_rate": f"{conversion:.1f}%",
    }


@login_required(login_url="/login/")
def admin_tenant_detail(request, tenant_id):
    if not request.user.is_staff:
        return JsonResponse({"error": "forbidden"}, status=403)
    tenant = Tenant.objects.filter(id=tenant_id).first()
    if not tenant:
        return JsonResponse({"error": "tenant not found"}, status=404)
    return JsonResponse({"tenant": _tenant_detail_payload(tenant)})


@login_required(login_url="/login/")
@require_POST
def admin_plan(request):
    if not request.user.is_staff:
        return JsonResponse({"error": "forbidden"}, status=403)
    payload = _json(request)
    tenant = Tenant.objects.filter(id=payload.get("tenant_id")).first()
    if not tenant:
        return JsonResponse({"error": "tenant not found"}, status=404)
    changed = []
    plan = str(payload.get("plan") or "").upper()
    if plan:
        if plan not in dict(Tenant.PLAN_CHOICES):
            return JsonResponse({"error": "invalid plan"}, status=400)
        tenant.plan = plan
        changed.append("plan")
    plan_status = str(payload.get("plan_status") or "").upper()
    if plan_status:
        if plan_status not in dict(Tenant.PLAN_STATUS_CHOICES):
            return JsonResponse({"error": "invalid plan status"}, status=400)
        tenant.plan_status = plan_status
        changed.append("plan_status")
    if changed:
        tenant.save(update_fields=changed)
    return JsonResponse({"ok": True, "changed": changed})


@login_required(login_url="/login/")
@require_POST
def admin_tenant_delete(request, tenant_id):
    if not request.user.is_staff:
        return JsonResponse({"error": "forbidden"}, status=403)
    tenant = Tenant.objects.filter(id=tenant_id).first()
    if not tenant:
        return JsonResponse({"error": "tenant not found"}, status=404)
    result = _wa_request(f"/wa/{tenant.id}/remove")
    if not result.get("ok"):
        return JsonResponse({"error": "Could not disconnect WhatsApp. Check the bridge and try again."}, status=503)
    images = set(Product.objects.filter(tenant=tenant).values_list("image_url", flat=True))
    for messages in Conversation.objects.filter(tenant=tenant).values_list("messages", flat=True):
        images.update(conversation_images(messages))
    media_root = Path(settings.MEDIA_ROOT)
    for file in (media_root / str(tenant.id)).rglob("*"):
        if file.is_file():
            images.add(f"{settings.MEDIA_URL}{file.relative_to(media_root).as_posix()}")
    with transaction.atomic():
        tenant.user.delete()
        cleanup_images(images)
    return JsonResponse({"ok": True})


def _normalize_llm_url(raw_url):
    url = str(raw_url or "").strip().rstrip("/")
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        if url.startswith(("localhost", "127.0.0.1")):
            url = f"http://{url}"
        else:
            url = f"https://{url}"
    if url.endswith("/chat/completions"):
        url = url[:-17].rstrip("/")
    elif url.endswith("/responses"):
        url = url[:-10].rstrip("/")
    elif url.endswith("/models"):
        url = url[:-7].rstrip("/")
    return url


@login_required(login_url="/login/")
@require_POST
def admin_models(request):
    if not request.user.is_staff:
        return JsonResponse({"error": "forbidden"}, status=403)
    payload = _json(request)
    config = SystemConfig.load()
    raw_base = payload.get("llm_base_url") if "llm_base_url" in payload else config.llm_base_url
    base = _normalize_llm_url(raw_base)

    raw_key = payload.get("api_key")
    if raw_key is not None and str(raw_key).strip():
        key = str(raw_key).strip()
    else:
        saved_host = urlparse(config.llm_base_url or "").netloc.lower()
        target_host = urlparse(base).netloc.lower()
        if target_host == saved_host or not target_host or not config.llm_base_url:
            key = str(config.api_key or "").strip()
        else:
            key = ""

    if not base or not base.startswith(("http://", "https://")):
        return JsonResponse({"error": "Enter a valid http(s) base URL first."}, status=400)

    headers = {"User-Agent": "opencode/1.17.12", "Accept": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"

    endpoints = [f"{base}/models"]
    if not base.endswith("/v1"):
        endpoints.append(f"{base}/v1/models")
    endpoints.append(f"{base}/api/tags")

    session = _make_http_session()
    response = None
    last_err = None
    successful_endpoint = None

    for ep in endpoints:
        try:
            r = session.get(ep, headers=headers, timeout=12)
            if r.status_code == 200:
                response = r
                successful_endpoint = ep
                break
            elif r.status_code in (401, 403):
                return JsonResponse(
                    {"error": "The provider rejected the API key. Check the key and try again."},
                    status=400,
                )
            elif r.status_code == 404:
                last_err = f"Endpoint {ep} returned 404 Not Found."
                continue
            else:
                last_err = f"The provider returned HTTP {r.status_code}."
        except requests.RequestException as exc:
            return JsonResponse({"error": f"Could not reach the provider: {exc}"}, status=400)

    if not response:
        return JsonResponse({"error": last_err or "No models endpoint found at this URL."}, status=400)

    try:
        data = response.json()
    except ValueError:
        return JsonResponse({"error": "The provider did not return a JSON model list."}, status=400)

    items = None
    if isinstance(data, dict):
        items = data.get("data")
        if not isinstance(items, list):
            items = data.get("models")
    elif isinstance(data, list):
        items = data

    models_set = set()
    if isinstance(items, list):
        for m in items:
            if isinstance(m, dict):
                val = m.get("id") or m.get("name") or m.get("model")
                if val:
                    models_set.add(str(val).strip())
            elif isinstance(m, str) and m.strip():
                models_set.add(m.strip())

    models = sorted(models_set)
    if not models:
        return JsonResponse({"error": "No models were returned by this provider."}, status=400)
    return JsonResponse({"models": models, "normalized_url": base, "endpoint": successful_endpoint})


@login_required(login_url="/login/")
@require_POST
def admin_test_llm(request):
    if not request.user.is_staff:
        return JsonResponse({"error": "forbidden"}, status=403)
    payload = _json(request)
    config = SystemConfig.load()

    raw_base = payload.get("llm_base_url") if "llm_base_url" in payload else config.llm_base_url
    base = _normalize_llm_url(raw_base)

    raw_key = payload.get("api_key")
    if raw_key is not None and str(raw_key).strip():
        key = str(raw_key).strip()
    else:
        saved_host = urlparse(config.llm_base_url or "").netloc.lower()
        target_host = urlparse(base).netloc.lower()
        if target_host == saved_host or not target_host or not config.llm_base_url:
            key = str(config.api_key or "").strip()
        else:
            key = ""

    model_name = str(payload.get("model_name") or config.model_name or "").strip()

    if not base or not base.startswith(("http://", "https://")):
        return JsonResponse({"ok": False, "live": False, "error": "Enter a valid base URL first."}, status=400)

    headers = {
        "User-Agent": "opencode/1.17.12",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if key:
        headers["Authorization"] = f"Bearer {key}"

    session = _make_http_session()

    if not model_name:
        try:
            r = session.get(f"{base}/models", headers=headers, timeout=10)
            if r.status_code == 200:
                data = r.json()
                items = data.get("data") if isinstance(data, dict) else data
                if isinstance(items, list) and items:
                    first = items[0]
                    model_name = str(first.get("id") or first.get("name") if isinstance(first, dict) else first).strip()
        except Exception:
            pass

    if not model_name:
        return JsonResponse({
            "ok": False,
            "live": False,
            "error": "Please select or enter a model name to test completions."
        }, status=400)

    # Determine if provider or model prefers OpenAI Responses API format (/responses)
    use_responses = (
        "agentrouter.org" in base.lower()
        or base.rstrip("/").endswith("/responses")
        or model_name.startswith(("gpt-5.", "gpt-6"))
    )

    t0 = time.perf_counter()
    res = None
    last_err = None

    if use_responses:
        resp_endpoints = [f"{base}/responses"]
        if not base.endswith("/v1"):
            resp_endpoints.append(f"{base}/v1/responses")
        resp_body = {
            "model": model_name,
            "input": [{"role": "user", "content": "Respond with the single word: OK"}],
        }
        for ep in resp_endpoints:
            try:
                r = session.post(ep, headers=headers, json=resp_body, timeout=35)
                if r.status_code == 200:
                    res = r
                    break
                elif r.status_code in (401, 403):
                    return JsonResponse({
                        "ok": False,
                        "live": False,
                        "error": "Authentication failed (HTTP 401/403): The provider rejected the API key."
                    }, status=400)
                elif r.status_code == 429:
                    return JsonResponse({
                        "ok": False,
                        "live": False,
                        "error": "Rate limit or quota exceeded (HTTP 429)."
                    }, status=400)
                else:
                    last_err = f"Provider error (HTTP {r.status_code}): {r.text[:200]}"
            except requests.Timeout:
                last_err = f"Connection timed out (35s) connecting to {ep}."
            except requests.RequestException as exc:
                last_err = f"Could not reach {ep}: {exc}"

    if not res:
        chat_endpoints = [f"{base}/chat/completions"]
        if not base.endswith("/v1"):
            chat_endpoints.append(f"{base}/v1/chat/completions")

        body = {
            "model": model_name,
            "messages": [{"role": "user", "content": "Respond with the single word: OK"}],
            "max_tokens": 10,
        }
        extra_opts = payload.get("request_options") or config.request_options
        if extra_opts:
            try:
                extra = json.loads(str(extra_opts))
                if isinstance(extra, dict):
                    for k, v in extra.items():
                        if k not in ("model", "messages", "max_tokens"):
                            body[k] = v
            except Exception:
                pass

        for ep in chat_endpoints:
            try:
                r = session.post(ep, headers=headers, json=body, timeout=25)
                if r.status_code == 200:
                    res = r
                    break
                elif r.status_code in (401, 403):
                    return JsonResponse({
                        "ok": False,
                        "live": False,
                        "error": "Authentication failed (HTTP 401/403): The provider rejected the API key."
                    }, status=400)
                elif r.status_code == 429:
                    return JsonResponse({
                        "ok": False,
                        "live": False,
                        "error": "Rate limit or quota exceeded (HTTP 429)."
                    }, status=400)
                else:
                    last_err = r.text[:250]
            except requests.Timeout:
                last_err = f"Connection timed out (25s) connecting to {ep}."
            except requests.RequestException as exc:
                last_err = f"Could not reach {ep}: {exc}"

    if not res and not use_responses:
        resp_endpoints = [f"{base}/responses"]
        if not base.endswith("/v1"):
            resp_endpoints.append(f"{base}/v1/responses")
        resp_body = {
            "model": model_name,
            "input": [{"role": "user", "content": "Respond with the single word: OK"}],
        }
        for ep in resp_endpoints:
            try:
                r = session.post(ep, headers=headers, json=resp_body, timeout=35)
                if r.status_code == 200:
                    res = r
                    break
                elif r.status_code in (401, 403):
                    return JsonResponse({
                        "ok": False,
                        "live": False,
                        "error": "Authentication failed (HTTP 401/403): The provider rejected the API key."
                    }, status=400)
                elif r.status_code == 429:
                    return JsonResponse({
                        "ok": False,
                        "live": False,
                        "error": "Rate limit or quota exceeded (HTTP 429)."
                    }, status=400)
                else:
                    last_err = f"Provider error (HTTP {r.status_code}): {r.text[:200]}"
            except requests.Timeout:
                last_err = f"Connection timed out (35s) connecting to {ep}."
            except requests.RequestException as exc:
                last_err = f"Could not reach {ep}: {exc}"

    latency_ms = int((time.perf_counter() - t0) * 1000)

    if not res:
        return JsonResponse({
            "ok": False,
            "live": False,
            "error": last_err or "The AI provider did not respond to connection tests at this URL."
        }, status=400)

    reply_snippet = ""
    try:
        reply_data = res.json()
        choices = reply_data.get("choices") or []
        if choices and isinstance(choices, list):
            first = choices[0]
            if isinstance(first, dict):
                msg = first.get("message") or {}
                reply_snippet = str(msg.get("content") or "").strip()
        if not reply_snippet:
            for item in reply_data.get("output") or []:
                if isinstance(item, dict) and item.get("type") == "message":
                    content_list = item.get("content") or []
                    if isinstance(content_list, list):
                        for c in content_list:
                            if isinstance(c, dict) and c.get("text"):
                                reply_snippet = str(c["text"]).strip()
                                break
                    elif isinstance(content_list, str):
                        reply_snippet = content_list.strip()
                if reply_snippet:
                    break
            if not reply_snippet and isinstance(reply_data.get("text"), str):
                reply_snippet = reply_data["text"].strip()
    except Exception:
        pass

    return JsonResponse({
        "ok": True,
        "live": True,
        "latency_ms": latency_ms,
        "model": model_name,
        "reply": reply_snippet[:100],
        "message": f"Connection successful. {model_name} responded in {latency_ms}ms.",
    })


@login_required(login_url="/login/")
@require_POST
def admin_config(request):
    if not request.user.is_staff:
        return JsonResponse({"error": "forbidden"}, status=403)
    payload = _json(request)
    config = SystemConfig.load()
    if "request_options" in payload:
        try:
            options = json.loads(str(payload["request_options"] or "{}"))
        except json.JSONDecodeError:
            return JsonResponse({"error": "Advanced options must be a JSON object."}, status=400)
        if not isinstance(options, dict):
            return JsonResponse({"error": "Advanced options must be a JSON object."}, status=400)
        payload["request_options"] = json.dumps(options)
    changed = []
    for field in ("llm_base_url", "api_key", "model_name", "system_prompt", "request_options"):
        if field in payload:
            val = str(payload[field] or "")
            if field == "llm_base_url" and val:
                val = _normalize_llm_url(val)
            setattr(config, field, val)
            changed.append(field)
    if changed:
        config.save()
    tenant = None
    if payload.get("tenant_id"):
        tenant = Tenant.objects.filter(id=payload["tenant_id"]).first()
    if tenant and "is_active" in payload:
        tenant.is_active = bool(payload["is_active"])
        tenant.save(update_fields=["is_active"])
    if payload.get("reset_tenant"):
        result = _wa_request(f"/wa/{payload['reset_tenant']}/reset")
        if not result.get("ok"):
            return JsonResponse({"error": "Could not reset WhatsApp. Check the bridge and try again."}, status=503)
    return JsonResponse({"ok": True, "changed": changed})
