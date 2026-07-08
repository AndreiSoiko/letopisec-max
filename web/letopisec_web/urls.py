from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("billing/", include("billing.urls")),
    path("api-keys/", include("api_keys.urls")),
    path("jobs/", include("jobs.urls")),
    path("", include("dashboard.urls")),
]
