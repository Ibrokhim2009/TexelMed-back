import uuid
import jwt
from datetime import datetime, timedelta, timezone  # ← timezone.utc — это экземпляр!

from django.conf import settings
from django.utils import timezone as dj_timezone  # ← Для dj_timezone.now()

from core.models import (
    Branch, Clinic, ClinicDirectorProfile, CustomUser, PasswordResetOTP, Plan, Subscription
)
from helper.auth import generate_otp, send_password_reset_email


# === КОНСТАНТЫ ===
ALGORITHM = "HS256"


# === ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ===

def decode_token(token: str):
    """Декодирует JWT токен, возвращает payload или None"""
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
    except:
        return None


def get_user_from_token(request):
    """Извлекает пользователя из access токена (с select_related)"""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header.split(" ")[1]

    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "access":
            return None
        return CustomUser.objects.select_related('clinic', 'branch').get(
            id=payload["user_id"], is_active=True
        )
    except:
        return None


def authenticate_user(request):
    """Альтернативная аутентификация (filter.first())"""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header.split(" ")[1]

    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "access":
            return None
        return CustomUser.objects.filter(id=payload["user_id"], is_active=True).first()
    except:
        return None


def authenticate(request):
    """Упрощённая аутентификация через decode_token"""
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
    """Парсит ISO дату → возвращает aware datetime в UTC"""
    if not date_str:
        return None
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)  # ← ЭКЗЕМПЛЯР!
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def generate_tokens(user_id: uuid.UUID):
    """Генерирует access и refresh токены"""
    now = datetime.now(timezone.utc)  # ← ЭКЗЕМПЛЯР timezone.utc

    access = jwt.encode({
        "user_id": str(user_id),
        "type": "access",
        "exp": now + timedelta(hours=24),
        "iat": now
    }, settings.SECRET_KEY, algorithm=ALGORITHM)

    refresh = jwt.encode({
        "user_id": str(user_id),
        "type": "refresh",
        "exp": now + timedelta(days=30),
        "iat": now
    }, settings.SECRET_KEY, algorithm=ALGORITHM)

    return access, refresh


# === ОСНОВНЫЕ ЭНДПОИНТЫ ===

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
        if hasattr(user, 'profile') and user.profile:
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


def choose_plan_and_activate(request, params):
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return {"response": {"error": "Токен обязателен"}, "status": 401}

    token = auth_header.split(" ")[1]

    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "access":
            return {"response": {"error": "Требуется access токен"}, "status": 401}

        user = CustomUser.objects.get(id=payload["user_id"], is_active=True)
    except jwt.ExpiredSignatureError:
        return {"response": {"error": "Токен истёк"}, "status": 401}
    except:
        return {"response": {"error": "Неверный токен"}, "status": 401}

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
        return {"response": {"error": f"Тариф не найден", }, "status": 404}
    

    current_clinics = Clinic.objects.filter(director_profile_link__user=user).count()
    if current_clinics >= plan.limit_clinics:
        return {
            "response": {
                "error": f"Лимит клиник: {current_clinics}/{plan.limit_clinics}. Выберите другой план."
            },
            "status": 400
        }

    clinic = Clinic.objects.create(
        name=clinic_name,
        legal_name=params.get("legal_name", clinic_name),
        inn=params.get("inn", ""),
        status="active"
    )

    Subscription.objects.create(
        clinic=clinic,
        plan=plan,
        status="trial",
        period_start=dj_timezone.now().date(),
        period_end=dj_timezone.now().date() + timedelta(days=30),
        auto_renew=True
    )

    user.role = CustomUser.Roles.CLINIC_DIRECTOR
    user.clinic = clinic
    user.save()

    ClinicDirectorProfile.objects.get_or_create(user=user, clinic=clinic)

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

    access, refresh = generate_tokens(user.id)

    return {
        "response": {
            "success": True,
            "message": "Вы стали директором клиники!",
            "clinic_id": str(clinic.id),
            "branch_id": str(branch.id),
            "plan": plan.name,
            "clinics_used": current_clinics + 1,
            "clinics_limit": plan.limit_clinics,
            "access_token": access,
            "refresh_token": refresh
        },
        "status": 200
    }


def payment_webhook(request, params):
    """
    Вебхук оплаты (Payme / Click)
    """
    transaction_id = params.get("transaction")
    account = params.get("account", {})
    subscription_id = account.get("subscription_id")
    state = params.get("state")

    if not transaction_id or not subscription_id:
        return {"response": {"error": "Недостаточно данных"}, "status": 400}

    if state != 2:  # 2 = оплачено
        return {"response": {"success": False, "message": "Оплата не подтверждена"}, "status": 200}

    try:
        subscription = Subscription.objects.get(id=subscription_id)
    except Subscription.DoesNotExist:
        return {"response": {"error": "Подписка не найдена"}, "status": 404}

    if subscription.status in ["trial", "pending_payment"]:
        subscription.status = "active"
        subscription.period_end = dj_timezone.now().date() + timedelta(days=30)
        subscription.auto_renew = True
        subscription.save()
        return {"response": {"success": True, "message": "Оплата подтверждена"}, "status": 200}

    return {"response": {"success": False, "message": "Подписка уже активна"}, "status": 200}


def forgot_password(request, params):
    """Шаг 1: Запрос сброса пароля → отправка OTP на email"""
    email = params.get("email")
    if not email:
        return {"response": {"error": "email обязателен"}, "status": 400}

    try:
        user = CustomUser.objects.get(email=email, is_active=True)
    except CustomUser.DoesNotExist:
        # Не говорим, существует ли пользователь (безопасность)
        return {"response": {"success": True, "message": "Если email зарегистрирован, на него отправлен код восстановления"}, "status": 200}

    # Удаляем старые неиспользованные OTP этого пользователя
    PasswordResetOTP.objects.filter(user=user, used=False).delete()

    # Генерируем новый код
    code = generate_otp()
    expires_at = dj_timezone.now() + timedelta(minutes=10)

    PasswordResetOTP.objects.create(
        user=user,
        code=code,
        expires_at=expires_at
    )

    # Отправляем email
    try:
        send_password_reset_email(user, code)
    except Exception as e:
        # В продакшене лучше логировать
        print(f"Ошибка отправки email: {e}")
        return {"response": {"error": "Ошибка отправки кода. Попробуйте позже."}, "status": 500}

    return {
        "response": {
            "success": True,
            "message": "Код восстановления отправлен на ваш email"
        },
        "status": 200
    }


def reset_password(request, params):
    """Шаг 2: Подтверждение OTP и смена пароля"""
    email = params.get("email")
    code = params.get("code")
    new_password = params.get("new_password")

    if not all([email, code, new_password]):
        return {"response": {"error": "email, code и new_password обязательны"}, "status": 400}

    if len(new_password) < 8:
        return {"response": {"error": "Пароль должен быть не менее 8 символов"}, "status": 400}

    try:
        user = CustomUser.objects.get(email=email, is_active=True)
    except CustomUser.DoesNotExist:
        return {"response": {"error": "Неверные данные"}, "status": 400}

    try:
        otp_obj = PasswordResetOTP.objects.filter(
            user=user,
            code=code,
            used=False,
            expires_at__gte=dj_timezone.now()
        ).latest('created_at')
    except PasswordResetOTP.DoesNotExist:
        return {"response": {"error": "Неверный или просроченный код"}, "status": 400}

    # Меняем пароль
    user.set_password(new_password)
    user.save()

    # Помечаем код как использованный
    otp_obj.used = True
    otp_obj.save()

    # Генерируем новые токены (чтобы старые access/refresh стали невалидными)
    access, refresh = generate_tokens(user.id)

    return {
        "response": {
            "success": True,
            "message": "Пароль успешно изменён",
            "access_token": access,
            "refresh_token": refresh
        },
        "status": 200
    }