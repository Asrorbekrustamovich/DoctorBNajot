from django.urls import path

from apps.audit.views import MyActivityView

app_name = "audit"

urlpatterns = [
    path("my/", MyActivityView.as_view(), name="my_activity"),
]
