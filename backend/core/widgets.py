from .models import Order, SystemConfig, Tenant


def _units_and_revenue(tenant):
    units = {}
    revenue = {}
    for order in tenant.order_set.exclude(status="CANCELLED"):
        for item in order.items or []:
            name = str(item.get("product") or item.get("sku") or "item")
            try:
                qty = int(item.get("qty", 1) or 1)
                price = float(item.get("price", 0) or 0)
            except (TypeError, ValueError):
                continue
            units[name] = units.get(name, 0) + qty
            revenue[name] = revenue.get(name, 0) + price * qty
    return units, revenue


def _sales_stats(tenant):
    units, revenue = _units_and_revenue(tenant)
    top = sorted(units.items(), key=lambda kv: (-kv[1], kv[0]))[:8]
    return {
        "orders": tenant.order_set.exclude(status="CANCELLED").count(),
        "total_units": sum(units.values()),
        "total_revenue": sum(revenue.values()),
        "top_sellers": [
            {"label": name, "units": units[name], "revenue": revenue.get(name, 0)}
            for name, _ in top
        ],
        "donut": [{"label": name, "value": units[name]} for name, _ in top],
    }


def _inventory_stats(tenant):
    units, _ = _units_and_revenue(tenant)
    rows = []
    for product in tenant.product_set.order_by("name"):
        stock = 0
        for sku in product.skus or []:
            try:
                stock += int(sku.get("stock", 0) or 0)
            except (TypeError, ValueError):
                continue
        rows.append({"name": product.name, "stock": stock, "sold": units.get(product.name, 0)})
    return {"rows": rows, "total_stock": sum(row["stock"] for row in rows)}


_ORDER_FIELDS = (
    "id",
    "customer_name",
    "customer_phone",
    "address",
    "items",
    "total",
    "status",
    "shipment",
    "created_at",
)


CLIENT_WIDGETS = {
    "summary_cards": lambda t: {
        "products": t.product_set.count(),
        "pending_orders": t.order_set.filter(status="PENDING").count(),
        "active_orders": t.order_set.filter(status="ACCEPTED").count(),
        "shipped_orders": t.order_set.filter(status="SHIPPED").count(),
        "human_alerts": t.conversation_set.filter(needs_human=True).count(),
    },
    "sales_stats": _sales_stats,
    "inventory_stats": _inventory_stats,
    "recent_orders": lambda t: list(
        t.order_set.order_by("-created_at").values(*_ORDER_FIELDS)[:50]
    ),
    "pending_orders": lambda t: list(
        t.order_set.filter(status="PENDING").order_by("-created_at").values(*_ORDER_FIELDS)[:50]
    ),
    "active_orders": lambda t: list(
        t.order_set.filter(status="ACCEPTED").order_by("-created_at").values(*_ORDER_FIELDS)[:50]
    ),
    "order_history": lambda t: list(
        t.order_set.exclude(status="PENDING").order_by("-created_at").values(*_ORDER_FIELDS)[:50]
    ),
    "catalog_skus": lambda t: _catalog_rows(t),
    "chat_threads": lambda t: list(
        t.conversation_set.order_by("-needs_human", "-updated_at").values(
            "id", "customer_phone", "customer_name", "needs_human", "messages", "updated_at"
        )[:50]
    ),
    "tenant_settings": lambda t: {
        "business_name": t.business_name,
        "greeting": (t.settings or {}).get("greeting", ""),
        "commands": (t.settings or {}).get("commands", []),
    },
}

def _catalog_rows(tenant):
    rows = []
    for product in tenant.product_set.order_by("is_active", "name"):
        stocks, prices = [], []
        for sku in product.skus or []:
            try:
                stocks.append(max(0, int(sku.get("stock", 0) or 0)))
            except (TypeError, ValueError):
                stocks.append(0)
            try:
                prices.append(float(sku.get("price", 0) or 0))
            except (TypeError, ValueError):
                continue
        rows.append(
            {
                "id": product.id,
                "name": product.name,
                "description": product.description,
                "base_price": product.base_price,
                "image_url": product.image_url,
                "skus": product.skus,
                "is_active": product.is_active,
                "variants": len(product.skus or []),
                "total_stock": sum(stocks),
                "min_price": min(prices) if prices else float(product.base_price or 0),
                "max_price": max(prices) if prices else float(product.base_price or 0),
                "low_stock": sum(1 for s in stocks if 0 < s <= 3),
                "out_of_stock": sum(1 for s in stocks if s == 0),
            }
        )
    return rows


def _tenant_rows():
    rows = []
    for tenant in Tenant.objects.order_by("id"):
        orders = tenant.order_set.all()
        orders_count = orders.count()
        converted = orders.exclude(status="CANCELLED").count()
        messages = int((tenant.usage_stats or {}).get("messages_count", 0))
        conversion = f"{converted / messages * 100:.1f}%" if messages else "-"
        rows.append(
            {
                "id": tenant.id,
                "business_name": tenant.business_name,
                "wa_status": tenant.wa_status,
                "is_active": tenant.is_active,
                "plan": tenant.plan,
                "plan_status": tenant.plan_status,
                "messages": messages,
                "orders": orders_count,
                "conversion": conversion,
                "usage_stats": tenant.usage_stats or {},
            }
        )
    return rows


ADMIN_WIDGETS = {
    "system_overview": lambda: {
        "total_tenants": Tenant.objects.count(),
        "active_tenants": Tenant.objects.filter(is_active=True).count(),
        "active_wa_sessions": Tenant.objects.filter(wa_status="CONNECTED").count(),
        "total_orders": Order.objects.count(),
    },
    "tenant_usage": _tenant_rows,
    "config_and_logs": lambda: SystemConfig.objects.values(
        "llm_base_url", "model_name", "system_prompt", "request_options", "error_logs"
    ).first()
    or {},
}
