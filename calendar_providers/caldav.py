import pickle
import caldav
from utility import is_stale
import os
import logging
import datetime
from zoneinfo import ZoneInfo
from .base_provider import BaseCalendarProvider, CalendarEvent


ttl = float(os.getenv("CALENDAR_TTL", 1 * 60 * 60))
LOCAL_TZ = ZoneInfo(os.getenv("LOCAL_TIMEZONE", "Europe/Zurich"))

class CalDavCalendar(BaseCalendarProvider):

    def __init__(self, calendar_url, calendar_id, max_event_results, from_date, to_date, username=None, password=None):
        self.calendar_url = calendar_url
        self.calendar_id = calendar_id
        self.max_event_results = max_event_results
        self.username = username
        self.password = password
        self.from_date = from_date
        self.to_date = to_date

    def _ensure_datetime(self, v):
        # Turn date -> datetime @ midnight local
        if isinstance(v, datetime.date) and not isinstance(v, datetime.datetime):
            v = datetime.datetime.combine(v, datetime.time.min)
        # If naive, assume local timezone
        if v.tzinfo is None:
            v = v.replace(tzinfo=LOCAL_TZ)
        # Normalize to UTC (choose UTC internally)
        return v.astimezone(datetime.timezone.utc)

    def get_calendar_events(self):

        caldav_calendar_pickle = f'cache_caldav_{self.calendar_id}.pickle'
        calendar_events: list[CalendarEvent] = []

        if is_stale(os.getcwd() + "/" + caldav_calendar_pickle, ttl):
            logging.debug("Pickle is stale, fetching CalDav Calendar")

            with caldav.DAVClient(url=self.calendar_url, username=self.username, password=self.password) as client:
                my_principal = client.principal()
                calendar = my_principal.calendar(cal_id=self.calendar_id)
                event_results = calendar.date_search(start=self.from_date, end=self.to_date, expand=True)

                components = []
                for result in event_results:
                    ical = result.icalendar_instance
                    for component in getattr(ical, "subcomponents", []):
                        name = getattr(component, "name", "").upper()
                        if name != "VEVENT":
                            continue
                        if 'DTSTART' not in component:
                            # Unexpected, but be defensive
                            logging.warning(
                                "Skipping VEVENT without DTSTART (UID=%s)",
                                component.get('UID', '?')
                            )
                            continue
                        components.append(component)

            if not components:
                logging.info("No VEVENT components with a DTSTART found in the requested range.")
                # Cache empty list
                with open(caldav_calendar_pickle, 'wb') as cal:
                    pickle.dump(calendar_events, cal)
                return calendar_events

            # Sort by DTSTART safely
            components.sort(key=lambda x: x.get('DTSTART').dt)

            for component in components[0:self.max_event_results]:
                start_prop = component.get('DTSTART')
                if start_prop is None:
                    # Should not happen after filtering, but guard anyway
                    logging.debug("Skipping component missing DTSTART after filter.")
                    continue
                start_raw = start_prop.dt

                # Determine end
                if 'DTEND' in component:
                    event_end = component['DTEND'].dt
                elif 'DURATION' in component:
                    event_end = start_raw + component['DURATION'].dt
                else:
                    event_end = start_raw  # zero-length fallback

                all_day_event = False
                # All-day events: DTEND is exclusive date; subtract one day
                if isinstance(event_end, datetime.date) and not isinstance(event_end, datetime.datetime):
                    event_end = event_end - datetime.timedelta(days=1)
                    all_day_event = True

                start_norm = self._ensure_datetime(start_raw)
                end_norm = self._ensure_datetime(event_end)

                calendar_events.append(
                    CalendarEvent(str(component.get('SUMMARY', '')), start_norm, end_norm, all_day_event)
                )

            # Now a simple sort works (all UTC aware)
            calendar_events.sort(key=lambda e: e.start)

            with open(caldav_calendar_pickle, 'wb') as cal:
                pickle.dump(calendar_events, cal)
        else:
            logging.info("Found in cache")
            with open(caldav_calendar_pickle, 'rb') as cal:
                calendar_events = pickle.load(cal)

        return calendar_events
