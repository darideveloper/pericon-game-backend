import json
import random
import string
from collections import deque
from channels.generic.websocket import AsyncWebsocketConsumer
from django.core.cache import cache

# A global set to track active room names
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
        

class MatchConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        self.room_name = self.scope["url_route"]["kwargs"]["room_name"]
        self.room_group_name = f"room_{self.room_name}"

        # Join room group
        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()
        
        # Initialize username
        self.username = None
        
        # Setup cards
        cards_types = ["clubs", "cups", "gold", "swords"]
        cards_values = ["1", "2", "3", "4", "5", "6", "7", "10", "11", "12"]
        self.cards = []
        for card_type in cards_types:
            for card_value in cards_values:
                self.cards.append(f"{card_value} {card_type}")
                
        # Initialize room data
        if not cache.get(self.room_group_name):
            cache.set(self.room_group_name, {
                "players": {},
                "middle_card": None
            })

    async def disconnect(self, close_code):
        # Leave room group
        await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    # Receive message from WebSocket
    async def receive(self, text_data):
        
        json_data = json.loads(text_data)
        message_type = json_data["type"]
        message_value = json_data["value"]
        
        # Get username and send cards
        if message_type == "username":
            self.username = message_value
            
            # Update player info in cache
            room_data = cache.get(self.room_group_name)
            room_data["players"][self.username] = {"wins": 0}
            cache.set(self.room_group_name, room_data)
                       
            # Get 3 random cards
            random_cards = random.sample(self.cards, 3)
            
            # Send cards only to current user
            await self.send(text_data=json.dumps({
                "type": "round cards",
                "value": random_cards
            }))
            
            # Set a random card as the table if both players are ready
            if len(room_data["players"]) == 2:
                random_card = random.choice(self.cards)
                await self.channel_layer.group_send(
                    self.room_group_name, {
                        "type": "cards.send_middile_card",
                        "value": random_card
                    }
                )
        
    # Receive cards from room group
    async def cards_send_middile_card(self, event):
        card = event["value"]
        
        # Send card to WebSocket
        await self.send(text_data=json.dumps({
            "type": "middle card",
            "value": card
        }))