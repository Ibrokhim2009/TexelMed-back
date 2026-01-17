from django.utils import timezone
from django.db.models import Q
from core.models import CustomUser, Clinic, Branch, ClinicDirectorProfile, Patient, Appointment
from .utils import get_user_from_token

def branch_list(request, params):
    user = get_user_from_token(request)
    if not user: return {"response": {"error": "401"}, "status": 401}

    # Клиники
    if user.role == CustomUser.Roles.SYSTEM_ADMIN:
        clinics = Clinic.objects.all()
    else:
        clinics = Clinic.objects.filter(director_profile_link__user=user)
        if not clinics.exists():
             return {"response": {"branches": [], "count": 0}, "status": 200}
    
    # Ветки
    branches = Branch.objects.filter(clinic__in=clinics)

    # Фильтры
    search = params.get("search")
    if search:
        branches = branches.filter(
            Q(name__icontains=search) |
            Q(address__icontains=search) |
            Q(phone__icontains=search) |
            Q(email__icontains=search)
        )
    
    status_filter = params.get("status")
    if status_filter == "active":
        branches = branches.filter(is_active=True)
    elif status_filter == "inactive":
        branches = branches.filter(is_active=False)

    # Данные
    data = []
    now = timezone.now()
    current_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    
    for b in branches:
        # Статистика
        employees_count = CustomUser.objects.filter(branch=b, is_active=True).count()
        patients_count = Patient.objects.filter(primary_branch=b).count()
        # Приемов в месяц
        appointments_month = Appointment.objects.filter(branch=b, start_time__gte=current_month_start).count()

        data.append({
            "id": str(b.id),
            "name": b.name,
            "address": b.address,
            "phone": str(b.phone),
            "email": b.email,
            "working_hours": b.working_hours,
            "employees_count": employees_count,
            "patients_count": patients_count,
            "appointments_month": appointments_month,
            "status": "Активен" if b.is_active else "Неактивен",
            "is_active": b.is_active,
            "clinic_name": b.clinic.name
        })

    return {"response": {"branches": data, "count": len(data)}, "status": 200}


def branch_create(request, params):
    user = get_user_from_token(request)
    if not user: return {"response": {"error": "401"}, "status": 401}

    # Данные
    clinic_id = params.get("clinic_id")
    name = params.get("name")
    address = params.get("address")
    phone = params.get("phone")
    email = params.get("email")
    working_hours = params.get("working_hours", "Пн-Пт 09:00 - 18:00")
    
    if not name or not address or not phone:
        return {"response": {"error": "Заполните обязательные поля (Название, Адрес, Телефон)"}, "status": 400}

    # Клиника
    try:
        if user.role == CustomUser.Roles.SYSTEM_ADMIN:
             if not clinic_id: return {"response": {"error": "clinic_id required"}, "status": 400}
             clinic = Clinic.objects.get(id=clinic_id)
        else:
             # Директор
             if clinic_id:
                 clinic = Clinic.objects.get(id=clinic_id, director_profile_link__user=user)
             else:
                 clinic = Clinic.objects.filter(director_profile_link__user=user).first()
                 if not clinic: return {"response": {"error": "Нет клиники"}, "status": 404}
    except Clinic.DoesNotExist:
        return {"response": {"error": "Клиника не найдена или нет доступа"}, "status": 404}

    # Лимиты
    limits = clinic.check_limits()
    if not limits["ok"] and "Филиалы" in limits["error"]:
         return {"response": {"error": limits["error"]}, "status": 400}
         
    # Доп проверка лимита филиалов
    sub = getattr(clinic, 'subscription', None)
    if sub and sub.plan:
        limit = sub.plan.limit_branches
        current = clinic.branches.filter(is_active=True).count()
        if current >= limit:
             return {"response": {"error": f"Лимит филиалов исчерпан ({current}/{limit})"}, "status": 400}

    # Создание
    try:
        branch = Branch.objects.create(
            clinic=clinic,
            name=name,
            address=address,
            phone=phone,
            email=email if email else "",
            working_hours=working_hours,
            is_active=True
        )
        return {"response": {"success": True, "id": str(branch.id), "message": "Филиал создан"}, "status": 201}
    except Exception as e:
        return {"response": {"error": str(e)}, "status": 400}


def branch_detail(request, params):
    user = get_user_from_token(request)
    if not user: return {"response": {"error": "401"}, "status": 401}
    
    branch_id = params.get("branch_id")
    if not branch_id: return {"response": {"error": "branch_id required"}, "status": 400}
    
    try:
        branch = Branch.objects.select_related('clinic').get(id=branch_id)
        if user.role != CustomUser.Roles.SYSTEM_ADMIN:
             if not ClinicDirectorProfile.objects.filter(user=user, clinic=branch.clinic).exists():
                 return {"response": {"error": "Нет доступа"}, "status": 403}
                 
        data = {
            "id": str(branch.id),
            "name": branch.name,
            "address": branch.address,
            "phone": str(branch.phone),
            "email": branch.email,
            "working_hours": branch.working_hours,
            "is_active": branch.is_active,
            "clinic_id": str(branch.clinic.id),
            "clinic_name": branch.clinic.name
        }
        return {"response": data, "status": 200}
    except Branch.DoesNotExist:
        return {"response": {"error": "Филиал не найден"}, "status": 404}


def branch_update(request, params):
    user = get_user_from_token(request)
    if not user: return {"response": {"error": "401"}, "status": 401}
    
    branch_id = params.get("branch_id")
    try:
        branch = Branch.objects.get(id=branch_id)
        if user.role != CustomUser.Roles.SYSTEM_ADMIN:
             if not ClinicDirectorProfile.objects.filter(user=user, clinic=branch.clinic).exists():
                 return {"response": {"error": "Нет доступа"}, "status": 403}
        
        if "name" in params: branch.name = params["name"]
        if "address" in params: branch.address = params["address"]
        if "phone" in params: branch.phone = params["phone"]
        if "email" in params: branch.email = params["email"]
        if "working_hours" in params: branch.working_hours = params["working_hours"]
        if "is_active" in params: 
             new_status = params["is_active"]
             if new_status and not branch.is_active:
                  # Активация - проверим лимиты
                  sub = getattr(branch.clinic, 'subscription', None)
                  if sub and sub.plan:
                        limit = sub.plan.limit_branches
                        current = branch.clinic.branches.filter(is_active=True).count()
                        if current >= limit:
                             return {"response": {"error": f"Лимит филиалов ({limit})"}, "status": 400}
             branch.is_active = new_status
             
        branch.save()
        return {"response": {"success": True}, "status": 200}
        
    except Branch.DoesNotExist:
        return {"response": {"error": "Not found"}, "status": 404}


def branch_delete(request, params):
    user = get_user_from_token(request)
    if not user: return {"response": {"error": "401"}, "status": 401}
    
    branch_id = params.get("branch_id")
    try:
        branch = Branch.objects.get(id=branch_id)
        if user.role != CustomUser.Roles.SYSTEM_ADMIN:
             if not ClinicDirectorProfile.objects.filter(user=user, clinic=branch.clinic).exists():
                 return {"response": {"error": "Нет доступа"}, "status": 403}
        
        # Soft delete
        branch.is_active = False
        branch.save()
        
        return {"response": {"success": True, "message": "Филиал деактивирован"}, "status": 200}
        
    except Branch.DoesNotExist:
        return {"response": {"error": "Not found"}, "status": 404}
