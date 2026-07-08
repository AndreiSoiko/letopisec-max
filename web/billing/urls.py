from django.urls import path
from billing import views

urlpatterns = [
    path("", views.billing_index, name="billing"),
    path("topup/", views.topup, name="topup"),
    path("tinkoff-notify/", views.tinkoff_notify, name="tinkoff_notify"),
    path("success/", views.payment_success, name="payment_success"),
    path("fail/", views.payment_fail, name="payment_fail"),
]
