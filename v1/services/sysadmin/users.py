import random
import string
from django.db import transaction
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Q
from core.models import CustomUser, Clinic, Branch, ClinicDirectorProfile, ClinicAdminProfile, DoctorProfile, ReceptionistProfile
from v1.services.auth import generate_tokens
from .utils import get_user_from_token

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


def list_all_users_for_admin(request, params):
    user = get_user_from_token(request)
    if not user:
        return {"response": {"error": "Токен обязателен"}, "status": 401}

    if user.role != CustomUser.Roles.SYSTEM_ADMIN:
        return {"response": {"error": "Доступ только системному администратору"}, "status": 403}

    search = params.get("search", "").strip().lower()
    clinic_id = params.get("clinic_id")
    role = params.get("role")
    status = params.get("status")
    registration_month = params.get("registration_month")

    users_qs = CustomUser.objects.select_related('clinic', 'branch').all()

    if status == "active":
        users_qs = users_qs.filter(is_active=True)
    elif status == "blocked":
        users_qs = users_qs.filter(is_active=False)

    if role and role in dict(CustomUser.Roles.choices):
        users_qs = users_qs.filter(role=role)

    if clinic_id:
        try:
            users_qs = users_qs.filter(clinic_id=clinic_id)
        except:
            pass

    if registration_month:
        try:
            year, month = map(int, registration_month.split('-'))
            if 1 <= month <= 12:
                users_qs = users_qs.filter(date_joined__year=year, date_joined__month=month)
        except:
            pass

    if search:
        users_qs = users_qs.filter(
            Q(full_name__icontains=search) |
            Q(email__icontains=search) |
            Q(phone__icontains=search)
        )

    users_qs = users_qs.order_by('-date_joined')

    data = []
    for u in users_qs:
        clinic_name = u.clinic.name if u.clinic else "Без клиники"
        clinic_id_out = str(u.clinic.id) if u.clinic else None
        branch_name = u.branch.name if u.branch else "Без филиала"
        branch_id_out = str(u.branch.id) if u.branch else None
        status_display = "Активен" if u.is_active else "Заблокирован"
        status_color = "green" if u.is_active else "red"
        role_display = u.get_role_display()
        phone_display = u.phone.as_e164 if u.phone else None
        reg_date = u.date_joined.strftime("%Y-%m-%d")

        data.append({
            "user_id": str(u.id),
            "full_name": u.full_name,
            "email": u.email,
            "phone": phone_display,
            "photo": u.photo.url if u.photo else None,
            "role": u.role,
            "role_display": role_display,
            "clinic": {"id": clinic_id_out, "name": clinic_name},
            "branch": {"id": branch_id_out, "name": branch_name},
            "status": "active" if u.is_active else "blocked",
            "status_display": status_display,
            "status_color": status_color,
            "registration_date": reg_date,
            "last_login": None,
            "is_staff": u.is_staff,
            "is_superuser": u.is_superuser,
        })

    return {
        "response": {
            "users": data,
            "total": len(data),
            "filters": {
                "search": params.get("search"),
                "clinic_id": clinic_id,
                "role": role,
                "status": status,
                "registration_month": registration_month
            }
        },
        "status": 200
    }


def block_user(request, params):
    user = get_user_from_token(request)
    if not user or user.role != CustomUser.Roles.SYSTEM_ADMIN:
        return {"response": {"error": "Доступ только системному администратору"}, "status": 403}

    user_id = params.get("user_id")
    if not user_id:
        return {"response": {"error": "user_id обязателен"}, "status": 400}

    try:
        target_user = CustomUser.objects.get(id=user_id)
        if not target_user.is_active:
            return {"response": {"error": "Пользователь уже заблокирован"}, "status": 400}

        target_user.is_active = False
        target_user.save()

        return {
            "response": {
                "success": True,
                "message": f"Пользователь {target_user.full_name} заблокирован",
                "user_id": str(target_user.id),
                "status": "blocked"
            },
            "status": 200
        }
    except ObjectDoesNotExist:
        return {"response": {"error": "Пользователь не найден"}, "status": 404}


def unblock_user(request, params):
    user = get_user_from_token(request)
    if not user or user.role != CustomUser.Roles.SYSTEM_ADMIN:
        return {"response": {"error": "Доступ только системному администратору"}, "status": 403}

    user_id = params.get("user_id")
    if not user_id:
        return {"response": {"error": "user_id обязателен"}, "status": 400}

    try:
        target_user = CustomUser.objects.get(id=user_id)
        if target_user.is_active:
            return {"response": {"error": "Пользователь уже активен"}, "status": 400}

        target_user.is_active = True
        target_user.save()

        return {
            "response": {
                "success": True,
                "message": f"Пользователь {target_user.full_name} разблокирован",
                "user_id": str(target_user.id),
                "status": "active"
            },
            "status": 200
        }
    except ObjectDoesNotExist:
        return {"response": {"error": "Пользователь не найден"}, "status": 404}


def delete_user(request, params):
    user = get_user_from_token(request)
    if not user or user.role != CustomUser.Roles.SYSTEM_ADMIN:
        return {"response": {"error": "Доступ только системному администратору"}, "status": 403}

    user_id = params.get("user_id")
    if not user_id:
        return {"response": {"error": "user_id обязателен"}, "status": 400}

    try:
        target_user = CustomUser.objects.get(id=user_id)

        if target_user.id == user.id:
            return {"response": {"error": "Нельзя удалить самого себя"}, "status": 400}

        if target_user.is_superuser:
            return {"response": {"error": "Нельзя удалить суперадмина"}, "status": 400}

        with transaction.atomic():
            target_user.is_active = False
            target_user.email = f"deleted_{target_user.id}@deleted.texelmed"
            target_user.phone = None
            target_user.full_name = "Удалённый пользователь"
            target_user.photo = None
            target_user.save()

        return {
            "response": {
                "success": True,
                "message": "Пользователь успешно удалён (мягкое удаление)"
            },
            "status": 200
        }
    except ObjectDoesNotExist:
        return {"response": {"error": "Пользователь не найден"}, "status": 404}


def create_user_for_admin(request, params):
    user = get_user_from_token(request)
    if not user or user.role != CustomUser.Roles.SYSTEM_ADMIN:
        return {"response": {"error": "Доступ только системному администратору"}, "status": 403}

    required_fields = ["full_name", "email", "phone", "role", "clinic_id"]
    for field in required_fields:
        if not params.get(field):
            return {"response": {"error": f"Обязательное поле: {field}"}, "status": 400}

    full_name = params["full_name"].strip()
    email = params["email"].strip().lower()
    phone = params["phone"]
    role = params["role"]
    clinic_id = params["clinic_id"]
    branch_id = params.get("branch_id")
    password = params.get("password") or "".join(random.choices(string.ascii_letters + string.digits, k=12))

    if role not in dict(CustomUser.Roles.choices):
        return {"response": {"error": "Неверная роль"}, "status": 400}

    if CustomUser.objects.filter(email=email).exists():
        return {"response": {"error": "Email уже используется"}, "status": 400}

    try:
        clinic = Clinic.objects.get(id=clinic_id)
    except ObjectDoesNotExist:
        return {"response": {"error": "Клиника не найдена"}, "status": 404}

    branch = None
    if branch_id:
        try:
            branch = Branch.objects.get(id=branch_id, clinic=clinic)
        except ObjectDoesNotExist:
            return {"response": {"error": "Филиал не найден или не принадлежит клинике"}, "status": 404}

    with transaction.atomic():
        new_user = CustomUser.objects.create(
            full_name=full_name,
            email=email,
            phone=phone,
            role=role,
            clinic=clinic,
            branch=branch,
            is_active=True
        )
        new_user.set_password(password)
        new_user.save()

        if role == CustomUser.Roles.CLINIC_DIRECTOR:
            ClinicDirectorProfile.objects.create(user=new_user, clinic=clinic)

        elif role == CustomUser.Roles.CLINIC_ADMIN:
            ClinicAdminProfile.objects.create(user=new_user)

        elif role == CustomUser.Roles.DOCTOR:
            DoctorProfile.objects.create(
                user=new_user,
                branch=branch,
                specialization="",
                color="#3B82F6"
            )

        elif role == CustomUser.Roles.RECEPTIONIST:
            if not branch:
                return {"response": {"error": "Для регистратора обязателен branch_id"}, "status": 400}
            ReceptionistProfile.objects.create(user=new_user, branch=branch)


    access, refresh = generate_tokens(new_user.id)

    return {
        "response": {
            "success": True,
            "message": "Пользователь успешно создан",
            "user": {
                "id": str(new_user.id),
                "full_name": new_user.full_name,
                "email": new_user.email,
                "phone": new_user.phone.as_e164 if new_user.phone else None,
                "role": new_user.role,
                "role_display": new_user.get_role_display(),
                "clinic": {"id": str(clinic.id), "name": clinic.name},
                "branch": {"id": str(branch.id), "name": branch.name} if branch else None,
                "password": password,
                "access_token": access,
                "refresh_token": refresh
            }
        },
        "status": 201
    }
