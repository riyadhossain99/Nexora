import re
import secrets
from datetime import timedelta

import requests
from django.conf import settings
from django.utils import timezone

from .agent import _log_error
from .models import EmailOTP, SystemConfig

OTP_TTL_MINUTES = 10
MAX_ATTEMPTS = 5
SEND_ERROR = "We couldn't send the code right now. Please try again in a moment."
CODE_ERROR = "That code is invalid or has expired. Request a new one if needed."


def password_error(password):
    password = str(password or "")
    if (not 8 <= len(password) <= 16
            or not re.search(r"[a-z]", password)
            or not re.search(r"[A-Z]", password)
            or not re.search(r"\d", password)):
        return "Password must be 8-16 characters and include a lowercase letter, an uppercase letter and a number."
    return None


def _new_code():
    return "".join(secrets.choice("0123456789") for _ in range(6))


def _dev_mode():
    return settings.DEBUG and settings.EMAIL_OTP_BACKEND == "dev"


def _stytch_post(path, payload):
    if not all((settings.STYTCH_PROJECT_ID, settings.STYTCH_SECRET, settings.STYTCH_ORGANIZATION_ID)):
        raise ValueError("Configure the Stytch project, secret and organization in backend/.env.")
    if settings.STYTCH_ENV not in ("test", "live"):
        raise ValueError("STYTCH_ENV must be test or live.")
    return requests.post(
        f"{settings.STYTCH_BASE_URL}{path}",
        auth=(settings.STYTCH_PROJECT_ID, settings.STYTCH_SECRET),
        json=payload,
        timeout=20,
    )


def _stytch_b2b_send(email):
    org = settings.STYTCH_ORGANIZATION_ID
    member = _stytch_post(
        f"/v1/b2b/organizations/{org}/members",
        {"email_address": email, "create_member_as_pending": True},
    )
    member_data = member.json()
    if member.status_code != 200 and member_data.get("error_type") != "duplicate_member_email":
        raise RuntimeError(member_data.get("error_message") or f"stytch status {member.status_code}")
    response = _stytch_post(
        "/v1/b2b/otps/email/login_or_signup",
        {
            "organization_id": org,
            "email_address": email,
            "login_expiration_minutes": OTP_TTL_MINUTES,
            "signup_expiration_minutes": OTP_TTL_MINUTES,
        },
    )
    data = response.json()
    if response.status_code != 200:
        raise RuntimeError(data.get("error_message") or f"stytch status {response.status_code}")


def _stytch_b2b_verify(email, code):
    response = _stytch_post(
        "/v1/b2b/otps/email/authenticate",
        {
            "organization_id": settings.STYTCH_ORGANIZATION_ID,
            "email_address": email,
            "code": code,
        },
    )
    return response.status_code == 200 and response.json().get("member_authenticated") is True


def send_otp(email, purpose):
    EmailOTP.objects.filter(email__iexact=email, purpose=purpose).delete()
    otp = EmailOTP.objects.create(
        email=email,
        purpose=purpose,
        expires_at=timezone.now() + timedelta(minutes=OTP_TTL_MINUTES),
    )
    try:
        if _dev_mode():
            otp.code = _new_code()
            otp.save(update_fields=["code"])
            print(f"[email-otp] {purpose} code for {email}: {otp.code}")
        elif settings.EMAIL_OTP_BACKEND == "stytch":
            _stytch_b2b_send(email)
            otp.method_id = "b2b"
            otp.save(update_fields=["method_id"])
        else:
            raise ValueError("Use EMAIL_OTP_BACKEND=stytch, or dev with DJANGO_DEBUG=1 for local testing.")
        return True, None
    except Exception as exc:
        otp.delete()
        _log_error(SystemConfig.load(), f"email otp {purpose} send to {email}: {exc}")
        return False, SEND_ERROR


def verify_otp(email, purpose, code):
    otp = (
        EmailOTP.objects.filter(email__iexact=email, purpose=purpose, used=False)
        .order_by("-id")
        .first()
    )
    if not otp or otp.expires_at <= timezone.now() or otp.attempts >= MAX_ATTEMPTS:
        return False
    code = str(code or "").strip()
    ok = False
    if re.fullmatch(r"[0-9]{6}", code) and otp.method_id == "b2b" and settings.EMAIL_OTP_BACKEND == "stytch":
        try:
            ok = _stytch_b2b_verify(email, code)
        except Exception as exc:
            _log_error(SystemConfig.load(), f"email otp {purpose} verify {email}: {exc}")
            return False
    elif re.fullmatch(r"[0-9]{6}", code) and not otp.method_id and _dev_mode():
        ok = bool(otp.code) and secrets.compare_digest(code, otp.code)
    if ok:
        otp.used = True
        otp.save(update_fields=["used"])
        return True
    otp.attempts += 1
    otp.save(update_fields=["attempts"])
    return False


def dev_code_for(email, purpose):
    if not _dev_mode():
        return ""
    otp = (
        EmailOTP.objects.filter(email__iexact=email, purpose=purpose, used=False)
        .order_by("-id")
        .first()
    )
    return otp.code if otp and otp.expires_at > timezone.now() else ""
