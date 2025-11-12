from core.models import CustomUser, Patient
from v1.services.director import parse_iso_datetime


def add_patient(request, params):
    allowed = [CustomUser.Roles.RECEPTIONIST, CustomUser.Roles.CLINIC_ADMIN, CustomUser.Roles.CLINIC_DIRECTOR]
    if not request.user or request.user.role not in allowed:
        return {"response": {"error": "Нет прав"}, "status": 403}

    full_name = params.get("full_name")
    phone = params.get("phone")
    birth_date_str = params.get("birth_date")
    gender = params.get("gender", "male")
    email = params.get("email", "")
    address = params.get("address", "")

    if not full_name or not phone:
        return {"response": {"error": "Имя и телефон обязательны"}, "status": 400}

    birth_date = parse_iso_datetime(birth_date_str) if birth_date_str else None

    patient = Patient.objects.create(
        clinic=request.user.clinic,
        primary_branch=request.user.branch,
        full_name=full_name,
        phone=phone,
        email=email,
        birth_date=birth_date.date() if birth_date else None,
        gender=gender,
        address=address
    )

    return {
        "response": {
            "success": True,
            "message": "Пациент добавлен",
            "patient_id": str(patient.id),
            "card_number": patient.card_number or "Автогенерация"
        },
        "status": 200
    }

