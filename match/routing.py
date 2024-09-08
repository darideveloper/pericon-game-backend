# chat/routing.py
from django.urls import re_path

from . import consumers

websocket_urlpatterns = [
    re_path(r"ws/pericon/match/(?P<room_name>\w+)/$", consumers.MatchConsumer.as_asgi()),
    re_path(r"ws/pericon/matchmaker/?$", consumers.MatchMatchmakerConsumer.as_asgi()),
]