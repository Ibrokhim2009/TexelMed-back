import random
from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone as dj_timezone
from datetime import timedelta
from core.models import CustomUser

def generate_otp():
    return str(random.randint(100000, 999999))

def send_password_reset_email(user: CustomUser, otp_code: str):
    subject = "Сброс пароля в Texelmed"
    message = f"""
    Здравствуйте, {user.full_name}!

    Вы запросили сброс пароля для аккаунта {user.email}.

    Ваш одноразовый код: {otp_code}

    Код действителен 10 минут.
    Если вы не запрашивали сброс пароля — проигнорируйте это письмо.

    С уважением,
    Команда Texelmed
    """
    send_mail(
        subject=subject,
        message=message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=False,
    )