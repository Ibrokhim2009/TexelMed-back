from django.db import transaction
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Q, Count
from core.models import Branch, Clinic, CustomUser, ClinicAdminProfile
from .utils import get_user_from_token

def list_all_branches_for_admin(request, params):
    user = get_user_from_token(request)
    if not user or user.role != CustomUser.Roles.SYSTEM_ADMIN:
        return {"response": {"error": "Доступ только системному администратору"}, "status": 403}

    search = params.get("search", "").strip()
    clinic_id = params.get("clinic_id")
    status_filter = params.get("status")
    city = params.get("city")
    
    branches_qs = Branch.objects.select_related('clinic').order_by('clinic__name', 'name')

    if search:
        branches_qs = branches_qs.filter(
            Q(name__icontains=search) |
            Q(address__icontains=search) |
            Q(phone__icontains=search) |
            Q(email__icontains=search) |
            Q(clinic__name__icontains=search)
        )

    if clinic_id:
        branches_qs = branches_qs.filter(clinic_id=clinic_id)

    if status_filter == "active":
        branches_qs = branches_qs.filter(is_active=True)
    elif status_filter == "inactive":
        branches_qs = branches_qs.filter(is_active=False)

    if city:
        branches_qs = branches_qs.filter(address__icontains=city)

    branch_ids = list(branches_qs.values_list('id', flat=True))

    staff_counts = CustomUser.objects.filter(branch_id__in=branch_ids, is_active=True)\
        .values('branch_id')\
        .annotate(count=Count('id'))\
        .values_list('branch_id', 'count')

    staff_map = {str(bid): count for bid, count in staff_counts}

    clinic_patient_counts = Clinic.objects.filter(branches__id__in=branch_ids)\
        .annotate(patients_count=Count('patients'))\
        .values_list('id', 'patients_count')

    patients_map = {str(clinic_id): count for clinic_id, count in clinic_patient_counts}

    data = []
    for branch in branches_qs:
        clinic = branch.clinic

        admin_profile = ClinicAdminProfile.objects.filter(branch=branch).select_related('user').first()
        admin_name = admin_profile.user.full_name if admin_profile else "Не назначен"

        city_name = branch.address.split(',')[-1].strip() if ',' in branch.address else "Не указан"

        status_display = "Активен" if branch.is_active else "Неактивен"
        status_color = "green" if branch.is_active else "red"

        data.append({
            "branch_id": str(branch.id),
            "clinic": {
                "id": str(clinic.id),
                "name": clinic.name
            },
            "name": branch.name,
            "address": branch.address,
            "city": city_name,
            "phone": str(branch.phone),
            "email": branch.email or None,
            "working_hours": branch.working_hours or "Не указан",
            "status": "active" if branch.is_active else "inactive",
            "status_display": status_display,
            "status_color": status_color,
            "admin": admin_name,
            "staff_count": staff_map.get(str(branch.id), 0),
            "patients_count": patients_map.get(str(clinic.id), 0),
        })

    return {
        "response": {
            "branches": data,
            "total": len(data),
            "filters": {
                "search": search or None,
                "clinic_id": clinic_id,
                "status": status_filter,
                "city": city
            }
        },
        "status": 200
    }


def create_branch_for_admin(request, params):
    user = get_user_from_token(request)
    if not user or user.role != CustomUser.Roles.SYSTEM_ADMIN:
        return {"response": {"error": "Доступ только системному администратору"}, "status": 403}

    required = ["clinic_id", "name", "address", "phone", "email", "working_hours", "admin_user_id"]
    for field in required:
        if not params.get(field):
            return {"response": {"error": f"Обязательное поле: {field}"}, "status": 400}

    clinic_id = params["clinic_id"]
    name = params["name"].strip()
    address = params["address"].strip()
    phone = params["phone"]
    email = params["email"].strip()
    working_hours = params["working_hours"].strip()
    admin_user_id = params["admin_user_id"]
    is_active = params.get("is_active", True) in (True, "true", "True", 1)

    try:
        clinic = Clinic.objects.get(id=clinic_id)
    except ObjectDoesNotExist:
        return {"response": {"error": "Клиника не найдена"}, "status": 404}

    try:
        admin_user = CustomUser.objects.get(
            id=admin_user_id,
            clinic=clinic,
            role=CustomUser.Roles.CLINIC_ADMIN,
            is_active=True
        )
    except ObjectDoesNotExist:
        return {"response": {"error": "Администратор филиала не найден или неактивен"}, "status": 404}

    sub = getattr(clinic, 'subscription', None)
    if sub and sub.plan:
        current_branches = clinic.branches.filter(is_active=True).count()
        if current_branches + 1 > sub.plan.limit_branches:
            return {"response": {"error": f"Лимит филиалов превышен: {current_branches}/{sub.plan.limit_branches}"}, "status": 400}

    with transaction.atomic():
        branch = Branch.objects.create(
            clinic=clinic,
            name=name,
            address=address,
            phone=phone,
            email=email,
            working_hours=working_hours,
            is_active=is_active
        )

        ClinicAdminProfile.objects.update_or_create(
            user=admin_user,
            defaults={"branch": branch}
        )

    return {
        "response": {
            "success": True,
            "message": "Филиал успешно создан",
            "branch_id": str(branch.id)
        },
        "status": 201
    }


def update_branch_for_admin(request, params):
    user = get_user_from_token(request)
    if not user or user.role != CustomUser.Roles.SYSTEM_ADMIN:
        return {"response": {"error": "Доступ только системному администратору"}, "status": 403}

    branch_id = params.get("branch_id")
    if not branch_id:
        return {"response": {"error": "branch_id обязателен"}, "status": 400}

    try:
        branch = Branch.objects.select_related('clinic').get(id=branch_id)
    except ObjectDoesNotExist:
        return {"response": {"error": "Филиал не найден"}, "status": 404}

    updated = False
    with transaction.atomic():
        if "name" in params:
            branch.name = params["name"]
            updated = True
        if "address" in params:
            branch.address = params["address"]
            updated = True
        if "phone" in params:
            branch.phone = params["phone"]
            updated = True
        if "email" in params:
            branch.email = params["email"]
            updated = True
        if "working_hours" in params:
            branch.working_hours = params["working_hours"]
            updated = True
        if "is_active" in params:
            branch.is_active = params["is_active"] in (True, "true", "True")
            updated = True

        if "admin_user_id" in params:
            try:
                new_admin = CustomUser.objects.get(
                    id=params["admin_user_id"],
                    clinic=branch.clinic,
                    role=CustomUser.Roles.CLINIC_ADMIN
                )
                ClinicAdminProfile.objects.update_or_create(
                    user=new_admin,
                    defaults={"branch": branch}
                )
                updated = True
            except ObjectDoesNotExist:
                return {"response": {"error": "Новый администратор не найден"}, "status": 404}

        if updated:
            branch.save()

    return {
        "response": {"success": True, "message": "Филиал обновлён" if updated else "Нет изменений"},
        "status": 200
    }


def toggle_branch_status(request, params):
    user = get_user_from_token(request)
    if not user or user.role != CustomUser.Roles.SYSTEM_ADMIN:
        return {"response": {"error": "Доступ только системному администратору"}, "status": 403}

    branch_id = params.get("branch_id")
    if not branch_id:
        return {"response": {"error": "branch_id обязателен"}, "status": 400}

    try:
        branch = Branch.objects.get(id=branch_id)
        branch.is_active = not branch.is_active
        branch.save()
        return {
            "response": {
                "success": True,
                "message": f"Филиал {'активирован' if branch.is_active else 'деактивирован'}"
            },
            "status": 200
        }
    except ObjectDoesNotExist:
        return {"response": {"error": "Филиал не найден"}, "status": 404}


def assign_admin_to_branch(request, params):
    user = get_user_from_token(request)
    if not user or user.role != CustomUser.Roles.SYSTEM_ADMIN:
        return {"response": {"error": "Доступ только системному администратору"}, "status": 403}

    admin_user_id = params.get("admin_user_id")
    branch_id = params.get("branch_id")
    if not admin_user_id or not branch_id:
        return {"response": {"error": "admin_user_id и branch_id обязательны"}, "status": 400}

    try:
        admin_user = CustomUser.objects.get(id=admin_user_id, role=CustomUser.Roles.CLINIC_ADMIN)
        branch = Branch.objects.get(id=branch_id)
    except ObjectDoesNotExist:
        return {"response": {"error": "Пользователь или филиал не найден"}, "status": 404}

    if admin_user.clinic != branch.clinic:
        return {"response": {"error": "Администратор и филиал должны быть из одной клиники"}, "status": 400}

    profile, created = ClinicAdminProfile.objects.update_or_create(
        user=admin_user,
        defaults={"branch": branch}
    )

    action = "назначен на" if created or profile.branch != branch else "уже был назначен на"
    return {
        "response": {
            "success": True,
            "message": f"Администратор {admin_user.full_name} {action} филиал {branch.name}"
        },
        "status": 200
    }


def unassign_admin_from_branch(request, params):
    user = get_user_from_token(request)
    if not user or user.role != CustomUser.Roles.SYSTEM_ADMIN:
        return {"response": {"error": "Доступ только системному администратору"}, "status": 403}

    admin_user_id = params.get("admin_user_id")
    if not admin_user_id:
        return {"response": {"error": "admin_user_id обязателен"}, "status": 400}

    try:
        profile = ClinicAdminProfile.objects.get(user_id=admin_user_id)
        old_branch = profile.branch.name if profile.branch else None
        profile.branch = None
        profile.save()
        return {
            "response": {
                "success": True,
                "message": f"Администратор снят с филиала '{old_branch}'" if old_branch else "Администратор не был привязан к филиалу"
            },
            "status": 200
        }
    except ClinicAdminProfile.DoesNotExist:
        return {"response": {"error": "Профиль администратора не найден"}, "status": 404}
