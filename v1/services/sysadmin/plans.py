from django.core.exceptions import ObjectDoesNotExist
from core.models import CustomUser, Plan, Subscription
from .utils import get_user_from_token

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

    if user.role != CustomUser.Roles.SYSTEM_ADMIN:
        return {"response": {"error": "Доступ запрещён. Только системный администратор"}, "status": 403}

    identifier = params.get("id") or params.get("slug")
    if not identifier:
        return {"response": {"error": "Передайте id или slug плана"}, "status": 400}

    try:
        if len(str(identifier)) > 30:  # вероятно UUID
            plan = Plan.objects.get(id=identifier)
        else:
            plan = Plan.objects.get(slug=identifier)
    except ObjectDoesNotExist:
        return {"response": {"error": "План не найден"}, "status": 404}

    # Получаем все подписки на этот план
    subscriptions = Subscription.objects.filter(plan=plan).select_related('clinic')

    # Статистика
    total_subscriptions = subscriptions.count()
    active_subscriptions = subscriptions.filter(status__in=['active', 'trial']).count()

    # Список клиник с подробностями
    clinics_data = []
    for sub in subscriptions:
        if not sub.clinic:
            continue

        # Проверка лимитов
        limits_check = sub.clinic.check_limits()
        limits_ok = limits_check.get("ok", False)

        clinic_data = {
            "id": str(sub.clinic.id),
            "name": sub.clinic.name,
            "legal_name": sub.clinic.legal_name or "",
            "status": sub.clinic.status,
            "subscription_status": sub.status,
            "period_start": sub.period_start.isoformat() if sub.period_start else None,
            "period_end": sub.period_end.isoformat() if sub.period_end else None,
            "auto_renew": sub.auto_renew,
            "created_at": sub.created_at.isoformat(),
            
            # Текущая загрузка
            "current_users": sub.clinic.users.filter(is_active=True).count(),
            "current_branches": sub.clinic.branches.filter(is_active=True).count(),
            "current_patients": sub.clinic.patients.count(),
            
            # Лимиты плана
            "limit_users": plan.limit_users,
            "limit_branches": plan.limit_branches,
            "limit_patients": plan.limit_patients,
            
            "limits_exceeded": not limits_ok,
            "limits_warning": limits_check.get("error") if not limits_ok else None,
        }
        clinics_data.append(clinic_data)

    return {
        "response": {
            "plan": {
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
            "statistics": {
                "total_subscriptions": total_subscriptions,
                "active_subscriptions": active_subscriptions,
                "total_clinics": len(clinics_data),
            },
            "clinics": clinics_data
        },
        "status": 200
    }
