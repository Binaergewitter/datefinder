"""
Integration tests for the Podcast Date Finder application.

These tests verify the complete flow of:
1. User login
2. Availability changes
3. Visibility of changes across users
4. Real-time updates via WebSocket
"""

import base64
import json
import tempfile
import xml.etree.ElementTree as ElementTree
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from channels.auth import AuthMiddlewareStack
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.contrib.auth.models import User
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from .dav import DAV_NS
from .models import Availability, CalendarKey, Reminder
from .routing import websocket_urlpatterns

# Test settings to disable channel layer for most tests
TEST_CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}


class AvailabilityModelTest(TestCase):
    """Tests for the Availability model."""

    def setUp(self):
        self.user1 = User.objects.create_user(username="testuser1", email="user1@test.com", password="testpass123")
        self.user2 = User.objects.create_user(username="testuser2", email="user2@test.com", password="testpass123")
        self.future_date = date.today() + timedelta(days=7)

    def test_toggle_availability_creates_available(self):
        """First toggle should create an 'available' entry."""
        status = Availability.toggle_availability(self.user1, self.future_date)
        self.assertEqual(status, "available")

        entry = Availability.objects.get(user=self.user1, date=self.future_date)
        self.assertEqual(entry.status, "available")

    def test_toggle_availability_changes_to_tentative(self):
        """Second toggle should change status to 'tentative'."""
        Availability.toggle_availability(self.user1, self.future_date)
        status = Availability.toggle_availability(self.user1, self.future_date)

        self.assertEqual(status, "tentative")
        entry = Availability.objects.get(user=self.user1, date=self.future_date)
        self.assertEqual(entry.status, "tentative")

    def test_toggle_availability_removes_entry(self):
        """Third toggle should remove the entry."""
        Availability.toggle_availability(self.user1, self.future_date)
        Availability.toggle_availability(self.user1, self.future_date)
        status = Availability.toggle_availability(self.user1, self.future_date)

        self.assertIsNone(status)
        self.assertFalse(Availability.objects.filter(user=self.user1, date=self.future_date).exists())

    def test_get_date_availability(self):
        """Test getting all availability for a date."""
        Availability.objects.create(user=self.user1, date=self.future_date, status="available")
        Availability.objects.create(user=self.user2, date=self.future_date, status="tentative")

        availability = Availability.get_date_availability(self.future_date)

        self.assertEqual(len(availability), 2)
        usernames = [a["username"] for a in availability]
        self.assertIn("testuser1", usernames)
        self.assertIn("testuser2", usernames)

    def test_count_available(self):
        """Test counting available users for a date."""
        Availability.objects.create(user=self.user1, date=self.future_date, status="available")
        Availability.objects.create(user=self.user2, date=self.future_date, status="tentative")

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
            username="podcasthost",
            email="host@podcast.com",
            password="hostpass123",
            first_name="Podcast",
            last_name="Host",
        )
        self.user2 = User.objects.create_user(
            username="podcastguest",
            email="guest@podcast.com",
            password="guestpass123",
            first_name="Podcast",
            last_name="Guest",
        )

        # Future date for testing
        self.test_date = date.today() + timedelta(days=5)
        self.test_date_str = self.test_date.isoformat()

        # Create a mock for the channel layer
        self.channel_layer_patcher = patch("calendar_app.views.get_channel_layer")
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
        login_success = self.client.login(username="podcasthost", password="hostpass123")
        self.assertTrue(login_success, "User 1 should be able to log in")

        # Verify user 1 can access the calendar
        response = self.client.get(reverse("calendar_app:calendar"))
        self.assertEqual(response.status_code, 200)

        # Step 2: User 1 marks a date as available
        response = self.client.post(reverse("calendar_app:toggle_availability", kwargs={"date": self.test_date_str}))

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["user_status"], "available")
        self.assertEqual(data["date"], self.test_date_str)

        # Verify the availability was saved
        availability = Availability.objects.get(user=self.user1, date=self.test_date)
        self.assertEqual(availability.status, "available")

        # Step 3: User 1 logs out
        self.client.logout()

        # Verify calendar requires login
        response = self.client.get(reverse("calendar_app:calendar"))
        self.assertEqual(response.status_code, 302)  # Redirect to login

        # Step 4: User 2 logs in
        login_success = self.client.login(username="podcastguest", password="guestpass123")
        self.assertTrue(login_success, "User 2 should be able to log in")

        # Step 5: User 2 sees User 1's availability
        response = self.client.get(reverse("calendar_app:get_all_availability"))
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["current_user_id"], self.user2.id)

        # Check that user 1's availability is visible
        self.assertIn(self.test_date_str, data["data"])
        date_data = data["data"][self.test_date_str]

        availability_list = date_data["availability"]
        self.assertEqual(len(availability_list), 1)
        self.assertEqual(availability_list[0]["user_id"], self.user1.id)
        self.assertEqual(availability_list[0]["username"], "Podcast Host")
        self.assertEqual(availability_list[0]["status"], "available")

    def test_multiple_users_same_date(self):
        """
        Test that multiple users can mark the same date and see each other.
        """
        # User 1 logs in and marks available
        self.client.login(username="podcasthost", password="hostpass123")

        self.client.post(reverse("calendar_app:toggle_availability", kwargs={"date": self.test_date_str}))

        self.client.logout()

        # User 2 logs in and also marks available
        self.client.login(username="podcastguest", password="guestpass123")

        response = self.client.post(reverse("calendar_app:toggle_availability", kwargs={"date": self.test_date_str}))

        data = response.json()
        self.assertTrue(data["success"])

        # Both users should now be in the availability list
        availability_list = data["availability"]
        self.assertEqual(len(availability_list), 2)

        user_ids = [a["user_id"] for a in availability_list]
        self.assertIn(self.user1.id, user_ids)
        self.assertIn(self.user2.id, user_ids)

    def test_star_indicator_with_three_users(self):
        """
        Test that the star indicator appears when 3+ users mark a date.
        """
        # Create a third user
        user3 = User.objects.create_user(username="podcasteditor", email="editor@podcast.com", password="editorpass123")

        # All three users mark the date as available
        for user in [self.user1, self.user2, user3]:
            Availability.objects.create(user=user, date=self.test_date, status="available")

        # Login and check the availability API
        self.client.login(username="podcasthost", password="hostpass123")
        response = self.client.get(reverse("calendar_app:get_all_availability"))

        data = response.json()
        date_data = data["data"][self.test_date_str]

        # Should have star indicator
        self.assertTrue(date_data["has_star"])
        self.assertEqual(len(date_data["availability"]), 3)

    def test_toggle_cycle_complete(self):
        """
        Test the complete toggle cycle: available -> tentative -> removed.
        """
        self.client.login(username="podcasthost", password="hostpass123")

        # First click: available
        response = self.client.post(reverse("calendar_app:toggle_availability", kwargs={"date": self.test_date_str}))
        self.assertEqual(response.json()["user_status"], "available")

        # Second click: tentative
        response = self.client.post(reverse("calendar_app:toggle_availability", kwargs={"date": self.test_date_str}))
        self.assertEqual(response.json()["user_status"], "tentative")

        # Third click: removed
        response = self.client.post(reverse("calendar_app:toggle_availability", kwargs={"date": self.test_date_str}))
        self.assertIsNone(response.json()["user_status"])
        self.assertEqual(len(response.json()["availability"]), 0)

    def test_cannot_modify_past_dates(self):
        """
        Test that users cannot modify past dates.
        """
        self.client.login(username="podcasthost", password="hostpass123")

        past_date = (date.today() - timedelta(days=1)).isoformat()

        response = self.client.post(reverse("calendar_app:toggle_availability", kwargs={"date": past_date}))

        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())

    def test_unauthenticated_access_denied(self):
        """
        Test that unauthenticated users cannot access the calendar or API.
        """
        # Calendar view should redirect to login
        response = self.client.get(reverse("calendar_app:calendar"))
        self.assertEqual(response.status_code, 302)

        # API endpoints should also require auth
        response = self.client.get(reverse("calendar_app:get_all_availability"))
        self.assertEqual(response.status_code, 302)

        response = self.client.post(reverse("calendar_app:toggle_availability", kwargs={"date": self.test_date_str}))
        self.assertEqual(response.status_code, 302)

    def test_static_pico_css_served(self):
        """
        Test that the PicoCSS static file is served correctly.
        """
        response = self.client.get("/static/css/pico.min.css")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/css", response["Content-Type"])

    def test_calendar_page_references_pico_css(self):
        """
        Test that the calendar page includes a link to the PicoCSS stylesheet.
        """
        self.client.login(username="podcasthost", password="hostpass123")
        response = self.client.get(reverse("calendar_app:calendar"))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("pico.min.css", content)


class WebSocketTest(TransactionTestCase):
    """
    Tests for WebSocket functionality.
    """

    def setUp(self):
        self.user = User.objects.create_user(username="wsuser", email="ws@test.com", password="wspass123")

    async def test_websocket_connect_authenticated(self):
        """Test that authenticated users can connect to WebSocket."""
        application = AuthMiddlewareStack(URLRouter(websocket_urlpatterns))
        communicator = WebsocketCommunicator(application, "/ws/calendar/")

        # Simulate authenticated user
        communicator.scope["user"] = self.user

        connected, _ = await communicator.connect()
        self.assertTrue(connected)

        await communicator.disconnect()

    async def test_websocket_receives_updates(self):
        """Test that WebSocket receives availability updates."""
        from channels.layers import get_channel_layer

        application = AuthMiddlewareStack(URLRouter(websocket_urlpatterns))
        communicator = WebsocketCommunicator(application, "/ws/calendar/")
        communicator.scope["user"] = self.user

        connected, _ = await communicator.connect()
        self.assertTrue(connected)

        # Send a message through the channel layer
        channel_layer = get_channel_layer()
        await channel_layer.group_send(
            "calendar_updates",
            {
                "type": "availability_update",
                "date": "2026-01-25",
                "availability": [{"user_id": 1, "username": "testuser", "status": "available"}],
                "has_star": False,
            },
        )

        # Receive the message
        response = await communicator.receive_json_from()

        self.assertEqual(response["type"], "availability_update")
        self.assertEqual(response["date"], "2026-01-25")
        self.assertEqual(len(response["availability"]), 1)

        await communicator.disconnect()


class CalendarViewTest(TestCase):
    """Tests for the calendar view template rendering."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="viewuser", email="view@test.com", password="viewpass123")

    def test_calendar_view_renders(self):
        """Test that the calendar view renders correctly."""
        self.client.login(username="viewuser", password="viewpass123")

        response = self.client.get(reverse("calendar_app:calendar"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Podcast Date Finder")
        self.assertContains(response, "calendar-grid")

    def test_calendar_view_has_csrf_token(self):
        """Test that the calendar view includes CSRF token for API calls."""
        self.client.login(username="viewuser", password="viewpass123")

        response = self.client.get(reverse("calendar_app:calendar"))

        self.assertContains(response, "csrfToken")


class ReminderIntegrationTest(TransactionTestCase):
    """
    Integration tests for the Reminder feature.
    No mocks — uses real DB and Django test client.
    """

    def setUp(self):
        self.client = Client()
        self.user1 = User.objects.create_user(
            username="reminderuser1",
            email="rem1@test.com",
            password="testpass123",
            first_name="Alice",
            last_name="Smith",
        )
        self.user2 = User.objects.create_user(
            username="reminderuser2",
            email="rem2@test.com",
            password="testpass123",
            first_name="Bob",
            last_name="Jones",
        )
        self.future_date = (date.today() + timedelta(days=30)).isoformat()

    # ------------------------------------------------------------------ #
    # CRUD tests
    # ------------------------------------------------------------------ #

    def test_create_reminder(self):
        """Create a reminder via the API and verify it in the DB."""
        self.client.login(username="reminderuser1", password="testpass123")
        response = self.client.post(
            reverse("calendar_app:create_reminder"),
            data=json.dumps(
                {
                    "title": "Conference Deadline",
                    "date": self.future_date,
                    "description": "Submit talk proposal",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["reminder"]["title"], "Conference Deadline")
        self.assertEqual(data["reminder"]["date"], self.future_date)
        self.assertEqual(data["reminder"]["description"], "Submit talk proposal")

        self.assertEqual(Reminder.objects.count(), 1)
        reminder = Reminder.objects.first()
        self.assertEqual(reminder.title, "Conference Deadline")
        self.assertEqual(reminder.created_by, self.user1)

    def test_create_reminder_title_required(self):
        """Creating a reminder without a title should fail."""
        self.client.login(username="reminderuser1", password="testpass123")
        response = self.client.post(
            reverse("calendar_app:create_reminder"),
            data=json.dumps({"title": "", "date": self.future_date}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())
        self.assertEqual(Reminder.objects.count(), 0)

    def test_create_reminder_date_required(self):
        """Creating a reminder without a date should fail."""
        self.client.login(username="reminderuser1", password="testpass123")
        response = self.client.post(
            reverse("calendar_app:create_reminder"),
            data=json.dumps({"title": "No Date", "date": ""}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())

    def test_update_reminder(self):
        """Update a reminder via the API and verify changes in DB."""
        self.client.login(username="reminderuser1", password="testpass123")
        reminder = Reminder.objects.create(
            title="Old Title",
            date=date.today() + timedelta(days=30),
            description="Old desc",
            created_by=self.user1,
        )
        new_date = (date.today() + timedelta(days=60)).isoformat()
        response = self.client.post(
            reverse("calendar_app:update_reminder", kwargs={"pk": reminder.pk}),
            data=json.dumps(
                {
                    "title": "New Title",
                    "date": new_date,
                    "description": "New desc",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["reminder"]["title"], "New Title")

        reminder.refresh_from_db()
        self.assertEqual(reminder.title, "New Title")
        self.assertEqual(reminder.date.isoformat(), new_date)
        self.assertEqual(reminder.description, "New desc")

    def test_update_nonexistent_reminder(self):
        """Updating a non-existent reminder returns 404."""
        self.client.login(username="reminderuser1", password="testpass123")
        response = self.client.post(
            reverse("calendar_app:update_reminder", kwargs={"pk": 99999}),
            data=json.dumps({"title": "X", "date": self.future_date}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)

    def test_delete_reminder(self):
        """Delete a reminder via the API and verify it's gone."""
        self.client.login(username="reminderuser1", password="testpass123")
        reminder = Reminder.objects.create(
            title="To Delete",
            date=date.today() + timedelta(days=30),
            created_by=self.user1,
        )
        response = self.client.post(
            reverse("calendar_app:delete_reminder", kwargs={"pk": reminder.pk}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        self.assertEqual(Reminder.objects.count(), 0)

    def test_delete_nonexistent_reminder(self):
        """Deleting a non-existent reminder returns 404."""
        self.client.login(username="reminderuser1", password="testpass123")
        response = self.client.post(
            reverse("calendar_app:delete_reminder", kwargs={"pk": 99999}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)

    # ------------------------------------------------------------------ #
    # Page rendering
    # ------------------------------------------------------------------ #

    def test_reminders_view_renders(self):
        """GET the reminders page and verify it renders correctly."""
        self.client.login(username="reminderuser1", password="testpass123")
        Reminder.objects.create(
            title="Visible Reminder",
            date=date.today() + timedelta(days=10),
            created_by=self.user1,
        )
        response = self.client.get(reverse("calendar_app:reminders"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Reminders")
        self.assertContains(response, "Visible Reminder")
        self.assertTemplateUsed(response, "calendar_app/reminders.html")

    def test_reminders_view_splits_past_and_future(self):
        """Past reminders are in a collapsible section; future are shown first."""
        self.client.login(username="reminderuser1", password="testpass123")

        past_reminder = Reminder.objects.create(
            title="Past Event",
            date=date.today() - timedelta(days=5),
            created_by=self.user1,
        )
        future_soon = Reminder.objects.create(
            title="Soon Event",
            date=date.today() + timedelta(days=3),
            created_by=self.user1,
        )
        future_later = Reminder.objects.create(
            title="Later Event",
            date=date.today() + timedelta(days=30),
            created_by=self.user1,
        )

        response = self.client.get(reverse("calendar_app:reminders"))
        self.assertEqual(response.status_code, 200)

        # Context has the right split
        ctx_future = list(response.context["future_reminders"])
        ctx_past = list(response.context["past_reminders"])

        self.assertEqual(len(ctx_future), 2)
        self.assertEqual(len(ctx_past), 1)

        # Future reminders are sorted ascending (nearest first)
        self.assertEqual(ctx_future[0].pk, future_soon.pk)
        self.assertEqual(ctx_future[1].pk, future_later.pk)

        # Past reminder is in the past list
        self.assertEqual(ctx_past[0].pk, past_reminder.pk)

        # The rendered page shows the past section inside a <details> element
        content = response.content.decode()
        self.assertIn("Past Reminders", content)
        self.assertIn("Past Event", content)
        self.assertIn("Soon Event", content)
        self.assertIn("Later Event", content)

    # ------------------------------------------------------------------ #
    # iCal integration
    # ------------------------------------------------------------------ #

    def test_ical_content_includes_reminders(self):
        """generate_ical_content() should include Reminder VEVENTs."""
        from .ical import generate_ical_content
        from .models import ConfirmedDate

        ConfirmedDate.objects.create(
            date=date.today() + timedelta(days=5),
            description="Folge 100",
            confirmed_by=self.user1,
        )
        Reminder.objects.create(
            title="My Important Reminder",
            date=date.today() + timedelta(days=15),
            description="Do not forget",
            created_by=self.user1,
        )

        ical = generate_ical_content()

        # Podcast event present
        self.assertIn("SUMMARY:Bin\\xe4rgewitter Podcast" if False else "SUMMARY:", ical)
        # Reminder event present
        self.assertIn("My Important Reminder", ical)
        self.assertIn("Do not forget", ical)
        # Both are VEVENTs
        self.assertGreaterEqual(ical.count("BEGIN:VEVENT"), 2)

    def test_ical_export_endpoint_includes_reminders(self):
        """The /export/calendar.ics endpoint should include reminder entries."""
        from .ical import generate_ical_file

        Reminder.objects.create(
            title="Export Test Reminder",
            date=date.today() + timedelta(days=20),
            created_by=self.user1,
        )
        # Regenerate the file so the endpoint serves fresh content
        generate_ical_file()

        # The export endpoint has no @login_required
        response = self.client.get(reverse("calendar_app:export_ical"))
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Export Test Reminder", response.content)

    # ------------------------------------------------------------------ #
    # Auth / permissions
    # ------------------------------------------------------------------ #

    def test_unauthenticated_access_denied(self):
        """API and page should redirect unauthenticated users."""
        reminder = Reminder.objects.create(
            title="Auth Test",
            date=date.today() + timedelta(days=10),
            created_by=self.user1,
        )
        urls = [
            reverse("calendar_app:reminders"),
            reverse("calendar_app:create_reminder"),
            reverse("calendar_app:update_reminder", kwargs={"pk": reminder.pk}),
            reverse("calendar_app:delete_reminder", kwargs={"pk": reminder.pk}),
        ]
        for url in urls:
            # GET or POST — should redirect to login
            response = self.client.get(url)
            self.assertIn(response.status_code, [302, 405], msg=f"Expected redirect for {url}")

    def test_any_user_can_edit_any_reminder(self):
        """User B should be able to update a reminder created by User A."""
        reminder = Reminder.objects.create(
            title="User A Created",
            date=date.today() + timedelta(days=10),
            created_by=self.user1,
        )
        self.client.login(username="reminderuser2", password="testpass123")
        response = self.client.post(
            reverse("calendar_app:update_reminder", kwargs={"pk": reminder.pk}),
            data=json.dumps(
                {
                    "title": "User B Updated",
                    "date": self.future_date,
                    "description": "Changed by B",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        reminder.refresh_from_db()
        self.assertEqual(reminder.title, "User B Updated")

    def test_any_user_can_delete_any_reminder(self):
        """User B should be able to delete a reminder created by User A."""
        reminder = Reminder.objects.create(
            title="User A Created",
            date=date.today() + timedelta(days=10),
            created_by=self.user1,
        )
        self.client.login(username="reminderuser2", password="testpass123")
        response = self.client.post(
            reverse("calendar_app:delete_reminder", kwargs={"pk": reminder.pk}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        self.assertEqual(Reminder.objects.count(), 0)


def _basic(username, key):
    return "Basic " + base64.b64encode(f"{username}:{key}".encode()).decode()


class CalendarKeyModelTest(TestCase):
    """Tests for the CalendarKey model."""

    def setUp(self):
        self.user1 = User.objects.create_user(username="keyuser1", password="testpass123")
        self.user2 = User.objects.create_user(username="keyuser2", password="testpass123")

    def test_generate_for_creates_key(self):
        key = CalendarKey.generate_for(self.user1)
        self.assertEqual(len(key), 40)
        int(key, 16)  # must be hex
        row = CalendarKey.objects.get(user=self.user1)
        self.assertEqual(row.key, key)

    def test_generate_for_rotates(self):
        first = CalendarKey.generate_for(self.user1)
        second = CalendarKey.generate_for(self.user1)
        self.assertNotEqual(first, second)
        self.assertEqual(CalendarKey.objects.filter(user=self.user1).count(), 1)
        self.assertEqual(CalendarKey.objects.get(user=self.user1).key, second)

    def test_distinct_users_distinct_keys(self):
        k1 = CalendarKey.generate_for(self.user1)
        k2 = CalendarKey.generate_for(self.user2)
        self.assertNotEqual(k1, k2)


class DavAuthTest(TestCase):
    """Basic auth gate for the CalDAV endpoints."""

    def setUp(self):
        self.user = User.objects.create_user(username="davuser", password="testpass123")
        self.key = CalendarKey.generate_for(self.user)
        self.client = Client()

    def test_no_auth_header_401_everywhere(self):
        for method in ("PROPFIND", "REPORT"):
            with self.subTest(method=method):
                response = self.client.generic(
                    method,
                    "/dav/calendar/",
                    "<x/>",
                    "application/xml",
                )
                self.assertEqual(response.status_code, 401)
        response = self.client.put("/dav/calendar/x.ics", b"x", "text/calendar")
        self.assertEqual(response.status_code, 401)
        self.assertTrue(response["WWW-Authenticate"].startswith("Basic realm="))
        response = self.client.delete("/dav/calendar/x.ics")
        self.assertEqual(response.status_code, 401)

    def test_wrong_key_401(self):
        response = self.client.generic(
            "PROPFIND",
            "/dav/calendar/",
            "<x/>",
            "application/xml",
            HTTP_AUTHORIZATION=_basic("davuser", "wrongkey"),
        )
        self.assertEqual(response.status_code, 401)

    def test_user_without_key_401(self):
        nobody = User.objects.create_user(username="nokeyuser", password="testpass123")
        response = self.client.generic(
            "PROPFIND",
            "/dav/calendar/",
            "<x/>",
            "application/xml",
            HTTP_AUTHORIZATION=_basic("nokeyuser", "whatever"),
        )
        self.assertEqual(response.status_code, 401)
        self.assertFalse(CalendarKey.objects.filter(user=nobody).exists())

    def test_correct_key_207(self):
        response = self.client.generic(
            "PROPFIND",
            "/dav/calendar/",
            "<x/>",
            "application/xml",
            HTTP_AUTHORIZATION=_basic("davuser", self.key),
        )
        self.assertEqual(response.status_code, 207)

    def test_crossed_username_key_401(self):
        # the key must belong to the named user, not merely exist in the table
        other = User.objects.create_user(username="otherdav", password="testpass123")
        other_key = CalendarKey.generate_for(other)
        response = self.client.generic(
            "PROPFIND",
            "/dav/calendar/",
            "<x/>",
            "application/xml",
            HTTP_AUTHORIZATION=_basic("davuser", other_key),
        )
        self.assertEqual(response.status_code, 401)

    def test_rotated_key_rejected_after_rotation(self):
        old_key = self.key
        new_key = CalendarKey.generate_for(self.user)
        for key, expected in ((old_key, 401), (new_key, 207)):
            with self.subTest(key=key):
                response = self.client.generic(
                    "PROPFIND",
                    "/dav/calendar/",
                    "<x/>",
                    "application/xml",
                    HTTP_AUTHORIZATION=_basic("davuser", key),
                )
                self.assertEqual(response.status_code, expected)

    def test_deactivated_user_401(self):
        # deactivating the account must revoke Basic-auth CalDAV access
        User.objects.filter(pk=self.user.pk).update(is_active=False)
        response = self.client.generic(
            "PROPFIND",
            "/dav/calendar/",
            "<x/>",
            "application/xml",
            HTTP_AUTHORIZATION=_basic("davuser", self.key),
        )
        self.assertEqual(response.status_code, 401)

    def test_non_ascii_key_401_not_500(self):
        # compare_digest must not raise TypeError on non-ASCII client input
        raw = base64.b64encode("davuser:ключ💥".encode("utf-8")).decode()
        response = self.client.generic(
            "PROPFIND",
            "/dav/calendar/",
            "<x/>",
            "application/xml",
            HTTP_AUTHORIZATION="Basic " + raw,
        )
        self.assertEqual(response.status_code, 401)

    def test_malformed_basic_header_401(self):
        response = self.client.generic(
            "PROPFIND",
            "/dav/calendar/",
            "<x/>",
            "application/xml",
            HTTP_AUTHORIZATION="Basic !!!notbase64!!!",
        )
        self.assertEqual(response.status_code, 401)


class DavProtocolTest(TestCase):
    """CalDAV protocol behaviour: PROPFIND, REPORT, PUT, DELETE, GET."""

    def setUp(self):
        self.user = User.objects.create_user(username="davproto", password="testpass123")
        self.key = CalendarKey.generate_for(self.user)
        self.auth = _basic("davproto", self.key)
        self.client = Client()
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.ical_path = Path(self.tmpdir.name) / "calendar.ics"
        override = override_settings(ICAL_EXPORT_PATH=str(self.ical_path))
        override.enable()
        self.addCleanup(override.disable)
        self.rem1 = Reminder.objects.create(
            title="Alpha Sync",
            date=date(2026, 10, 5),
            description="first",
            created_by=self.user,
        )
        self.rem2 = Reminder.objects.create(
            title="Beta Live",
            date=date(2026, 11, 20),
            description="",
            created_by=self.user,
        )
        # another user's row: the calendar is shared, every key must see it
        self.other_user = User.objects.create_user(username="davother", password="testpass123")
        self.other_auth = _basic("davother", CalendarKey.generate_for(self.other_user))
        self.rem_other = Reminder.objects.create(
            title="Gamma Other",
            date=date(2026, 12, 15),
            description="foreign",
            created_by=self.other_user,
        )

    def _propfind(self, depth="0", path="/dav/calendar/"):
        xml = (
            '<?xml version="1.0"?><D:propfind xmlns:D="DAV:"><D:prop>'
            "<D:getetag/><D:getcontenttype/></D:prop></D:propfind>"
        )
        return self.client.generic(
            "PROPFIND",
            path,
            xml,
            "application/xml",
            HTTP_AUTHORIZATION=self.auth,
            HTTP_DEPTH=depth,
        )

    def _report(self, xml):
        return self.client.generic(
            "REPORT",
            "/dav/calendar/",
            xml,
            "application/xml",
            HTTP_AUTHORIZATION=self.auth,
        )

    def test_options_headers(self):
        response = self.client.options("/dav/calendar/", HTTP_AUTHORIZATION=self.auth)
        self.assertEqual(response.status_code, 200)
        self.assertIn("calendar-access", response["DAV"])
        self.assertNotIn("calendar-auto-schedule", response["DAV"])

    def test_propfind_depth0_collection(self):
        response = self._propfind("0")
        self.assertEqual(response.status_code, 207)
        body = response.content.decode()
        self.assertIn("<D:collection/>", body)
        self.assertIn("urn:ietf:params:xml:ns:caldav", body)
        self.assertIn('<C:comp name="VEVENT"/>', body)

    def test_propfind_depth1_lists_items(self):
        response = self._propfind("1")
        self.assertEqual(response.status_code, 207)
        body = response.content.decode()
        for rem in (self.rem1, self.rem2):
            self.assertIn(f"/dav/calendar/{rem.uid}.ics", body)
        self.assertIn("&quot;", body)  # quoted etags
        self.assertIn("text/calendar", body)
        self.assertEqual(body.count("<D:response>"), Reminder.objects.count() + 1)
        # item responses must not carry resourcetype (Thunderbird wipe guard)
        for fragment in body.split("<D:response>")[1:]:
            if ".ics<" in fragment.split("<D:status>")[0]:
                self.assertNotIn("<D:resourcetype", fragment.split("<D:status>")[0])

    def test_report_multiget(self):
        xml = (
            '<?xml version="1.0"?><C:calendar-multiget xmlns:D="DAV:" '
            'xmlns:C="urn:ietf:params:xml:ns:caldav"><D:prop><D:getetag/>'
            "<C:calendar-data/></D:prop>"
            f"<D:href>/dav/calendar/{self.rem1.uid}.ics</D:href>"
            "<D:href>/dav/calendar/bogus.ics</D:href>"
            "</C:calendar-multiget>"
        )
        response = self._report(xml)
        self.assertEqual(response.status_code, 207)
        body = response.content.decode()
        self.assertIn("BEGIN:VEVENT", body)
        self.assertIn(self.rem1.uid, body)
        self.assertIn("DTSTART;VALUE=DATE:20261005", body)
        self.assertIn("404 Not Found", body)

    def _event_body(self, uid, summary, description, compact_date, fold=False):
        lines = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "BEGIN:VEVENT",
            f"UID:{uid}",
            "DTSTAMP:20260919T120000Z",
            f"DTSTART;VALUE=DATE:{compact_date}",
            f"DTEND;VALUE=DATE:{compact_date}",
            f"SUMMARY:{summary}",
            f"DESCRIPTION:{description}",
            "END:VEVENT",
            "END:VCALENDAR",
        ]
        return "\r\n".join(lines)

    def test_put_creates_reminder_and_regenerates_ics(self):
        # fold the SUMMARY across a continuation line and escape a newline
        body = (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\n"
            "UID:newitem1\r\nDTSTAMP:20260919T120000Z\r\n"
            "DTSTART;VALUE=DATE:20261224\r\nDTEND;VALUE=DATE:20261225\r\n"
            "SUMMARY:Very Long Event Name That Was Fol\r\n ded And Escaped: a\\,comma\r\n"
            "DESCRIPTION:line1\\nline2\r\n"
            "END:VEVENT\r\nEND:VCALENDAR\r\n"
        )
        response = self.client.put(
            "/dav/calendar/newitem1.ics",
            body,
            "text/calendar",
            HTTP_AUTHORIZATION=self.auth,
            HTTP_IF_NONE_MATCH="*",
        )
        self.assertEqual(response.status_code, 204)
        rem = Reminder.objects.get(uid="newitem1")
        self.assertEqual(rem.title, "Very Long Event Name That Was Folded And Escaped: a,comma")
        self.assertEqual(rem.description, "line1\nline2")
        self.assertEqual(rem.date, date(2026, 12, 24))
        self.assertEqual(rem.created_by, self.user)
        # export escapes commas per RFC 5545, so match the escaped form
        self.assertIn(
            "SUMMARY:Very Long Event Name That Was Folded And Escaped: a\\,comma",
            self.ical_path.read_text(encoding="utf-8"),
        )

    def test_put_update_same_uid(self):
        body = self._event_body(self.rem1.uid, "Updated Title", "desc", "20261005")
        response = self.client.put(
            f"/dav/calendar/{self.rem1.uid}.ics",
            body,
            "text/calendar",
            HTTP_AUTHORIZATION=self.auth,
        )
        self.assertEqual(response.status_code, 204)
        self.rem1.refresh_from_db()
        self.assertEqual(self.rem1.title, "Updated Title")
        self.assertEqual(Reminder.objects.count(), 3)  # rem1, rem2, rem_other

    def test_put_if_none_match_conflict(self):
        body = self._event_body(self.rem1.uid, "X", "", "20261005")
        response = self.client.put(
            f"/dav/calendar/{self.rem1.uid}.ics",
            body,
            "text/calendar",
            HTTP_AUTHORIZATION=self.auth,
            HTTP_IF_NONE_MATCH="*",
        )
        self.assertEqual(response.status_code, 409)

    def test_put_if_match_stale_etag(self):
        body = self._event_body(self.rem1.uid, "X", "", "20261005")
        response = self.client.put(
            f"/dav/calendar/{self.rem1.uid}.ics",
            body,
            "text/calendar",
            HTTP_AUTHORIZATION=self.auth,
            HTTP_IF_MATCH='"bogus"',
        )
        self.assertEqual(response.status_code, 412)

    def test_put_garbage_400(self):
        response = self.client.put(
            "/dav/calendar/junk.ics",
            b"not-ical",
            "text/calendar",
            HTTP_AUTHORIZATION=self.auth,
        )
        self.assertEqual(response.status_code, 400)

    def test_delete_flow(self):
        response = self.client.delete(f"/dav/calendar/{self.rem2.uid}.ics", HTTP_AUTHORIZATION=self.auth)
        self.assertEqual(response.status_code, 204)
        self.assertFalse(Reminder.objects.filter(uid=self.rem2.uid).exists())
        response = self.client.delete(f"/dav/calendar/{self.rem2.uid}.ics", HTTP_AUTHORIZATION=self.auth)
        self.assertEqual(response.status_code, 404)

    def test_get_item(self):
        response = self.client.get(f"/dav/calendar/{self.rem1.uid}.ics", HTTP_AUTHORIZATION=self.auth)
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/calendar", response["Content-Type"])
        self.assertIn(f"UID:{self.rem1.uid}".encode(), response.content)
        response = self.client.get("/dav/calendar/missing.ics", HTTP_AUTHORIZATION=self.auth)
        self.assertEqual(response.status_code, 404)

    def test_report_calendar_query_time_range(self):
        xml = (
            '<?xml version="1.0"?><C:calendar-query xmlns:D="DAV:" '
            'xmlns:C="urn:ietf:params:xml:ns:caldav"><D:prop><D:getetag/>'
            '<C:calendar-data/></D:prop><C:filter><C:comp-filter name="VCALENDAR">'
            '<C:comp-filter name="VEVENT"><C:event-filter start="20261001T000000Z" '
            'end="20261101T000000Z"/></C:comp-filter></C:comp-filter></C:filter>'
            "</C:calendar-query>"
        )
        response = self._report(xml)
        self.assertEqual(response.status_code, 207)
        body = response.content.decode()
        self.assertIn(self.rem1.uid, body)
        self.assertNotIn(self.rem2.uid, body)
        self.assertIn("BEGIN:VEVENT", body)

    def test_get_collection_405(self):
        response = self.client.get("/dav/calendar/", HTTP_AUTHORIZATION=self.auth)
        self.assertEqual(response.status_code, 405)

    def test_propfind_item(self):
        xml = (
            '<?xml version="1.0"?><D:propfind xmlns:D="DAV:"><D:prop>'
            "<D:getetag/><D:getcontenttype/></D:prop></D:propfind>"
        )
        response = self.client.generic(
            "PROPFIND",
            f"/dav/calendar/{self.rem1.uid}.ics",
            xml,
            "application/xml",
            HTTP_AUTHORIZATION=self.auth,
            HTTP_DEPTH="0",
        )
        self.assertEqual(response.status_code, 207)
        body = response.content.decode()
        self.assertIn(f"/dav/calendar/{self.rem1.uid}.ics", body)
        self.assertIn("&quot;", body)  # quoted etag
        self.assertIn("text/calendar", body)
        response = self.client.generic(
            "PROPFIND",
            "/dav/calendar/missing.ics",
            xml,
            "application/xml",
            HTTP_AUTHORIZATION=self.auth,
            HTTP_DEPTH="0",
        )
        self.assertEqual(response.status_code, 404)

    def test_report_invalid_xml_400(self):
        response = self._report("not xml at all")
        self.assertEqual(response.status_code, 400)

    def test_report_calendar_query_no_filter(self):
        xml = (
            '<?xml version="1.0"?><C:calendar-query xmlns:D="DAV:" '
            'xmlns:C="urn:ietf:params:xml:ns:caldav"><D:prop><D:getetag/>'
            "<C:calendar-data/></D:prop></C:calendar-query>"
        )
        response = self._report(xml)
        self.assertEqual(response.status_code, 207)
        body = response.content.decode()
        self.assertIn(self.rem1.uid, body)
        self.assertIn(self.rem2.uid, body)

    def test_put_if_match_fresh_etag(self):
        etag = self.client.get(
            f"/dav/calendar/{self.rem1.uid}.ics",
            HTTP_AUTHORIZATION=self.auth,
        )["ETag"]
        body = self._event_body(self.rem1.uid, "Fresh Etag", "", "20261005")
        response = self.client.put(
            f"/dav/calendar/{self.rem1.uid}.ics",
            body,
            "text/calendar",
            HTTP_AUTHORIZATION=self.auth,
            HTTP_IF_MATCH=etag,
        )
        self.assertEqual(response.status_code, 204)
        self.rem1.refresh_from_db()
        self.assertEqual(self.rem1.title, "Fresh Etag")

    def test_put_body_uid_mismatch_400(self):
        # RFC 4791: body UID must equal the item URL UID. A mismatch must not
        # be silently stored under the URL UID (phantom event for clients
        # keyed on their own UID) nor collide into another row's identity.
        body = self._event_body(self.rem1.uid, "Collide", "", "20261005")
        response = self.client.put(
            "/dav/calendar/fresh-path-uid.ics",
            body,
            "text/calendar",
            HTTP_AUTHORIZATION=self.auth,
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Reminder.objects.filter(uid="fresh-path-uid").exists())
        self.rem1.refresh_from_db()
        self.assertEqual(self.rem1.title, "Alpha Sync")  # rejected PUT left the row untouched

        body = self._event_body("other-uid", "Path Wins", "", "20261005")
        response = self.client.put(
            "/dav/calendar/path-uid.ics",
            body,
            "text/calendar",
            HTTP_AUTHORIZATION=self.auth,
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Reminder.objects.filter(uid__in=["path-uid", "other-uid"]).exists())

    def test_put_default_summary(self):
        lines = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "BEGIN:VEVENT",
            "UID:nosummary1",
            "DTSTAMP:20260919T120000Z",
            "DTSTART;VALUE=DATE:20261005",
            "END:VEVENT",
            "END:VCALENDAR",
        ]
        response = self.client.put(
            "/dav/calendar/nosummary1.ics",
            "\r\n".join(lines),
            "text/calendar",
            HTTP_AUTHORIZATION=self.auth,
        )
        self.assertEqual(response.status_code, 204)
        self.assertEqual(Reminder.objects.get(uid="nosummary1").title, "Erinnerung")

    def test_put_timed_dtstart(self):
        # clients like Thunderbird may send timed DTSTART; the date part is used
        lines = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "BEGIN:VEVENT",
            "UID:timed1",
            "DTSTAMP:20260919T120000Z",
            "DTSTART:20261010T180000Z",
            "DTEND:20261010T210000Z",
            "SUMMARY:Timed Event",
            "END:VEVENT",
            "END:VCALENDAR",
        ]
        response = self.client.put(
            "/dav/calendar/timed1.ics",
            "\r\n".join(lines),
            "text/calendar",
            HTTP_AUTHORIZATION=self.auth,
        )
        self.assertEqual(response.status_code, 204)
        self.assertEqual(Reminder.objects.get(uid="timed1").date, date(2026, 10, 10))

    def test_put_over_1mib_413(self):
        body = "BEGIN:VCALENDAR\r\nDESCRIPTION:" + "X" * (1024 * 1024 + 10) + "\r\nEND:VCALENDAR"
        response = self.client.put(
            "/dav/calendar/big.ics",
            body,
            "text/calendar",
            HTTP_AUTHORIZATION=self.auth,
        )
        self.assertEqual(response.status_code, 413)

    def test_shared_calendar_visible_to_other_users_key(self):
        # the calendar is shared: another user's key must see (and in this
        # model, edit/delete) every row, not just its owner's.
        response = self._propfind("1")
        body = response.content.decode()
        self.assertIn(self.rem_other.uid, body)
        response = self.client.generic(
            "PROPFIND",
            "/dav/calendar/",
            "<x/>",
            "application/xml",
            HTTP_AUTHORIZATION=self.other_auth,
            HTTP_DEPTH="1",
        )
        self.assertEqual(response.status_code, 207)
        body = response.content.decode()
        for rem in (self.rem1, self.rem2, self.rem_other):
            self.assertIn(rem.uid, body)
        # and DELETE of a foreign row is intended behaviour
        response = self.client.delete(f"/dav/calendar/{self.rem2.uid}.ics", HTTP_AUTHORIZATION=self.other_auth)
        self.assertEqual(response.status_code, 204)
        self.assertFalse(Reminder.objects.filter(uid=self.rem2.uid).exists())

    def test_put_if_match_missing_resource_412(self):
        # RFC 7232: If-Match against a missing resource must not create it
        body = self._event_body("resurrect1", "Ghost", "", "20261005")
        response = self.client.put(
            "/dav/calendar/resurrect1.ics",
            body,
            "text/calendar",
            HTTP_AUTHORIZATION=self.auth,
            HTTP_IF_MATCH='"anything"',
        )
        self.assertEqual(response.status_code, 412)
        self.assertFalse(Reminder.objects.filter(uid="resurrect1").exists())

    def test_report_dtd_rejected_400(self):
        xml = (
            '<!DOCTYPE R [<!ENTITY a "&a;&a;">]>'
            '<C:calendar-multiget xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">'
            "<D:prop><D:getetag/></D:prop></C:calendar-multiget>"
        )
        response = self._report(xml)
        self.assertEqual(response.status_code, 400)

    def test_report_multiget_href_injection_sanitized(self):
        # client-controlled hrefs are echoed back; markup must not survive raw
        xml = (
            '<?xml version="1.0"?><C:calendar-multiget xmlns:D="DAV:" '
            'xmlns:C="urn:ietf:params:xml:ns:caldav"><D:prop><D:getetag/></D:prop>'
            "<D:href>/dav/calendar/&lt;x/&gt;</D:href>"
            "<D:href>/evil/x.ics</D:href>"
            "<D:href>/dav/calendar/" + self.rem1.uid + ".ics</D:href>"
            "</C:calendar-multiget>"
        )
        response = self._report(xml)
        self.assertEqual(response.status_code, 207)
        root = ElementTree.fromstring(response.content)  # must stay well-formed
        hrefs = [el.text for el in root.iter(f"{{{DAV_NS}}}href")]
        self.assertNotIn("/evil/x.ics", hrefs)
        self.assertIn("/dav/calendar/" + self.rem1.uid + ".ics", hrefs)
        self.assertEqual(len(root.findall(f"{{{DAV_NS}}}response")), 3)

    def test_put_roundtrip_preserves_escaped_whitespace(self):
        # the server's own serialization must survive an unchanged re-PUT:
        # a client (Thunderbird) GETs the ICS and PUTs it back verbatim.
        self.rem1.description = "Line one\n\tLine two"
        self.rem1.save()
        body = self.client.get(
            f"/dav/calendar/{self.rem1.uid}.ics",
            HTTP_AUTHORIZATION=self.auth,
        ).content.decode()
        # fold the DESCRIPTION line like a real client would
        folded = body.replace("DESCRIPTION:Line one", "DESCRIPTION:Long Prefix Here\r\n\tLine one")
        response = self.client.put(
            f"/dav/calendar/{self.rem1.uid}.ics",
            folded,
            "text/calendar",
            HTTP_AUTHORIZATION=self.auth,
        )
        self.assertEqual(response.status_code, 204)
        self.rem1.refresh_from_db()
        self.assertEqual(self.rem1.description, "Long Prefix HereLine one\n\tLine two")


class DavKeyApiTest(TestCase):
    """Session-auth key management APIs behind the 🔑 Sync page."""

    def setUp(self):
        self.user = User.objects.create_user(username="keyapi", password="testpass123")
        self.client = Client()

    def test_unauthenticated_redirects(self):
        response = self.client.get(reverse("calendar_app:get_dav_key"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response["Location"].lower())

    def test_get_key_none_initially(self):
        self.client.login(username="keyapi", password="testpass123")
        response = self.client.get(reverse("calendar_app:get_dav_key"))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertIsNone(data["data"]["key"])
        self.assertEqual(data["data"]["username"], "keyapi")

    def test_generate_and_rotate(self):
        self.client.login(username="keyapi", password="testpass123")
        response = self.client.post(reverse("calendar_app:generate_dav_key"))
        self.assertEqual(response.status_code, 200)
        key = response.json()["data"]["key"]
        self.assertEqual(CalendarKey.objects.get(user=self.user).key, key)
        response2 = self.client.post(reverse("calendar_app:generate_dav_key"))
        key2 = response2.json()["data"]["key"]
        self.assertNotEqual(key, key2)
        self.assertEqual(CalendarKey.objects.filter(user=self.user).count(), 1)

    def test_generate_requires_csrf(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.login(username="keyapi", password="testpass123")
        response = csrf_client.post(reverse("calendar_app:generate_dav_key"))
        self.assertEqual(response.status_code, 403)

    def test_sync_page_renders(self):
        self.client.login(username="keyapi", password="testpass123")
        response = self.client.get(reverse("calendar_app:dav"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Calendar-Key")


class EntryApiTest(TestCase):
    """Key-authenticated JSON entry API."""

    def setUp(self):
        self.user = User.objects.create_user(username="entryapi", password="testpass123")
        self.key = CalendarKey.generate_for(self.user)
        self.auth = _basic("entryapi", self.key)
        self.client = Client()
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.ical_path = Path(self.tmpdir.name) / "calendar.ics"
        override = override_settings(ICAL_EXPORT_PATH=str(self.ical_path))
        override.enable()
        self.addCleanup(override.disable)

    def test_unauthenticated_401_json(self):
        response = self.client.get(reverse("calendar_app:entry_list"))
        self.assertEqual(response.status_code, 401)
        self.assertIn("error", response.json())

    def test_wrong_key_401(self):
        response = self.client.get(
            reverse("calendar_app:entry_list"),
            headers={"Authorization": _basic("entryapi", "wrong")},
        )
        self.assertEqual(response.status_code, 401)

    def test_list_with_basic(self):
        Reminder.objects.create(title="Seeded", date=date(2026, 10, 1), created_by=self.user)
        # a foreign row must be visible too: the calendar is shared, not per-user
        foreign = User.objects.create_user(username="entryother", password="testpass123")
        Reminder.objects.create(title="Foreign", date=date(2026, 10, 2), created_by=foreign)
        response = self.client.get(reverse("calendar_app:entry_list"), headers={"Authorization": self.auth})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(len(data["data"]), 2)
        self.assertIn("id", data["data"][0])
        self.assertIn("uid", data["data"][0])

    def test_create_with_basic(self):
        response = self.client.post(
            reverse("calendar_app:entry_create"),
            data=json.dumps({"title": "From API", "date": "2026-10-01", "description": "d"}),
            content_type="application/json",
            headers={"Authorization": self.auth},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertTrue(data["data"]["uid"])
        rem = Reminder.objects.get(title="From API")
        self.assertEqual(rem.created_by, self.user)
        self.assertIn("From API", self.ical_path.read_text(encoding="utf-8"))

    def test_create_empty_title_400(self):
        response = self.client.post(
            reverse("calendar_app:entry_create"),
            data=json.dumps({"title": "", "date": "2026-10-01"}),
            content_type="application/json",
            headers={"Authorization": self.auth},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "Title is required")

    def test_update_partial(self):
        rem = Reminder.objects.create(title="Old", date=date(2026, 10, 1), created_by=self.user)
        response = self.client.post(
            reverse("calendar_app:entry_update", kwargs={"pk": rem.pk}),
            data=json.dumps({"title": "New", "date": "2026-11-11"}),
            content_type="application/json",
            headers={"Authorization": self.auth},
        )
        self.assertEqual(response.status_code, 200)
        rem.refresh_from_db()
        self.assertEqual(rem.title, "New")
        self.assertEqual(rem.date, date(2026, 11, 11))
        self.assertEqual(Reminder.objects.count(), 1)

    def test_update_delete_missing_404(self):
        for name in ("entry_update", "entry_delete"):
            response = self.client.post(
                reverse(f"calendar_app:{name}", kwargs={"pk": 99999}),
                data=json.dumps({}),
                content_type="application/json",
                headers={"Authorization": self.auth},
            )
            self.assertEqual(response.status_code, 404, msg=name)
            self.assertEqual(response.json()["error"], "Reminder not found")

    def test_delete_flow(self):
        rem = Reminder.objects.create(title="Doomed", date=date(2026, 10, 1), created_by=self.user)
        response = self.client.post(
            reverse("calendar_app:entry_delete", kwargs={"pk": rem.pk}),
            content_type="application/json",
            headers={"Authorization": self.auth},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        self.assertEqual(Reminder.objects.count(), 0)

    def test_session_post_without_csrf_rejected(self):
        """Session-auth unsafe calls must still pass CSRF (unlike Basic calls)."""
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.login(username="entryapi", password="testpass123")
        response = csrf_client.post(
            reverse("calendar_app:entry_create"),
            data=json.dumps({"title": "Session", "date": "2026-10-01"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_session_post_with_csrf_works(self):
        self.client.login(username="entryapi", password="testpass123")
        response = self.client.post(
            reverse("calendar_app:entry_create"),
            data=json.dumps({"title": "Session", "date": "2026-10-01"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        self.assertEqual(Reminder.objects.get(title="Session").created_by, self.user)

    def test_session_post_with_csrf_token_accepted(self):
        """Re-check inside key_or_session_auth must ACCEPT a valid token
        (not just reject missing ones) — the dav.html browser flows depend
        on X-CSRFToken POSTs succeeding."""
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.login(username="entryapi", password="testpass123")
        csrf_client.get(reverse("calendar_app:dav"))  # renders a csrf_token cookie
        token = csrf_client.cookies["csrftoken"].value
        response = csrf_client.post(
            reverse("calendar_app:entry_create"),
            data=json.dumps({"title": "Csrf OK", "date": "2026-10-01"}),
            content_type="application/json",
            headers={"X-CSRFToken": token},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])

    def test_invalid_json_bodies_400_not_500(self):
        for body in ("[]", '"x"', "null"):
            with self.subTest(body=body):
                response = self.client.post(
                    reverse("calendar_app:entry_create"),
                    data=body,
                    content_type="application/json",
                    headers={"Authorization": self.auth},
                )
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["error"], "Invalid JSON")

    def test_create_error_contracts_400(self):
        cases = [
            ({"title": "X"}, "Date is required"),
            ({"title": "X", "date": "not-a-date"}, "Invalid date format"),
            ({"title": "X", "date": "2026-10-09", "uid": "dup-uid"}, None),
            ({"title": "X", "date": "2026-10-09", "uid": "dup-uid"}, "UID already exists"),
            ({"title": "X", "date": "2026-10-09", "uid": "bad uid!"}, "Invalid UID"),
        ]
        for body, error in cases:
            response = self.client.post(
                reverse("calendar_app:entry_create"),
                data=json.dumps(body),
                content_type="application/json",
                headers={"Authorization": self.auth},
            )
            if error is None:
                self.assertEqual(response.status_code, 200, msg=str(body))
                continue
            self.assertEqual(response.status_code, 400, msg=str(body))
            self.assertEqual(response.json()["error"], error, msg=str(body))
        self.assertEqual(Reminder.objects.filter(title="X").count(), 1)

    def test_update_error_contracts_400(self):
        rem = Reminder.objects.create(title="Keep", date=date(2026, 10, 1), created_by=self.user)
        orig_uid = rem.uid
        other = Reminder.objects.create(title="Other", date=date(2026, 10, 2), created_by=self.user)
        cases = [
            ({"title": None}, "Title is required"),
            ({"title": ""}, "Title is required"),
            ({"date": "nope"}, "Invalid date format"),
            ({"uid": ""}, "UID is required"),
            ({"uid": "has space"}, "Invalid UID"),
            ({"uid": other.uid}, "UID already exists"),
        ]
        for body, error in cases:
            response = self.client.post(
                reverse("calendar_app:entry_update", kwargs={"pk": rem.pk}),
                data=json.dumps(body),
                content_type="application/json",
                headers={"Authorization": self.auth},
            )
            self.assertEqual(response.status_code, 400, msg=str(body))
            self.assertEqual(response.json()["error"], error, msg=str(body))
        # no rejected update may have touched the row
        rem.refresh_from_db()
        self.assertEqual(rem.title, "Keep")
        self.assertEqual(rem.date, date(2026, 10, 1))
        self.assertEqual(rem.uid, orig_uid)  # rejected uid updates must not stick

    def test_scalar_json_update_400(self):
        rem = Reminder.objects.create(title="Keep", date=date(2026, 10, 1), created_by=self.user)
        response = self.client.post(
            reverse("calendar_app:entry_update", kwargs={"pk": rem.pk}),
            data=json.dumps("title"),
            content_type="application/json",
            headers={"Authorization": self.auth},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "Invalid JSON")

    def test_uid_with_crlf_rejected_400(self):
        # CRLF in a uid would inject lines into every generated VEVENT
        response = self.client.post(
            reverse("calendar_app:entry_create"),
            data=json.dumps({"title": "X", "date": "2026-10-01", "uid": "a\r\nDTSTART;VALUE=DATE:20260101"}),
            content_type="application/json",
            headers={"Authorization": self.auth},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "Invalid UID")

    def test_get_on_post_only_endpoints_405(self):
        rem = Reminder.objects.create(title="R", date=date(2026, 10, 1), created_by=self.user)
        for name, kwargs in (("entry_create", {}), ("entry_update", {"pk": rem.pk}), ("entry_delete", {"pk": rem.pk})):
            response = self.client.get(
                reverse(f"calendar_app:{name}", kwargs=kwargs),
                headers={"Authorization": self.auth},
            )
            self.assertEqual(response.status_code, 405, msg=name)
