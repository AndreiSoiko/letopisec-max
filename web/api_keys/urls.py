from django.urls import path
from api_keys import views

urlpatterns = [
    path("", views.index, name="api_keys"),
    path("create/", views.create_key, name="create_key"),
    path("clear-session-key/", views.clear_session_key, name="clear_session_key"),
    path("<int:key_id>/revoke/", views.revoke_key, name="revoke_key"),
]
