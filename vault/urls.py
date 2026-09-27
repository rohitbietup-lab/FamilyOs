from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='vault'),
    path('upload/', views.upload, name='vault-upload'),
    path('people/new/', views.person, name='vault-person'),
    path('<uuid:document_id>/edit/', views.edit, name='vault-edit'),
    path('<uuid:document_id>/archive/', views.archive, name='vault-archive'),
    path('<uuid:document_id>/download/', views.download, name='vault-download'),
    path('<uuid:document_id>/view/', views.download, {'inline': True}, name='vault-view'),
    path('gmail/connect/', views.connect, name='gmail-connect'),
    path('gmail/callback/', views.callback, name='gmail-callback'),
    path('gmail/disconnect/', views.disconnect, name='gmail-disconnect'),
    path('refresh/', views.refresh, name='vault-refresh'),
]
