from methodism.main import METHODISM
from v1 import services
from v1.services.auth import authenticate_user



class MainView(METHODISM):
    file = services

    not_auth_methods = ["*"]

    def get_token(self, request):
        user = authenticate_user(request)
        if user:
            return {"user": user} 
        return None 