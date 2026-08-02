from django.urls import path

from apps.patients import views

app_name = "patients"

urlpatterns = [
    path("", views.PatientListView.as_view(), name="list"),
    path("new/", views.PatientCreateView.as_view(), name="create"),
    path("<uuid:pk>/", views.PatientDetailView.as_view(), name="detail"),
    path("<uuid:pk>/edit/", views.PatientUpdateView.as_view(), name="update"),
]
