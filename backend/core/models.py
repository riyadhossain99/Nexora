import logging
import os
from pathlib import Path
from urllib.parse import unquote, urlsplit

from django.conf import settings
from django.contrib.auth.models import User
from django.db import models, transaction


class SystemConfig(models.Model):
    llm_base_url = models.URLField(default="https://api.openai.com/v1")
    api_key = models.CharField(max_length=500, blank=True)
    model_name = models.CharField(max_length=100, default="gpt-4o-mini")
    system_prompt = models.TextField(blank=True)
    request_options = models.TextField(default="{}", blank=True)
    error_logs = models.JSONField(default=list, blank=True)

    def __str__(self):
        return f"SystemConfig({self.model_name})"

    @classmethod
    def load(cls):
        config = cls.objects.first()
        if config is None:
            config = cls.objects.create(
                llm_base_url=os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1"),
                api_key=os.environ.get("LLM_API_KEY", os.environ.get("OPENAI_API_KEY", "")),
                model_name=os.environ.get("LLM_MODEL", "gpt-4o-mini"),
            )
        else:
            updated = False
            env_key = os.environ.get("LLM_API_KEY", os.environ.get("OPENAI_API_KEY", "")).strip()
            if not config.api_key and env_key:
                config.api_key = env_key
                updated = True
            env_url = os.environ.get("LLM_BASE_URL", "").strip()
            if env_url and (config.llm_base_url == "https://api.openai.com/v1" or not config.llm_base_url):
                config.llm_base_url = env_url
                updated = True
            env_model = os.environ.get("LLM_MODEL", "").strip()
            if env_model and (config.model_name == "gpt-4o-mini" or not config.model_name):
                config.model_name = env_model
                updated = True
            if updated:
                config.save()
        return config


class Tenant(models.Model):
    WA_CHOICES = [
        ("CONNECTING", "Connecting"),
        ("QR_READY", "QR Ready"),
        ("CONNECTED", "Connected"),
        ("DISCONNECTED", "Disconnected"),
    ]
    PLAN_CHOICES = [
        ("BASIC", "Basic"),
        ("PLUS", "Plus"),
        ("PRO", "Pro"),
    ]
    PLAN_STATUS_CHOICES = [
        ("ACTIVE", "Active"),
        ("CANCELLED", "Cancelled"),
    ]
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="tenant")
    business_name = models.CharField(max_length=200)
    plan = models.CharField(max_length=10, choices=PLAN_CHOICES, default="BASIC")
    plan_status = models.CharField(max_length=10, choices=PLAN_STATUS_CHOICES, default="ACTIVE")
    wa_status = models.CharField(max_length=20, choices=WA_CHOICES, default="DISCONNECTED")
    usage_stats = models.JSONField(default=dict, blank=True)
    settings = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.business_name


PLAN_LIMITS = {
    "BASIC": {"products": 50, "messages_per_min": 5},
    "PLUS": {"products": 150, "messages_per_min": 20},
    "PRO": {"products": 300, "messages_per_min": 50},
}


def plan_limits(tenant):
    return PLAN_LIMITS.get(getattr(tenant, "plan", "BASIC"), PLAN_LIMITS["BASIC"])


def product_limit(tenant):
    return plan_limits(tenant)["products"]


def messages_per_min(tenant):
    return plan_limits(tenant)["messages_per_min"]


class EmailOTP(models.Model):
    PURPOSE_CHOICES = [
        ("signup", "Signup"),
        ("reset", "Password reset"),
    ]
    email = models.EmailField()
    purpose = models.CharField(max_length=10, choices=PURPOSE_CHOICES)
    method_id = models.CharField(max_length=200, blank=True)
    code = models.CharField(max_length=10, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    used = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    def __str__(self):
        return f"{self.purpose}:{self.email}"


class Product(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    base_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    image_url = models.URLField(blank=True)
    skus = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Conversation(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE)
    customer_phone = models.CharField(max_length=30)
    customer_name = models.CharField(max_length=200, blank=True)
    messages = models.JSONField(default=list, blank=True)
    needs_human = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("tenant", "customer_phone")]

    def __str__(self):
        return self.customer_phone


class Order(models.Model):
    STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("ACCEPTED", "Accepted"),
        ("SHIPPED", "Shipped"),
        ("CANCELLED", "Cancelled"),
        ("COMPLETED", "Completed"),
    ]
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE)
    customer_phone = models.CharField(max_length=30)
    customer_name = models.CharField(max_length=200, blank=True)
    address = models.TextField(blank=True)
    items = models.JSONField(default=list, blank=True)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="PENDING")
    shipment = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Order#{self.pk} {self.status}"


def find_sku(tenant, code):
    code = str(code or "").strip().lower()
    for product in Product.objects.filter(tenant=tenant):
        for sku in product.skus or []:
            if str(sku.get("sku", "")).strip().lower() == code:
                return product, sku
    return None, None


def adjust_stock(tenant, code, delta):
    product, sku = find_sku(tenant, code)
    if not sku:
        return None
    sku["stock"] = max(0, int(sku.get("stock", 0) or 0) + delta)
    product.save(update_fields=["skus"])
    return sku


def conversation_images(messages):
    urls = set()
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        for media in message.get("media") or []:
            url = media.get("url") if isinstance(media, dict) else media
            if isinstance(url, str):
                urls.add(url)
    return urls


def local_image_path(url):
    root = Path(settings.MEDIA_ROOT).resolve()
    try:
        path = unquote(urlsplit(url or "").path)
        if not path.startswith(settings.MEDIA_URL):
            return None
        file = (root / path.removeprefix(settings.MEDIA_URL)).resolve()
        if root in file.parents and file.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"):
            return file
    except (OSError, ValueError):
        pass
    return None


def cleanup_images(urls):
    root = Path(settings.MEDIA_ROOT).resolve()

    candidates = {local_image_path(url) for url in urls if isinstance(url, str) and url.startswith(settings.MEDIA_URL)} - {None}
    if not candidates:
        return

    def remove_unused():
        # Check every business, including archived products and photos kept in chats.
        referenced = {local_image_path(url) for url in Product.objects.exclude(image_url="").values_list("image_url", flat=True)}
        for messages in Conversation.objects.values_list("messages", flat=True).iterator():
            referenced.update(local_image_path(url) for url in conversation_images(messages))
        for file in candidates - referenced:
            try:
                file.unlink(missing_ok=True)
            except OSError as exc:
                logging.getLogger(__name__).warning("Could not remove unused photo %s: %s", file, exc)
                continue
            if file.parent != root:
                try:
                    file.parent.rmdir()
                except OSError:
                    pass  # The folder still contains another photo.

    transaction.on_commit(remove_unused, robust=True)
