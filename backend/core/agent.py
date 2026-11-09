import base64
import binascii
import json
import re
import unicodedata
from datetime import datetime, timezone
from threading import Lock

import requests
from django.core.cache.backends.locmem import LocMemCache
from django.db import transaction

from .models import (
    Conversation,
    Order,
    Product,
    SystemConfig,
    Tenant,
    adjust_stock,
    cleanup_images,
    conversation_images,
    find_sku,
)


# Never use a disk/database cache for temporary customer photos.
# Source: https://docs.djangoproject.com/en/6.1/topics/cache/#local-memory-caching
# shortcut: process-local context; use a shared TTL store if deploying multiple workers.
_IMAGE_CONTEXT = LocMemCache(
    "nexora-agent-image-context", {"TIMEOUT": 600, "OPTIONS": {"MAX_ENTRIES": 16}}
)
_IMAGE_CONTEXT_LOCK = Lock()


def _chat_image(tenant, conv, image):
    key = f"agent-image:{tenant.pk}:{conv.pk}"
    with _IMAGE_CONTEXT_LOCK:
        if image is None:
            current = _IMAGE_CONTEXT.get(key)
            if current:
                _IMAGE_CONTEXT.touch(key)
            return current

        _IMAGE_CONTEXT.delete(key)
        if isinstance(image, dict):
            mime = image.get("mime", "image/jpeg")
            b64 = image.get("b64")
            if (
                mime in ("image/jpeg", "image/png", "image/webp", "image/gif")
                and isinstance(b64, str) and 0 < len(b64) <= 4 * 1024 * 1024
            ):
                try:
                    base64.b64decode(b64, validate=True)
                except (binascii.Error, ValueError):
                    return image
                _IMAGE_CONTEXT.set(key, {"mime": mime, "b64": b64})
        return image


def _make_http_session():
    session = requests.Session()
    session.trust_env = False
    session.proxies = {"http": None, "https": None}
    return session

DEFAULT_PROMPT = (
    "You are a dedicated sales assistant for {business} on WhatsApp. "
    "You strictly answer questions ONLY about {business}, its products, catalog items, pricing, "
    "stock availability, order placement, order status, and store services. "
    "Do not answer general knowledge, mathematical, technical, personal, or any off-topic questions outside of this shop. "
    "If a customer asks anything unrelated to {business} or its products, decline politely: "
    "'Sorry, I can only answer questions related to our products and store services. Let me know if you would like information on any of our items.' "
    "Reply briefly, politely, and professionally in the customer's language. Never use emojis; keep all responses clean, professional, and factual. "
    "Never invent products, prices, stock or delivery times: always use search_inventory first and quote only what it returns. "
    "You can send catalogue photos of products to the customer using the send_product_photo tool. "
    "Whenever a customer asks to see pictures, photos, or what a product looks like, or asks you to show them an item, always call send_product_photo with the product name. "
    "To place an order you must have the customer's full name, full delivery address, exact SKU and quantity, all confirmed by the customer. "
    "Use get_customer_context for returning customers. Then call create_or_update_order. "
    "For custom, unclear or complex requests call request_human_support."
)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_inventory",
            "description": "Search this business's catalog. Returns matching products with price, photo availability, and exact SKU options (size, color, stock).",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Product name or keywords"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_product_photo",
            "description": "Send a catalogue photo of a product to the customer on WhatsApp. Call this whenever the customer asks to see pictures, photos, or what a product looks like, or to showcase an item.",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_name": {
                        "type": "string",
                        "description": "Exact name or keywords of the product in the catalogue",
                    },
                    "caption": {
                        "type": "string",
                        "description": "Optional brief caption (e.g. product name and price)",
                    },
                },
                "required": ["product_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_customer_context",
            "description": "Get the customer's saved name, address and recent orders.",
            "parameters": {
                "type": "object",
                "properties": {"phone": {"type": "string", "description": "Leave empty for the current chat."}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_or_update_order",
            "description": "Create a PENDING order, or add an item to this customer's existing PENDING order. Validates SKU stock and deducts it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Customer full name"},
                    "address": {"type": "string", "description": "Full delivery address"},
                    "sku": {"type": "string", "description": "Exact SKU code from search_inventory"},
                    "qty": {"type": "integer", "description": "Quantity"},
                    "notes": {"type": "string", "description": "Optional notes (customization, landmark)"},
                },
                "required": ["name", "address", "sku", "qty"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "request_human_support",
            "description": "Escalate to the business owner when the request is custom, unclear or outside the catalog.",
            "parameters": {
                "type": "object",
                "properties": {"reason": {"type": "string"}},
                "required": ["reason"],
            },
        },
    },
]


def _log_error(config, message):
    logs = list(config.error_logs or [])
    logs.append({"at": datetime.now(timezone.utc).isoformat(), "message": str(message)[:500]})
    config.error_logs = logs[-50:]
    config.save(update_fields=["error_logs"])


def _request_payload(config, messages):
    payload = {"model": config.model_name, "messages": messages, "tools": TOOLS}
    try:
        extra = json.loads(config.request_options or "{}")
    except (TypeError, json.JSONDecodeError):
        extra = {}
    if isinstance(extra, dict):
        for key, value in extra.items():
            if key not in ("model", "messages", "tools"):
                payload[key] = value
    return payload


def _search_inventory(tenant, query):
    q = str(query or "").strip().lower()
    tokens = [w for w in re.findall(r"\w+", q) if w]
    scored = []
    for product in Product.objects.filter(tenant=tenant, is_active=True):
        name_desc = f"{product.name} {product.description}".lower()
        sku_attrs = []
        if isinstance(product.skus, list):
            for s in product.skus:
                if isinstance(s, dict):
                    if s.get("color"):
                        sku_attrs.append(str(s["color"]).lower())
                    if s.get("size"):
                        sku_attrs.append(str(s["size"]).lower())
                    if s.get("sku"):
                        sku_attrs.append(str(s["sku"]).lower())
        full_text = f"{name_desc} {' '.join(sku_attrs)}"
        full_words = set(re.findall(r"\w+", full_text))
        name_desc_words = set(re.findall(r"\w+", name_desc))

        if not q:
            score = 1
        elif q in name_desc:
            score = 4
        elif q in full_text:
            score = 3
        elif tokens and all(w in full_words for w in tokens):
            score = 2
        elif tokens and len(tokens) > 1 and any(w in name_desc_words for w in tokens):
            score = 1
        else:
            continue

        scored.append(
            (
                score,
                {
                    "name": product.name,
                    "base_price": float(product.base_price),
                    "description": product.description[:200],
                    "has_photo": bool(product.image_url),
                    "image_url": product.image_url or None,
                    "skus": product.skus,
                },
            )
        )

    if scored:
        scored.sort(key=lambda item: item[0], reverse=True)
        return [item[1] for item in scored[:10]]
    return "No matching products. Offer to escalate."


def _send_product_photo(tenant, product_name, caption=None):
    q = str(product_name or "").strip().lower()
    if not q:
        return {"error": "Product name is required."}
    product = Product.objects.filter(tenant=tenant, is_active=True, name__iexact=q).first()
    if not product:
        for p in Product.objects.filter(tenant=tenant, is_active=True):
            if q in p.name.lower() or p.name.lower() in q:
                product = p
                break
    if not product:
        return {"error": f"Product '{product_name}' was not found in the catalog."}
    if not product.image_url:
        return {"error": f"Product '{product.name}' does not have a catalogue photo yet."}
    cap = str(caption or "").strip()
    if not cap:
        cap = f"{product.name} - ${product.base_price:.2f}" if product.base_price else product.name
    return {
        "ok": True,
        "success": True,
        "product": product.name,
        "image_url": product.image_url,
        "caption": cap,
        "note": f"Catalogue photo of '{product.name}' attached and sent to customer.",
    }


def _customer_context(tenant, phone):
    conv = Conversation.objects.filter(tenant=tenant, customer_phone=phone).first()
    orders = list(
        Order.objects.filter(tenant=tenant, customer_phone=phone).values(
            "id", "status", "items", "total", "address"
        )[:5]
    )
    return {"name": (conv.customer_name if conv else ""), "recent_orders": orders}


@transaction.atomic
def _create_or_update_order(tenant, phone, args):
    sku_code = str(args.get("sku") or "").strip()
    name = str(args.get("name") or "").strip()
    address = str(args.get("address") or "").strip()
    try:
        qty = max(1, int(args.get("qty") or 1))
    except (TypeError, ValueError):
        qty = 1
    if not name or not address:
        return {"error": "Customer name and address are required."}
    product, sku = find_sku(tenant, sku_code)
    if not sku:
        return {"error": f"SKU '{sku_code}' not found. Use search_inventory for exact SKU codes."}
    if product and not product.is_active:
        return {"error": f"'{product.name}' is no longer available for ordering."}
    if int(sku.get("stock", 0) or 0) < qty:
        return {"error": f"Insufficient stock for {sku_code}: only {sku.get('stock', 0)} left."}

    price = float(sku.get("price") or product.base_price or 0)
    item = {
        "sku": sku_code,
        "qty": qty,
        "product": product.name,
        "price": price,
        "notes": str(args.get("notes") or ""),
    }
    order = Order.objects.filter(tenant=tenant, customer_phone=phone, status="PENDING").first()
    items = (list(order.items) if order else []) + [item]
    if not order:
        order = Order(tenant=tenant, customer_phone=phone)
    order.customer_name = name
    order.address = address
    order.items = items
    order.total = sum(float(i.get("price", 0)) * int(i.get("qty", 1)) for i in items)
    order.status = "PENDING"
    order.save()
    adjust_stock(tenant, sku_code, -qty)
    return {"ok": True, "order_id": order.id, "total": order.total}


def _request_human(tenant, phone, reason):
    Conversation.objects.filter(tenant=tenant, customer_phone=phone).update(needs_human=True)
    return {"ok": True, "note": f"Owner alerted: {reason}"}


def _match_command(settings_data, text):
    lowered = (text or "").strip().lower()
    if not lowered:
        return None
    for command in settings_data.get("commands") or []:
        trigger = str(command.get("trigger") or "").strip().lower()
        if trigger and (lowered == trigger or lowered.startswith(trigger)):
            reply = str(command.get("reply") or "").strip()
            if reply:
                return reply
    return None


def _run_tool(tenant, phone, name, args, media_collector=None):
    if name == "search_inventory":
        return _search_inventory(tenant, args.get("query"))
    if name == "send_product_photo":
        res = _send_product_photo(tenant, args.get("product_name"), args.get("caption"))
        if res.get("ok") and res.get("image_url") and media_collector is not None:
            if not any(m.get("url") == res["image_url"] for m in media_collector):
                media_collector.append({"url": res["image_url"], "caption": res.get("caption", "")})
        return res
    if name == "get_customer_context":
        return _customer_context(tenant, phone)
    if name == "create_or_update_order":
        return _create_or_update_order(tenant, phone, args)
    if name == "request_human_support":
        return _request_human(tenant, phone, args.get("reason", ""))
    return {"error": f"Unknown tool '{name}'"}


def run_agent(tenant, phone, text, image=None, return_media=False):
    config = SystemConfig.load()
    conv, _ = Conversation.objects.get_or_create(tenant=tenant, customer_phone=phone)
    baseline = list(conv.messages or [])
    settings_data = tenant.settings or {}

    entry_text = (text or "").strip()
    if image:
        entry_text = (entry_text + " [image attached]").strip()
    entry = {"role": "user", "content": entry_text or "[empty message]"}
    image = _chat_image(tenant, conv, image)

    tokens = 0
    media_to_send = []
    reply = _match_command(settings_data, entry_text)

    if not reply:
        names = list(
            Product.objects.filter(tenant=tenant, is_active=True).values_list("name", flat=True)[:50]
        )
        prompt_tmpl = config.system_prompt or DEFAULT_PROMPT
        system_prompt = (
            prompt_tmpl.format(business=tenant.business_name)
            if "{business}" in prompt_tmpl
            else prompt_tmpl
        )
        system_prompt += "\nCatalog product names: " + (", ".join(names) if names else "(empty)")

        api_messages = [{"role": "system", "content": system_prompt}]
        for m in baseline[-40:]:
            api_messages.append({"role": m.get("role", "user"), "content": m.get("content", "")})
        use_responses = (
            "agentrouter.org" in (config.llm_base_url or "").lower()
            or (config.llm_base_url or "").rstrip("/").endswith("/responses")
        )
        if image:
            image_url = f"data:{image.get('mime', 'image/jpeg')};base64,{image['b64']}"
            content = [
                {"type": "input_text" if use_responses else "text", "text": entry_text or "What product is in this image?"},
                {"type": "input_image", "image_url": image_url, "detail": "auto"}
                if use_responses else {"type": "image_url", "image_url": {"url": image_url}},
            ]
        else:
            content = entry_text
        api_messages.append({"role": "user", "content": content})

        base_clean = (config.llm_base_url or "").rstrip("/")
        if use_responses:
            url = base_clean if base_clean.endswith("/responses") else (base_clean + "/responses")
        else:
            url = base_clean + "/chat/completions"

        headers = {
            "User-Agent": "opencode/1.17.12",
            "Content-Type": "application/json",
        }
        if config.api_key:
            headers["Authorization"] = f"Bearer {config.api_key}"

        session = _make_http_session()
        try:
            if not config.api_key and "api.openai.com" in config.llm_base_url:
                raise RuntimeError("No LLM API key configured")

            if use_responses:
                resp_tools = [
                    {
                        "type": "function",
                        "name": t["function"]["name"],
                        "description": t["function"]["description"],
                        "parameters": t["function"]["parameters"],
                    }
                    for t in TOOLS
                ]
                input_msgs = list(api_messages)
                for _ in range(5):
                    resp_payload = {
                        "model": config.model_name,
                        "input": input_msgs,
                        "tools": resp_tools,
                    }
                    try:
                        extra = json.loads(config.request_options or "{}")
                        if isinstance(extra, dict):
                            for k, v in extra.items():
                                if k not in ("model", "input", "messages", "tools"):
                                    resp_payload[k] = v
                    except Exception:
                        pass

                    response = session.post(url, headers=headers, json=resp_payload, timeout=90)
                    response.raise_for_status()
                    data = response.json()
                    tokens += int((data.get("usage") or {}).get("total_tokens", 0) or 0)
                    output_items = data.get("output") or []

                    fn_calls = [
                        item for item in output_items
                        if isinstance(item, dict) and item.get("type") == "function_call"
                    ]
                    if not fn_calls:
                        for item in output_items:
                            if isinstance(item, dict) and item.get("type") == "message":
                                content_list = item.get("content") or []
                                if isinstance(content_list, list):
                                    for c in content_list:
                                        if isinstance(c, dict) and c.get("text"):
                                            reply = str(c["text"]).strip()
                                            break
                                elif isinstance(content_list, str):
                                    reply = content_list.strip()
                                if reply:
                                    break
                        if not reply and isinstance(data.get("text"), str):
                            reply = data["text"].strip()
                        break

                    for fc in fn_calls:
                        call_id = fc.get("call_id") or fc.get("id")
                        fn_name = fc.get("name")
                        try:
                            fn_args = json.loads(fc.get("arguments") or "{}")
                        except (TypeError, json.JSONDecodeError):
                            fn_args = {}
                        result = _run_tool(tenant, phone, fn_name, fn_args, media_collector=media_to_send)
                        input_msgs.append({
                            "type": "function_call",
                            "call_id": call_id,
                            "name": fn_name,
                            "arguments": fc.get("arguments") or "{}",
                        })
                        input_msgs.append({
                            "type": "function_call_output",
                            "call_id": call_id,
                            "output": json.dumps(result, ensure_ascii=False, default=str),
                        })
            else:
                for _ in range(5):
                    response = session.post(
                        url,
                        headers=headers,
                        json=_request_payload(config, api_messages),
                        timeout=90,
                    )
                    response.raise_for_status()
                    data = response.json()
                    tokens += int((data.get("usage") or {}).get("total_tokens", 0) or 0)
                    message = data["choices"][0]["message"]
                    calls = message.get("tool_calls") or []
                    if not calls:
                        reply = (message.get("content") or "").strip()
                        break
                    api_messages.append(message)
                    for call in calls:
                        fn = call.get("function", {})
                        try:
                            args = json.loads(fn.get("arguments") or "{}")
                        except json.JSONDecodeError:
                            args = {}
                        result = _run_tool(tenant, phone, fn.get("name"), args, media_collector=media_to_send)
                        api_messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": call.get("id"),
                                "content": json.dumps(result, ensure_ascii=False, default=str),
                            }
                        )
        except Exception as exc:
            print(f"[run_agent ERROR] LLM failure for '{tenant.business_name}' (phone={phone}): {exc}")
            _log_error(config, f"agent tenant={tenant.id} phone={phone}: {exc}")
            conv.needs_human = True
            reply = (
                "Sorry, our assistant is temporarily unavailable. "
                "A team member will reply to you shortly."
            )

    if reply:
        reply = "".join(
            c for c in reply
            if not (unicodedata.category(c) in ("So", "Cn") or ord(c) > 0x1F000)
        ).strip()

    # Automatic catalogue photo attachment if customer asked for photos but tool was not called
    PHOTO_TRIGGERS = (
        "photo", "photos", "picture", "pictures", "pic", "pics",
        "image", "images", "look like", "show me", "dekhi", "chobi", "tasveer"
    )
    entry_lower = entry_text.lower()
    if any(trigger in entry_lower for trigger in PHOTO_TRIGGERS):
        for p in Product.objects.filter(tenant=tenant, is_active=True):
            if p.image_url:
                p_lower = p.name.lower()
                if (p_lower in entry_lower) or (reply and p_lower in reply.lower()):
                    if not any(m.get("url") == p.image_url for m in media_to_send):
                        cap = f"{p.name} - ${p.base_price:.2f}" if p.base_price else p.name
                        media_to_send.append({"url": p.image_url, "caption": cap})

    if reply and not baseline:
        greeting = str(settings_data.get("greeting") or "").strip()
        if greeting:
            reply = f"{greeting}\n\n{reply}"

    history = baseline + [entry]
    if reply or media_to_send:
        msg = {"role": "assistant", "content": reply or ""}
        if media_to_send:
            msg["media"] = media_to_send
        history.append(msg)
    conv.messages = history[-60:]
    conv.save()
    cleanup_images(conversation_images(baseline))

    fresh = Tenant.objects.filter(id=tenant.id).values_list("usage_stats", flat=True).first()
    stats = dict(fresh or {})
    stats["messages_count"] = int(stats.get("messages_count", 0)) + 1
    stats["tokens_used"] = int(stats.get("tokens_used", 0)) + tokens
    stats["last_active"] = datetime.now(timezone.utc).isoformat()
    tenant.usage_stats = stats
    tenant.save(update_fields=["usage_stats"])

    if return_media:
        return reply, media_to_send
    return reply
