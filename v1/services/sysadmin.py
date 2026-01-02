from gettext import translation
import random
import string
from core.models import Branch, Clinic, ClinicDirectorProfile, CustomUser, Plan, Subscription
from v1.services.auth import generate_tokens
from v1.services.director import get_user_from_token
from django.db import transaction
from django.core.exceptions import ObjectDoesNotExist




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



def create_plan(request, params):
    user = get_user_from_token(request)
    if not user:
        return {"response": {"error": "Токен обязателен"}, "status": 401}

    if user.role != CustomUser.Roles.SYSTEM_ADMIN:
        return {"response": {"error": "Доступ запрещён. Только системный администратор"}, "status": 403}

    required_fields = ["name", "slug", "price_monthly"]
    for field in required_fields:
        if not params.get(field):
            return {"response": {"error": f"Обязательное поле: {field}"}, "status": 400}

    slug = params["slug"].strip().lower()

    if Plan.objects.filter(slug=slug).exists():
        return {"response": {"error": "План с таким slug уже существует"}, "status": 400}

    plan = Plan.objects.create(
        name=params["name"].strip(),
        slug=slug,
        price_monthly=params["price_monthly"],
        currency=params.get("currency", "UZS"),
        limit_users=int(params.get("limit_users", 10)),
        limit_branches=int(params.get("limit_branches", 1)),
        limit_clinics=int(params.get("limit_clinics", 1)),
        limit_patients=int(params.get("limit_patients", 5000)),
        is_active=params.get("is_active", True) in (True, "true", "True", 1, "1")
    )

    return {
        "response": {
            "success": True,
            "message": "Тарифный план успешно создан",
            "plan": {
                "id": str(plan.id),
                "name": plan.name,
                "slug": plan.slug,
                "price_monthly": str(plan.price_monthly),
                "currency": plan.currency,
                "limit_users": plan.limit_users,
                "limit_branches": plan.limit_branches,
                "limit_clinics": plan.limit_clinics,
                "limit_patients": plan.limit_patients,
                "is_active": plan.is_active,
            }
        },
        "status": 201
    }


def update_plan(request, params):
    user = get_user_from_token(request)
    if not user:
        return {"response": {"error": "Токен обязателен"}, "status": 401}

    if user.role != CustomUser.Roles.SYSTEM_ADMIN:
        return {"response": {"error": "Доступ запрещён. Только системный администратор"}, "status": 403}

    plan_id = params.get("id")
    if not plan_id:
        return {"response": {"error": "Поле id обязательно"}, "status": 400}

    try:
        plan = Plan.objects.get(id=plan_id)
    except ObjectDoesNotExist:
        return {"response": {"error": "Тарифный план не найден"}, "status": 404}

    updated = False

    if "name" in params:
        plan.name = params["name"].strip()
        updated = True
    if "price_monthly" in params:
        plan.price_monthly = params["price_monthly"]
        updated = True
    if "currency" in params:
        plan.currency = params["currency"]
        updated = True
    if "limit_users" in params:
        plan.limit_users = int(params["limit_users"])
        updated = True
    if "limit_branches" in params:
        plan.limit_branches = int(params["limit_branches"])
        updated = True
    if "limit_clinics" in params:
        plan.limit_clinics = int(params["limit_clinics"])
        updated = True
    if "limit_patients" in params:
        plan.limit_patients = int(params["limit_patients"])
        updated = True
    if "is_active" in params:
        plan.is_active = params["is_active"] in (True, "true", "True", 1, "1")
        updated = True
    if "slug" in params:
        new_slug = params["slug"].strip().lower()
        if new_slug != plan.slug and Plan.objects.filter(slug=new_slug).exists():
            return {"response": {"error": "Этот slug уже занят"}, "status": 400}
        plan.slug = new_slug
        updated = True

    if not updated:
        return {"response": {"error": "Нет данных для обновления"}, "status": 400}

    plan.save()

    return {
        "response": {
            "success": True,
            "message": "Тарифный план обновлён",
            "plan": {
                "id": str(plan.id),
                "name": plan.name,
                "slug": plan.slug,
                "price_monthly": str(plan.price_monthly),
                "currency": plan.currency,
                "limit_users": plan.limit_users,
                "limit_branches": plan.limit_branches,
                "limit_clinics": plan.limit_clinics,
                "limit_patients": plan.limit_patients,
                "is_active": plan.is_active,
            }
        },
        "status": 200
    }


def delete_plan(request, params):
    user = get_user_from_token(request)
    if not user:
        return {"response": {"error": "Токен обязателен"}, "status": 401}

    if user.role != CustomUser.Roles.SYSTEM_ADMIN:
        return {"response": {"error": "Доступ запрещён. Только системный администратор"}, "status": 403}

    plan_id = params.get("id")
    if not plan_id:
        return {"response": {"error": "Поле id обязательно"}, "status": 400}

    try:
        plan = Plan.objects.get(id=plan_id)
    except ObjectDoesNotExist:
        return {"response": {"error": "Тарифный план не найден"}, "status": 404}

    if Subscription.objects.filter(plan=plan, status__in=['active', 'trial', 'overdue']).exists():
        return {"response": {"error": "Нельзя удалить план — есть активные подписки"}, "status": 400}

    plan_name = plan.name
    plan.delete()

    return {
        "response": {
            "success": True,
            "message": f"Тарифный план «{plan_name}» удалён"
        },
        "status": 200
    }


def list_plans(request, params):
    user = get_user_from_token(request)
    if not user:
        return {"response": {"error": "Токен обязателен"}, "status": 401}

    if user.role not in [CustomUser.Roles.SYSTEM_ADMIN, CustomUser.Roles.CLINIC_DIRECTOR, CustomUser.Roles.PENDING_DIRECTOR]:
        return {"response": {"error": "Доступ запрещён"}, "status": 403}

    plans = Plan.objects.filter(is_active=True).order_by('price_monthly')

    data = []
    for p in plans:
        active_count = Subscription.objects.filter(plan=p, status__in=['active', 'trial']).count()
        data.append({
            "id": str(p.id),
            "name": p.name,
            "slug": p.slug,
            "price_monthly": str(p.price_monthly),
            "currency": p.currency,
            "limit_users": p.limit_users,
            "limit_branches": p.limit_branches,
            "limit_clinics": p.limit_clinics,
            "limit_patients": p.limit_patients,
            "active_subscriptions": active_count,
        })

    return {"response": data, "status": 200}


def get_plan(request, params):
    user = get_user_from_token(request)
    if not user:
        return {"response": {"error": "Токен обязателен"}, "status": 401}

    if user.role != CustomUser.Roles.SYSTEM_ADMIN:
        return {"response": {"error": "Доступ запрещён. Только системный администратор"}, "status": 403}

    identifier = params.get("id") or params.get("slug")
    if not identifier:
        return {"response": {"error": "Передайте id или slug плана"}, "status": 400}

    try:
        if len(str(identifier)) > 30:  # вероятно UUID
            plan = Plan.objects.get(id=identifier)
        else:
            plan = Plan.objects.get(slug=identifier)
    except ObjectDoesNotExist:
        return {"response": {"error": "План не найден"}, "status": 404}

    # Получаем все подписки на этот план
    subscriptions = Subscription.objects.filter(plan=plan).select_related('clinic')

    # Статистика
    total_subscriptions = subscriptions.count()
    active_subscriptions = subscriptions.filter(status__in=['active', 'trial']).count()

    # Список клиник с подробностями
    clinics_data = []
    for sub in subscriptions:
        if not sub.clinic:
            continue

        # Проверка лимитов
        limits_check = sub.clinic.check_limits()
        limits_ok = limits_check.get("ok", False)

        clinic_data = {
            "id": str(sub.clinic.id),
            "name": sub.clinic.name,
            "legal_name": sub.clinic.legal_name or "",
            "status": sub.clinic.status,
            "subscription_status": sub.status,
            "period_start": sub.period_start.isoformat() if sub.period_start else None,
            "period_end": sub.period_end.isoformat() if sub.period_end else None,
            "auto_renew": sub.auto_renew,
            "created_at": sub.created_at.isoformat(),
            
            # Текущая загрузка
            "current_users": sub.clinic.users.filter(is_active=True).count(),
            "current_branches": sub.clinic.branches.filter(is_active=True).count(),
            "current_patients": sub.clinic.patients.count(),
            
            # Лимиты плана
            "limit_users": plan.limit_users,
            "limit_branches": plan.limit_branches,
            "limit_patients": plan.limit_patients,
            
            "limits_exceeded": not limits_ok,
            "limits_warning": limits_check.get("error") if not limits_ok else None,
        }
        clinics_data.append(clinic_data)

    return {
        "response": {
            "plan": {
                "id": str(plan.id),
                "name": plan.name,
                "slug": plan.slug,
                "price_monthly": str(plan.price_monthly),
                "currency": plan.currency,
                "limits": {
                    "users": plan.limit_users,
                    "branches": plan.limit_branches,
                    "clinics": plan.limit_clinics,
                    "patients": plan.limit_patients,
                },
                "is_active": plan.is_active,
            },
            "statistics": {
                "total_subscriptions": total_subscriptions,
                "active_subscriptions": active_subscriptions,
                "total_clinics": len(clinics_data),
            },
            "clinics": clinics_data
        },
        "status": 200
    }
    
from django.db.models import Q
from datetime import date
import uuid

def list_clinic_subscriptions(request, params):
    """
    Возвращает список всех клиник с данными по подписке для системного админа.
    Используется на странице "Подписки клиник".
    """
    user = get_user_from_token(request)
    if not user:
        return {"response": {"error": "Токен обязателен"}, "status": 401}

    if user.role != CustomUser.Roles.SYSTEM_ADMIN:
        return {"response": {"error": "Доступ запрещён. Только системный администратор"}, "status": 403}

    # Фильтры (можно расширять)
    search = params.get("search", "").strip()
    status_filter = params.get("status")  # 'active', 'trial', 'overdue', 'cancelled' или None
    plan_slug = params.get("plan")
    payment_method = params.get("payment_method")

    today = date.today()

    # Базовый queryset: все клиники с подпиской
    subscriptions = Subscription.objects.select_related('clinic', 'plan').all()

    if search:
        subscriptions = subscriptions.filter(
            Q(clinic__name__icontains=search) |
            Q(clinic__legal_name__icontains=search) |
            Q(clinic__inn__icontains=search)
        )

    if status_filter:
        subscriptions = subscriptions.filter(status=status_filter)

    if plan_slug:
        subscriptions = subscriptions.filter(plan__slug=plan_slug)

    # Здесь payment_method сложнее — он не хранится в Subscription напрямую.
    # Если у тебя есть модель Payment для подписок (отдельно от приёмов), то можно join.
    # Пока пропустим, или добавим позже.

    # Статистика сверху
    total_clinics = subscriptions.count()
    paid_count = subscriptions.filter(status__in=['active', 'trial']).count()
    waiting_count = subscriptions.filter(status='overdue').count()  # или отдельное поле?
    overdue_count = subscriptions.filter(
        Q(status__in=['active', 'trial']) &
        Q(period_end__lt=today)
    ).count()

    total_amount = sum(
        sub.plan.price_monthly for sub in subscriptions 
        if sub.plan and sub.status in ['active', 'trial']
    ) if subscriptions else 0

    paid_amount = sum(
        sub.plan.price_monthly for sub in subscriptions 
        if sub.plan and sub.status in ['active', 'trial'] and sub.period_end >= today
    ) if subscriptions else 0

    # Данные для таблицы
    clinics_data = []
    for sub in subscriptions.order_by('-period_end'):
        clinic = sub.clinic
        plan = sub.plan

        if not clinic or not plan:
            continue  # пропускаем битые записи

        # Дней до окончания
        if sub.period_end:
            days_left = (sub.period_end - today).days
            if days_left > 0:
                days_text = f"+{days_left} дн."
                days_color = "green"
            elif days_left == 0:
                days_text = "Сегодня"
                days_color = "yellow"
            else:
                days_text = f"{abs(days_left)} дн."
                days_color = "red"
        else:
            days_text = "—"
            days_color = "gray"

        # Статус оплаты
        if sub.status in ['active', 'trial'] and (not sub.period_end or sub.period_end >= today):
            payment_status = "Оплачено"
            payment_color = "green"
        elif sub.status == 'overdue' or (sub.period_end and sub.period_end < today):
            payment_status = "Просрочено"
            payment_color = "red"
        else:
            payment_status = "Ожидает"
            payment_color = "yellow"

        payment_method_display = "Банковский перевод"

        clinics_data.append({
            "clinic_id": str(clinic.id),
            "clinic_name": clinic.name,
            "plan_name": plan.name,
            "period_end": sub.period_end.strftime("%d.%m.%Y") if sub.period_end else None,
            "days_left": days_text,
            "days_color": days_color,  # для фронта, чтобы покрасить
            "payment_status": payment_status,
            "payment_status_color": payment_color,
            "payment_method": payment_method_display,
            "amount": str(plan.price_monthly),
            "currency": plan.currency,
            "status": sub.status,
            "auto_renew": sub.auto_renew,
        })

    return {
        "response": {
            "summary": {
                "total_clinics": total_clinics,
                "total_amount": f"{total_amount:,.0f}".replace(",", " "),

                "paid_clinics": paid_count,
                "paid_amount": f"{paid_amount:,.0f}".replace(",", " "),

                "waiting_clinics": waiting_count,
                "overdue_clinics": overdue_count,
            },
            "clinics": clinics_data
        },
        "status": 200
    }
from django.db.models import Q, Max, Prefetch
from django.utils import timezone
from django.db.models import Q, Max
from django.utils import timezone

def list_all_clinics_for_admin(request, params):
    """
    Список всех клиник для системного администратора.
    100% безопасно: НЕ падает при отсутствии директора, подписки, плана и т.д.
    Поддерживает поиск и все фильтры с экрана.
    """
    user = get_user_from_token(request)
    if not user:
        return {"response": {"error": "Токен обязателен"}, "status": 401}

    if user.role != CustomUser.Roles.SYSTEM_ADMIN:
        return {"response": {"error": "Доступ только системному администратору"}, "status": 403}

    # Фильтры
    search = params.get("search", "").strip().lower()
    status_filter = params.get("status")               # active/suspended/blocked
    plan_slug = params.get("plan_slug")
    registration_month = params.get("registration_month")  # YYYY-MM

    # Базовый queryset — только Clinic, без опасных related
    clinics_qs = Clinic.objects.all().annotate(
        last_payment_date=Max('payments__paid_at')
    )

    # Фильтры по полям клиники
    if status_filter and status_filter in dict(Clinic.Status.choices):
        clinics_qs = clinics_qs.filter(status=status_filter)

    if registration_month:
        try:
            year, month = map(int, registration_month.split('-'))
            if 1 <= month <= 12:
                clinics_qs = clinics_qs.filter(created_at__year=year, created_at__month=month)
        except:
            pass

    if search:
        clinics_qs = clinics_qs.filter(
            Q(name__icontains=search) |
            Q(legal_name__icontains=search) |
            Q(inn__icontains=search)
        )

    # Фильтр по плану — через подписку (безопасно, NULL допускается)
    if plan_slug:
        clinics_qs = clinics_qs.filter(subscription__plan__slug=plan_slug)

    # Сортировка
    clinics_qs = clinics_qs.order_by('-created_at')

    # ID всех клиник для пакетных запросов
    clinic_ids = list(clinics_qs.values_list('id', flat=True))

    if not clinic_ids:
        return {"response": {"clinics": [], "total": 0, "filters": {}}, "status": 200}

    # === ПАКЕТНЫЕ ЗАПРОСЫ ДЛЯ СВЯЗАННЫХ ДАННЫХ ===
    from django.db.models import Prefetch

    # 1. Директора (OneToOne → берём только существующие)
    director_profiles = ClinicDirectorProfile.objects.filter(clinic_id__in=clinic_ids)\
        .select_related('user')\
        .values('clinic_id', 'user__full_name', 'user__email', 'user__phone')

    director_map = {}
    for d in director_profiles:
        director_map[d['clinic_id']] = {
            "full_name": d['user__full_name'],
            "email": d['user__email'],
            "phone": str(d['user__phone']) if d['user__phone'] else None
        }

    # 2. Подписки и планы
    subscriptions = Subscription.objects.filter(clinic_id__in=clinic_ids)\
        .select_related('plan')\
        .values('clinic_id', 'status', 'plan__name', 'plan__slug')

    subscription_map = {}
    for s in subscriptions:
        subscription_map[s['clinic_id']] = {
            "status": s['status'],
            "plan_name": s['plan__name'],
            "plan_slug": s['plan__slug']
        }

    # === СБОР ФИНАЛЬНЫХ ДАННЫХ ===
    data = []

    for clinic in clinics_qs:
        clinic_id = clinic.id

        # Директор
        director_info = director_map.get(clinic_id, {
            "full_name": "Нет директора",
            "email": None,
            "phone": None
        })

        # Подписка и план
        sub_info = subscription_map.get(clinic_id, {})
        plan_name = sub_info.get("plan_name", "Без тарифа")
        plan_slug_out = sub_info.get("plan_slug")

        # Поиск по директору (если был search и не нашли по клинике)
        if search:
            if not (
                search in clinic.name.lower() or
                (clinic.legal_name and search in clinic.legal_name.lower()) or
                (clinic.inn and search in clinic.inn) or
                search in director_info["full_name"].lower() or
                (director_info["email"] and search in director_info["email"].lower())
            ):
                continue

        # Статус клиники
        status_display = dict(Clinic.Status.choices).get(clinic.status, "Неизвестно")
        status_color = {
            'active': 'green',
            'suspended': 'yellow',
            'blocked': 'red'
        }.get(clinic.status, 'gray')

        # Даты
        reg_date = clinic.created_at.strftime("%Y-%m-%d")
        last_payment = clinic.last_payment_date.strftime("%Y-%m-%d") if clinic.last_payment_date else None

        # Статистика (агрегация по related, безопасно)
        users_count = CustomUser.objects.filter(clinic_id=clinic_id, is_active=True).count()
        branches_count = Branch.objects.filter(clinic_id=clinic_id, is_active=True).count()

        # Проверка лимитов
        limits_ok = True
        if clinic_id in subscription_map and subscription_map[clinic_id].get("plan_name"):
            limits_check = clinic.check_limits()
            limits_ok = limits_check.get("ok", False)

        data.append({
            "clinic_id": str(clinic_id),
            "name": clinic.name,
            "logo": clinic.logo.url if clinic.logo else None,

            "director": director_info,

            "status": clinic.status,
            "status_display": status_display,
            "status_color": status_color,

            "plan": plan_name,
            "plan_slug": plan_slug_out,

            "registration_date": reg_date,

            "users_count": users_count,
            "branches_count": branches_count,

            "last_payment": last_payment,

            "limits_ok": limits_ok,

            "subscription_status": sub_info.get("status"),
        })

    return {
        "response": {
            "clinics": data,
            "total": len(data),
            "filters": {
                "search": params.get("search"),
                "status": status_filter,
                "plan_slug": plan_slug,
                "registration_month": registration_month
            }
        },
        "status": 200
    }
    
    
from django.db.models import Q, Max
from django.utils import timezone
from core.models import CustomUser, Clinic, Branch

def list_all_users_for_admin(request, params):
    """
    Список ВСЕХ пользователей платформы для системного администратора.
    Полностью безопасно: нет клиники, филиала, профиля — всё ок.
    Поддерживает все фильтры с экрана: поиск, клиника, роль, статус, дата регистрации.
    """
    user = get_user_from_token(request)
    if not user:
        return {"response": {"error": "Токен обязателен"}, "status": 401}

    if user.role != CustomUser.Roles.SYSTEM_ADMIN:
        return {"response": {"error": "Доступ только системному администратору"}, "status": 403}

    # === ФИЛЬТРЫ ИЗ PARAMS ===
    search = params.get("search", "").strip().lower()
    clinic_id = params.get("clinic_id")  # UUID клиники
    role = params.get("role")  # 'doctor', 'clinic_director' и т.д.
    status = params.get("status")  # 'active' или 'blocked' (is_active=True/False)
    registration_month = params.get("registration_month")  # YYYY-MM

    # === БАЗОВЫЙ QUERYSET ПОЛЬЗОВАТЕЛЕЙ ===
    users_qs = CustomUser.objects.select_related('clinic', 'branch').all()

    # Фильтр по активности (статус)
    if status == "active":
        users_qs = users_qs.filter(is_active=True)
    elif status == "blocked":
        users_qs = users_qs.filter(is_active=False)

    # Фильтр по роли
    if role and role in dict(CustomUser.Roles.choices):
        users_qs = users_qs.filter(role=role)

    # Фильтр по клинике
    if clinic_id:
        try:
            users_qs = users_qs.filter(clinic_id=clinic_id)
        except:
            pass  # неверный UUID — игнорируем

    # Фильтр по месяцу регистрации
    if registration_month:
        try:
            year, month = map(int, registration_month.split('-'))
            if 1 <= month <= 12:
                users_qs = users_qs.filter(date_joined__year=year, date_joined__month=month)
        except:
            pass

    # Поиск по ФИО, email, телефону
    if search:
        users_qs = users_qs.filter(
            Q(full_name__icontains=search) |
            Q(email__icontains=search) |
            Q(phone__icontains=search)
        )

    # Сортировка: новые сверху
    users_qs = users_qs.order_by('-date_joined')

    # === ПАКЕТНЫЕ ДАННЫЕ ДЛЯ БЕЗОПАСНОСТИ ===
    user_ids = list(users_qs.values_list('id', flat=True))
    if not user_ids:
        return {"response": {"users": [], "total": 0, "filters": {}}, "status": 200}

    # Клиники и филиалы уже в select_related — безопасно, т.к. ForeignKey SET_NULL
    # Они могут быть None → обработаем ниже

    # === СБОР ДАННЫХ ===
    data = []

    for u in users_qs:
        # Клиника
        clinic_name = u.clinic.name if u.clinic else "Без клиники"
        clinic_id_out = str(u.clinic.id) if u.clinic else None

        # Филиал
        branch_name = u.branch.name if u.branch else "Без филиала"
        branch_id_out = str(u.branch.id) if u.branch else None

        # Статус
        status_display = "Активен" if u.is_active else "Заблокирован"
        status_color = "green" if u.is_active else "red"

        # Роль (красивое название)
        role_display = u.get_role_display()

        # Телефон (красивый формат)
        phone_display = u.phone.as_e164 if u.phone else None

        # Последний вход — пока нет поля last_login, можно добавить позже
        # Если добавишь в модель: last_login = models.DateTimeField(null=True, blank=True)
        last_login = None  # или u.last_login.strftime(...) если добавишь

        # Дата регистрации
        reg_date = u.date_joined.strftime("%Y-%m-%d")

        data.append({
            "user_id": str(u.id),
            "full_name": u.full_name,
            "email": u.email,
            "phone": phone_display,
            "photo": u.photo.url if u.photo else None,

            "role": u.role,
            "role_display": role_display,

            "clinic": {
                "id": clinic_id_out,
                "name": clinic_name
            },

            "branch": {
                "id": branch_id_out,
                "name": branch_name
            },

            "status": "active" if u.is_active else "blocked",
            "status_display": status_display,
            "status_color": status_color,

            "registration_date": reg_date,
            "last_login": last_login,  # можно добавить поле в модель позже

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
    
    
    
from django.db import transaction
from django.core.exceptions import ObjectDoesNotExist
from core.models import (
    CustomUser, Clinic, Branch,
    ClinicDirectorProfile, ClinicAdminProfile,
    DoctorProfile, ReceptionistProfile
)
import random
import string

# === 1. БЛОКИРОВКА ПОЛЬЗОВАТЕЛЯ ===
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


# === 2. РАЗБЛОКИРОВКА ПОЛЬЗОВАТЕЛЯ ===
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


# === 3. УДАЛЕНИЕ ПОЛЬЗОВАТЕЛЯ (мягкое — деактивация + пометка) ===
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
    """
    Создаёт пользователя от имени системного админа.
    Автоматически создаёт пустой профиль в зависимости от роли.
    """
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
            # Создаём профиль БЕЗ филиала — потом назначим отдельно
            ClinicAdminProfile.objects.create(user=new_user)  # branch=None по умолчанию

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
    
    

from django.db import transaction
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Q, Count

from core.models import Branch, Clinic, CustomUser, ClinicAdminProfile

# === 1. СПИСОК ВСЕХ ФИЛИАЛОВ ДЛЯ СИСАДМИНА (ИСПРАВЛЕНО) ===
def list_all_branches_for_admin(request, params):
    """
    Список всех филиалов платформы для системного администратора.
    Без ошибок, с правильной статистикой.
    """
    user = get_user_from_token(request)
    if not user or user.role != CustomUser.Roles.SYSTEM_ADMIN:
        return {"response": {"error": "Доступ только системному администратору"}, "status": 403}

    # Фильтры
    search = params.get("search", "").strip()
    clinic_id = params.get("clinic_id")
    status_filter = params.get("status")  # 'active' или 'inactive'
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

    # Пакетно считаем статистику
    branch_ids = list(branches_qs.values_list('id', flat=True))

    # Количество сотрудников в филиале (через обратную связь branch в CustomUser)
    staff_counts = CustomUser.objects.filter(branch_id__in=branch_ids, is_active=True)\
        .values('branch_id')\
        .annotate(count=Count('id'))\
        .values_list('branch_id', 'count')

    staff_map = {str(bid): count for bid, count in staff_counts}

    # Пациенты — по клинике филиала
    clinic_patient_counts = Clinic.objects.filter(branches__id__in=branch_ids)\
        .annotate(patients_count=Count('patients'))\
        .values_list('id', 'patients_count')

    patients_map = {str(clinic_id): count for clinic_id, count in clinic_patient_counts}

    data = []
    for branch in branches_qs:
        clinic = branch.clinic

        # Ответственный администратор
        admin_profile = ClinicAdminProfile.objects.filter(branch=branch).select_related('user').first()
        admin_name = admin_profile.user.full_name if admin_profile else "Не назначен"

        # Город (из адреса)
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


# === 2. СОЗДАНИЕ ФИЛИАЛА ===
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

    # Проверка лимита филиалов
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

        # Назначаем администратора
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


# === 3. ОБНОВЛЕНИЕ ФИЛИАЛА ===
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

        # Смена администратора
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


# === 4. ПЕРЕКЛЮЧЕНИЕ СТАТУСА ===
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

    # Назначаем (или меняем филиал)
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