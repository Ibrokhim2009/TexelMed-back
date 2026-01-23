# core/models.py — ПОЛНЫЙ, ГОТОВЫЙ К ПРОДАКШЕНУ (TEXELMED 2026)

from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from phonenumber_field.modelfields import PhoneNumberField
import uuid


# === 1. ПОЛЬЗОВАТЕЛЬ ===
class CustomUserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("Email обязателен")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user
    

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('role', CustomUser.Roles.SYSTEM_ADMIN)
        return self.create_user(email, password, **extra_fields)


class CustomUser(AbstractBaseUser, PermissionsMixin):
    class Roles(models.TextChoices):
        SYSTEM_ADMIN     = 'system_admin',     _('Системный администратор')
        PENDING_DIRECTOR = 'pending_director', _('Ожидает активации')
        CLINIC_DIRECTOR  = 'clinic_director',  _('Директор клиники')
        CLINIC_ADMIN     = 'clinic_admin',     _('Администратор филиала')
        DOCTOR           = 'doctor',           _('Врач')
        RECEPTIONIST     = 'receptionist',     _('Регистратор')
        PATIENT          = 'patient',          _('Пациент')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True, db_index=True)
    phone = PhoneNumberField(blank=True, null=True, db_index=True)
    full_name = models.CharField(max_length=255)
    photo = models.ImageField(upload_to='users/photos/', blank=True, null=True)

    role = models.CharField(max_length=20, choices=Roles.choices, db_index=True, default=Roles.PENDING_DIRECTOR)

    clinic = models.ForeignKey('Clinic', on_delete=models.SET_NULL, null=True, blank=True, related_name='users')
    branch = models.ForeignKey('Branch', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)

    objects = CustomUserManager()
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['full_name']

    def __str__(self):
        return f"{self.full_name} • {self.get_role_display()}"

    @property
    def profile(self):
        mapping = {
            self.Roles.CLINIC_DIRECTOR: 'director_profiles',
            self.Roles.CLINIC_ADMIN: 'admin_profile',
            self.Roles.DOCTOR: 'doctor_profile',
            self.Roles.RECEPTIONIST: 'receptionist_profile',
            self.Roles.PATIENT: 'patient_profiles',
        }
        rel_name = mapping.get(self.role)
        if not rel_name:
            return None
            
        profile = getattr(self, rel_name, None)
        
        # Если это директор, то 'director_profiles' вернет RelatedManager
        if self.role in [self.Roles.CLINIC_DIRECTOR, self.Roles.PATIENT] and profile:
            return profile.first()
            
        return profile


# === 13. СБРОС ПАРОЛЯ (OTP) ===
class PasswordResetOTP(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='password_reset_otps')
    code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    used = models.BooleanField(default=False)
    expires_at = models.DateTimeField()

    class Meta:
        indexes = [
            models.Index(fields=['user', 'created_at']),
            models.Index(fields=['code']),
        ]
        ordering = ['-created_at']

    def __str__(self):
        return f"OTP {self.code} для {self.user.email} ({'использован' if self.used else 'активен'})"

    def is_valid(self):
        return not self.used and timezone.now() <= self.expires_at
# === 2. ПРОФИЛИ ===
class ClinicDirectorProfile(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='director_profiles')
    clinic = models.OneToOneField('Clinic', on_delete=models.CASCADE, related_name='director_profile_link')

    notify_new_patient = models.BooleanField(default=True)
    notify_payment_overdue = models.BooleanField(default=True)
    notify_subscription_end = models.BooleanField(default=True)

    def __str__(self):
        return f"Директор: {self.user.full_name}"


class ClinicAdminProfile(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='admin_profile')
    branch = models.ForeignKey(
        'Branch',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='admin_profiles'
    )

    can_edit_schedule = models.BooleanField(default=True)
    can_manage_patients = models.BooleanField(default=True)
    can_handle_payments = models.BooleanField(default=True)
    can_send_notifications = models.BooleanField(default=True)

    def __str__(self):
        return f"Админ филиала: {self.user.full_name} ({self.branch.name if self.branch else 'не назначен'})"


class DoctorProfile(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='doctor_profile')
    branch = models.ForeignKey('Branch', on_delete=models.SET_NULL, null=True, related_name='doctor_profiles')

    specialization = models.CharField(max_length=200)
    cabinet = models.CharField(max_length=50, blank=True)
    experience_years = models.PositiveSmallIntegerField(null=True, blank=True)
    education = models.TextField(blank=True)
    work_history = models.TextField(blank=True)
    biography = models.TextField(blank=True)
    certificates = models.JSONField(default=list, blank=True)
    rating = models.DecimalField(max_digits=3, decimal_places=2, default=0.0)
    color = models.CharField(max_length=7, default="#3B82F6")

    schedule = models.JSONField(default=dict)
    default_duration = models.PositiveSmallIntegerField(default=30)
    break_time = models.JSONField(default=dict, blank=True)

    allow_online_booking = models.BooleanField(default=True)
    is_on_vacation = models.BooleanField(default=False)
    vacation_until = models.DateField(null=True, blank=True)

    def __str__(self):
        return f"Врач {self.user.full_name} • {self.specialization}"


class ReceptionistProfile(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='receptionist_profile')
    branch = models.ForeignKey('Branch', on_delete=models.CASCADE, related_name='receptionist_profiles')

    can_create_appointment = models.BooleanField(default=True)
    can_edit_patient = models.BooleanField(default=True)
    can_take_payment = models.BooleanField(default=True)

    def __str__(self):
        return f"Регистратор: {self.user.full_name}"


# === 3. КЛИНИКА ===
class Clinic(models.Model):
    class Status(models.TextChoices):
        ACTIVE = 'active', 'Активна'
        SUSPENDED = 'suspended', 'Приостановлена'
        BLOCKED = 'blocked', 'Заблокирована'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    legal_name = models.CharField(max_length=500, blank=True)
    inn = models.CharField(max_length=20, blank=True)
    logo = models.ImageField(upload_to='clinics/logos/', blank=True, null=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    def check_limits(self):
        """Проверка лимитов по подписке"""
        sub = getattr(self, 'subscription', None)
        if not sub or not sub.plan:
            return {"ok": False, "error": "Нет активного плана"}

        plan = sub.plan
        users = self.users.filter(is_active=True).count()
        branches = self.branches.filter(is_active=True).count()
        patients = self.patients.count()

        if users > plan.limit_users:
            return {"ok": False, "error": f"Пользователи: {users}/{plan.limit_users}"}
        if branches > plan.limit_branches:
            return {"ok": False, "error": f"Филиалы: {branches}/{plan.limit_branches}"}
        if patients > plan.limit_patients:
            return {"ok": False, "error": f"Пациенты: {patients}/{plan.limit_patients}"}

        return {"ok": True}


class Branch(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    clinic = models.ForeignKey(Clinic, on_delete=models.CASCADE, related_name='branches')
    name = models.CharField(max_length=255)
    address = models.CharField(max_length=500)
    phone = PhoneNumberField()
    email = models.EmailField(blank=True)
    working_hours = models.CharField(max_length=100, blank=True, default="", help_text="Пн-Пт 09:00 - 18:00")
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.clinic.name} • {self.name}"


class Plan(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)
    price_monthly = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default="UZS")

    limit_users = models.PositiveIntegerField(default=10, help_text="Макс. пользователей")
    limit_branches = models.PositiveIntegerField(default=1, help_text="Макс. филиалов")
    limit_clinics = models.PositiveIntegerField(default=1, help_text="Макс. клиник для директора")
    limit_patients = models.PositiveIntegerField(default=5000, help_text="Макс. пациентов")

    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.name} • {self.price_monthly} {self.currency}/мес"


class Subscription(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    clinic = models.OneToOneField(
        Clinic,
        on_delete=models.CASCADE,
        related_name='subscription',
        null=True,
        blank=True
    )
    plan = models.ForeignKey(Plan, on_delete=models.SET_NULL, null=True, blank=True, related_name='subscriptions')
    status = models.CharField(
        max_length=20,
        choices=[
            ('trial', 'Пробный'),
            ('active', 'Активна'),
            ('overdue', 'Просрочена'),
            ('cancelled', 'Отменена'),
        ],
        default='trial'
    )
    period_start = models.DateField(null=True, blank=True)
    period_end = models.DateField(null=True, blank=True)
    auto_renew = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.clinic} • {self.plan}" if self.clinic else "Без клиники"


class Patient(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='patient_profiles')
    clinic = models.ForeignKey(Clinic, on_delete=models.CASCADE, related_name='patients')
    primary_branch = models.ForeignKey(Branch, on_delete=models.SET_NULL, null=True, blank=True)

    full_name = models.CharField(max_length=255, db_index=True)
    phone = PhoneNumberField(db_index=True)
    email = models.EmailField(blank=True)
    birth_date = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=10, choices=[('male', 'Мужской'), ('female', 'Женский')], blank=True)
    address = models.TextField(blank=True)
    card_number = models.CharField(max_length=50, db_index=True, unique=True, null=True, blank=True)

    blood_type = models.CharField(max_length=10, blank=True)
    allergies = models.TextField(blank=True)
    chronic_diseases = models.TextField(blank=True)
    notes = models.TextField(blank=True)

    class Status(models.TextChoices):
        ACTIVE = 'active', 'Активен'
        INACTIVE = 'inactive', 'Неактивен'
        ARCHIVED = 'archived', 'Архив'

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)

    total_visits = models.PositiveIntegerField(default=0)
    total_spent = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    debt = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    last_visit = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.full_name} • {self.phone}"


# === 8. УСЛУГИ ===
class ServiceCategory(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    clinic = models.ForeignKey(Clinic, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    order = models.PositiveSmallIntegerField(default=0)

    def __str__(self):
        return self.name


class Service(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    clinic = models.ForeignKey(Clinic, on_delete=models.CASCADE, related_name='services')
    category = models.ForeignKey(ServiceCategory, on_delete=models.SET_NULL, null=True, related_name='services')
    name = models.CharField(max_length=255)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    discount_percent = models.PositiveSmallIntegerField(default=0, help_text="Скидка на услугу в %")
    duration_minutes = models.PositiveSmallIntegerField(default=30)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.name} • {self.price} UZS"


# === 9. ЗАПИСЬ ===
class Appointment(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Ожидает'
        CONFIRMED = 'confirmed', 'Подтверждён'
        IN_PROGRESS = 'in_progress', 'Идёт'
        COMPLETED = 'completed', 'Завершён'
        CANCELLED = 'cancelled', 'Отменён'
        NO_SHOW = 'no_show', 'Не явился'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    clinic = models.ForeignKey(Clinic, on_delete=models.CASCADE, related_name='appointments')
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE)
    doctor = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='appointments')
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name='appointments')
    service = models.ForeignKey(Service, on_delete=models.SET_NULL, null=True)

    start_time = models.DateTimeField(db_index=True)
    end_time = models.DateTimeField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    notes = models.TextField(blank=True)
    price_paid = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.patient} → {self.doctor} • {self.start_time.strftime('%d.%m %H:%M')}"


# === 10. ОПЛАТА ===
class Payment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    clinic = models.ForeignKey(Clinic, on_delete=models.CASCADE, related_name='payments')
    patient = models.ForeignKey(Patient, on_delete=models.SET_NULL, null=True, blank=True)
    appointment = models.ForeignKey(Appointment, on_delete=models.SET_NULL, null=True, blank=True)

    amount = models.DecimalField(max_digits=12, decimal_places=2)
    method = models.CharField(max_length=50, choices=[
        ('cash', 'Наличные'), ('card', 'Карта'), ('uzcard', 'Uzcard'),
        ('payme', 'Payme'), ('click', 'Click'), ('transfer', 'Перевод'),
    ])
    status = models.CharField(max_length=20, default='success')
    transaction_id = models.CharField(max_length=255, blank=True)
    paid_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.amount} UZS • {self.get_method_display()}"


# === 11. МЕДИЦИНСКАЯ КАРТА ===
class MedicalRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name='medical_records')
    doctor = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True)
    appointment = models.OneToOneField(Appointment, on_delete=models.SET_NULL, null=True, blank=True)

    visit_date = models.DateTimeField(default=timezone.now)
    complaints = models.TextField(blank=True)
    anamnesis = models.TextField(blank=True)
    diagnosis_icd10 = models.CharField(max_length=20, blank=True)
    diagnosis_text = models.TextField(blank=True)
    prescriptions = models.TextField(blank=True)
    recommendations = models.TextField(blank=True)
    next_visit = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Карта {self.patient} • {self.visit_date.strftime('%d.%m.%Y')}"


# === 12. ФАЙЛЫ ПАЦИЕНТА ===
class PatientFile(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    class FileType(models.TextChoices):
        ANALYSIS = 'analysis', 'Анализы'
        XRAY = 'xray', 'Рентген'
        ULTRASOUND = 'ultrasound', 'УЗИ'
        CONSENT = 'consent', 'Согласие'
        RECIPE = 'recipe', 'Рецепт'
        OTHER = 'other', 'Другое'

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name='files')
    medical_record = models.ForeignKey(MedicalRecord, on_delete=models.SET_NULL, null=True, blank=True)
    file = models.FileField(upload_to='patient_files/')
    file_type = models.CharField(max_length=20, choices=FileType.choices, default=FileType.OTHER)
    description = models.CharField(max_length=500, blank=True)
    uploaded_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.get_file_type_display()} • {self.patient}"
# === 13. МАРКЕТИНГ И ПАКЕТЫ ===

class ServicePackage(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    clinic = models.ForeignKey(Clinic, on_delete=models.CASCADE, related_name='service_packages')
    name = models.CharField(max_length=255)
    services = models.ManyToManyField(Service, related_name='packages')
    
    total_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    price = models.DecimalField(max_digits=12, decimal_places=2)
    discount_percent = models.PositiveSmallIntegerField(default=0)
    
    valid_until = models.DateField(null=True, blank=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    sold_count = models.PositiveIntegerField(default=0)

    def __str__(self):
        return self.name


class DiscountCategory(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    clinic = models.ForeignKey(Clinic, on_delete=models.CASCADE, related_name='discount_categories')
    name = models.CharField(max_length=100)
    percent = models.PositiveSmallIntegerField()
    description = models.CharField(max_length=500, blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.name} - {self.percent}%"


class Promotion(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    clinic = models.ForeignKey(Clinic, on_delete=models.CASCADE, related_name='promotions')
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    
    start_date = models.DateField()
    end_date = models.DateField()
    
    discount_percent = models.PositiveSmallIntegerField()
    service_categories = models.ManyToManyField(ServiceCategory, blank=True)
    
    is_active = models.BooleanField(default=True)
    usage_count = models.PositiveIntegerField(default=0)

    def __str__(self):
        return self.name
