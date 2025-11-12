

import uuid
from django.conf import settings
import jwt
from core.models import Branch, Clinic, ClinicDirectorProfile, CustomUser, Plan, Subscription
from django.conf import settings
from datetime import datetime, timedelta, timezone






def decode_token(token: str):
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
    except:
        return None





def get_user_from_token(request):
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header.split(" ")[1]

    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        if payload.get("type") != "access":
            return None
        user = CustomUser.objects.select_related('clinic', 'branch').get(
            id=payload["user_id"], is_active=True
        )
        return user
    except:
        return None
def authenticate_user(request):
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header.split(" ")[1]
    
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        if payload.get("type") != "access":
            return None
        user = CustomUser.objects.filter(id=payload["user_id"], is_active=True).first()
        return user
    except:
        return None

def authenticate(request):
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    token = header.split(" ")[1]
    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        return None
    try:
        return CustomUser.objects.get(id=payload["user_id"], is_active=True)
    except CustomUser.DoesNotExist:
        return None


def parse_iso_datetime(date_str: str) -> datetime:
    """Принимает 2025-11-11T14:30:00Z или 2025-11-11T14:30:00+05:00 → возвращает aware datetime"""
    if not date_str:
        return None
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except:
        return None

ALGORITHM = "HS256"



def generate_tokens(user_id: uuid.UUID):
    now = datetime.now(timezone.utc)

    access = jwt.encode({
        "user_id": str(user_id),
        "type": "access",
        "exp": now + timedelta(hours=24),
        "iat": now
    }, settings.SECRET_KEY, algorithm="HS256")

    refresh = jwt.encode({
        "user_id": str(user_id),
        "type": "refresh",
        "exp": now + timedelta(days=30),
        "iat": now
    }, settings.SECRET_KEY, algorithm="HS256")

    return access, refresh



def login(request, params):
    email = params.get("email")
    password = params.get("password")

    if not email or not password:
        return {"response": {"error": "email и password обязательны"}, "status": 400}

    try:
        user = CustomUser.objects.get(email=email)
        if not user.check_password(password):
            return {"response": {"error": "Неверный пароль"}, "status": 401}
        if not user.is_active:
            return {"response": {"error": "Аккаунт заблокирован"}, "status": 403}

        access, refresh = generate_tokens(user.id)

        profile_data = {}
        if user.profile:
            if user.role == "doctor":
                profile_data = {
                    "specialization": user.profile.specialization,
                    "cabinet": user.profile.cabinet,
                    "color": user.profile.color
                }

        return {
            "response": {
                "success": True,
                "access_token": access,
                "refresh_token": refresh,
                "user": {
                    "id": str(user.id),
                    "full_name": user.full_name,
                    "email": user.email,
                    "phone": user.phone.as_e164 if user.phone else None,
                    "role": user.role,
                    "clinic_id": str(user.clinic.id) if user.clinic else None,
                    "branch_id": str(user.branch.id) if user.branch else None,
                    "profile": profile_data
                }
            },
            "status": 200
        }
    except CustomUser.DoesNotExist:
        return {"response": {"error": "Пользователь не найден"}, "status": 404}


def refresh_token(request, params):
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return {"response": {"error": "Требуется Bearer refresh_token"}, "status": 400}

    refresh_token = header.split(" ")[1]
    payload = decode_token(refresh_token)

    if not payload or payload.get("type") != "refresh":
        return {"response": {"error": "Неверный refresh token"}, "status": 401}

    try:
        user = CustomUser.objects.get(id=payload["user_id"], is_active=True)
        new_access, _ = generate_tokens(user.id)
        return {
            "response": {
                "success": True,
                "access_token": new_access
            },
            "status": 200
        }
    except CustomUser.DoesNotExist:
        return {"response": {"error": "Пользователь не найден"}, "status": 404}

def register(request, params):
    email = params.get("email")
    phone = params.get("phone")
    full_name = params.get("full_name")
    password = params.get("password")

    if not all([email, phone, full_name, password]):
        return {"response": {"error": "Заполните все поля"}, "status": 400}

    if CustomUser.objects.filter(email=email).exists():
        return {"response": {"error": "Email уже используется"}, "status": 400}

    user = CustomUser.objects.create(
        email=email,
        phone=phone,
        full_name=full_name,
        role=CustomUser.Roles.PENDING_DIRECTOR,
        is_active=True
    )
    user.set_password(password)
    user.save()

    access, refresh = generate_tokens(user.id)

    return {
        "response": {
            "success": True,
            "message": "Регистрация успешна. Выберите тариф.",
            "access_token": access,
            "refresh_token": refresh,
            "next_step": "choose_plan"
        },
        "status": 200
    }
    
    
    
    
    
 # v1/services/auth.py — ФИНАЛЬНАЯ ВЕРСИЯ (МНОГО КЛИНИК + ЛИМИТЫ)

import jwt
from django.conf import settings
from django.utils import timezone
from datetime import timedelta
from core.models import (
    CustomUser, Clinic, Branch, Plan, Subscription,
    ClinicDirectorProfile
)
from v1.services.auth import generate_tokens  # ← УБЕДИСЬ, ЧТО ЭТО ЕСТЬ


# === ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ: ПОЛУЧАЕМ ПОЛЬЗОВАТЕЛЯ ПО ТОКЕНУ ===
def get_user_from_token(request):
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header.split(" ")[1]
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        if payload.get("type") != "access":
            return None
        return CustomUser.objects.select_related('clinic', 'branch').get(
            id=payload["user_id"], is_active=True
        )
    except:
        return None


# v1/services/auth.py — ФИНАЛЬНАЯ ВЕРСИЯ (МНОГО КЛИНИК + ЛИМИТЫ)

import jwt
from django.conf import settings
from django.utils import timezone
from datetime import timedelta
from core.models import (
    CustomUser, Clinic, Branch, Plan, Subscription,
    ClinicDirectorProfile
)
from v1.services.auth import generate_tokens  # ← УБЕДИСЬ, ЧТО ЭТО ЕСТЬ


# === ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ: ПОЛУЧАЕМ ПОЛЬЗОВАТЕЛЯ ПО ТОКЕНУ ===
def get_user_from_token(request):
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header.split(" ")[1]
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        if payload.get("type") != "access":
            return None
        return CustomUser.objects.select_related('clinic', 'branch').get(
            id=payload["user_id"], is_active=True
        )
    except:
        return None


# === 1. ВЫБОР ПЛАНА И АКТИВАЦИЯ (ТОЛЬКО PENDING_DIRECTOR) ===
def choose_plan_and_activate(request, params):
    # ← ПРОВЕРКА ТОКЕНА ВРУЧНУЮ
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return {"response": {"error": "Токен обязателен"}, "status": 401}

    token = auth_header.split(" ")[1]

    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        if payload.get("type") != "access":
            return {"response": {"error": "Требуется access токен"}, "status": 401}

        user = CustomUser.objects.get(id=payload["user_id"], is_active=True)
    except jwt.ExpiredSignatureError:
        return {"response": {"error": "Токен истёк"}, "status": 401}
    except:
        return {"response": {"error": "Неверный токен"}, "status": 401}

    # ← ТОЛЬКО PENDING_DIRECTOR МОЖЕТ АКТИВИРОВАТЬ ПЕРВУЮ КЛИНИКУ
    if user.role != CustomUser.Roles.PENDING_DIRECTOR:
        return {"response": {"error": "Вы уже активировали клинику или не можете это сделать"}, "status": 400}

    plan_slug = params.get("plan_slug")
    clinic_name = params.get("clinic_name")
    address = params.get("address", "")

    if not plan_slug or not clinic_name:
        return {"response": {"error": "plan_slug и clinic_name обязательны"}, "status": 400}

    try:
        plan = Plan.objects.get(slug=plan_slug, is_active=True)
    except Plan.DoesNotExist:
        return {"response": {"error": "Тариф не найден"}, "status": 404}

    # === ПРОВЕРКА ЛИМИТА КЛИНИК (ДЛЯ PENDING — ЭТО ПЕРВАЯ) ===
    current_clinics = Clinic.objects.filter(director_profile_link__user=user).count()
    if current_clinics >= plan.limit_clinics:
        return {
            "response": {
                "error": f"Лимит клиник: {current_clinics}/{plan.limit_clinics}. Выберите другой план."
            },
            "status": 400
        }

    # === СОЗДАЁМ КЛИНИКУ ===
    clinic = Clinic.objects.create(
        name=clinic_name,
        legal_name=params.get("legal_name", clinic_name),
        inn=params.get("inn", ""),
        status="active"
    )

    # === СОЗДАЁМ ПОДПИСКУ ===
    Subscription.objects.create(
        clinic=clinic,
        plan=plan,
        status="trial",
        period_start=timezone.now().date(),
        period_end=timezone.now().date() + timedelta(days=30),
        auto_renew=True
    )

    # === ДЕЛАЕМ ПОЛЬЗОВАТЕЛЯ ДИРЕКТОРОМ ===
    user.role = CustomUser.Roles.CLINIC_DIRECTOR
    user.clinic = clinic  # ← основная клиника (для удобства)
    user.save()

    ClinicDirectorProfile.objects.get_or_create(user=user, clinic=clinic)

    # === ГЛАВНЫЙ ФИЛИАЛ ===
    branch = Branch.objects.create(
        clinic=clinic,
        name="Главный филиал",
        address=address or "Ташкент",
        phone=user.phone,
        email=user.email,
        is_active=True
    )
    user.branch = branch
    user.save()

    # === НОВЫЕ ТОКЕНЫ ===
    access, refresh = generate_tokens(user.id)

    return {
        "response": {
            "success": True,
            "message": "Вы стали директором клиники!",
            "clinic_id": str(clinic.id),
            "branch_id": str(branch.id),
            "plan": plan.name,
            "clinics_used": 1,
            "clinics_limit": plan.limit_clinics,
            "trial_days_left": 30,
            "access_token": access,
            "refresh_token": refresh
        },
        "status": 200
    }


# === 2. ВЕБХУК ОПЛАТЫ (Payme / Click) ===
def payment_webhook(request, params):
    """
    Пример от Payme:
    {
        "method": "Payme",
        "params": {
            "account": {"subscription_id": "uuid"},
            "transaction": "123456789",
            "state": 2
        }
    }
    """
    transaction_id = params.get("transaction")
    subscription_id = params.get("account", {}).get("subscription_id")
    state = params.get("state")

    if not transaction_id or not subscription_id:
        return {"response": {"error": "Недостаточно данных"}, "status": 400}

    if state != 2:  # 2 = оплачено
        return {"response": {"success": False, "message": "Оплата не подтверждена"}, "status": 200}

    try:
        subscription = Subscription.objects.get(id=subscription_id)
    except Subscription.DoesNotExist:
        return {"response": {"error": "Подписка не найдена"}, "status": 404}

    # ← АКТИВИРУЕМ ПОДПИСКУ
    if subscription.status in ["trial", "pending_payment"]:
        subscription.status = "active"
        subscription.period_end = timezone.now().date() + timedelta(days=30)
        subscription.auto_renew = True
        subscription.save()

        # ← Можно отправить уведомление директору
        # send_notification(subscription.clinic.director_profile_link.user, "Оплата прошла!")

        return {"response": {"success": True, "message": "Оплата подтверждена"}, "status": 200}

    return {"response": {"success": False, "message": "Подписка уже активна"}, "status": 200}