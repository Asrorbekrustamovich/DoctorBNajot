"""Root URL configuration."""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("apps.core.urls", namespace="core")),
    path("accounts/", include("apps.accounts.urls", namespace="accounts")),
    path("staff/", include("apps.accounts.staff_urls", namespace="staff")),
    path("patients/", include("apps.patients.urls", namespace="patients")),
    path("registration/", include("apps.registration.urls", namespace="registration")),
    path("clinical/", include("apps.clinical.urls")),
    path("pharmacy/", include("apps.pharmacy.urls")),
    path("billing/", include("apps.billing.urls")),
    path("audit/", include("apps.audit.urls", namespace="audit")),
    path("api/v1/accounts/", include("apps.accounts.api_urls")),
    path("api/v1/", include("apps.patients.api_urls")),
    path("api/v1/", include("apps.registration.api_urls")),
    path("api-auth/", include("rest_framework.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

admin.site.site_header = "Doctor B Najot boshqaruvi"
admin.site.site_title = "Doctor B Najot"
admin.site.index_title = "Administratsiya"
