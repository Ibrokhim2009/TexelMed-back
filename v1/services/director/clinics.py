from datetime import timedelta
from django.utils import timezone
from core.models import CustomUser, Clinic, Branch, Plan, Subscription, ClinicDirectorProfile
from v1.services.auth import generate_tokens
from .utils import get_user_from_token

def get_my_status(request, params):
    user = get_user_from_token(request)
    if not user:
        return {"response": {"error": "Токен обязателен"}, "status": 401}

    director_clinics = Clinic.objects.filter(director_profile_link__user=user).select_related('subscription__plan')

    response = {
        "success": True,
        "user": {
            "id": str(user.id),
            "full_name": user.full_name,
            "email": user.email,
            "phone": user.phone.as_e164 if user.phone else None,
            "role": user.role,
            "clinics_count": director_clinics.count(),
            "is_director": user.role == CustomUser.Roles.CLINIC_DIRECTOR,
            "is_pending": user.role == CustomUser.Roles.PENDING_DIRECTOR,
        }
    }

    if user.role == CustomUser.Roles.PENDING_DIRECTOR:
        response["next_step"] = "choose_plan"
    elif director_clinics.exists():
        response["next_step"] = "dashboard"

    return {"response": response, "status": 200}


def create_clinic(request, params):
    user = get_user_from_token(request)
    if not user:
        return {"response": {"error": "Авторизуйтесь"}, "status": 401}

    if user.role not in [CustomUser.Roles.PENDING_DIRECTOR, CustomUser.Roles.CLINIC_DIRECTOR]:
        return {"response": {"error": "Недостаточно прав"}, "status": 403}

    clinic_name = params.get("clinic_name")
    plan_slug = params.get("plan_slug")

    if not clinic_name or not plan_slug:
        return {"response": {"error": "clinic_name и plan_slug обязательны"}, "status": 400}

    try:
        plan = Plan.objects.get(slug=plan_slug, is_active=True)
    except Plan.DoesNotExist:
        return {"response": {"error": "Тариф не найден"}, "status": 404}

    current_clinics = Clinic.objects.filter(director_profile_link__user=user).count()
    if current_clinics >= plan.limit_clinics:
        return {
            "response": {
                "error": f"Лимит клиник: {current_clinics}/{plan.limit_clinics}. Обновите план."
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
        period_start=timezone.now().date(),
        period_end=timezone.now().date() + timedelta(days=30),
        auto_renew=True
    )

    ClinicDirectorProfile.objects.update_or_create(
        user=user, clinic=clinic
    )

    branch = Branch.objects.create(
        clinic=clinic,
        name="Главный филиал",
        address=params.get("address", "Ташкент"),
        phone=user.phone,
        email=user.email,
        is_active=True
    )

    if user.role == CustomUser.Roles.PENDING_DIRECTOR:
        user.role = CustomUser.Roles.CLINIC_DIRECTOR
        user.clinic = clinic
        user.branch = branch
        user.save()

    access, refresh = generate_tokens(user.id)

    return {
        "response": {
            "success": True,
            "message": "Клиника создана!",
            "clinic_id": str(clinic.id),
            "branch_id": str(branch.id),
            "clinics_total": current_clinics + 1,
            "clinics_limit": plan.limit_clinics,
            "access_token": access,
            "refresh_token": refresh
        },
        "status": 200
    }


def clinic_list(request, params):
    user = get_user_from_token(request)
    if not user:
        return {"response": {"error": "Авторизуйтесь"}, "status": 401}

    if user.role == CustomUser.Roles.SYSTEM_ADMIN:
        clinics = Clinic.objects.all()
    else:
        clinics = Clinic.objects.filter(director_profile_link__user=user)

    data = []
    for c in clinics:
        # Безопасное получение подписки
        try:
            sub = c.subscription
            plan = sub.plan
        except (Subscription.DoesNotExist, AttributeError, Clinic.subscription.RelatedObjectDoesNotExist):
            sub = None
            plan = None
            
        limit_users = plan.limit_users if plan else '∞'
        limit_branches = plan.limit_branches if plan else '∞'
        limit_patients = plan.limit_patients if plan else '∞'
        limit_clinics = plan.limit_clinics if plan else 1

        data.append({
            "id": str(c.id),
            "name": c.name,
            "status": c.status,
            "plan": plan.name if plan else "Нет",
            "clinics_used": Clinic.objects.filter(director_profile_link__user=user).count(),
            "clinics_limit": limit_clinics,
            "users": f"{c.users.filter(is_active=True).count()}/{limit_users}",
            "branches": f"{c.branches.filter(is_active=True).count()}/{limit_branches}",
            "patients": f"{c.patients.count()}/{limit_patients}",
        })

    return {"response": data, "status": 200}


def clinic_detail(request, params):
    clinic_id = params.get("clinic_id")
    if not clinic_id:
        return {"response": {"error": "clinic_id обязателен"}, "status": 400}

    user = get_user_from_token(request)
    if not user:
        return {"response": {"error": "Авторизуйтесь"}, "status": 401}

    try:
        clinic = Clinic.objects.get(id=clinic_id)
    except Clinic.DoesNotExist:
        return {"response": {"error": "Клиника не найдена"}, "status": 404}

    # СТРОГАЯ проверка: если не админ, обязан быть директором ЭТОЙ клиники
    if user.role != CustomUser.Roles.SYSTEM_ADMIN:
        is_owner = ClinicDirectorProfile.objects.filter(user_id=user.id, clinic_id=clinic.id).exists()
        if not is_owner:
            return {"response": {"error": "Доступ запрещён. Вы не являетесь директором этой клиники."}, "status": 403}

    sub = getattr(clinic, 'subscription', None)
    plan = sub.plan if sub else None
    
    # Получаем директора через связь профиля
    profile = getattr(clinic, 'director_profile_link', None)
    director = profile.user if profile else None

    return {
        "response": {
            "id": str(clinic.id),
            "name": clinic.name,
            "legal_name": clinic.legal_name,
            "inn": clinic.inn,
            "status": clinic.status,
            "director": {
                "id": str(director.id),
                "full_name": director.full_name,
                "email": director.email
            },
            "plan": plan.name if plan else None,
            "clinics_used": Clinic.objects.filter(director_profile_link__user=user).count(),
            "clinics_limit": plan.limit_clinics if plan else 1,
            "limits": {
                "users": f"{clinic.users.filter(is_active=True).count()}/{plan.limit_users if plan else '∞'}",
                "branches": f"{clinic.branches.filter(is_active=True).count()}/{plan.limit_branches if plan else '∞'}",
                "patients": f"{clinic.patients.count()}/{plan.limit_patients if plan else '∞'}"
            }
        },
        "status": 200
    }


def clinic_update(request, params):
    clinic_id = params.get("clinic_id")
    if not clinic_id:
        return {"response": {"error": "clinic_id обязателен"}, "status": 400}

    user = get_user_from_token(request)
    if not user:
        return {"response": {"error": "Авторизуйтесь"}, "status": 401}

    try:
        clinic = Clinic.objects.get(id=clinic_id)
    except Clinic.DoesNotExist:
        return {"response": {"error": "Клиника не найдена"}, "status": 404}

    # СТРОГАЯ проверка
    if user.role != CustomUser.Roles.SYSTEM_ADMIN:
        is_owner = ClinicDirectorProfile.objects.filter(user_id=user.id, clinic_id=clinic.id).exists()
        if not is_owner:
            return {"response": {"error": "Нет прав на редактирование этой клиники"}, "status": 403}

    clinic.name = params.get("name", clinic.name)
    clinic.legal_name = params.get("legal_name", clinic.legal_name)
    clinic.inn = params.get("inn", clinic.inn)
    clinic.status = params.get("status", clinic.status)
    clinic.save()

    return {"response": {"success": True, "message": "Клиника обновлена"}, "status": 200}


def clinic_delete(request, params):
    user = get_user_from_token(request)
    if not user or user.role != CustomUser.Roles.SYSTEM_ADMIN:
        return {"response": {"error": "Только системный админ"}, "status": 403}

    clinic_id = params.get("clinic_id")
    if not clinic_id:
        return {"response": {"error": "clinic_id обязателен"}, "status": 400}

    try:
        clinic = Clinic.objects.get(id=clinic_id)
        clinic_name = clinic.name
        clinic.delete()
        return {"response": {"success": True, "message": f"Клиника '{clinic_name}' удалена"}, "status": 200}
    except Clinic.DoesNotExist:
        return {"response": {"error": "Клиника не найдена"}, "status": 404}
