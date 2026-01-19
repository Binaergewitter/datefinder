"""
Integration tests for the Podcast Date Finder application.

These tests verify the complete flow of:
1. User login
2. Availability changes
3. Visibility of changes across users
4. Real-time updates via WebSocket
"""

import json
from datetime import date, timedelta
from django.test import TestCase, Client, TransactionTestCase
from django.contrib.auth.models import User
from django.urls import reverse
from channels.testing import WebsocketCommunicator
from channels.routing import URLRouter
from channels.auth import AuthMiddlewareStack
from asgiref.sync import sync_to_async
from unittest.mock import patch

from .models import Availability
from .consumers import CalendarConsumer
from .routing import websocket_urlpatterns


class AvailabilityModelTest(TestCase):
    """Tests for the Availability model."""
    
    def setUp(self):
        self.user1 = User.objects.create_user(
            username='testuser1',
            email='user1@test.com',
            password='testpass123'
        )
        self.user2 = User.objects.create_user(
            username='testuser2',
            email='user2@test.com',
            password='testpass123'
        )
        self.future_date = date.today() + timedelta(days=7)
    
    def test_toggle_availability_creates_available(self):
        """First toggle should create an 'available' entry."""
        status = Availability.toggle_availability(self.user1, self.future_date)
        self.assertEqual(status, 'available')
        
        entry = Availability.objects.get(user=self.user1, date=self.future_date)
        self.assertEqual(entry.status, 'available')
    
    def test_toggle_availability_changes_to_tentative(self):
        """Second toggle should change status to 'tentative'."""
        Availability.toggle_availability(self.user1, self.future_date)
        status = Availability.toggle_availability(self.user1, self.future_date)
        
        self.assertEqual(status, 'tentative')
        entry = Availability.objects.get(user=self.user1, date=self.future_date)
        self.assertEqual(entry.status, 'tentative')
    
    def test_toggle_availability_removes_entry(self):
        """Third toggle should remove the entry."""
        Availability.toggle_availability(self.user1, self.future_date)
        Availability.toggle_availability(self.user1, self.future_date)
        status = Availability.toggle_availability(self.user1, self.future_date)
        
        self.assertIsNone(status)
        self.assertFalse(
            Availability.objects.filter(user=self.user1, date=self.future_date).exists()
        )
    
    def test_get_date_availability(self):
        """Test getting all availability for a date."""
        Availability.objects.create(
            user=self.user1, date=self.future_date, status='available'
        )
        Availability.objects.create(
            user=self.user2, date=self.future_date, status='tentative'
        )
        
        availability = Availability.get_date_availability(self.future_date)
        
        self.assertEqual(len(availability), 2)
        usernames = [a['username'] for a in availability]
        self.assertIn('testuser1', usernames)
        self.assertIn('testuser2', usernames)
    
    def test_count_available(self):
        """Test counting available users for a date."""
        Availability.objects.create(
            user=self.user1, date=self.future_date, status='available'
        )
        Availability.objects.create(
            user=self.user2, date=self.future_date, status='tentative'
        )
        
        count = Availability.count_available(self.future_date)
        self.assertEqual(count, 2)


class IntegrationTest(TransactionTestCase):
    """
    Integration tests that verify the complete user flow:
    - Login as user 1
    - Make an availability change
    - Logout
    - Login as user 2
    - Verify the availability change is visible
    """
    
    def setUp(self):
        """Set up test users and client."""
        self.client = Client()
        
        # Create test users
        self.user1 = User.objects.create_user(
            username='podcasthost',
            email='host@podcast.com',
            password='hostpass123',
            first_name='Podcast',
            last_name='Host'
        )
        self.user2 = User.objects.create_user(
            username='podcastguest',
            email='guest@podcast.com',
            password='guestpass123',
            first_name='Podcast',
            last_name='Guest'
        )
        
        # Future date for testing
        self.test_date = date.today() + timedelta(days=5)
        self.test_date_str = self.test_date.isoformat()
    
    def test_full_availability_flow(self):
        """
        Test the complete flow:
        1. User 1 logs in
        2. User 1 marks a date as available
        3. User 1 logs out
        4. User 2 logs in
        5. User 2 sees User 1's availability
        """
        # Step 1: User 1 logs in
        login_success = self.client.login(username='podcasthost', password='hostpass123')
        self.assertTrue(login_success, "User 1 should be able to log in")
        
        # Verify user 1 can access the calendar
        response = self.client.get(reverse('calendar_app:calendar'))
        self.assertEqual(response.status_code, 200)
        
        # Step 2: User 1 marks a date as available
        with patch('calendar_app.views.get_channel_layer') as mock_channel_layer:
            # Mock the channel layer to avoid async issues in tests
            mock_channel_layer.return_value.group_send = lambda *args, **kwargs: None
            
            response = self.client.post(
                reverse('calendar_app:toggle_availability', kwargs={'date': self.test_date_str})
            )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['user_status'], 'available')
        self.assertEqual(data['date'], self.test_date_str)
        
        # Verify the availability was saved
        availability = Availability.objects.get(user=self.user1, date=self.test_date)
        self.assertEqual(availability.status, 'available')
        
        # Step 3: User 1 logs out
        self.client.logout()
        
        # Verify calendar requires login
        response = self.client.get(reverse('calendar_app:calendar'))
        self.assertEqual(response.status_code, 302)  # Redirect to login
        
        # Step 4: User 2 logs in
        login_success = self.client.login(username='podcastguest', password='guestpass123')
        self.assertTrue(login_success, "User 2 should be able to log in")
        
        # Step 5: User 2 sees User 1's availability
        response = self.client.get(reverse('calendar_app:get_all_availability'))
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['current_user_id'], self.user2.id)
        
        # Check that user 1's availability is visible
        self.assertIn(self.test_date_str, data['data'])
        date_data = data['data'][self.test_date_str]
        
        availability_list = date_data['availability']
        self.assertEqual(len(availability_list), 1)
        self.assertEqual(availability_list[0]['user_id'], self.user1.id)
        self.assertEqual(availability_list[0]['username'], 'Podcast Host')
        self.assertEqual(availability_list[0]['status'], 'available')
    
    def test_multiple_users_same_date(self):
        """
        Test that multiple users can mark the same date and see each other.
        """
        # User 1 logs in and marks available
        self.client.login(username='podcasthost', password='hostpass123')
        
        with patch('calendar_app.views.get_channel_layer') as mock_channel_layer:
            mock_channel_layer.return_value.group_send = lambda *args, **kwargs: None
            self.client.post(
                reverse('calendar_app:toggle_availability', kwargs={'date': self.test_date_str})
            )
        
        self.client.logout()
        
        # User 2 logs in and also marks available
        self.client.login(username='podcastguest', password='guestpass123')
        
        with patch('calendar_app.views.get_channel_layer') as mock_channel_layer:
            mock_channel_layer.return_value.group_send = lambda *args, **kwargs: None
            response = self.client.post(
                reverse('calendar_app:toggle_availability', kwargs={'date': self.test_date_str})
            )
        
        data = response.json()
        self.assertTrue(data['success'])
        
        # Both users should now be in the availability list
        availability_list = data['availability']
        self.assertEqual(len(availability_list), 2)
        
        user_ids = [a['user_id'] for a in availability_list]
        self.assertIn(self.user1.id, user_ids)
        self.assertIn(self.user2.id, user_ids)
    
    def test_star_indicator_with_three_users(self):
        """
        Test that the star indicator appears when 3+ users mark a date.
        """
        # Create a third user
        user3 = User.objects.create_user(
            username='podcasteditor',
            email='editor@podcast.com',
            password='editorpass123'
        )
        
        # All three users mark the date as available
        for user in [self.user1, self.user2, user3]:
            Availability.objects.create(
                user=user,
                date=self.test_date,
                status='available'
            )
        
        # Login and check the availability API
        self.client.login(username='podcasthost', password='hostpass123')
        response = self.client.get(reverse('calendar_app:get_all_availability'))
        
        data = response.json()
        date_data = data['data'][self.test_date_str]
        
        # Should have star indicator
        self.assertTrue(date_data['has_star'])
        self.assertEqual(len(date_data['availability']), 3)
    
    def test_toggle_cycle_complete(self):
        """
        Test the complete toggle cycle: available -> tentative -> removed.
        """
        self.client.login(username='podcasthost', password='hostpass123')
        
        with patch('calendar_app.views.get_channel_layer') as mock_channel_layer:
            mock_channel_layer.return_value.group_send = lambda *args, **kwargs: None
            
            # First click: available
            response = self.client.post(
                reverse('calendar_app:toggle_availability', kwargs={'date': self.test_date_str})
            )
            self.assertEqual(response.json()['user_status'], 'available')
            
            # Second click: tentative
            response = self.client.post(
                reverse('calendar_app:toggle_availability', kwargs={'date': self.test_date_str})
            )
            self.assertEqual(response.json()['user_status'], 'tentative')
            
            # Third click: removed
            response = self.client.post(
                reverse('calendar_app:toggle_availability', kwargs={'date': self.test_date_str})
            )
            self.assertIsNone(response.json()['user_status'])
            self.assertEqual(len(response.json()['availability']), 0)
    
    def test_cannot_modify_past_dates(self):
        """
        Test that users cannot modify past dates.
        """
        self.client.login(username='podcasthost', password='hostpass123')
        
        past_date = (date.today() - timedelta(days=1)).isoformat()
        
        response = self.client.post(
            reverse('calendar_app:toggle_availability', kwargs={'date': past_date})
        )
        
        self.assertEqual(response.status_code, 400)
        self.assertIn('error', response.json())
    
    def test_unauthenticated_access_denied(self):
        """
        Test that unauthenticated users cannot access the calendar or API.
        """
        # Calendar view should redirect to login
        response = self.client.get(reverse('calendar_app:calendar'))
        self.assertEqual(response.status_code, 302)
        
        # API endpoints should also require auth
        response = self.client.get(reverse('calendar_app:get_all_availability'))
        self.assertEqual(response.status_code, 302)
        
        response = self.client.post(
            reverse('calendar_app:toggle_availability', kwargs={'date': self.test_date_str})
        )
        self.assertEqual(response.status_code, 302)


class WebSocketTest(TransactionTestCase):
    """
    Tests for WebSocket functionality.
    """
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='wsuser',
            email='ws@test.com',
            password='wspass123'
        )
    
    async def test_websocket_connect_authenticated(self):
        """Test that authenticated users can connect to WebSocket."""
        application = AuthMiddlewareStack(URLRouter(websocket_urlpatterns))
        communicator = WebsocketCommunicator(application, "/ws/calendar/")
        
        # Simulate authenticated user
        communicator.scope['user'] = self.user
        
        connected, _ = await communicator.connect()
        self.assertTrue(connected)
        
        await communicator.disconnect()
    
    async def test_websocket_receives_updates(self):
        """Test that WebSocket receives availability updates."""
        from channels.layers import get_channel_layer
        
        application = AuthMiddlewareStack(URLRouter(websocket_urlpatterns))
        communicator = WebsocketCommunicator(application, "/ws/calendar/")
        communicator.scope['user'] = self.user
        
        connected, _ = await communicator.connect()
        self.assertTrue(connected)
        
        # Send a message through the channel layer
        channel_layer = get_channel_layer()
        await channel_layer.group_send(
            "calendar_updates",
            {
                "type": "availability_update",
                "date": "2026-01-25",
                "availability": [
                    {"user_id": 1, "username": "testuser", "status": "available"}
                ],
                "has_star": False,
            }
        )
        
        # Receive the message
        response = await communicator.receive_json_from()
        
        self.assertEqual(response['type'], 'availability_update')
        self.assertEqual(response['date'], '2026-01-25')
        self.assertEqual(len(response['availability']), 1)
        
        await communicator.disconnect()


class CalendarViewTest(TestCase):
    """Tests for the calendar view template rendering."""
    
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='viewuser',
            email='view@test.com',
            password='viewpass123'
        )
    
    def test_calendar_view_renders(self):
        """Test that the calendar view renders correctly."""
        self.client.login(username='viewuser', password='viewpass123')
        
        response = self.client.get(reverse('calendar_app:calendar'))
        
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Podcast Date Finder')
        self.assertContains(response, 'viewuser')
        self.assertContains(response, 'calendar-grid')
    
    def test_calendar_view_has_csrf_token(self):
        """Test that the calendar view includes CSRF token for API calls."""
        self.client.login(username='viewuser', password='viewpass123')
        
        response = self.client.get(reverse('calendar_app:calendar'))
        
        self.assertContains(response, 'csrfToken')
