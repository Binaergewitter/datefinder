import json
from channels.generic.websocket import AsyncWebsocketConsumer


class CalendarConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for real-time calendar updates.
    """
    
    async def connect(self):
        """
        Called when a WebSocket connection is opened.
        """
        # Only allow authenticated users
        if self.scope["user"].is_anonymous:
            await self.close()
            return
        
        self.room_group_name = "calendar_updates"
        
        # Join the calendar updates group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        
        await self.accept()
    
    async def disconnect(self, close_code):
        """
        Called when a WebSocket connection is closed.
        """
        # Leave the calendar updates group
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )
    
    async def receive(self, text_data):
        """
        Called when a message is received from the WebSocket.
        We don't expect to receive messages from clients in this implementation,
        but this method is required.
        """
        pass
    
    async def availability_update(self, event):
        """
        Called when an availability update is broadcast to the group.
        Sends the update to the WebSocket.
        """
        await self.send(text_data=json.dumps({
            'type': 'availability_update',
            'date': event['date'],
            'availability': event['availability'],
            'has_star': event['has_star'],
        }))

    async def confirmation_update(self, event):
        """
        Called when a confirmation update is broadcast to the group.
        Sends the update to the WebSocket.
        """
        await self.send(text_data=json.dumps({
            'type': 'confirmation_update',
            'date': event['date'],
            'confirmed': event['confirmed'],
            'description': event['description'],
            'confirmed_by': event['confirmed_by'],
        }))
