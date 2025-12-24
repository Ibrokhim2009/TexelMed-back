from gettext import translation
import random
import string
from core.models import Clinic, ClinicDirectorProfile, CustomUser, Plan, Subscription
from v1.services.auth import generate_tokens
from v1.services.director import get_user_from_token
from django.db import transaction
from django.core.exceptions import ObjectDoesNotExist











def sys_create_director(request, params):
    if not request.user or request.user.role != CustomUser.Roles.SYSTEM_ADMIN:
        return {"response": {"error": "Только системный администратор"}, "status": 403}

    full_name = params.get("full_name")
    email = params.get("email")
    phone = params.get("phone")
    password = params.get("password", "".join(random.choices(string.ascii_letters + string.digits, k=12)))
    clinic_id = params.get("clinic_id")

    if not all([full_name, email, phone]):
        return {"response": {"error": "Заполните все поля"}, "status": 400}

    if CustomUser.objects.filter(email=email).exists():
        return {"response": {"error": "Email уже используется"}, "status": 400}

    user = CustomUser.objects.create(
        full_name=full_name,
        email=email,
        phone=phone,
        role=CustomUser.Roles.CLINIC_DIRECTOR,
        is_active=True
    )
    user.set_password(password)
    user.save()

    if clinic_id:
        try:
            clinic = Clinic.objects.get(id=clinic_id)
            user.clinic = clinic
            user.save()
            ClinicDirectorProfile.objects.create(user=user, clinic=clinic)
            message = f"Директор назначен в клинику: {clinic.name}"
        except Clinic.DoesNotExist:
            return {"response": {"error": "Клиника не найдена"}, "status": 404}
    else:
        message = "Директор создан (без клиники)"

    access, refresh = generate_tokens(user.id)

    return {
        "response": {
            "success": True,
            "message": message,
            "user_id": str(user.id),
            "login": email,
            "password": password,
            "clinic_id": str(clinic.id) if clinic_id else None,
            "access_token": access,
            "refresh_token": refresh
        },
        "status": 200
    }



def create_plan(request, params):
    user = get_user_from_token(request)
    if not user:
        return {"response": {"error": "Токен обязателен"}, "status": 401}

    if user.role != CustomUser.Roles.SYSTEM_ADMIN:
        return {"response": {"error": "Доступ запрещён. Только системный администратор"}, "status": 403}

    required_fields = ["name", "slug", "price_monthly"]
    for field in required_fields:
        if not params.get(field):
            return {"response": {"error": f"Обязательное поле: {field}"}, "status": 400}

    slug = params["slug"].strip().lower()

    if Plan.objects.filter(slug=slug).exists():
        return {"response": {"error": "План с таким slug уже существует"}, "status": 400}

    plan = Plan.objects.create(
        name=params["name"].strip(),
        slug=slug,
        price_monthly=params["price_monthly"],
        currency=params.get("currency", "UZS"),
        limit_users=int(params.get("limit_users", 10)),
        limit_branches=int(params.get("limit_branches", 1)),
        limit_clinics=int(params.get("limit_clinics", 1)),
        limit_patients=int(params.get("limit_patients", 5000)),
        is_active=params.get("is_active", True) in (True, "true", "True", 1, "1")
    )

    return {
        "response": {
            "success": True,
            "message": "Тарифный план успешно создан",
            "plan": {
                "id": str(plan.id),
                "name": plan.name,
                "slug": plan.slug,
                "price_monthly": str(plan.price_monthly),
                "currency": plan.currency,
                "limit_users": plan.limit_users,
                "limit_branches": plan.limit_branches,
                "limit_clinics": plan.limit_clinics,
                "limit_patients": plan.limit_patients,
                "is_active": plan.is_active,
            }
        },
        "status": 201
    }


def update_plan(request, params):
    user = get_user_from_token(request)
    if not user:
        return {"response": {"error": "Токен обязателен"}, "status": 401}

    if user.role != CustomUser.Roles.SYSTEM_ADMIN:
        return {"response": {"error": "Доступ запрещён. Только системный администратор"}, "status": 403}

    plan_id = params.get("id")
    if not plan_id:
        return {"response": {"error": "Поле id обязательно"}, "status": 400}

    try:
        plan = Plan.objects.get(id=plan_id)
    except ObjectDoesNotExist:
        return {"response": {"error": "Тарифный план не найден"}, "status": 404}

    updated = False

    if "name" in params:
        plan.name = params["name"].strip()
        updated = True
    if "price_monthly" in params:
        plan.price_monthly = params["price_monthly"]
        updated = True
    if "currency" in params:
        plan.currency = params["currency"]
        updated = True
    if "limit_users" in params:
        plan.limit_users = int(params["limit_users"])
        updated = True
    if "limit_branches" in params:
        plan.limit_branches = int(params["limit_branches"])
        updated = True
    if "limit_clinics" in params:
        plan.limit_clinics = int(params["limit_clinics"])
        updated = True
    if "limit_patients" in params:
        plan.limit_patients = int(params["limit_patients"])
        updated = True
    if "is_active" in params:
        plan.is_active = params["is_active"] in (True, "true", "True", 1, "1")
        updated = True
    if "slug" in params:
        new_slug = params["slug"].strip().lower()
        if new_slug != plan.slug and Plan.objects.filter(slug=new_slug).exists():
            return {"response": {"error": "Этот slug уже занят"}, "status": 400}
        plan.slug = new_slug
        updated = True

    if not updated:
        return {"response": {"error": "Нет данных для обновления"}, "status": 400}

    plan.save()

    return {
        "response": {
            "success": True,
            "message": "Тарифный план обновлён",
            "plan": {
                "id": str(plan.id),
                "name": plan.name,
                "slug": plan.slug,
                "price_monthly": str(plan.price_monthly),
                "currency": plan.currency,
                "limit_users": plan.limit_users,
                "limit_branches": plan.limit_branches,
                "limit_clinics": plan.limit_clinics,
                "limit_patients": plan.limit_patients,
                "is_active": plan.is_active,
            }
        },
        "status": 200
    }


def delete_plan(request, params):
    user = get_user_from_token(request)
    if not user:
        return {"response": {"error": "Токен обязателен"}, "status": 401}

    if user.role != CustomUser.Roles.SYSTEM_ADMIN:
        return {"response": {"error": "Доступ запрещён. Только системный администратор"}, "status": 403}

    plan_id = params.get("id")
    if not plan_id:
        return {"response": {"error": "Поле id обязательно"}, "status": 400}

    try:
        plan = Plan.objects.get(id=plan_id)
    except ObjectDoesNotExist:
        return {"response": {"error": "Тарифный план не найден"}, "status": 404}

    if Subscription.objects.filter(plan=plan, status__in=['active', 'trial', 'overdue']).exists():
        return {"response": {"error": "Нельзя удалить план — есть активные подписки"}, "status": 400}

    plan_name = plan.name
    plan.delete()

    return {
        "response": {
            "success": True,
            "message": f"Тарифный план «{plan_name}» удалён"
        },
        "status": 200
    }


def list_plans(request, params):
    user = get_user_from_token(request)
    if not user:
        return {"response": {"error": "Токен обязателен"}, "status": 401}

    if user.role not in [CustomUser.Roles.SYSTEM_ADMIN, CustomUser.Roles.CLINIC_DIRECTOR, CustomUser.Roles.PENDING_DIRECTOR]:
        return {"response": {"error": "Доступ запрещён"}, "status": 403}

    plans = Plan.objects.filter(is_active=True).order_by('price_monthly')

    data = []
    for p in plans:
        active_count = Subscription.objects.filter(plan=p, status__in=['active', 'trial']).count()
        data.append({
            "id": str(p.id),
            "name": p.name,
            "slug": p.slug,
            "price_monthly": str(p.price_monthly),
            "currency": p.currency,
            "limit_users": p.limit_users,
            "limit_branches": p.limit_branches,
            "limit_clinics": p.limit_clinics,
            "limit_patients": p.limit_patients,
            "active_subscriptions": active_count,
        })

    return {"response": data, "status": 200}


def get_plan(request, params):
    user = get_user_from_token(request)
    if not user:
        return {"response": {"error": "Токен обязателен"}, "status": 401}

    identifier = params.get("id") or params.get("slug")
    if not identifier:
        return {"response": {"error": "Передайте id или slug плана"}, "status": 400}

    try:
        if len(str(identifier)) > 30:  # UUID
            plan = Plan.objects.get(id=identifier)
        else:
            plan = Plan.objects.get(slug=identifier)
    except ObjectDoesNotExist:
        return {"response": {"error": "План не найден"}, "status": 404}

    return {
        "response": {
            "id": str(plan.id),
            "name": plan.name,
            "slug": plan.slug,
            "price_monthly": str(plan.price_monthly),
            "currency": plan.currency,
            "limits": {
                "users": plan.limit_users,
                "branches": plan.limit_branches,
                "clinics": plan.limit_clinics,
                "patients": plan.limit_patients,
            },
            "is_active": plan.is_active,
        },
        "status": 200
    }