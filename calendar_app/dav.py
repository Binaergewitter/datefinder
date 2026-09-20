"""
Minimal CalDAV backend for the shared Reminder calendar.

Hand-rolled subset (stdlib xml.etree only, no new deps): Thunderbird's native
CalDAV provider speaks OPTIONS, PROPFIND (Depth 0/1), REPORT calendar-multiget,
PUT and DELETE. calendar-query (time-range only) is added for DAVx5/Apple
clients. No MKCALENDAR/MKCOL/PROPPATCH/POST, no sync-collection, no
calendar-auto-schedule.

Auth is HTTP Basic with username + per-user calendar key (CalendarKey);
session cookies are never sent by DAV clients, so none of these views use
request.user or @login_required.
"""

import base64
import binascii
import hashlib
import logging
import re
import secrets
import xml.etree.ElementTree as ElementTree
from datetime import datetime, timedelta, timezone

from django.contrib.auth.models import User
from django.db import IntegrityError
from django.http import HttpResponse, HttpResponseNotAllowed, JsonResponse
from django.middleware.csrf import CsrfViewMiddleware
from django.utils.http import http_date
from django.views.decorators.csrf import csrf_exempt

from .ical import _ical_escape, _ical_unescape

logger = logging.getLogger(__name__)

DAV_NS = "DAV:"
C_NS = "urn:ietf:params:xml:ns:caldav"
CS_NS = "http://calendarserver.org/ns/"

COLLECTION_PATH = "/dav/calendar/"
XML_HEADER = '<?xml version="1.0" encoding="utf-8"?>'
MAX_BODY_BYTES = 1024 * 1024

for _prefix, _uri in {"D": DAV_NS, "C": C_NS, "CS": CS_NS}.items():
    ElementTree.register_namespace(_prefix, _uri)


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

def authenticate_key(request):
    """Return the User matching an `Authorization: Basic username:key` header, else None."""
    header = request.META.get("HTTP_AUTHORIZATION", "")
    if not header.startswith("Basic "):
        return None
    try:
        decoded = base64.b64decode(header[len("Basic ") :], validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return None
    username, sep, key = decoded.partition(":")
    if not sep or not username or not key:
        return None
    user = User.objects.filter(username=username, is_active=True).select_related("calendar_key").first()
    if user is None:
        return None
    calendar_key = getattr(user, "calendar_key", None)
    if calendar_key is None:
        return None
    if not secrets.compare_digest(key.encode("utf-8"), calendar_key.key.encode("utf-8")):
        return None
    return user


def basic_dav_auth(view):
    """Require valid Basic username+calendar-key; attach request.dav_user or 401."""

    def wrapper(request, *args, **kwargs):
        user = authenticate_key(request)
        if user is None:
            return _unauthorized()
        request.dav_user = user
        return view(request, *args, **kwargs)

    return wrapper


def key_or_session_auth(view):
    """JSON API auth: Basic username+key, else session user (with CSRF re-check)."""

    def wrapper(request, *args, **kwargs):
        if request.META.get("HTTP_AUTHORIZATION"):
            user = authenticate_key(request)
            if user is None:
                return JsonResponse({"error": "Invalid credentials"}, status=401)
            request.api_user = user
            return view(request, *args, **kwargs)
        if request.user.is_authenticated:
            request.api_user = request.user
            # These views are @csrf_exempt (for cookie-less Basic clients), so
            # the middleware never saw them; re-run CSRF for unsafe session calls.
            if request.method not in ("GET", "HEAD", "OPTIONS", "TRACE"):
                check = CsrfViewMiddleware(lambda r: None)
                result = check.process_view(request, None, (), {})
                if result is not None:
                    return result
            return view(request, *args, **kwargs)
        return JsonResponse({"error": "Authentication required"}, status=401)

    return wrapper


def _unauthorized():
    response = HttpResponse("Authentication required", status=401)
    response["WWW-Authenticate"] = 'Basic realm="datefinder CalDAV"'
    return response


# ---------------------------------------------------------------------------
# iCalendar (de)serialization
# ---------------------------------------------------------------------------

def _serialize_reminder_vevent(reminder) -> str:
    """Serialize one Reminder as a single-VEVENT VCALENDAR (all-day event)."""
    updated = reminder.updated_at
    if updated.tzinfo is not None:
        updated = updated.astimezone(timezone.utc)
    dtstamp = updated.strftime("%Y%m%dT%H%M%SZ")
    d = reminder.date
    day_after = d + timedelta(days=1)
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Binärgewitter Live Podcast Schedule//EN",
        "CALSCALE:GREGORIAN",
        "BEGIN:VEVENT",
        f"UID:{reminder.uid}",
        f"DTSTAMP:{dtstamp}",
        f"DTSTART;VALUE=DATE:{d.strftime('%Y%m%d')}",
        f"DTEND;VALUE=DATE:{day_after.strftime('%Y%m%d')}",
        f"SUMMARY:{_ical_escape(reminder.title)}",
        f"DESCRIPTION:{_ical_escape(reminder.description)}",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    return "\r\n".join(lines)


def _unfold(text: str) -> str:
    # RFC 5545: a fold is a CRLF plus ONE leading space/tab on the next
    # physical line; unfolding removes exactly that CRLF+WSP pair, line by
    # line. Global replacement corrupts values that legitimately contain
    # tabs/newlines around the fold positions.
    lines = text.replace("\r\n", "\n").split("\n")
    logical = []
    for line in lines:
        if logical and line[:1] in (" ", "\t"):
            logical[-1] += line[1:]
        else:
            logical.append(line)
    return "\n".join(logical)


def _clean_text(value: str) -> str:
    # A bare CR inside a value survives the \n line split; stored verbatim it
    # becomes an ICS line break (RFC 5545 §3.1) and injects fake properties
    # into every client's view. NUL would corrupt the _ical_unescape
    # placeholder and is illegal in XML. Strip both at the border.
    return _ical_unescape(value.replace("\x00", "").replace("\r", ""))


def _parse_vevent(body: str):
    """Parse SUMMARY/DESCRIPTION/DTSTART/UID from the first VEVENT; None when absent."""
    unfolded = _unfold(body)
    try:
        start = unfolded.index("BEGIN:VEVENT")
    except ValueError:
        return None
    end = unfolded.find("END:VEVENT", start)
    if end == -1:
        return None
    block = unfolded[start + len("BEGIN:VEVENT") : end]

    fields = {}
    for line in block.replace("\r\n", "\n").split("\n"):
        line = line.strip()
        if not line or ":" not in line:
            continue
        name_part, value = line.split(":", 1)
        name = name_part.split(";", 1)[0].strip().upper()
        if name in ("RRULE", "RDATE", "EXDATE", "RECURRENCE-ID"):
            # Recurrence would be silently dropped by the single-day model;
            # reject so clients don't show an event the server never stored.
            return None
        if name in ("UID", "SUMMARY", "DESCRIPTION", "DTSTART"):
            fields[name] = value

    if "DTSTART" not in fields:
        return None
    m = re.search(r"(\d{8})", fields["DTSTART"])
    if not m:
        return None
    try:
        date_value = datetime.strptime(m.group(1), "%Y%m%d").date()
    except ValueError:
        return None

    return {
        "uid": fields.get("UID", "").strip() or None,
        "summary": _clean_text(fields.get("SUMMARY", "").strip()),
        "description": _clean_text(fields.get("DESCRIPTION", "").strip()),
        "date": date_value,
    }


def _reminder_etag(reminder) -> str:
    return hashlib.sha256(_serialize_reminder_vevent(reminder).encode("utf-8")).hexdigest()


def _strip_quotes(value: str) -> str:
    return value.strip().strip('"').strip()


# ---------------------------------------------------------------------------
# XML response builders
# ---------------------------------------------------------------------------

_XML_INVALID_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _xml_escape(text: str) -> str:
    # Control chars are illegal in XML 1.0; leaving them raw breaks the whole
    # multistatus for every client, not just the offending entry.
    text = _XML_INVALID_CHARS.sub("", text)
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _xml_response(body: str, status: int = 207) -> HttpResponse:
    return HttpResponse(body, status=status, content_type="application/xml")


def _propfind_item_response(href: str, etag: str, lastmod: str) -> str:
    # Thunderbird's CalDavEtagHandler wipes items whose response lacks a quoted
    # getetag or getcontenttype, and item responses must NOT carry resourcetype.
    return (
        f"<D:response><D:href>{_xml_escape(href)}</D:href><D:propstat><D:prop>"
        f"<D:getetag>&quot;{etag}&quot;</D:getetag>"
        "<D:getcontenttype>text/calendar; charset=utf-8</D:getcontenttype>"
        f"<D:getlastmodified>{lastmod}</D:getlastmodified>"
        "</D:prop><D:status>HTTP/1.1 200 OK</D:status></D:propstat></D:response>"
    )


def _multistatus(responses: list) -> HttpResponse:
    body = (
        XML_HEADER
        + '<D:multistatus xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav"'
        ' xmlns:CS="http://calendarserver.org/ns/">'
        + "".join(responses)
        + "</D:multistatus>"
    )
    return _xml_response(body, status=207)


def _http_date(dt) -> str:
    # Locale-independent RFC 7231 date (strftime %a/%b follows the process locale).
    return http_date(dt.timestamp())


def _collection_etag(reminders) -> str:
    material = "|".join(f"{r.uid}:{_reminder_etag(r)}" for r in reminders)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Collection view: OPTIONS / PROPFIND / REPORT
# ---------------------------------------------------------------------------

def _options_response(allow: str) -> HttpResponse:
    response = HttpResponse(status=200)
    response["DAV"] = "1, 3, calendar-access"
    # Advertise exactly what each endpoint dispatches; a shared blanket list
    # makes clients negotiate writes the endpoint then rejects with 405.
    response["Allow"] = allow
    response["MS-Author-Via"] = "DAV"
    return response


def _collection_propfind_response(reminders) -> str:
    return (
        f"<D:response><D:href>{COLLECTION_PATH}</D:href><D:propstat><D:prop>"
        "<D:resourcetype><D:collection/><C:calendar/></D:resourcetype>"
        "<D:displayname>BGT Podcast-Kalender</D:displayname>"
        "<D:current-user-privilege-set>"
        "<D:privilege><D:read/></D:privilege>"
        "<D:privilege><D:write/></D:privilege>"
        "<D:privilege><D:all/></D:privilege>"
        "</D:current-user-privilege-set>"
        '<C:supported-calendar-component-set><C:comp name="VEVENT"/></C:supported-calendar-component-set>'
        "<D:supported-report-set>"
        "<D:supported-report><D:report><D:target><C:calendar-multiget/></D:target></D:report></D:supported-report>"
        "<D:supported-report><D:report><D:target><C:calendar-query/></D:target></D:report></D:supported-report>"
        "</D:supported-report-set>"
        f"<CS:getctag>{_collection_etag(reminders)}</CS:getctag>"
        "</D:prop><D:status>HTTP/1.1 200 OK</D:status></D:propstat></D:response>"
    )


@csrf_exempt
@basic_dav_auth
def dav_collection(request):
    from .models import Reminder

    if request.method == "OPTIONS":
        return _options_response("OPTIONS, PROPFIND, REPORT")

    if request.method == "GET":
        return HttpResponseNotAllowed(["OPTIONS", "PROPFIND", "REPORT"])

    if request.method == "PROPFIND":
        depth = request.headers.get("Depth", "infinity")
        # RFC 4918 §9.5: only 0/1/infinity are defined; fail closed on garbage
        # instead of silently returning an item-less collection.
        if depth not in ("0", "1", "infinity"):
            return HttpResponse("Invalid Depth header", status=400)
        reminders = list(Reminder.objects.all())
        responses = [_collection_propfind_response(reminders)]
        if depth == "1":
            for r in reminders:
                responses.append(
                    _propfind_item_response(
                        f"{COLLECTION_PATH}{r.uid}.ics",
                        _reminder_etag(r),
                        _http_date(r.updated_at),
                    )
                )
        return _multistatus(responses)

    if request.method == "REPORT":
        return _dav_report(request)

    return HttpResponseNotAllowed(["OPTIONS", "PROPFIND", "REPORT"])


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if tag.startswith("{") else tag


UID_PATH_RE = re.compile(r"[A-Za-z0-9._@+-]{1,64}\Z")

def _dav_report(request):
    from .models import Reminder

    declared = request.headers.get("Content-Length")
    if declared is not None:
        # Reject by declared length before the body is buffered: chunked
        # uploads bypass DATA_UPLOAD_MAX_MEMORY_SIZE, so the post-read check
        # below alone would still let an oversized body stream fully into RAM.
        try:
            if int(declared) > MAX_BODY_BYTES:
                return HttpResponse("Payload too large", status=413)
        except ValueError:
            return HttpResponse("Invalid Content-Length", status=400)
    body = request.body
    if len(body) > MAX_BODY_BYTES:
        return HttpResponse("Payload too large", status=413)
    # stdlib expat expands internal DTD entities after the raw-byte cap is
    # measured; DAV request bodies never need a DTD, so reject them outright.
    lowered = body[:MAX_BODY_BYTES + 1].lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        return HttpResponse("DTD not allowed", status=400)

    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError:
        return HttpResponse("Invalid XML", status=400)

    kind = _localname(root.tag)

    if kind == "calendar-multiget":
        responses = []
        for href_el in root.iter(f"{{{DAV_NS}}}href"):
            href = (href_el.text or "").strip()
            uid = None
            if href.startswith(COLLECTION_PATH):
                uid = href[len(COLLECTION_PATH) :]
                if uid.endswith(".ics"):
                    uid = uid[: -len(".ics")]
            # hrefs are echoed back, so echo the sanitized canonical form only;
            # arbitrary client markup must never reach the response body.
            if uid is None or not UID_PATH_RE.match(uid):
                responses.append(_href_status_response("", 404))
                continue
            reminder = Reminder.objects.filter(uid=uid).first()
            if reminder is None:
                responses.append(_href_status_response(f"{COLLECTION_PATH}{uid}.ics", 404))
                continue
            responses.append(_calendar_data_response(f"{COLLECTION_PATH}{uid}.ics", reminder))
        return _multistatus(responses)

    if kind == "calendar-query":
        requested = {
            _localname(el.tag)
            for el in root.iter()
            if _localname(el.tag)
            in ("calendar-data", "getetag", "resourcetype", "getcontenttype", "getlastmodified")
        }
        time_range = None
        for el in root.iter():
            # Apple/DAVx5 send either C:time-range or C:event-filter with start/end
            if _localname(el.tag) in ("time-range", "event-filter"):
                start, end = el.get("start"), el.get("end")
                if start or end:
                    time_range = (start, end)
                    break
        reminders = list(Reminder.objects.all())
        if time_range:
            start_d = _compact_date(time_range[0]) if time_range[0] else None
            end_d = _compact_date(time_range[1]) if time_range[1] else None
            # A present-but-malformed filter must not silently widen the
            # result to the whole collection (RFC 4791 valid-request).
            if (time_range[0] and start_d is None) or (time_range[1] and end_d is None):
                return HttpResponse("Invalid time-range", status=400)
            if start_d:
                reminders = [r for r in reminders if r.date >= start_d]
            if end_d:
                # end is exclusive; events are all-day [date, date+1)
                reminders = [r for r in reminders if r.date < end_d]
        responses = [
            _calendar_data_response(f"{COLLECTION_PATH}{r.uid}.ics", r, requested) for r in reminders
        ]
        return _multistatus(responses)

    return HttpResponse(f"Unsupported report: {kind}", status=400)


def _compact_date(value):
    """Parse CALDAV time-range values (YYYYMMDD'T'HHMMSS'Z' or YYYYMMDD) to date."""
    if not value:
        return None
    m = re.search(r"(\d{8})", value)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y%m%d").date()
    except ValueError:
        return None


def _href_status_response(href: str, status: int) -> str:
    text = "404 Not Found" if status == 404 else f"{status} Error"
    return f"<D:response><D:href>{_xml_escape(href)}</D:href><D:status>HTTP/1.1 {text}</D:status></D:response>"


def _calendar_data_response(href: str, reminder, requested=None) -> str:
    props = []
    if requested is None or "calendar-data" in requested:
        props.append(f"<C:calendar-data>{_xml_escape(_serialize_reminder_vevent(reminder))}</C:calendar-data>")
    if requested is None or "getetag" in requested:
        props.append(f"<D:getetag>&quot;{_reminder_etag(reminder)}&quot;</D:getetag>")
    if requested is None or "resourcetype" in requested:
        props.append("<D:resourcetype/>")
    if requested is None or "getcontenttype" in requested:
        props.append("<D:getcontenttype>text/calendar; charset=utf-8</D:getcontenttype>")
    if requested is None or "getlastmodified" in requested:
        props.append(f"<D:getlastmodified>{_http_date(reminder.updated_at)}</D:getlastmodified>")
    return (
        f"<D:response><D:href>{_xml_escape(href)}</D:href><D:propstat><D:prop>"
        + "".join(props)
        + "</D:prop><D:status>HTTP/1.1 200 OK</D:status></D:propstat></D:response>"
    )


# ---------------------------------------------------------------------------
# Item view: /dav/calendar/<uid>.ics
# ---------------------------------------------------------------------------

@csrf_exempt
@basic_dav_auth
def dav_item(request, uid):
    from .models import Reminder

    if not UID_PATH_RE.match(uid):
        return HttpResponse("Not found", status=404)
    if request.method == "OPTIONS":
        return _options_response("OPTIONS, GET, HEAD, PROPFIND, PUT, DELETE")

    # RFC 9110: HEAD must be supported wherever GET is.
    if request.method in ("GET", "HEAD"):
        reminder = Reminder.objects.filter(uid=uid).first()
        if reminder is None:
            return HttpResponse("Not found", status=404)
        response = HttpResponse(
            _serialize_reminder_vevent(reminder) if request.method == "GET" else b"",
            content_type="text/calendar; charset=utf-8",
        )
        response["ETag"] = f'"{_reminder_etag(reminder)}"'
        return response

    if request.method == "PROPFIND":
        reminder = Reminder.objects.filter(uid=uid).first()
        if reminder is None:
            return HttpResponse("Not found", status=404)
        href = f"{COLLECTION_PATH}{uid}.ics"
        body = (
            f"<D:response><D:href>{_xml_escape(href)}</D:href><D:propstat><D:prop>"
            f"<D:getetag>&quot;{_reminder_etag(reminder)}&quot;</D:getetag>"
            "<D:getcontenttype>text/calendar; charset=utf-8</D:getcontenttype>"
            "<D:resourcetype/>"
            f"<D:getlastmodified>{_http_date(reminder.updated_at)}</D:getlastmodified>"
            "</D:prop><D:status>HTTP/1.1 200 OK</D:status></D:propstat></D:response>"
        )
        return _multistatus([body])

    if request.method == "PUT":
        return _dav_put(request, uid)

    if request.method == "DELETE":
        reminder = Reminder.objects.filter(uid=uid).first()
        if reminder is None:
            return HttpResponse("Not found", status=404)
        reminder.delete()
        _regenerate_ical("CalDAV delete")
        return HttpResponse(status=204)

    return HttpResponseNotAllowed(["OPTIONS", "GET", "HEAD", "PROPFIND", "PUT", "DELETE"])


def _dav_put(request, uid):
    from .models import Reminder

    declared = request.headers.get("Content-Length")
    if declared is not None:
        # Reject by declared length before the body is buffered: chunked
        # uploads bypass DATA_UPLOAD_MAX_MEMORY_SIZE, so the post-read check
        # below alone would still let an oversized body stream fully into RAM.
        try:
            if int(declared) > MAX_BODY_BYTES:
                return HttpResponse("Payload too large", status=413)
        except ValueError:
            return HttpResponse("Invalid Content-Length", status=400)
    body = request.body
    if len(body) > MAX_BODY_BYTES:
        return HttpResponse("Payload too large", status=413)

    parsed = _parse_vevent(body.decode("utf-8", errors="replace"))
    if parsed is None:
        return HttpResponse("Invalid iCalendar data", status=400)

    existing = Reminder.objects.filter(uid=uid).first()

    if_none_match = request.headers.get("If-None-Match")
    if_match = request.headers.get("If-Match")

    if if_none_match == "*" and existing is not None:
        return HttpResponse(status=409)

    # RFC 7232: If-Match must fail (412) both on a stale etag and on a
    # missing resource, so a client retry after DELETE cannot silently
    # resurrect the event.
    if if_match and (existing is None or _strip_quotes(if_match) != _reminder_etag(existing)):
        return HttpResponse(status=412)

    body_uid = parsed["uid"]
    if body_uid and body_uid != uid:
        # RFC 4791: the body UID must match the item URL. Storing a different
        # UID under the URL UID leaves clients keyed on their own UID with a
        # permanent 404 (phantom event), so reject the mismatch outright.
        return HttpResponse("UID mismatch between body and request path", status=400)

    title = parsed["summary"] or "Erinnerung"
    # CharField max_length is not enforced by save(); an overlong SUMMARY
    # would 500 with a Postgres DataError instead of a clean 400.
    if len(title) > 200:
        return HttpResponse("SUMMARY too long (max 200 characters)", status=400)
    if existing is not None:
        existing.title = title
        existing.date = parsed["date"]
        existing.description = parsed["description"]
        existing.save()
    else:
        try:
            Reminder.objects.create(
                uid=uid,
                title=title,
                date=parsed["date"],
                description=parsed["description"],
                created_by=request.dav_user,
            )
        except IntegrityError:
            # Lost a race against a concurrent PUT/JSON-create for this uid.
            return HttpResponse("Conflict", status=409)
    _regenerate_ical("CalDAV save")
    return HttpResponse(status=204)


def _regenerate_ical(reason: str) -> None:
    from .ical import generate_ical_file

    try:
        generate_ical_file()
    except Exception as e:
        logger.error(f"Failed to regenerate iCal after {reason}: {e}")
