from django.db import transaction
from django.db.models import Q, Sum, Count, Avg
from django.utils import timezone
from datetime import timedelta, datetime
from core.models import CustomUser, Clinic, Branch, DoctorProfile, Appointment, Payment, ClinicDirectorProfile
from .utils import get_user_from_token
import random
import string

def get_current_month_range():
    now = timezone.now()
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end

def calculate_doctor_stats(doctor_user, start_date, end_date):
    appts = Appointment.objects.filter(doctor=doctor_user, start_time__range=(start_date, end_date))
    
    total_appts = appts.exclude(status=Appointment.Status.CANCELLED).count()
    cancelled_appts = appts.filter(status=Appointment.Status.CANCELLED).count()
    
    # Среднее время приема (в минутах)
    completed_appts = appts.filter(status=Appointment.Status.COMPLETED)
    avg_minutes = 0
    if completed_appts.exists():
        durations = [(a.end_time - a.start_time).total_seconds() / 60 for a in completed_appts]
        avg_minutes = sum(durations) / len(durations)
    
    # Доход
    income = appts.aggregate(total=Sum('price_paid'))['total'] or 0.0
    
    # Загрузка
    # Допустим, считаем за текущую неделю для простоты или за день. 
    # В идеале нужно парсить profile.schedule.
    # Для демонстрации вернем статические или полу-динамические данные, 
    # так как полноценный расчет сетки времени - это тяжелая логика.
    profile = getattr(doctor_user, 'doctor_profile', None)
    load_percent = 0
    free_slots = 0
    if profile and profile.schedule:
        # Упрощенный расчет: допустим 8 часов в день * 22 рабочих дня = 176 часов
        # Считаем сколько часов занято в приёмах
        total_worked_seconds = sum([(a.end_time - a.start_time).total_seconds() for a in appts.exclude(status=Appointment.Status.CANCELLED)])
        total_available_seconds = 176 * 3600 # Заглушка
        load_percent = min(int((total_worked_seconds / total_available_seconds) * 100), 100) if total_available_seconds > 0 else 0
        free_slots = max(0, 20 - total_appts) # Заглушка
        
    return {
        "appointments_count": total_appts,
        "avg_time": int(avg_minutes),
        "income": float(income),
        "cancelled": cancelled_appts,
        "load_percent": load_percent,
        "free_slots": free_slots
    }

def doctor_list(request, params):
    user = get_user_from_token(request)
    if not user: return {"response": {"error": "401"}, "status": 401}

    # Получаем клиники директора
    clinics = Clinic.objects.filter(director_profile_link__user=user)
    if not clinics.exists() and user.role != CustomUser.Roles.SYSTEM_ADMIN:
         return {"response": {"error": "Доступ запрещен"}, "status": 403}
    
    if user.role == CustomUser.Roles.SYSTEM_ADMIN:
        clinics = Clinic.objects.all()

    # Базовый запрос
    doctors = CustomUser.objects.filter(
        clinic__in=clinics, 
        role=CustomUser.Roles.DOCTOR
    ).select_related('doctor_profile', 'branch', 'clinic')

    # Фильтры
    search = params.get("search", "").strip()
    if search:
        doctors = doctors.filter(
            Q(full_name__icontains=search) |
            Q(email__icontains=search) |
            Q(phone__icontains=search) |
            Q(doctor_profile__specialization__icontains=search)
        )

    branch_id = params.get("branch_id")
    if branch_id:
        doctors = doctors.filter(branch_id=branch_id)

    spec_filter = params.get("specialization")
    if spec_filter:
        doctors = doctors.filter(doctor_profile__specialization__icontains=spec_filter)

    # Статистика за месяц
    start, end = get_current_month_range()
    
    data = []
    for d in doctors:
        profile = getattr(d, 'doctor_profile', None)
        stats = calculate_doctor_stats(d, start, end)
        
        data.append({
            "id": str(d.id),
            "full_name": d.full_name,
            "specialization": profile.specialization if profile else "Не указана",
            "branch": d.branch.name if d.branch else "Не назначен",
            "branch_id": str(d.branch.id) if d.branch else None,
            "cabinet": profile.cabinet if profile else "-",
            "contacts": {
                "phone": str(d.phone) if d.phone else "",
                "email": d.email
            },
            "experience_years": profile.experience_years if profile else 0,
            "rating": float(profile.rating) if profile else 0.0,
            "education": profile.education if profile else "",
            "work_history": profile.work_history if profile else "",
            "biography": profile.biography if profile else "",
            "stats_month": {
                "appointments": stats["appointments_count"],
                "avg_time_min": stats["avg_time"],
                "income": stats["income"],
                "cancelled": stats["cancelled"]
            },
            "load": {
                "percent": stats["load_percent"],
                "free_slots": stats["free_slots"]
            },
            "status": "Активен" if d.is_active else "Неактивен",
            "is_active": d.is_active,
            "photo": d.photo.url if d.photo else None
        })

    return {"response": {"doctors": data, "count": len(data)}, "status": 200}

def doctor_create(request, params):
    user = get_user_from_token(request)
    if not user: return {"response": {"error": "401"}, "status": 401}

    # Данные
    full_name = params.get("full_name")
    phone = params.get("phone")
    email = params.get("email")
    password = params.get("password") or "".join(random.choices(string.ascii_letters + string.digits, k=8))
    
    specialization = params.get("specialization")
    branch_id = params.get("branch_id")
    clinic_id = params.get("clinic_id")
    cabinet = params.get("cabinet")
    experience_years = params.get("experience_years", 0)
    education = params.get("education", "")
    work_history = params.get("work_history", "") # Можем сохранить в notes или расширить модель
    certificates = params.get("certificates", []) # List of strings
    schedule = params.get("schedule", {}) # JSON
    
    if not all([full_name, phone, email, specialization, branch_id]):
        return {"response": {"error": "Заполните обязательные поля (ФИО, Телефон, Email, Специальность, Филиал)"}, "status": 400}

    # Проверка клиники и прав
    if user.role == CustomUser.Roles.SYSTEM_ADMIN:
        if not clinic_id: return {"response": {"error": "clinic_id обязателен для админа"}, "status": 400}
        clinic = Clinic.objects.get(id=clinic_id)
    else:
        director_clinics = Clinic.objects.filter(director_profile_link__user=user)
        if clinic_id:
            clinic = director_clinics.filter(id=clinic_id).first()
        else:
            clinic = director_clinics.first()
        
        if not clinic:
            return {"response": {"error": "Нет доступа к клинике"}, "status": 403}

    try:
        branch = Branch.objects.get(id=branch_id, clinic=clinic)
    except Branch.DoesNotExist:
        return {"response": {"error": "Филиал не найден"}, "status": 404}

    if CustomUser.objects.filter(email=email).exists():
        return {"response": {"error": "Email уже занят"}, "status": 400}

    try:
        with transaction.atomic():
            new_user = CustomUser.objects.create(
                clinic=clinic,
                branch=branch,
                full_name=full_name,
                email=email,
                phone=phone,
                role=CustomUser.Roles.DOCTOR,
                is_active=params.get("status", "Активен") == "Активен"
            )
            new_user.set_password(password)
            new_user.save()
            
            DoctorProfile.objects.create(
                user=new_user,
                branch=branch,
                specialization=specialization,
                cabinet=cabinet,
                experience_years=experience_years,
                education=education,
                work_history=work_history,
                biography=params.get("biography", ""),
                certificates=certificates,
                schedule=schedule,
                rating=params.get("rating", 0.0)
            )
            
            return {"response": {"success": True, "id": str(new_user.id), "password": password}, "status": 201}
    except Exception as e:
        return {"response": {"error": str(e)}, "status": 400}

def doctor_detail(request, params):
    user = get_user_from_token(request)
    if not user: return {"response": {"error": "401"}, "status": 401}

    doctor_id = params.get("doctor_id")
    try:
        doctor = CustomUser.objects.select_related('doctor_profile', 'branch', 'clinic').get(id=doctor_id, role=CustomUser.Roles.DOCTOR)
        
        # Проверка прав (этот директор управляет этой клиникой?)
        if user.role != CustomUser.Roles.SYSTEM_ADMIN:
             if not ClinicDirectorProfile.objects.filter(user=user, clinic=doctor.clinic).exists():
                 return {"response": {"error": "Нет доступа"}, "status": 403}
                 
        profile = doctor.doctor_profile
        start, end = get_current_month_range()
        stats = calculate_doctor_stats(doctor, start, end)
        
        data = {
            "id": str(doctor.id),
            "full_name": doctor.full_name,
            "specialization": profile.specialization,
            "status": "Активен" if doctor.is_active else "Неактивен",
            "branch": {
                "id": str(doctor.branch.id) if doctor.branch else None,
                "name": doctor.branch.name if doctor.branch else "Не назначен"
            },
            "cabinet": profile.cabinet,
            "experience_years": profile.experience_years,
            "rating": float(profile.rating),
            "contacts": {
                "phone": str(doctor.phone),
                "email": doctor.email
            },
            "stats_month": {
                "appointments": stats["appointments_count"],
                "avg_time_min": stats["avg_time"],
                "income": stats["income"],
                "cancelled": stats["cancelled"]
            },
            "load": {
                "percent": stats["load_percent"],
                "slots_free": stats["free_slots"]
            },
            "education": profile.education,
            "work_history": profile.work_history,
            "biography": profile.biography,
            "certificates": profile.certificates,
            "schedule": profile.schedule,
            "photo": doctor.photo.url if doctor.photo else None
        }
        return {"response": data, "status": 200}
        
    except CustomUser.DoesNotExist:
        return {"response": {"error": "Врач не найден"}, "status": 404}

def doctor_update(request, params):
    user = get_user_from_token(request)
    if not user: return {"response": {"error": "401"}, "status": 401}
    
    doctor_id = params.get("doctor_id")
    try:
        doctor = CustomUser.objects.get(id=doctor_id, role=CustomUser.Roles.DOCTOR)
        if user.role != CustomUser.Roles.SYSTEM_ADMIN:
             if not ClinicDirectorProfile.objects.filter(user=user, clinic=doctor.clinic).exists():
                 return {"response": {"error": "Нет прав"}, "status": 403}

        # Обновление CustomUser
        if "full_name" in params: doctor.full_name = params["full_name"]
        if "phone" in params: doctor.phone = params["phone"]
        if "email" in params: doctor.email = params["email"]
        if "is_active" in params: doctor.is_active = params["is_active"]
        if "status" in params: doctor.is_active = (params["status"] == "Активен")
        doctor.save()
        
        # Обновление Profile
        profile = doctor.doctor_profile
        if "specialization" in params: profile.specialization = params["specialization"]
        if "cabinet" in params: profile.cabinet = params["cabinet"]
        if "experience_years" in params: profile.experience_years = params["experience_years"]
        if "education" in params: profile.education = params["education"]
        if "work_history" in params: profile.work_history = params["work_history"]
        if "biography" in params: profile.biography = params["biography"]
        if "certificates" in params: profile.certificates = params["certificates"]
        if "rating" in params: profile.rating = params["rating"]
        if "schedule" in params: profile.schedule = params["schedule"]
        
        if "branch_id" in params:
             branch = Branch.objects.get(id=params["branch_id"], clinic=doctor.clinic)
             doctor.branch = branch
             profile.branch = branch
             doctor.save()
             
        profile.save()
        
        return {"response": {"success": True, "message": "Данные врача обновлены"}, "status": 200}
        
    except CustomUser.DoesNotExist:
        return {"response": {"error": "Врач не найден"}, "status": 404}
    except Exception as e:
        return {"response": {"error": str(e)}, "status": 400}

def doctor_update_schedule(request, params):
    user = get_user_from_token(request)
    if not user: return {"response": {"error": "401"}, "status": 401}
    
    doctor_id = params.get("doctor_id")
    schedule = params.get("schedule") # JSON
    
    if not doctor_id or schedule is None:
        return {"response": {"error": "doctor_id и schedule обязательны"}, "status": 400}
        
    try:
        doctor = CustomUser.objects.get(id=doctor_id, role=CustomUser.Roles.DOCTOR)
        if user.role != CustomUser.Roles.SYSTEM_ADMIN:
             if not ClinicDirectorProfile.objects.filter(user=user, clinic=doctor.clinic).exists():
                 return {"response": {"error": "Нет прав"}, "status": 403}
        
        profile = doctor.doctor_profile
        profile.schedule = schedule
        profile.save()
        
        return {"response": {"success": True}, "status": 200}
    except CustomUser.DoesNotExist:
        return {"response": {"error": "Врач не найден"}, "status": 404}

def doctor_transfer(request, params):
    user = get_user_from_token(request)
    if not user: return {"response": {"error": "401"}, "status": 401}
    
    doctor_id = params.get("doctor_id")
    new_branch_id = params.get("branch_id")
    new_cabinet = params.get("cabinet")
    
    if not doctor_id or not new_branch_id:
        return {"response": {"error": "doctor_id и branch_id обязательны"}, "status": 400}
        
    try:
        doctor = CustomUser.objects.get(id=doctor_id, role=CustomUser.Roles.DOCTOR)
        if user.role != CustomUser.Roles.SYSTEM_ADMIN:
             if not ClinicDirectorProfile.objects.filter(user=user, clinic=doctor.clinic).exists():
                 return {"response": {"error": "Нет прав"}, "status": 403}
        
        new_branch = Branch.objects.get(id=new_branch_id, clinic=doctor.clinic)
        
        with transaction.atomic():
            doctor.branch = new_branch
            doctor.save()
            
            profile = doctor.doctor_profile
            profile.branch = new_branch
            if new_cabinet:
                profile.cabinet = new_cabinet
            profile.save()
            
        return {"response": {"success": True, "message": f"Врач переведен в {new_branch.name}"}, "status": 200}
    except CustomUser.DoesNotExist:
        return {"response": {"error": "Врач не найден"}, "status": 404}
    except Branch.DoesNotExist:
        return {"response": {"error": "Целевой филиал не найден в этой клинике"}, "status": 404}
