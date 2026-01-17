import jwt
from django.conf import settings
from core.models import CustomUser

def get_user_from_token(request):
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header.split(" ")[1]
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        if payload.get("type") != "access":
            return None
        return CustomUser.objects.select_related('clinic', 'branch').get(
            id=payload["user_id"], is_active=True
        )
    except:
        return None
