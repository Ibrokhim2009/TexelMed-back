import random
import string
from core.models import Clinic, ClinicDirectorProfile, CustomUser
from v1.services.auth import generate_tokens












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

