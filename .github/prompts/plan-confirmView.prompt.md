## Plan: Add Confirm View with Post-Action Hooks

Add a "Confirm" view showing future dates with 2+ availabilities, with modal confirmation including descriptions, blue calendar styling, unconfirm functionality, apprise notifications, and public CSV export.

### Steps

1. **Create `ConfirmedDate` model** in calendar_app/models.py with `date` (unique), `description` (TextField), `confirmed_by` (ForeignKey to User), and `created_at` fields. Generate and run migration.

2. **Add confirm views** in calendar_app/views.py:
   - `confirm_list_view` — GET page listing future dates with 2+ availabilities (from `DateAvailability`)
   - `confirm_date` — POST to create `ConfirmedDate` with description
   - `unconfirm_date` — POST to delete `ConfirmedDate`
   - `get_confirmed_dates` — API returning all confirmed dates
   - `export_csv` — **Public** (no auth) CSV export of confirmed dates

3. **Register new URL patterns** in calendar_app/urls.py:
   - `confirm/` → `confirm_list_view`
   - `api/confirm/<str:date>/` → `confirm_date`
   - `api/unconfirm/<str:date>/` → `unconfirm_date`
   - `api/confirmed/` → `get_confirmed_dates`
   - `export/calendar.csv` → `export_csv`

4. **Create new template** `templates/calendar_app/confirm.html` with:
   - List of candidate dates with availability count
   - Modal for confirming (description textarea + submit)
   - Modal for unconfirming existing confirmations
   - Fetch confirmed dates from API to show current status

5. **Update calendar template** templates/calendar_app/calendar.html:
   - Add blue CSS styles for `.calendar-day.confirmed` (`#cce5ff` bg, `#007bff` border)
   - Extend JavaScript to fetch confirmed dates and apply `.confirmed` class
   - Handle `confirmation_update` WebSocket messages to update in real-time
   - Add "Confirmed" entry to the legend

6. **Add WebSocket broadcast** in calendar_app/consumers.py:
   - Add `confirmation_update` handler method to broadcast confirmation changes to all clients

7. **Create post-action hooks module** `calendar_app/hooks.py`:
   - Create `PostActionHook` interface (abstract base class) with `on_confirm(date, description)` and `on_unconfirm(date)` methods
   - Implement `AppriseHook` class that sends notifications via apprise library
   - Implement `CSVExportHook` class that regenerates the public CSV file on confirm/unconfirm
   - Add `HOOK_REGISTRY` list for pluggable hooks

8. **Update settings and requirements**:
   - Add `apprise>=1.0.0` to requirements.txt
   - Add `APPRISE_URLS` and `PUBLIC_CSV_PATH` settings in datefinder/settings.py

### Further Considerations

1. **Authorization for confirming dates?** Currently all logged-in users can toggle availability. Should confirming be restricted to admins/specific users, or any authenticated user?
No Need for further restrictions, all human problems are solved in a sidechannel

2. **CSV export location** — Should the public CSV be written to `static/` for WhiteNoise serving, or served dynamically via the view? Static file is simpler but requires write access. 
use a view, nginx will handle caching

3. **Apprise notification format** — What information should be included in notifications? Suggested: date, description, confirmed-by username, and a link to the calendar.
use a jinja2 template to configure the notification message. default should be just the description