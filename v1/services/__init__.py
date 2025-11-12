from .auth import register, login, choose_plan_and_activate, refresh_token
from .director import get_my_status, create_clinic, clinic_list, clinic_detail, clinic_update, clinic_delete
from .sysadmin import sys_create_director
from methodism import custom_response
methods = dir()

def method_names(request, params) :
    natija = [x. replace("_", '.') for x in methods if "__" not in x and x != "custom_response"]
    return custom_response(True, data=natija)
