# ==================== СИГНАЛЫ ====================
from django.db.models.signals import post_save
from django.dispatch import receiver

from core.models import ClinicAdminProfile, ClinicDirectorProfile, CustomUser, DoctorProfile, ReceptionistProfile

@receiver(post_save, sender=CustomUser)
def create_role_profile(sender, instance, created, **kwargs):
    if created and instance.role != CustomUser.Roles.SYSTEM_ADMIN:
        if instance.role == CustomUser.Roles.CLINIC_DIRECTOR:
            ClinicDirectorProfile.objects.get_or_create(user=instance)
        elif instance.role == CustomUser.Roles.CLINIC_ADMIN:
            if instance.branch:
                ClinicAdminProfile.objects.get_or_create(user=instance, branch=instance.branch)
        elif instance.role == CustomUser.Roles.DOCTOR:
            if instance.branch:
                DoctorProfile.objects.get_or_create(user=instance, branch=instance.branch)
        elif instance.role == CustomUser.Roles.RECEPTIONIST:
            if instance.branch:
                ReceptionistProfile.objects.get_or_create(user=instance, branch=instance.branch)