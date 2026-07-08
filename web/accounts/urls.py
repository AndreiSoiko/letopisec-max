from django.urls import path
from accounts import views

urlpatterns = [
    path("register/", views.register, name="register"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("profile/", views.profile, name="profile"),
    path("change-password/", views.change_password, name="change_password"),
    path("vk/", views.vk_login, name="vk_login"),
    path("vk/callback/", views.vk_callback, name="vk_callback"),
    path("yandex/", views.yandex_login, name="yandex_login"),
    path("yandex/callback/", views.yandex_callback, name="yandex_callback"),
    path("link-max/", views.link_max, name="link_max"),
]
