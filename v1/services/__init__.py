from .auth import register, login, choose_plan_and_activate, refresh_token
from .director import get_my_status, create_clinic, clinic_list, clinic_detail, clinic_update, clinic_delete
from .sysadmin import (
    sys_create_director,
    list_plans,
    get_plan,
    delete_plan,
    create_plan,
    update_plan,
    list_clinic_subscriptions,
    list_all_clinics_for_admin,
    list_all_users_for_admin,
    create_user_for_admin,
    list_all_branches_for_admin,
    toggle_branch_status,
    update_branch_for_admin,
    create_branch_for_admin,
    unassign_admin_from_branch,
    assign_admin_to_branch
)
from methodism import custom_response
methods = dir()

def method_names(request, params) :
    natija = [x. replace("_", '.') for x in methods if "__" not in x and x != "custom_response"]
    return custom_response(True, data=natija)
