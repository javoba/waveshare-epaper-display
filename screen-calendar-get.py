import datetime
import os.path
import os
import logging
import emoji
from xml.sax.saxutils import escape
from calendar_providers.base_provider import CalendarEvent
from calendar_providers.caldav import CalDavCalendar
from calendar_providers.google import GoogleCalendar
from calendar_providers.ics import ICSCalendar
from calendar_providers.outlook import OutlookCalendar
from utility import get_formatted_time, update_svg, configure_logging, get_formatted_date, configure_locale

configure_locale()
configure_logging()

# note: increasing this will require updates to the SVG template to accommodate more events

google_calendar_id = os.getenv("GOOGLE_CALENDAR_ID", "primary")
outlook_calendar_id = os.getenv("OUTLOOK_CALENDAR_ID", None)

caldav_calendar_url = os.getenv('CALDAV_CALENDAR_URL', None)
caldav_username = os.getenv("CALDAV_USERNAME", None)
caldav_password = os.getenv("CALDAV_PASSWORD", None)
caldav_calendar_ids = os.getenv("CALDAV_CALENDAR_IDS", None)
screen_layout = os.getenv("SCREEN_LAYOUT", None)

if screen_layout == "6":
    max_event_results = 100
else:
    max_event_results = 10

ics_calendar_url = os.getenv("ICS_CALENDAR_URL", None)

ttl = float(os.getenv("CALENDAR_TTL", 1 * 60 * 60))

def get_weekly_formatted_calendar_events(fetched_events: list[CalendarEvent], start_day) -> dict:
    formatted_events = {}
    for day, events in fetched_events.items():
        formatted_events[f'WEEKDAY_{day}'] = (start_day + datetime.timedelta(days=day)).strftime("%A")
        for index, event in enumerate(events):
            formatted_events[f'BOX_{day}_{index}_STROKE']="#000"
            try:
                formatted_events[f'DATE_{day}_{index}'] = get_datetime_formatted(event.start, event.end, event.all_day_event).split(" - ")[0].split()[1]
            except IndexError:
                formatted_events[f'DATE_{day}_{index}'] = "All Day"
            formatted_events[f'EVENTS_{day}_{index}'] = event.summary[:15].replace("(+) ","")
        if len(events) < 3:
            for index in range(len(events), 3):
                formatted_events[f'BOX_{day}_{index}_STROKE']="none"
                formatted_events[f'DATE_{day}_{index}'] = ""
                formatted_events[f'EVENTS_{day}_{index}'] = ""
    print(formatted_events)
    return formatted_events

def get_formatted_calendar_events(fetched_events: list[CalendarEvent]) -> dict:
    formatted_events = {}
    event_count = len(fetched_events)

    for index in range(max_event_results):
        event_label_id = str(index + 1)
        if index <= event_count - 1:
            formatted_events['CAL_DATETIME_' + event_label_id] = get_datetime_formatted(fetched_events[index].start, fetched_events[index].end, fetched_events[index].all_day_event)
            formatted_events['CAL_DATETIME_START_' + event_label_id] = get_datetime_formatted(fetched_events[index].start, fetched_events[index].end, fetched_events[index].all_day_event, True)
            formatted_events['CAL_DESC_' + event_label_id] = fetched_events[index].summary
        else:
            formatted_events['CAL_DATETIME_' + event_label_id] = ""
            formatted_events['CAL_DESC_' + event_label_id] = ""

    return formatted_events

def get_daily_events(calendar_events: list[CalendarEvent], start_day) -> list[CalendarEvent]:
    weekly_events = {}
    for day in range(0,7):
        daily_events = []
        for event in calendar_events:
            if type(event.start) == datetime.datetime:
                event_day = event.start.date()
            elif type(event.start) == datetime.date:
                event_day = event.start
            day_diff = (event_day - start_day.date()).days
            if day_diff == day:
                daily_events.append(event)
        weekly_events[day] = daily_events
    return weekly_events

def get_datetime_formatted(event_start, event_end, is_all_day_event, start_only=False):

    if is_all_day_event or type(event_start) == datetime.date:
        start = datetime.datetime.combine(event_start, datetime.time.min)
        end = datetime.datetime.combine(event_end, datetime.time.min)

        start_day = get_formatted_date(start, include_time=False)
        end_day = get_formatted_date(end, include_time=False)
        if start == end:
            day = start_day
        else:
            day = "{} - {}".format(start_day, end_day)
    elif type(event_start) == datetime.datetime:
        start_date = event_start
        end_date = event_end
        if start_date.date() == end_date.date():
            start_formatted = get_formatted_date(start_date)
            end_formatted = get_formatted_time(end_date)
        else:
            start_formatted = get_formatted_date(start_date)
            end_formatted = get_formatted_date(end_date)
        day = start_formatted if start_only else "{} - {}".format(start_formatted, end_formatted)
    else:
        day = ''
    return day

def fetch_caldav_events_multi(base_url, ids, max_events, start_dt, end_dt, username, password):
    from calendar_providers.caldav import CalDavCalendar
    aggregated = []
    seen = set()
    for cid in ids:
        provider = CalDavCalendar(base_url, cid, max_events, start_dt, end_dt, username, password)
        events = provider.get_calendar_events()
        for ev in events:
            # Deduplicate by (summary, start, end)
            key = (ev.summary, ev.start, ev.end)
            if key not in seen:
                seen.add(key)
                aggregated.append(ev)
    print(aggregated)
    # Sort by start time
    aggregated.sort(
    key=lambda e: (
        e.start if isinstance(e.start, datetime.datetime)
        else datetime.datetime.combine(e.start, datetime.time.min)
        )
    )
    return aggregated[:max_events]

def main():

    output_svg_filename = 'screen-output-weather.svg'

    today_start_time = datetime.datetime.now().astimezone()
    if os.getenv("CALENDAR_INCLUDE_PAST_EVENTS_FOR_TODAY", "0") == "1":
        today_start_time = datetime.datetime.combine(datetime.datetime.utcnow(), datetime.datetime.min.time())

    if screen_layout == "6":
        time_until_iso = (datetime.datetime.now().astimezone()
                        + datetime.timedelta(days=7)).astimezone()
    else:
        time_until_iso = (datetime.datetime.now().astimezone()
                          + datetime.timedelta(days=365)).astimezone()

    if outlook_calendar_id:
        logging.info("Fetching Outlook Calendar Events")
        provider = OutlookCalendar(outlook_calendar_id, max_event_results, today_start_time, time_until_iso)
    elif caldav_calendar_url:
        if "," in caldav_calendar_ids:
            ids = [c.strip() for c in caldav_calendar_ids.split(",") if c.strip()]
            calendar_events = fetch_caldav_events_multi(
                caldav_calendar_url, ids, max_event_results, today_start_time, time_until_iso,
                caldav_username, caldav_password
            )
        else:
            logging.info("Fetching Caldav Calendar Events")
            provider = CalDavCalendar(caldav_calendar_url, caldav_calendar_ids, max_event_results,
                                  today_start_time, time_until_iso, caldav_username, caldav_password)
            calendar_events = provider.get_calendar_events()

    elif ics_calendar_url:
        logging.info("Fetching ics Calendar Events")
        provider = ICSCalendar(ics_calendar_url, max_event_results, today_start_time, time_until_iso)
    else:
        logging.info("Fetching Google Calendar Events")
        provider = GoogleCalendar(google_calendar_id, max_event_results, today_start_time, time_until_iso)

    if screen_layout == "6":
        daily_events = get_daily_events(calendar_events, today_start_time)
        output_dict = get_weekly_formatted_calendar_events(daily_events, today_start_time)
    else:
        output_dict = get_formatted_calendar_events(calendar_events)

    # XML escape for safety
    for key, value in output_dict.items():
        output_dict[key] = escape(value)

    # Surround emojis with font-family emoji so it's rendered properly. Workaround for cairo not using fallback fonts.
    for key, value in output_dict.items():
        output_dict[key] = emoji.replace_emoji(value,  replace=lambda chars, data_dict: '<tspan style="font-family:emoji">' + chars + '</tspan>')

    logging.info("main() - {}".format(output_dict))

    logging.info("Updating SVG")
    update_svg(output_svg_filename, output_svg_filename, output_dict)


if __name__ == "__main__":
    main()
