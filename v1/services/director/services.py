from django.db import transaction
from django.db.models import Q, Sum, Count
from django.utils import timezone
from datetime import date
import uuid
from core.models import (
    CustomUser, Clinic, Service, ServiceCategory, 
    ServicePackage, DiscountCategory, Promotion, 
    ClinicDirectorProfile
)
from .utils import get_user_from_token

# === КАТЕГОРИИ УСЛУГ ===

def category_list(request, params):
    user = get_user_from_token(request)
    if not user: return {"response": {"error": "401"}, "status": 401}
    clinic = Clinic.objects.filter(director_profile_link__user=user).first()
    if not clinic: return {"response": {"error": "Нет доступа"}, "status": 403}

    # Используем 'services', так как добавили related_name='services' в модели Service
    categories = ServiceCategory.objects.filter(clinic=clinic).annotate(
        service_count=Count('services')
    ).order_by('order')
    
    data = []
    for c in categories:
        data.append({
            "id": str(c.id),
            "name": str(c.name),
            "order": c.order or 0,
            "services_count": c.service_count or 0
        })
    return {"response": {"categories": data}, "status": 200}

def category_create(request, params):
    user = get_user_from_token(request)
    if not user: return {"response": {"error": "401"}, "status": 401}
    clinic = Clinic.objects.filter(director_profile_link__user=user).first()
    if not clinic: return {"response": {"error": "Нет доступа"}, "status": 403}

    name = params.get("name")
    if not name: return {"response": {"error": "Название обязательно"}, "status": 400}

    cat, created = ServiceCategory.objects.get_or_create(clinic=clinic, name=str(name))
    
    return {"response": {"success": True, "id": str(cat.id), "name": cat.name, "created": created}, "status": 201}

def category_update(request, params):
    user = get_user_from_token(request)
    if not user: return {"response": {"error": "401"}, "status": 401}
    clinic = Clinic.objects.filter(director_profile_link__user=user).first()
    if not clinic: return {"response": {"error": "Нет доступа"}, "status": 403}

    cat_id = params.get("id")
    name = params.get("name")
    
    if not cat_id or not name:
        return {"response": {"error": "ID и название обязательны"}, "status": 400}

    try:
        cat = ServiceCategory.objects.get(id=cat_id, clinic=clinic)
        cat.name = str(name)
        cat.save()
        return {"response": {"success": True}, "status": 200}
    except ServiceCategory.DoesNotExist:
        return {"response": {"error": "Категория не найдена"}, "status": 404}

def category_delete(request, params):
    user = get_user_from_token(request)
    if not user: return {"response": {"error": "401"}, "status": 401}
    clinic = Clinic.objects.filter(director_profile_link__user=user).first()
    
    cat_id = params.get("id")
    try:
        cat = ServiceCategory.objects.get(id=cat_id, clinic=clinic)
        cat.delete()
        return {"response": {"success": True}, "status": 200}
    except ServiceCategory.DoesNotExist:
        return {"response": {"error": "Категория не найдена"}, "status": 404}


# === УСЛУГИ ===

def service_list(request, params):
    user = get_user_from_token(request)
    if not user: return {"response": {"error": "401"}, "status": 401}

    if user.role == CustomUser.Roles.SYSTEM_ADMIN:
        clinic_id = params.get("clinic_id")
        clinic = Clinic.objects.filter(id=clinic_id).first()
    else:
        clinic = Clinic.objects.filter(director_profile_link__user=user).first()
        
    if not clinic: return {"response": {"error": "Нет прав"}, "status": 403}

    services = Service.objects.filter(clinic=clinic).select_related('category')

    search = params.get("search", "").strip()
    if search:
        services = services.filter(Q(name__icontains=search) | Q(description__icontains=search))

    category_id = params.get("category_id")
    if category_id:
        services = services.filter(category_id=category_id)

    status = params.get("status")
    if status == "active": services = services.filter(is_active=True)
    elif status == "inactive": services = services.filter(is_active=False)

    data = []
    for s in services:
        price = float(s.price)
        discount = s.discount_percent
        final_price = price * (1 - discount / 100)
        
        data.append({
            "id": str(s.id),
            "name": s.name,
            "description": s.description,
            "category": {
                "id": str(s.category.id) if s.category else None,
                "name": s.category.name if s.category else "Без категории"
            },
            "price": price,
            "discount_percent": discount,
            "final_price": final_price,
            "duration": s.duration_minutes,
            "status": "Активна" if s.is_active else "Неактивна"
        })
        
    return {"response": {"services": data}, "status": 200}

def service_create(request, params):
    user = get_user_from_token(request)
    if not user: return {"response": {"error": "401"}, "status": 401}

    clinic = Clinic.objects.filter(director_profile_link__user=user).first()
    if not clinic: return {"response": {"error": "Нет доступа"}, "status": 403}

    name = params.get("name")
    price = params.get("price")
    
    if not name or price is None:
        return {"response": {"error": "Название и цена обязательны"}, "status": 400}

    category_id = params.get("category_id")
    category = None
    if category_id:
        category = ServiceCategory.objects.filter(id=category_id, clinic=clinic).first()

    try:
        service = Service.objects.create(
            clinic=clinic,
            category=category,
            name=name,
            price=price,
            duration_minutes=params.get("duration", 30),
            discount_percent=params.get("discount_percent", 0),
            is_active=params.get("is_active", True)
        )
        return {"response": {"success": True, "id": str(service.id)}, "status": 201}
    except Exception as e:
        return {"response": {"error": str(e)}, "status": 400}

def service_update(request, params):
    user = get_user_from_token(request)
    if not user: return {"response": {"error": "401"}, "status": 401}
    
    service_id = params.get("id")
    try:
        service = Service.objects.get(id=service_id)
        if user.role != CustomUser.Roles.SYSTEM_ADMIN:
            if not ClinicDirectorProfile.objects.filter(user=user, clinic=service.clinic).exists():
                return {"response": {"error": "Нет прав"}, "status": 403}
                
        if "name" in params: service.name = params["name"]
        if "price" in params: service.price = params["price"]
        if "discount_percent" in params: service.discount_percent = params["discount_percent"]
        if "is_active" in params: service.is_active = params["is_active"]
        
        if "category_id" in params:
            cid = params["category_id"]
            service.category = ServiceCategory.objects.filter(id=cid, clinic=service.clinic).first() if cid else None

        service.save()
        return {"response": {"success": True}, "status": 200}
    except Service.DoesNotExist:
        return {"response": {"error": "Услуга не найдена"}, "status": 404}

def service_delete(request, params):
    user = get_user_from_token(request)
    if not user: return {"response": {"error": "401"}, "status": 401}
    service_id = params.get("id")
    try:
        service = Service.objects.get(id=service_id)
        service.delete()
        return {"response": {"success": True}, "status": 200}
    except Service.DoesNotExist:
        return {"response": {"error": "Не найдено"}, "status": 404}


# === ПАКЕТЫ УСЛУГ ===

def package_list(request, params):
    user = get_user_from_token(request)
    if not user: return {"response": {"error": "401"}, "status": 401}
    clinic = Clinic.objects.filter(director_profile_link__user=user).first()
    if not clinic: return {"response": {"error": "Клиника не найдена"}, "status": 404}

    packages = ServicePackage.objects.filter(clinic=clinic).order_by('-created_at')
    data = []
    for p in packages:
        data.append({
            "id": str(p.id),
            "name": p.name,
            "services": [s.name for s in p.services.all()],
            "price_full": float(p.total_price),
            "price_discounted": float(p.price),
            "discount_percent": p.discount_percent,
            "is_active": p.is_active
        })
    return {"response": {"packages": data}, "status": 200}

def package_create(request, params):
    user = get_user_from_token(request)
    if not user: return {"response": {"error": "401"}, "status": 401}
    clinic = Clinic.objects.filter(director_profile_link__user=user).first()
    if not clinic: return {"response": {"error": "Нет прав"}, "status": 403}

    name = params.get("name")
    service_ids = params.get("service_ids", [])
    discount_percent = params.get("discount_percent", 0)

    services = Service.objects.filter(id__in=service_ids, clinic=clinic)
    total_price = sum(s.price for s in services)
    price_discounted = params.get("price_discounted") or (total_price * (1 - int(discount_percent)/100))
    
    with transaction.atomic():
        pkg = ServicePackage.objects.create(
            clinic=clinic, name=name, total_price=total_price,
            price=price_discounted, discount_percent=discount_percent
        )
        pkg.services.set(services)
        
    return {"response": {"success": True, "id": str(pkg.id)}, "status": 201}


# === МАРКЕТИНГ (СКИДКИ И АКЦИИ) ===

def marketing_list(request, params):
    user = get_user_from_token(request)
    if not user: return {"response": {"error": "401"}, "status": 401}
    clinic = Clinic.objects.filter(director_profile_link__user=user).first()
    
    discounts = DiscountCategory.objects.filter(clinic=clinic)
    promotions = Promotion.objects.filter(clinic=clinic)

    return {
        "response": {
            "discounts": [{"id": str(d.id), "name": d.name, "percent": d.percent} for d in discounts],
            "promotions": [{"id": str(p.id), "name": p.name, "percent": p.discount_percent} for p in promotions]
        },
        "status": 200
    }

def discount_create(request, params):
    user = get_user_from_token(request)
    if not user: return {"response": {"error": "401"}, "status": 401}
    clinic = Clinic.objects.filter(director_profile_link__user=user).first()

    DiscountCategory.objects.create(
        clinic=clinic, name=params.get("name"), percent=params.get("percent")
    )
    return {"response": {"success": True}, "status": 201}

def promotion_create(request, params):
    user = get_user_from_token(request)
    if not user: return {"response": {"error": "401"}, "status": 401}
    clinic = Clinic.objects.filter(director_profile_link__user=user).first()

    Promotion.objects.create(
        clinic=clinic, name=params.get("name"), 
        start_date=params.get("start_date"), end_date=params.get("end_date"),
        discount_percent=params.get("discount_percent", 0)
    )
    return {"response": {"success": True}, "status": 201}
