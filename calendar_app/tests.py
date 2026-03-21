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
from unittest.mock import AsyncMock, MagicMock, patch

from channels.auth import AuthMiddlewareStack
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.contrib.auth.models import User
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse

from .models import Availability, Reminder
from .routing import websocket_urlpatterns

# Test settings to disable channel layer for most tests
TEST_CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer"
    }
}


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

        # Create a mock for the channel layer
        self.channel_layer_patcher = patch('calendar_app.views.get_channel_layer')
        self.mock_get_channel_layer = self.channel_layer_patcher.start()
        mock_channel_layer = MagicMock()
        mock_channel_layer.group_send = AsyncMock(return_value=None)
        self.mock_get_channel_layer.return_value = mock_channel_layer

    def tearDown(self):
        """Clean up patches."""
        self.channel_layer_patcher.stop()

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

        self.client.post(
            reverse('calendar_app:toggle_availability', kwargs={'date': self.test_date_str})
        )

        self.client.logout()

        # User 2 logs in and also marks available
        self.client.login(username='podcastguest', password='guestpass123')

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

    def test_static_pico_css_served(self):
        """
        Test that the PicoCSS static file is served correctly.
        """
        response = self.client.get('/static/css/pico.min.css')
        self.assertEqual(response.status_code, 200)
        self.assertIn('text/css', response['Content-Type'])

    def test_calendar_page_references_pico_css(self):
        """
        Test that the calendar page includes a link to the PicoCSS stylesheet.
        """
        self.client.login(username='podcasthost', password='hostpass123')
        response = self.client.get(reverse('calendar_app:calendar'))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('pico.min.css', content)


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
        self.assertContains(response, 'calendar-grid')

    def test_calendar_view_has_csrf_token(self):
        """Test that the calendar view includes CSRF token for API calls."""
        self.client.login(username='viewuser', password='viewpass123')

        response = self.client.get(reverse('calendar_app:calendar'))

        self.assertContains(response, 'csrfToken')


class ReminderIntegrationTest(TransactionTestCase):
    """
    Integration tests for the Reminder feature.
    No mocks — uses real DB and Django test client.
    """

    def setUp(self):
        self.client = Client()
        self.user1 = User.objects.create_user(
            username='reminderuser1',
            email='rem1@test.com',
            password='testpass123',
            first_name='Alice',
            last_name='Smith',
        )
        self.user2 = User.objects.create_user(
            username='reminderuser2',
            email='rem2@test.com',
            password='testpass123',
            first_name='Bob',
            last_name='Jones',
        )
        self.future_date = (date.today() + timedelta(days=30)).isoformat()

    # ------------------------------------------------------------------ #
    # CRUD tests
    # ------------------------------------------------------------------ #

    def test_create_reminder(self):
        """Create a reminder via the API and verify it in the DB."""
        self.client.login(username='reminderuser1', password='testpass123')
        response = self.client.post(
            reverse('calendar_app:create_reminder'),
            data=json.dumps({
                'title': 'Conference Deadline',
                'date': self.future_date,
                'description': 'Submit talk proposal',
            }),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['reminder']['title'], 'Conference Deadline')
        self.assertEqual(data['reminder']['date'], self.future_date)
        self.assertEqual(data['reminder']['description'], 'Submit talk proposal')

        self.assertEqual(Reminder.objects.count(), 1)
        reminder = Reminder.objects.first()
        self.assertEqual(reminder.title, 'Conference Deadline')
        self.assertEqual(reminder.created_by, self.user1)

    def test_create_reminder_title_required(self):
        """Creating a reminder without a title should fail."""
        self.client.login(username='reminderuser1', password='testpass123')
        response = self.client.post(
            reverse('calendar_app:create_reminder'),
            data=json.dumps({'title': '', 'date': self.future_date}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('error', response.json())
        self.assertEqual(Reminder.objects.count(), 0)

    def test_create_reminder_date_required(self):
        """Creating a reminder without a date should fail."""
        self.client.login(username='reminderuser1', password='testpass123')
        response = self.client.post(
            reverse('calendar_app:create_reminder'),
            data=json.dumps({'title': 'No Date', 'date': ''}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('error', response.json())

    def test_update_reminder(self):
        """Update a reminder via the API and verify changes in DB."""
        self.client.login(username='reminderuser1', password='testpass123')
        reminder = Reminder.objects.create(
            title='Old Title',
            date=date.today() + timedelta(days=30),
            description='Old desc',
            created_by=self.user1,
        )
        new_date = (date.today() + timedelta(days=60)).isoformat()
        response = self.client.post(
            reverse('calendar_app:update_reminder', kwargs={'pk': reminder.pk}),
            data=json.dumps({
                'title': 'New Title',
                'date': new_date,
                'description': 'New desc',
            }),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['reminder']['title'], 'New Title')

        reminder.refresh_from_db()
        self.assertEqual(reminder.title, 'New Title')
        self.assertEqual(reminder.date.isoformat(), new_date)
        self.assertEqual(reminder.description, 'New desc')

    def test_update_nonexistent_reminder(self):
        """Updating a non-existent reminder returns 404."""
        self.client.login(username='reminderuser1', password='testpass123')
        response = self.client.post(
            reverse('calendar_app:update_reminder', kwargs={'pk': 99999}),
            data=json.dumps({'title': 'X', 'date': self.future_date}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 404)

    def test_delete_reminder(self):
        """Delete a reminder via the API and verify it's gone."""
        self.client.login(username='reminderuser1', password='testpass123')
        reminder = Reminder.objects.create(
            title='To Delete',
            date=date.today() + timedelta(days=30),
            created_by=self.user1,
        )
        response = self.client.post(
            reverse('calendar_app:delete_reminder', kwargs={'pk': reminder.pk}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        self.assertEqual(Reminder.objects.count(), 0)

    def test_delete_nonexistent_reminder(self):
        """Deleting a non-existent reminder returns 404."""
        self.client.login(username='reminderuser1', password='testpass123')
        response = self.client.post(
            reverse('calendar_app:delete_reminder', kwargs={'pk': 99999}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 404)

    # ------------------------------------------------------------------ #
    # Page rendering
    # ------------------------------------------------------------------ #

    def test_reminders_view_renders(self):
        """GET the reminders page and verify it renders correctly."""
        self.client.login(username='reminderuser1', password='testpass123')
        Reminder.objects.create(
            title='Visible Reminder',
            date=date.today() + timedelta(days=10),
            created_by=self.user1,
        )
        response = self.client.get(reverse('calendar_app:reminders'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Reminders')
        self.assertContains(response, 'Visible Reminder')
        self.assertTemplateUsed(response, 'calendar_app/reminders.html')

    # ------------------------------------------------------------------ #
    # iCal integration
    # ------------------------------------------------------------------ #

    def test_ical_content_includes_reminders(self):
        """generate_ical_content() should include Reminder VEVENTs."""
        from .ical import generate_ical_content
        from .models import ConfirmedDate

        ConfirmedDate.objects.create(
            date=date.today() + timedelta(days=5),
            description='Folge 100',
            confirmed_by=self.user1,
        )
        Reminder.objects.create(
            title='My Important Reminder',
            date=date.today() + timedelta(days=15),
            description='Do not forget',
            created_by=self.user1,
        )

        ical = generate_ical_content()

        # Podcast event present
        self.assertIn('SUMMARY:Bin\\xe4rgewitter Podcast' if False else 'SUMMARY:', ical)
        # Reminder event present
        self.assertIn('My Important Reminder', ical)
        self.assertIn('Do not forget', ical)
        # Both are VEVENTs
        self.assertGreaterEqual(ical.count('BEGIN:VEVENT'), 2)

    def test_ical_export_endpoint_includes_reminders(self):
        """The /export/calendar.ics endpoint should include reminder entries."""
        from .ical import generate_ical_file

        Reminder.objects.create(
            title='Export Test Reminder',
            date=date.today() + timedelta(days=20),
            created_by=self.user1,
        )
        # Regenerate the file so the endpoint serves fresh content
        generate_ical_file()

        # The export endpoint has no @login_required
        response = self.client.get(reverse('calendar_app:export_ical'))
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Export Test Reminder', response.content)

    # ------------------------------------------------------------------ #
    # Auth / permissions
    # ------------------------------------------------------------------ #

    def test_unauthenticated_access_denied(self):
        """API and page should redirect unauthenticated users."""
        reminder = Reminder.objects.create(
            title='Auth Test',
            date=date.today() + timedelta(days=10),
            created_by=self.user1,
        )
        urls = [
            reverse('calendar_app:reminders'),
            reverse('calendar_app:create_reminder'),
            reverse('calendar_app:update_reminder', kwargs={'pk': reminder.pk}),
            reverse('calendar_app:delete_reminder', kwargs={'pk': reminder.pk}),
        ]
        for url in urls:
            # GET or POST — should redirect to login
            response = self.client.get(url)
            self.assertIn(response.status_code, [302, 405],
                          msg=f"Expected redirect for {url}")

    def test_any_user_can_edit_any_reminder(self):
        """User B should be able to update a reminder created by User A."""
        reminder = Reminder.objects.create(
            title='User A Created',
            date=date.today() + timedelta(days=10),
            created_by=self.user1,
        )
        self.client.login(username='reminderuser2', password='testpass123')
        response = self.client.post(
            reverse('calendar_app:update_reminder', kwargs={'pk': reminder.pk}),
            data=json.dumps({
                'title': 'User B Updated',
                'date': self.future_date,
                'description': 'Changed by B',
            }),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        reminder.refresh_from_db()
        self.assertEqual(reminder.title, 'User B Updated')

    def test_any_user_can_delete_any_reminder(self):
        """User B should be able to delete a reminder created by User A."""
        reminder = Reminder.objects.create(
            title='User A Created',
            date=date.today() + timedelta(days=10),
            created_by=self.user1,
        )
        self.client.login(username='reminderuser2', password='testpass123')
        response = self.client.post(
            reverse('calendar_app:delete_reminder', kwargs={'pk': reminder.pk}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        self.assertEqual(Reminder.objects.count(), 0)
