from datetime import datetime, timezone
import requests

PATHAO_SANDBOX_URL = "https://courier-api-sandbox.pathao.com"
PATHAO_PROD_URL = "https://api-hermes.pathao.com"


def _make_session():
    s = requests.Session()
    s.trust_env = False
    s.proxies = {"http": None, "https": None}
    return s


def _tracking_number(value):
    if isinstance(value, str):
        return value.strip()
    if type(value) is int and value > 0:
        return str(value)
    return ""


def _pathao_base(cfg):
    env = str((cfg or {}).get("environment") or "sandbox").lower()
    return PATHAO_PROD_URL if env == "production" else PATHAO_SANDBOX_URL


def pathao_config_error(cfg, require_store=False):
    if cfg.get("environment", "sandbox") not in ("sandbox", "production"):
        return "Choose the Pathao sandbox or production environment."
    if not all(str(cfg.get(key) or "").strip() for key in ("client_id", "client_secret", "username", "password")):
        return "Pathao Client ID, Secret, Username, and Password are all required."
    if require_store:
        try:
            if int(str(cfg.get("store_id") or "")) <= 0:
                raise ValueError
        except ValueError:
            return "Enter your Pathao pickup Store ID in Settings before shipping."
    return ""


def _pathao_issue_token(cfg):
    error = pathao_config_error(cfg)
    if error:
        return None, error

    session = _make_session()
    base = _pathao_base(cfg)
    payload = {
        "client_id": cfg["client_id"],
        "client_secret": cfg["client_secret"],
        "username": cfg["username"],
        "password": cfg["password"],
        "grant_type": "password",
    }
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    try:
        r = session.post(f"{base}/aladdin/api/v1/issue-token", headers=headers, json=payload, timeout=20)
        if r.status_code == 200:
            data = r.json()
            token = data.get("access_token")
            if token:
                return token, None
            return None, "Pathao did not return an access token."
        return None, f"Pathao auth failed (HTTP {r.status_code}): {r.text[:200]}"
    except Exception as exc:
        return None, f"Pathao connection error: {exc}"


def test_pathao_connection(cfg):
    token, err = _pathao_issue_token(cfg)
    if err:
        return {"ok": False, "provider": "pathao", "error": err}

    session = _make_session()
    base = _pathao_base(cfg)
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    stores = []
    try:
        r = session.get(f"{base}/aladdin/api/v1/stores", headers=headers, timeout=15)
        if r.status_code == 200:
            data = r.json()
            stores_list = data.get("data", {}).get("data", [])
            stores = [
                {"store_id": s.get("store_id"), "store_name": s.get("store_name")}
                for s in stores_list
            ]
    except Exception:
        pass

    msg = "Connected to Pathao successfully."
    if stores:
        msg += f" Found {len(stores)} pickup store(s)."

    return {
        "ok": True,
        "provider": "pathao",
        "message": msg,
        "stores": stores,
    }


def create_pathao_order(cfg, order):
    error = pathao_config_error(cfg, require_store=True)
    if error:
        return {"ok": False, "error": error}
    token, err = _pathao_issue_token(cfg)
    if err:
        return {"ok": False, "error": err}

    session = _make_session()
    base = _pathao_base(cfg)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    total_qty = max(1, sum(int(i.get("qty", 1) or 1) for i in (order.items or [])))
    payload = {
        "store_id": int(cfg["store_id"]),
        "merchant_order_id": f"ORD-{order.id}",
        "recipient_name": order.customer_name or "Valued Customer",
        "recipient_phone": order.customer_phone or "",
        "recipient_address": order.address or "Address not specified",
        "delivery_type": 48,
        "item_type": 2,
        "special_instruction": f"Order #{order.id}",
        "item_quantity": total_qty,
        "item_weight": 0.5,
        "amount_to_collect": float(order.total or 0),
    }

    try:
        r = session.post(f"{base}/aladdin/api/v1/orders", headers=headers, json=payload, timeout=25)
        data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        if r.status_code in (200, 201) and data.get("type") == "success":
            order_data = data.get("data") or {}
            cons_id = _tracking_number(order_data.get("consignment_id"))
            if not cons_id:
                return {"ok": False, "error": "Pathao did not return a consignment ID. Check the merchant portal before retrying."}
            return {
                "ok": True,
                "consignment": cons_id,
                "consignment_id": cons_id,
                "status": order_data.get("order_status", "placed"),
                "raw": data,
            }
        err = data.get("message") or r.text[:200]
        return {"ok": False, "error": f"Pathao error ({r.status_code}): {err}"}
    except Exception as exc:
        return {"ok": False, "error": f"Pathao dispatch error: {exc}"}


def dispatch(order):
    tenant = getattr(order, "tenant", None)
    settings = (tenant.settings or {}).get("couriers", {}) if tenant else {}
    config = settings.get("pathao") or {}
    if not config.get("enabled"):
        return {
            "courier": "MANUAL",
            "consignment": "",
            "status": "manual",
            "shipped_at": datetime.now(timezone.utc).isoformat(),
        }
    result = create_pathao_order(config, order)
    if not result.get("ok"):
        return {"error": result.get("error") or "The courier could not book this shipment."}
    tracking = _tracking_number(result.get("consignment"))
    if not tracking:
        return {"error": "The courier did not return tracking. Check the merchant portal before retrying."}
    return {
        "courier": "PATHAO",
        "consignment": tracking,
        "consignment_id": result.get("consignment_id"),
        "status": result.get("status", "placed"),
        "shipped_at": datetime.now(timezone.utc).isoformat(),
    }
