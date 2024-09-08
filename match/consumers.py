import random
import string
from collections import deque
from channels.generic.websocket import AsyncWebsocketConsumer
import json

# A global set to track active room names
active_rooms = set()
waiting_queue = deque()


class MatchMatchmakerConsumer(AsyncWebsocketConsumer):
    
    async def connect(self):
        # Add user to the waiting queue
        waiting_queue.append(self.channel_name)

        # Send a message to the user that they are in the queue
        await self.accept()

        # Check if there are enough users in the queue to start a match
        if len(waiting_queue) >= 2:
            # Get the first two users from the queue
            user1 = waiting_queue.popleft()
            user2 = waiting_queue.popleft()

            # Create a unique room name for the match
            characters = string.ascii_lowercase
            while True:
                room_name = ''.join(random.choice(characters) for _ in range(6))
                if room_name not in active_rooms:
                    active_rooms.add(room_name)
                    break

            # Create a new room group
            await self.channel_layer.group_add(room_name, user1)
            await self.channel_layer.group_add(room_name, user2)

            # Send a message to the users that the match has started
            await self.channel_layer.group_send(
                room_name, {"type": "match.start", "room_name": room_name}
            )

    async def disconnect(self, close_code):
        # Remove user from the waiting queue
        if self.channel_name in waiting_queue:
            waiting_queue.remove(self.channel_name)

    # Receive message from room group
    async def match_start(self, event):
        room_name = event["room_name"]

        # Send message to WebSocket
        await self.send(text_data=json.dumps({"room_name": room_name}))
    
    # Delete active room when match ends
    async def match_end(self, event):
        room_name = event["room_name"]
        active_rooms.remove(room_name)


class MatchConsumer(AsyncWebsocketConsumer):
    
    async def connect(self):
        self.room_name = self.scope["url_route"]["kwargs"]["room_name"]
        self.room_group_name = f"chat_{self.room_name}"

        # Join room group
        await self.channel_layer.group_add(self.room_group_name, self.channel_name)

        await self.accept()

    async def disconnect(self, close_code):
        # Leave room group
        await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    # Receive message from WebSocket
    async def receive(self, text_data):
        text_data_json = json.loads(text_data)
        message = text_data_json["message"]

        # Send message to room group
        await self.channel_layer.group_send(
            self.room_group_name, {"type": "chat.message", "message": message}
        )

    # Receive message from room group
    async def chat_message(self, event):
        message = event["message"]

        # Send message to WebSocket
        await self.send(text_data=json.dumps({"message": message}))