from rest_framework.routers import DefaultRouter

from apps.registration.views import AppointmentViewSet, VisitViewSet

router = DefaultRouter()
router.register("visits", VisitViewSet, basename="visit")
router.register("appointments", AppointmentViewSet, basename="appointment")

urlpatterns = router.urls
