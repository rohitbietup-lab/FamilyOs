from django.urls import path
from core import views
from core import central

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('login/', views.sign_in, name='login'),
    path('logout/', views.sign_out, name='logout'),
    path('profile/', views.profile, name='profile'),
    path('family/', views.family_settings, name='family'),
    path('sessions/', views.sessions, name='sessions'),
    path('sessions/<uuid:session_id>/revoke/', views.revoke_session, name='revoke-session'),
    path('sessions/revoke-all/', views.revoke_all, name='revoke-all'),
    path('api/v1/me/', views.api_me),
    path('api/v1/family/', views.api_family),
    path('api/v1/audit/', views.api_audit),
    path('api/v1/invitations/', views.invitations),
    path('finance/', central.finance_list, name='finance-list'),
    path('finance/new/', central.finance_edit, name='finance-new'),
    path('finance/<uuid:record_id>/edit/', central.finance_edit, name='finance-edit'),
    path('finance/<uuid:record_id>/archive/', central.finance_archive, name='finance-archive'),
    path('finance/<uuid:record_id>/restore/', central.finance_archive, {'restore': True}, name='finance-restore'),
    path('goals/', central.goals_list, name='goals-list'),
    path('goals/new/', central.goal_edit, name='goal-new'),
    path('goals/<uuid:record_id>/edit/', central.goal_edit, name='goal-edit'),
    path('goals/<uuid:record_id>/archive/', central.goal_archive, name='goal-archive'),
    path('goals/<uuid:record_id>/restore/', central.goal_archive, {'restore': True}, name='goal-restore'),
    path('api/v1/summary/', central.api_summary),
]
