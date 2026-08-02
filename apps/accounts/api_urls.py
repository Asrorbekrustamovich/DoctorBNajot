from rest_framework.routers import DefaultRouter

from apps.accounts.views import RoleViewSet, UserViewSet

router = DefaultRouter()
router.register("users", UserViewSet, basename="user")
router.register("roles", RoleViewSet, basename="role")

urlpatterns = router.urls
