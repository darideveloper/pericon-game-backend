import json
import random
import string

from collections import deque
from time import sleep

from django.core.cache import cache
from django.conf import settings
from channels.generic.websocket import AsyncWebsocketConsumer

# A global set to track active room names
waiting_queue = deque()


class MatchMatchmakerConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        # Add user to the waiting queue
        waiting_queue.append(self.channel_name)
        print(f"User {self.channel_name} added to the queue")

        # Send a message to the user that they are in the queue
        await self.accept()

        # Check if there are enough users in the queue to start a match
        if len(waiting_queue) >= 2:
            # Get the first two users from the queue
            user1 = waiting_queue.popleft()
            user2 = waiting_queue.popleft()

            # Get active rooms from django cache
            active_rooms = cache.get("active_rooms", set())

            # Create a unique room name for the match
            characters = string.ascii_lowercase
            while True:
                room_name = ''.join(random.choice(characters)
                                    for _ in range(6))
                if room_name not in active_rooms:
                    active_rooms.add(room_name)
                    break

            # Create a new room group
            await self.channel_layer.group_add(room_name, user1)
            await self.channel_layer.group_add(room_name, user2)

            # Send a message to the users that the match has started
            await self.channel_layer.group_send(
                room_name, {"type": "send.match_start", "room_name": room_name}
            )

    async def disconnect(self, close_code):
        # Remove user from the waiting queue
        if self.channel_name in waiting_queue:
            waiting_queue.remove(self.channel_name)

    # Receive message from room group
    async def send_match_start(self, event):
        room_name = event["room_name"]

        # Send message to WebSocket
        await self.send(text_data=json.dumps({"room_name": room_name}))


class MatchConsumer(AsyncWebsocketConsumer):
    
    def __get_round_winner__(self, round_cards, middle_card):
        # Calculate winner

        player_1_username = round_cards[0]["player"]
        player_2_username = round_cards[1]["player"]
        player_1_card = round_cards[0]["card"]
        player_2_card = round_cards[1]["card"]
                
        player_1_card_num = int(player_1_card.split(" ")[0])
        player_2_card_num = int(player_2_card.split(" ")[0])
        # middle_card_num = int(middle_card.split(" ")[0])

        # Determine the winner based on the highest card number
        if (player_1_card_num > player_2_card_num):
            winner = player_1_username  # Player 1 wins if their card is highest
        elif (player_2_card_num > player_1_card_num):
            winner = player_2_username  # Player 2 wins if their card is highest
        else:
            winner = "draw"  # No clear winner if neither player has the highest card

        return winner
    
    async def __send_round_new_cards__(self):
        """ Send random cards and middile card to each user and start round """
        
        # Validate if the user already have cards
        room_data = cache.get(self.room_group_name)
        random_cards = room_data["players"][self.username]["cards"]
        if not random_cards:
                
            # Get 3 random cards
            random_cards = random.sample(self.cards, 3)
        
            # Save card in cache
            room_data["players"][self.username]["cards"] = random_cards
            cache.set(self.room_group_name, room_data)

        # Send cards only to current user
        await self.send(text_data=json.dumps({
            "type": "round cards",
            "value": random_cards
        }))
        
    async def __create_middle_card__(self):
        """ Create middile card and save in cache """
        
        room_data = cache.get(self.room_group_name)
        
        # Set a random card as the table if both players are ready
        if len(room_data["players"]) == 2:
            
            # Reset old round data
            room_data["middle_card"] = ""
            for player in room_data["players"]:
                room_data["players"][player]["current_card"] = ""
                room_data["players"][player]["ready"] = False
                
            # Get a random cards
            random_card = random.choice(self.cards)
            
            # Save middle card in cache
            room_data["middle_card"] = random_card
            cache.set(self.room_group_name, room_data)
            
    async def __send_middile_card__(self, create_new=False):
        """ Submit a new message with the current middle card
        (optional: create a new middle card) """
        
        if create_new:
            await self.__create_middle_card__()
        
        room_data = cache.get(self.room_group_name)
        middle_card = room_data["middle_card"]
        
        # Send middle card to both players
        await self.channel_layer.group_send(
            self.room_group_name, {
                "type": "send.middile_card",
                "value": middle_card
            }
        )

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
                "middle_card": "",
            })

        # TODO: DEBUG: Disconnect if the room is full
        room_data = cache.get(self.room_group_name)
        if len(room_data["players"]) > 2:
            await self.disconnect()
            return

    async def disconnect(self, close_code):
        # Leave room group
        await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    async def receive(self, text_data):
        
        json_data = json.loads(text_data)
        print(json_data)
        message_type = json_data["type"]
        message_value = json_data["value"]

        # Get username and send cards
        if message_type == "username":
            self.username = message_value
            
            # Skip if user already exists
            room_data = cache.get(self.room_group_name)
            if self.username not in room_data["players"]:
                if len(room_data["players"]) < 2:
                            
                    # Update player info in cache
                    room_data = cache.get(self.room_group_name)
                    room_data["players"][self.username] = {
                        "wins": 0,
                        "current_card": "",
                        "ready": False,
                        "cards": []
                    }
                    
                    cache.set(self.room_group_name, room_data)
                    
                    # new middle card
                    await self.__create_middle_card__()
                    
                else:

                    # TODO: DEBUG: Disconnect if the room is full
                    # Send full room message
                    await self.send(text_data=json.dumps({
                        "type": "error",
                        "value": "La sala está llena"
                    }))

                    await self.disconnect(1000)
                    return
            
            print(room_data)

            # Send random cards to user
            await self.__send_round_new_cards__()
            
            # Send current middle card
            await self.__send_middile_card__()
            
            # Send usernames
            usernames = list(room_data["players"].keys())
            await self.channel_layer.group_send(
                self.room_group_name, {
                    "type": "send_usernames",
                    "value": usernames
                }
            )
            
        if message_type == "use card":
            # Update player info in cache
            room_data = cache.get(self.room_group_name)
            middle_card = room_data["middle_card"]
            print(room_data)
            room_data["players"][self.username]["current_card"] = message_value
            cache.set(self.room_group_name, room_data)
            
            # Check if both players have used a card
            if all(player["current_card"] for player in room_data["players"].values()):

                # Get cards from each player
                round_cards = []
                for player, player_data in room_data["players"].items():
                    player_card = player_data["current_card"]
                    round_cards.append({
                        "player": player,
                        "card": player_card
                    })

                # Send cards to both players
                await self.channel_layer.group_send(
                    self.room_group_name, {
                        "type": "send.round_played_cards",
                        "value": round_cards
                    }
                )

                # Calculate winner only if both players have played a card
                if not round_cards[0]["card"] or not round_cards[1]["card"]:
                    return
                    
                round_winner = self.__get_round_winner__(round_cards, middle_card)
                
                # Submit round winner
                await self.channel_layer.group_send(
                    self.room_group_name, {
                        "type": "send.round_winner",
                        "value": round_winner
                    }
                )
                
                # Save wins in cache
                if round_winner != "draw":
                    room_data["players"][round_winner]["wins"] += 1
                    cache.set(self.room_group_name, room_data)
                    
                    # Submit points
                    points = []
                    for player, player_data in room_data["players"].items():
                        points.append({
                            "player": player,
                            "points": player_data["wins"]
                        })
                    await self.channel_layer.group_send(
                        self.room_group_name, {
                            "type": "send.points",
                            "value": points
                        }
                    )
                    
                    # Validate if any player match the max points
                    if room_data["players"][round_winner]["wins"] >= settings.MAX_POINTS:
                        # Send winner message
                        await self.channel_layer.group_send(
                            self.room_group_name, {
                                "type": "send.game_winner",
                                "value": round_winner
                            }
                        )
                        
                        # Disconnect players
                        await self.disconnect(1000)
                        return
        
        if message_type == "next round":
            
            # Update user status to ready
            room_data = cache.get(self.room_group_name)
            room_data["players"][self.username]["ready"] = True
            cache.set(self.room_group_name, room_data)
            
            # update middle card (validate if both players are ready 3 times)
            for _ in range(3):
                room_data = cache.get(self.room_group_name)
                
                # Check if both players are ready
                if all(player["ready"] for player in room_data["players"].values()):
                    await self.__send_middile_card__(create_new=True)
                    break
                    
                sleep(0.5)
        
        if message_type == "more cards":
                        
            # Update user status to ready
            room_data = cache.get(self.room_group_name)
            room_data["players"][self.username]["ready"] = True
            cache.set(self.room_group_name, room_data)
            await self.__send_round_new_cards__()
            
            # Check if both players are ready
            if all(player["ready"] for player in room_data["players"].values()):
                await self.__start_round__()
            
    async def send_middile_card(self, event):
        card = event["value"]

        # Send card to WebSocket
        await self.send(text_data=json.dumps({
            "type": "middle card",
            "value": card
        }))

    async def send_round_played_cards(self, event):
        cards = event["value"]

        # Send cards to WebSocket
        await self.send(text_data=json.dumps({
            "type": "round played cards",
            "value": cards
        }))
        
    async def send_round_winner(self, event):
        winner = event["value"]

        # Send winner to WebSocket
        await self.send(text_data=json.dumps({
            "type": "round winner",
            "value": winner
        }))
        
    async def send_points(self, event):
        points = event["value"]

        # Send points to WebSocket
        await self.send(text_data=json.dumps({
            "type": "points",
            "value": points
        }))

    async def send_game_winner(self, event):
        winner = event["value"]

        # Send winner to WebSocket
        await self.send(text_data=json.dumps({
            "type": "game winner",
            "value": winner
        }))
        
    async def send_usernames(self, event):
        usernames = event["value"]

        # Send usernames to WebSocket
        await self.send(text_data=json.dumps({
            "type": "usernames",
            "value": usernames
        }))