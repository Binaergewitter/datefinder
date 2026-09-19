"""
Integration tests driving the real python `caldav` client (nixpkgs python3Packages.caldav)
against a live HTTP server, cross-checked with the JSON entry API and the public ICS file.

Verifies the CalDAV backend behaves for actual client libraries (Thunderbird/DAVx5-grade
HTTP), not just hand-rolled requests: PROPFIND/REPORT/PUT/DELETE round-trips, etag
preconditions (If-Match -> 412 -> ETagMismatchError), and bidirectional visibility
between CalDAV mutations, the shared Reminder rows, the JSON API, and the export file.
"""

import datetime
import tempfile
from pathlib import Path

import requests
from caldav.davclient import DAVClient
from caldav.lib.error import ETagMismatchError
from django.contrib.auth.models import User
from django.test import LiveServerTestCase, override_settings

from .models import CalendarKey, Reminder


class CaldavClientIntegrationTest(LiveServerTestCase):
    """Real caldav client against the live server; JSON API used as independent observer."""

    def setUp(self):
        self.user = User.objects.create_user(username='clientuser', password='testpass123')
        self.key = CalendarKey.generate_for(self.user)
        self.auth = (self.user.username, self.key)
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.ical_path = Path(self.tmpdir.name) / 'calendar.ics'
        override = override_settings(ICAL_EXPORT_PATH=str(self.ical_path))
        override.enable()
        self.addCleanup(override.disable)
        # the WSGI live server reads the same rows this transaction writes.
        self.client_dav = DAVClient(
            self.live_server_url + '/dav/calendar/',
            username=self.user.username,
            password=self.key,
        )
        self.cal = self.client_dav.calendar(url=self.live_server_url + '/dav/calendar/')

    def _entries(self):
        response = requests.get(self.live_server_url + '/calendar/api/entries/', auth=self.auth)
        self.assertEqual(response.status_code, 200)
        return response.json()['data']

    # -- caldav client -> server -> other surfaces --------------------------------

    def test_client_create_visible_in_api_and_export(self):
        self.cal.save_event(
            uid='clientcreate1',
            dtstart=datetime.date(2026, 11, 3),
            summary='Via CalDAV Client',
            description='cross desc',
        )
        rows = self._entries()
        self.assertTrue(
            any(r['uid'] == 'clientcreate1' and r['title'] == 'Via CalDAV Client'
                and r['date'] == '2026-11-03' for r in rows),
            rows,
        )
        # public ICS regenerated on save
        export = self.ical_path.read_text(encoding='utf-8')
        self.assertIn('SUMMARY:Via CalDAV Client', export)

    def test_client_list_sees_api_created_rows(self):
        response = requests.post(
            self.live_server_url + '/calendar/api/entries/create/',
            auth=self.auth,
            json={'title': 'Via JSON API', 'date': '2026-11-04', 'description': 'api desc'},
        )
        self.assertEqual(response.status_code, 200)
        datas = [str(event.data) for event in self.cal.events()]
        self.assertTrue(any('SUMMARY:Via JSON API' in d for d in datas), datas)

    def test_api_update_visible_via_client_get(self):
        response = requests.post(
            self.live_server_url + '/calendar/api/entries/create/',
            auth=self.auth,
            json={'title': 'Orig Title', 'date': '2026-11-05'},
        )
        uid = response.json()['data']['uid']
        pk = response.json()['data']['id']
        response = requests.post(
            self.live_server_url + f'/calendar/api/entries/{pk}/update/',
            auth=self.auth,
            json={'title': 'Renamed Title'},
        )
        self.assertEqual(response.status_code, 200)
        event = self.cal.event_by_url(str(self.cal.url) + uid + '.ics')
        self.assertIn('SUMMARY:Renamed Title', str(event.data))

    def test_client_delete_removes_row(self):
        self.cal.save_event(
            uid='clientdelete1',
            dtstart=datetime.date(2026, 11, 6),
            summary='Doomed By Client',
        )
        self.assertTrue(any(r['uid'] == 'clientdelete1' for r in self._entries()))
        self.cal.event_by_url(str(self.cal.url) + 'clientdelete1.ics').delete()
        self.assertFalse(any(r['uid'] == 'clientdelete1' for r in self._entries()))

    def test_client_time_search(self):
        self.cal.save_event(uid='inrange1', dtstart=datetime.date(2026, 11, 10), summary='In Range')
        self.cal.save_event(uid='outrange1', dtstart=datetime.date(2026, 12, 20), summary='Out Range')
        hits = self.cal.search(
            event=True,
            start=datetime.datetime(2026, 11, 1, tzinfo=datetime.timezone.utc),
            end=datetime.datetime(2026, 12, 1, tzinfo=datetime.timezone.utc),
        )
        uids = [str(h.url) for h in hits]
        self.assertTrue(any('inrange1' in u for u in uids), uids)
        self.assertFalse(any('outrange1' in u for u in uids), uids)

    # -- corner cases exercised through raw HTTP against the live server ----------

    def test_raw_http_corner_cases(self):
        base = self.live_server_url
        mismatch = (
            'BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:other-uid\r\n'
            'DTSTAMP:20261103T000000Z\r\nDTSTART:20261103\r\nSUMMARY:Mismatch\r\n'
            'END:VEVENT\r\nEND:VCALENDAR\r\n'
        )
        ical_headers = {'Content-Type': 'text/calendar'}
        # body UID differing from the path UID violates RFC 4791 -> 400, no row
        response = requests.put(base + '/dav/calendar/path-uid.ics', data=mismatch,
                                headers=ical_headers, auth=self.auth)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(any(r['uid'] in ('path-uid', 'other-uid') for r in self._entries()))

        # a different body UID is a path/body mismatch regardless of which
        # rows already exist -> 400 (not a silent create/overwrite)
        collide = mismatch.replace('UID:other-uid', 'UID:some-other-uid')
        response = requests.put(base + '/dav/calendar/new-uid.ics', data=collide,
                                headers=ical_headers, auth=self.auth)
        self.assertEqual(response.status_code, 400)

        # oversized body -> 413
        big = ('BEGIN:VCALENDAR\r\nDESCRIPTION:' + 'X' * (1024 * 1024 + 10) +
               '\r\nEND:VCALENDAR')
        response = requests.put(base + '/dav/calendar/big.ics', data=big,
                                headers=ical_headers, auth=self.auth)
        self.assertEqual(response.status_code, 413)

        # invalid REPORT XML -> 400
        response = requests.request('REPORT', base + '/dav/calendar/', data='not xml',
                                    headers={'Content-Type': 'application/xml'}, auth=self.auth)
        self.assertEqual(response.status_code, 400)

        # malformed Basic header -> 401 (no auth= so the raw header survives)
        response = requests.request('PROPFIND', base + '/dav/calendar/', data='<x/>',
                                    headers={'Content-Type': 'application/xml',
                                             'Authorization': 'Basic !!!notbase64!!!'})
        self.assertEqual(response.status_code, 401)

        # GET on the collection -> 405
        response = requests.get(base + '/dav/calendar/', auth=self.auth)
        self.assertEqual(response.status_code, 405)

        # multiget href outside the collection -> per-resource 404 inside 207
        xml = ('<?xml version="1.0"?><C:calendar-multiget xmlns:D="DAV:" '
               'xmlns:C="urn:ietf:params:xml:ns:caldav"><D:prop><D:getetag/>'
               '<C:calendar-data/></D:prop><D:href>/dav/calendar/nope.ics</D:href>'
               '</C:calendar-multiget>')
        response = requests.request('REPORT', base + '/dav/calendar/', data=xml,
                                    headers={'Content-Type': 'application/xml'}, auth=self.auth)
        self.assertEqual(response.status_code, 207)
        self.assertIn('404', response.text)

    def test_client_stale_etag_raises(self):
        from django.utils import timezone

        self.cal.save_event(uid='etagc1', dtstart=datetime.date(2026, 12, 1), summary='Etag Corner')
        event = self.cal.event_by_url(str(self.cal.url) + 'etagc1.ics')
        event.icalendar_component  # force load now, before the etag goes stale
        # Mutate the row behind the client's back so the etag it cached goes stale
        # (etags derive from updated_at); queryset update bypasses auto_now.
        Reminder.objects.filter(uid='etagc1').update(
            updated_at=timezone.now() - datetime.timedelta(days=365)
        )
        event.icalendar_component['SUMMARY'] = 'Etag Corner Changed'
        with self.assertRaises(ETagMismatchError):
            event.save()
        # server rejected the write: title unchanged server-side
        self.assertEqual(Reminder.objects.get(uid='etagc1').title, 'Etag Corner')
