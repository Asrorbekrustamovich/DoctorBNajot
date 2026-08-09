from django.urls import path

from apps.registration import views

app_name = "registration"

urlpatterns = [
    path("queue/", views.QueueView.as_view(), name="queue"),
    path("visits/new/", views.VisitCreateWebView.as_view(), name="visit_create"),
    path("visits/<uuid:pk>/transition/", views.visit_transition_web, name="visit_transition"),
    path("board/", views.BoardView.as_view(), name="board"),
    path("board/feed/", views.board_feed, name="board_feed"),
    path("board/tts/", views.tts_speak, name="tts_speak"),
    path("board/tts/health/", views.tts_health, name="tts_health"),
]
