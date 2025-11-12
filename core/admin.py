from django.contrib import admin

from core.models import Clinic, CustomUser, Plan, Subscription

# Register your models here.
admin.site.register(Subscription)
admin.site.register(CustomUser)
admin.site.register(Plan)
admin.site.register(Clinic)