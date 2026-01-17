from django.db.models import Q, Max, Prefetch
from datetime import date
from core.models import CustomUser, Clinic, Branch, Subscription, Plan, ClinicDirectorProfile
from .utils import get_user_from_token

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

    # Фильтры
    search = params.get("search", "").strip()
    status_filter = params.get("status")
    plan_slug = params.get("plan")
    
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

    # Статистика сверху
    total_clinics = subscriptions.count()
    paid_count = subscriptions.filter(status__in=['active', 'trial']).count()
    waiting_count = subscriptions.filter(status='overdue').count()
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
            continue

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
            "days_color": days_color,
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


def list_all_clinics_for_admin(request, params):
    """
    Список всех клиник для системного администратора.
    """
    user = get_user_from_token(request)
    if not user:
        return {"response": {"error": "Токен обязателен"}, "status": 401}

    if user.role != CustomUser.Roles.SYSTEM_ADMIN:
        return {"response": {"error": "Доступ только системному администратору"}, "status": 403}

    # Фильтры
    search = params.get("search", "").strip().lower()
    status_filter = params.get("status")
    plan_slug = params.get("plan_slug")
    registration_month = params.get("registration_month")

    # Базовый queryset
    clinics_qs = Clinic.objects.all().annotate(
        last_payment_date=Max('payments__paid_at')
    )

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

    if plan_slug:
        clinics_qs = clinics_qs.filter(subscription__plan__slug=plan_slug)

    clinics_qs = clinics_qs.order_by('-created_at')

    # ID всех клиник
    clinic_ids = list(clinics_qs.values_list('id', flat=True))

    if not clinic_ids:
        return {"response": {"clinics": [], "total": 0, "filters": {}}, "status": 200}

    # Пакетные запросы
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

    data = []

    for clinic in clinics_qs:
        clinic_id = clinic.id

        director_info = director_map.get(clinic_id, {
            "full_name": "Нет директора",
            "email": None,
            "phone": None
        })

        sub_info = subscription_map.get(clinic_id, {})
        plan_name = sub_info.get("plan_name", "Без тарифа")
        plan_slug_out = sub_info.get("plan_slug")

        if search:
            if not (
                search in clinic.name.lower() or
                (clinic.legal_name and search in clinic.legal_name.lower()) or
                (clinic.inn and search in clinic.inn) or
                search in director_info["full_name"].lower() or
                (director_info["email"] and search in director_info["email"].lower())
            ):
                continue

        status_display = dict(Clinic.Status.choices).get(clinic.status, "Неизвестно")
        status_color = {
            'active': 'green',
            'suspended': 'yellow',
            'blocked': 'red'
        }.get(clinic.status, 'gray')

        reg_date = clinic.created_at.strftime("%Y-%m-%d")
        last_payment = clinic.last_payment_date.strftime("%Y-%m-%d") if clinic.last_payment_date else None

        users_count = CustomUser.objects.filter(clinic_id=clinic_id, is_active=True).count()
        branches_count = Branch.objects.filter(clinic_id=clinic_id, is_active=True).count()

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
