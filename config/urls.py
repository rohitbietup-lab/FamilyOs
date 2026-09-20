from django.urls import path
from core import views

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
]
