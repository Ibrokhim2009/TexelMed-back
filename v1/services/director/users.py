from django.db import transaction
from django.db.models import Q, Count
from django.utils import timezone
from datetime import timedelta
from core.models import CustomUser, Clinic, Branch, ClinicAdminProfile, DoctorProfile, ReceptionistProfile, ClinicDirectorProfile, Patient
from .utils import get_user_from_token
import random
import string

def user_list(request, params):
    user = get_user_from_token(request)
    if not user: return {"response": {"error": "401"}, "status": 401}

    # Получаем все клиники директора
    if user.role == CustomUser.Roles.SYSTEM_ADMIN:
        clinics = Clinic.objects.all()
    else:
        clinics = Clinic.objects.filter(director_profile_link__user=user)
        if not clinics.exists():
             return {"response": {"error": "Доступ разрешен только директорам клиник"}, "status": 403}

    # Базовый QuerySet для сотрудников
    staff_qs = CustomUser.objects.filter(clinic__in=clinics).exclude(id=user.id).select_related('branch', 'clinic')
    
    # Базовый QuerySet для пациентов
    patients_qs = Patient.objects.filter(clinic__in=clinics).select_related('primary_branch', 'clinic')

    # Фильтры для статистики (до поиска)
    total_staff = staff_qs.count()
    active_staff = staff_qs.filter(is_active=True).count()
    blocked_staff = staff_qs.filter(is_active=False).count()
    
    total_patients = patients_qs.count()
    active_patients = patients_qs.filter(status='active').count()
    blocked_patients = patients_qs.filter(status='inactive').count()

    # Фильтры
    search = params.get("search", "").strip()
    if search:
        staff_qs = staff_qs.filter(
            Q(full_name__icontains=search) |
            Q(email__icontains=search) |
            Q(phone__icontains=search)
        )
        patients_qs = patients_qs.filter(
            Q(full_name__icontains=search) |
            Q(email__icontains=search) |
            Q(phone__icontains=search)
        )

    role_filter = params.get("role")
    if role_filter:
        if role_filter == "patient":
            staff_qs = staff_qs.none()
        else:
            staff_qs = staff_qs.filter(role=role_filter)
            patients_qs = patients_qs.none()

    status_filter = params.get("status") # active / blocked
    if status_filter == "active":
        staff_qs = staff_qs.filter(is_active=True)
        patients_qs = patients_qs.filter(status='active')
    elif status_filter == "blocked":
        staff_qs = staff_qs.filter(is_active=False)
        patients_qs = patients_qs.filter(status__in=['inactive', 'archived'])

    branch_id = params.get("branch_id")
    if branch_id:
        staff_qs = staff_qs.filter(branch_id=branch_id)
        patients_qs = patients_qs.filter(primary_branch_id=branch_id)

    # Online (только для персонала)
    one_hour_ago = timezone.now() - timedelta(hours=1)
    online_users = staff_qs.filter(last_login__gte=one_hour_ago).count()

    data = []
    
    # Собираем сотрудников
    for u in staff_qs.order_by('-date_joined'):
        data.append({
            "id": str(u.id),
            "type": "staff",
            "full_name": u.full_name,
            "email": u.email,
            "phone": str(u.phone) if u.phone else "",
            "role": u.role,
            "role_display": u.get_role_display(),
            "branch": u.branch.name if u.branch else "Без филиала",
            "branch_id": str(u.branch.id) if u.branch else None,
            "clinic_name": u.clinic.name if u.clinic else "",
            "status": "Активен" if u.is_active else "Заблокирован",
            "is_active": u.is_active,
            "date_registered": u.date_joined.strftime("%Y-%m-%d"),
            "last_login": u.last_login.strftime("%Y-%m-%d %H:%M") if u.last_login else "Никогда"
        })
        
    # Собираем пациентов
    for p in patients_qs.order_by('-created_at'):
        data.append({
            "id": str(p.id),
            "type": "patient",
            "full_name": p.full_name,
            "email": p.email,
            "phone": str(p.phone) if p.phone else "",
            "role": "patient",
            "role_display": "Пациент",
            "branch": p.primary_branch.name if p.primary_branch else "Без филиала",
            "branch_id": str(p.primary_branch.id) if p.primary_branch else None,
            "clinic_name": p.clinic.name if p.clinic else "",
            "status": p.get_status_display(),
            "is_active": p.status == 'active',
            "date_registered": p.created_at.strftime("%Y-%m-%d"),
            "last_login": p.last_visit.strftime("%Y-%m-%d %H:%M") if p.last_visit else "Нет визитов"
        })

    return {
        "response": {
            "users": data,
            "stats": {
                "total": total_staff + total_patients,
                "staff": total_staff,
                "patients": total_patients,
                "active": active_staff + active_patients,
                "blocked": blocked_staff + blocked_patients,
                "online": online_users
            }
        },
        "status": 200
    }


def user_create(request, params):
    user = get_user_from_token(request)
    if not user: return {"response": {"error": "401"}, "status": 401}

    # Получаем клиники директора
    director_clinics = Clinic.objects.filter(director_profile_link__user=user)
    if not director_clinics.exists():
        return {"response": {"error": "У вас нет разрешенных клиник"}, "status": 403}

    clinic_id = params.get("clinic_id")
    if clinic_id:
        clinic = director_clinics.filter(id=clinic_id).first()
    else:
        clinic = director_clinics.first()
    
    if not clinic:
        return {"response": {"error": "Выбранная клиника не найдена или недоступна"}, "status": 404}
    
    # Лимиты
    limits = clinic.check_limits()
    if not limits["ok"] and "Пользователи" in limits["error"]:
         return {"response": {"error": limits["error"]}, "status": 400}
    
    # Sub check limit
    sub = getattr(clinic, 'subscription', None)
    if sub and sub.plan:
        limit = sub.plan.limit_users
        current = clinic.users.filter(is_active=True).count()
        if current >= limit:
             return {"response": {"error": f"Лимит пользователей исчерпан ({current}/{limit})"}, "status": 400}

    # Данные формы
    full_name = params.get("full_name")
    email = params.get("email")
    phone = params.get("phone")
    role = params.get("role")
    branch_id = params.get("branch_id")
    password = params.get("password")
    status = params.get("status", "Активен") # UI sends "Активен" text possibly, or key "active"
    is_active = status in ["active", "Активен", True]

    # Валидация
    if not all([full_name, email, phone, role, password]):
        return {"response": {"error": "Заполните все обязательные поля"}, "status": 400}

    # Проверка уникальности email
    if CustomUser.objects.filter(email=email).exists():
        return {"response": {"error": "Email уже занят"}, "status": 400}
        
    # Проверка филиала
    branch = None
    if branch_id:
        try:
            branch = Branch.objects.get(id=branch_id, clinic=clinic)
        except Branch.DoesNotExist:
            return {"response": {"error": "Филиал не найден"}, "status": 400}
    
    # Создание
    try:
        with transaction.atomic():
            new_user = CustomUser.objects.create(
                clinic=clinic,
                branch=branch,
                full_name=full_name,
                email=email,
                phone=phone,
                role=role,
                is_active=is_active
            )
            new_user.set_password(password)
            new_user.save()
            
            # Создание профиля
            if role == CustomUser.Roles.CLINIC_ADMIN:
                ClinicAdminProfile.objects.create(user=new_user, branch=branch)
            elif role == CustomUser.Roles.DOCTOR:
                DoctorProfile.objects.create(user=new_user, branch=branch, specialization="Общий", color="#1E88E5")
            elif role == CustomUser.Roles.RECEPTIONIST:
                ReceptionistProfile.objects.create(user=new_user, branch=branch)
            
            return {"response": {"success": True, "message": "Пользователь создан"}, "status": 201}
            
    except Exception as e:
        return {"response": {"error": str(e)}, "status": 400}


def user_detail(request, params):
    user = get_user_from_token(request)
    if not user: return {"response": {"error": "401"}, "status": 401}
    
    target_id = params.get("user_id")
    try:
        target_user = CustomUser.objects.get(id=target_id)
        # Проверка что юзер из моей клиники
        director_profile = ClinicDirectorProfile.objects.filter(user=user, clinic=target_user.clinic).exists()
        if not director_profile and user.role != CustomUser.Roles.SYSTEM_ADMIN:
             return {"response": {"error": "Доступ запрещен"}, "status": 403}
             
        data = {
            "id": str(target_user.id),
            "full_name": target_user.full_name,
            "email": target_user.email,
            "phone": str(target_user.phone) if target_user.phone else "",
            "role": target_user.role,
            "branch_id": str(target_user.branch.id) if target_user.branch else None,
            "branch_name": target_user.branch.name if target_user.branch else None,
            "is_active": target_user.is_active,
            "status": "Активен" if target_user.is_active else "Заблокирован"
        }
        return {"response": data, "status": 200}
    except CustomUser.DoesNotExist:
        return {"response": {"error": "Пользователь не найден"}, "status": 404}


def user_update(request, params):
    user = get_user_from_token(request)
    if not user: return {"response": {"error": "401"}, "status": 401}
    
    target_id = params.get("user_id")
    try:
        target_user = CustomUser.objects.get(id=target_id)
        director_profile = ClinicDirectorProfile.objects.filter(user=user, clinic=target_user.clinic).exists()
        if not director_profile and user.role != CustomUser.Roles.SYSTEM_ADMIN:
             return {"response": {"error": "Доступ запрещен"}, "status": 403}

        # Обновление полей
        if "full_name" in params: target_user.full_name = params["full_name"]
        if "email" in params: target_user.email = params["email"]
        if "phone" in params: target_user.phone = params["phone"]
        if "role" in params: target_user.role = params["role"]
        if "branch_id" in params: 
            bid = params["branch_id"]
            if bid:
                 target_user.branch = Branch.objects.get(id=bid, clinic=target_user.clinic)
            else:
                 target_user.branch = None
        
        # Status change
        if "status" in params or "is_active" in params:
             val = params.get("is_active", params.get("status"))
             new_status = val in [True, "active", "Активен", 1, "True"]
             
             if new_status and not target_user.is_active:
                  # Activation - check limits
                  clinic = target_user.clinic
                  sub = getattr(clinic, 'subscription', None)
                  limit = sub.plan.limit_users if (sub and sub.plan) else 999
                  current = clinic.users.filter(is_active=True).count()
                  if current >= limit:
                      return {"response": {"error": f"Лимит пользователей ({limit})"}, "status": 400}
             
             target_user.is_active = new_status

        target_user.save()
        return {"response": {"success": True, "message": "Обновлено"}, "status": 200}

    except CustomUser.DoesNotExist:
        return {"response": {"error": "Not found"}, "status": 404}
    except Exception as e:
        return {"response": {"error": str(e)}, "status": 400}


def user_delete(request, params):
    # Soft delete
    user = get_user_from_token(request)
    if not user: return {"response": {"error": "401"}, "status": 401}
    
    target_id = params.get("user_id")
    try:
        target_user = CustomUser.objects.get(id=target_id)
        if target_user.id == user.id:
             return {"response": {"error": "Нельзя удалить себя"}, "status": 400}
             
        director_profile = ClinicDirectorProfile.objects.filter(user=user, clinic=target_user.clinic).exists()
        if not director_profile and user.role != CustomUser.Roles.SYSTEM_ADMIN:
             return {"response": {"error": "Доступ запрещен"}, "status": 403}
        
        target_user.is_active = False
        target_user.save()
        
        return {"response": {"success": True, "message": "Пользователь деактивирован"}, "status": 200}
        
    except CustomUser.DoesNotExist:
        return {"response": {"error": "Not found"}, "status": 404}
