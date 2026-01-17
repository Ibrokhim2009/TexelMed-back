from datetime import timedelta
from django.utils import timezone
from django.db.models import Q
from core.models import CustomUser, Clinic, ClinicDirectorProfile, Patient, MedicalRecord, PatientFile, Payment, Appointment, Branch
from .utils import get_user_from_token

def patient_list(request, params):
    user = get_user_from_token(request)
    if not user:
        return {"response": {"error": "Токен обязателен"}, "status": 401}

    # Проверка прав (Директор или Системный админ)
    is_director = user.role == CustomUser.Roles.CLINIC_DIRECTOR
    if not is_director and user.role != CustomUser.Roles.SYSTEM_ADMIN:
        if not ClinicDirectorProfile.objects.filter(user=user).exists():
             return {"response": {"error": "Только для директоров"}, "status": 403}

    # Получаем клиники директора
    if user.role == CustomUser.Roles.SYSTEM_ADMIN:
        clinics = Clinic.objects.all()
    else:
        clinics = Clinic.objects.filter(director_profile_link__user=user)

    # Базовый QuerySet
    patients = Patient.objects.filter(clinic__in=clinics).select_related('clinic').prefetch_related('appointments__doctor')

    # === Фильтры ===
    
    # 1. Поиск (ФИО, телефон, email, карта)
    search = params.get("search", "").strip()
    if search:
        patients = patients.filter(
            Q(full_name__icontains=search) |
            Q(phone__icontains=search) |
            Q(email__icontains=search) |
            Q(card_number__icontains=search)
        )

    # 2. Статус
    status_filter = params.get("status")
    if status_filter:
        patients = patients.filter(status=status_filter)

    # 3. Долг
    debt_filter = params.get("debt")
    if debt_filter == "has_debt":
        patients = patients.filter(debt__gt=0)
    elif debt_filter == "no_debt":
        patients = patients.filter(debt=0)

    # Сортировка
    patients = patients.order_by('-last_visit', '-created_at')

    # Формирование ответа
    data = []
    now = timezone.now()

    for p in patients:
        # Последний визит (Врач)
        last_appt = p.appointments.filter(start_time__lte=now).order_by('-start_time').first()
        last_doctor = last_appt.doctor.full_name if last_appt and last_appt.doctor else None
        
        # Следующий визит
        next_appt = p.appointments.filter(start_time__gt=now).order_by('start_time').first()
        next_visit_date = next_appt.start_time if next_appt else None

        data.append({
            "id": str(p.id),
            "full_name": p.full_name,
            "contacts": {
                "phone": str(p.phone) if p.phone else "",
                "email": p.email
            },
            "last_visit": {
                "date": p.last_visit,
                "doctor": last_doctor
            },
            "next_visit": next_visit_date,
            "visits_count": p.total_visits,
            "total_paid": float(p.total_spent),
            "debt": float(p.debt),
            "status": p.get_status_display(),
            "clinic_name": p.clinic.name
        })

    return {"response": {"patients": data, "count": len(data)}, "status": 200}


def patient_create(request, params):
    user = get_user_from_token(request)
    if not user:
        return {"response": {"error": "Токен обязателен"}, "status": 401}

    # Проверяем права (Директор или Админ)
    if user.role not in [CustomUser.Roles.CLINIC_DIRECTOR, CustomUser.Roles.SYSTEM_ADMIN]:
             return {"response": {"error": "Нет прав"}, "status": 403}

    # Получаем данные
    full_name = params.get("full_name")
    phone = params.get("phone")
    birth_date = params.get("birth_date")  # Обязательно (YYYY-MM-DD)
    gender = params.get("gender")          # Обязательно
    branch_id = params.get("branch_id")    # Обязательно
    clinic_id = params.get("clinic_id") 
    
    # 1. Проверка обязательных полей
    errors = []
    if not full_name: errors.append("ФИО обязательно")
    if not phone: errors.append("Телефон обязателен")
    if not birth_date: errors.append("Дата рождения обязательна")
    if not gender: errors.append("Пол обязателен")
    
    if not branch_id and user.role == CustomUser.Roles.CLINIC_DIRECTOR:
         errors.append("Выберите филиал")

    if errors:
        return {"response": {"error": ", ".join(errors)}, "status": 400}

    # Определяем клинику
    if user.role == CustomUser.Roles.CLINIC_DIRECTOR:
        director_clinics = Clinic.objects.filter(director_profile_link__user=user)
        if clinic_id:
            clinic = director_clinics.filter(id=clinic_id).first()
        else:
            clinic = director_clinics.first()
        
        if not clinic:
            return {"response": {"error": "У вас нет клиник"}, "status": 404}
            
        limits = clinic.check_limits()
        if not limits["ok"]:
             return {"response": {"error": limits["error"]}, "status": 400}
             
    else:
        if not clinic_id:
             return {"response": {"error": "Админ должен указать clinic_id"}, "status": 400}
        clinic = Clinic.objects.get(id=clinic_id)

    # Обработка необязательных полей
    card_number = params.get("card_number")
    if not card_number or card_number.strip() == "":
        card_number = None

    # Создание
    try:
        patient = Patient.objects.create(
            clinic=clinic,
            full_name=full_name,
            phone=phone,
            birth_date=birth_date,
            gender=gender,
            primary_branch_id=branch_id,
            
            # Опциональные поля
            email=params.get("email", ""),
            address=params.get("address", ""),
            card_number=card_number,
            blood_type=params.get("blood_type", ""),
            allergies=params.get("allergies", ""),
            chronic_diseases=params.get("chronic_diseases", ""),
            notes=params.get("notes", ""),
            status=params.get("status", "active")
        )
        return {"response": {"success": True, "id": str(patient.id), "message": "Пациент создан"}, "status": 201}
    except Exception as e:
        return {"response": {"error": str(e)}, "status": 400}


def patient_detail(request, params):
    user = get_user_from_token(request)
    if not user: 
        return {"response": {"error": "Нет доступа"}, "status": 401}

    patient_id = params.get("patient_id")
    if not patient_id:
        return {"response": {"error": "patient_id обязателен"}, "status": 400}

    try:
        patient = Patient.objects.get(id=patient_id)
        
        if user.role != CustomUser.Roles.SYSTEM_ADMIN:
            if not ClinicDirectorProfile.objects.filter(user=user, clinic=patient.clinic).exists():
                 return {"response": {"error": "Это пациент другой клиники"}, "status": 403}

    except Patient.DoesNotExist:
        return {"response": {"error": "Пациент не найден"}, "status": 404}

    # Возраст
    age = None
    if patient.birth_date:
        today = timezone.now().date()
        age = today.year - patient.birth_date.year - ((today.month, today.day) < (patient.birth_date.month, patient.birth_date.day))

    data = {
        "id": str(patient.id),
        "full_name": patient.full_name,
        "age": age,
        "gender": patient.gender,
        "clinic": {
            "id": str(patient.clinic.id),
            "name": patient.clinic.name
        },
        "contacts": {
            "phone": str(patient.phone),
            "email": patient.email,
            "address": patient.address,
            "branch": patient.primary_branch.name if patient.primary_branch else None
        },
        "medical_info": {
            "blood_type": patient.blood_type,
            "card_number": patient.card_number,
            "allergies": patient.allergies,
            "chronic_diseases": patient.chronic_diseases,
            "notes": patient.notes,
            "status": patient.status,
            "status_display": patient.get_status_display()
        },
        "stats": {
            "total_visits": patient.total_visits,
            "total_paid": float(patient.total_spent),
            "debt": float(patient.debt)
        }
    }
    return {"response": data, "status": 200}


def patient_update(request, params):
    user = get_user_from_token(request)
    if not user: return {"response": {"error": "401"}, "status": 401}
    
    patient_id = params.get("patient_id")
    try:
        patient = Patient.objects.get(id=patient_id)
        if user.role != CustomUser.Roles.SYSTEM_ADMIN:
             if not ClinicDirectorProfile.objects.filter(user=user, clinic=patient.clinic).exists():
                 return {"response": {"error": "Нет прав"}, "status": 403}
                 
        if "full_name" in params: patient.full_name = params["full_name"]
        if "phone" in params: patient.phone = params["phone"]
        if "email" in params: patient.email = params["email"]
        if "address" in params: patient.address = params["address"]
        if "birth_date" in params: patient.birth_date = params["birth_date"]
        if "gender" in params: patient.gender = params["gender"]
        if "card_number" in params: patient.card_number = params["card_number"]
        if "blood_type" in params: patient.blood_type = params["blood_type"]
        if "allergies" in params: patient.allergies = params["allergies"]
        if "chronic_diseases" in params: patient.chronic_diseases = params["chronic_diseases"]
        if "notes" in params: patient.notes = params["notes"]
        if "branch_id" in params: patient.primary_branch_id = params["branch_id"]
        if "status" in params: patient.status = params["status"]
        
        patient.save()
        return {"response": {"success": True}, "status": 200}
        
    except Patient.DoesNotExist:
        return {"response": {"error": "Not found"}, "status": 404}


def patient_history(request, params):
    user = get_user_from_token(request)
    if not user: return {"response": {"error": "401"}, "status": 401}
    
    patient_id = params.get("patient_id")
    try:
        patient = Patient.objects.get(id=patient_id)
        if user.role != CustomUser.Roles.SYSTEM_ADMIN and not ClinicDirectorProfile.objects.filter(user=user, clinic=patient.clinic).exists():
             return {"response": {"error": "Нет прав"}, "status": 403}
    except Patient.DoesNotExist:
        return {"response": {"error": "Not found"}, "status": 404}

    records = MedicalRecord.objects.filter(patient=patient).select_related('doctor', 'appointment', 'appointment__branch', 'appointment__service').order_by('-visit_date')
    
    history = []
    for r in records:
        appt = r.appointment
        history.append({
            "id": str(r.id),
            "date": r.visit_date.strftime("%d.%m.%Y"),
            "doctor_name": r.doctor.full_name if r.doctor else "Неизвестно",
            "branch": appt.branch.name if appt and appt.branch else "Центральный",
            "services": appt.service.name if appt and appt.service else "Консультация",
            "diagnosis": r.diagnosis_text or r.diagnosis_icd10,
            "prescriptions": r.prescriptions,
            "cost": float(appt.price_paid) if appt and appt.price_paid else 0.0,
            "status": "Оплачено" if appt and appt.price_paid else "Не оплачено"
        })
        
    return {"response": {"history": history}, "status": 200}


def patient_documents(request, params):
    user = get_user_from_token(request)
    if not user: return {"response": {"error": "401"}, "status": 401}
    
    patient_id = params.get("patient_id")
    try:
        patient = Patient.objects.get(id=patient_id)
        if user.role != CustomUser.Roles.SYSTEM_ADMIN and not ClinicDirectorProfile.objects.filter(user=user, clinic=patient.clinic).exists():
             return {"response": {"error": "Нет прав"}, "status": 403}
    except Patient.DoesNotExist:
        return {"response": {"error": "Not found"}, "status": 404}

    files = PatientFile.objects.filter(patient=patient).order_by('-uploaded_at')
    data = []
    for f in files:
        data.append({
            "id": str(f.id),
            "name": f.description or f.get_file_type_display(),
            "type": f.get_file_type_display(),
            "date": f.uploaded_at.strftime("%d.%m.%Y"),
            "size": f"{f.file.size / 1024:.1f} KB",
            "url": f.file.url
        })
        
    return {"response": {"documents": data}, "status": 200}


def patient_finance(request, params):
    user = get_user_from_token(request)
    if not user: return {"response": {"error": "401"}, "status": 401}
    
    patient_id = params.get("patient_id")
    try:
        patient = Patient.objects.get(id=patient_id)
        if user.role != CustomUser.Roles.SYSTEM_ADMIN and not ClinicDirectorProfile.objects.filter(user=user, clinic=patient.clinic).exists():
             return {"response": {"error": "Нет прав"}, "status": 403}
    except Patient.DoesNotExist:
        return {"response": {"error": "Not found"}, "status": 404}

    payments = Payment.objects.filter(patient=patient).order_by('-paid_at')
    
    history = []
    for p in payments:
        history.append({
            "id": str(p.id),
            "date": p.paid_at.strftime("%d.%m.%Y"),
            "amount": float(p.amount),
            "method": p.get_method_display(),
            "status": "Оплачено" if p.status == 'success' else "Ошибка"
        })

    return {
        "response": {
            "summary": {
                "total_paid": float(patient.total_spent),
                "debt": float(patient.debt)
            },
            "history": history
        }, 
        "status": 200
    }


def patient_delete(request, params):
    user = get_user_from_token(request)
    if not user: return {"response": {"error": "401"}, "status": 401}
    
    patient_id = params.get("patient_id")
    if not patient_id: return {"response": {"error": "ID пациента обязателен"}, "status": 400}
    
    try:
        patient = Patient.objects.get(id=patient_id)
        
        if user.role != CustomUser.Roles.SYSTEM_ADMIN:
             is_owner = ClinicDirectorProfile.objects.filter(user=user, clinic=patient.clinic).exists()
             if not is_owner:
                 return {"response": {"error": "Вы не владелец этой клиники"}, "status": 403}
        
        patient.delete()
        return {"response": {"success": True, "message": "Пациент удален"}, "status": 200}
        
    except Patient.DoesNotExist:
        return {"response": {"error": "Пациент не найден"}, "status": 404}
