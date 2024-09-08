from django.urls import path

from . import views


urlpatterns = [
    path("", views.index, name="index"),
    path("match/<str:room_name>/", views.room, name="room"),
    path('matchmaking/', views.matchmaking, name='matchmaking'),
]