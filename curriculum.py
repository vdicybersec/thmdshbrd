"""Bootcamp curriculum (curriculum.json) and per-participant catch-up maths.

Progress counts only curriculum rooms, matched by title against the rooms a participant has
completed on TryHackMe (the public API exposes titles, not room codes or completion dates).
"""
from datetime import date, datetime, timedelta, timezone
import json
import math
import os
import re

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Curriculum title -> THM title, for rooms whose names differ. Add entries here if a room the
# participant clearly finished shows as "belum" on the dashboard.
ALIASES = {
    # Assumed: on THM this is the SOC Simulator scenario, not a regular room.
    'Introduction to Phishing': 'SOC Simulator: Introduction to Phishing',
}

BEHIND_WARNING = 1   # rooms behind schedule before the status turns amber
BEHIND_CRITICAL = 5  # roughly one full day of rooms


def norm(title):
    return re.sub(r'[^a-z0-9]', '', (title or '').lower())


def _d(iso):
    return date.fromisoformat(iso[:10])


class Curriculum:
    def __init__(self, path=os.path.join(BASE_DIR, 'curriculum.json')):
        with open(path) as f:
            raw = json.load(f)
        self.raw = raw
        self.name = raw['name']
        self.period = raw['period']
        self.start, self.end = _d(raw['start']), _d(raw['end'])
        self.parts = raw['parts']
        self.holidays = {_d(h['date']): h['label'] for h in raw['holidays']}
        self.sections = raw['sections']
        self.section_by_code = {s['code']: s for s in self.sections}
        self.rooms = [dict(r, section=s['code'], part=s['part'], key=norm(ALIASES.get(r['title'], r['title'])))
                      for s in self.sections for r in s['rooms']]
        self.total = len(self.rooms)
        self.part_total = {p: sum(r['part'] == p for r in self.rooms) for p in (1, 2)}
        self.days = []
        cum = 0
        for d in raw['days']:
            cum += d['rooms']
            self.days.append(dict(d, date=_d(d['date']), cum=cum,
                                  section_list=[self.section_by_code[c] for c in d['sections']]))
        self.day_by_date = {d['date']: d for d in self.days}
        self.milestones = []
        for m in raw['milestones']:
            # Catch-up target = every room scheduled up to this milestone (cumulative), while the
            # pass/fail check uses the milestone's own acceptance criteria (its listed sections).
            last = m['sections'][-1]
            order = [s['code'] for s in self.sections]
            cum_sections = set(order[:order.index(last) + 1])
            self.milestones.append(dict(m, date=_d(m['date']), criteria_sections=set(m['sections']),
                                        cum_sections=cum_sections))

    # ------------------------------------------------------------------ calendar helpers
    def planned_by(self, d):
        """Rooms scheduled on program days up to and including d."""
        return max([x['cum'] for x in self.days if x['date'] <= d], default=0)

    def working_days(self, a, b):
        """Program days in [a, b]."""
        return sum(1 for x in self.days if a <= x['date'] <= b)

    def day_index(self, today):
        """(days done, total) - a program day counts as done once it is over."""
        return sum(1 for x in self.days if x['date'] < today), len(self.days)

    def next_day(self, today):
        return next((x for x in self.days if x['date'] >= today), None)

    def next_milestone(self, today):
        return next((m for m in self.milestones if m['date'] >= today), None)

    def next_em(self, today):
        return next((x for x in self.days if x['em'] and x['date'] >= today), None)

    def week(self, today):
        """Mon-Fri of the current week; on weekends the coming week."""
        monday = today - timedelta(days=today.weekday())
        if today.weekday() >= 5:
            monday += timedelta(days=7)
        out = []
        for i in range(5):
            d = monday + timedelta(days=i)
            out.append({'date': d, 'day': self.day_by_date.get(d), 'holiday': self.holidays.get(d),
                        'today': d == today, 'past': d < today})
        return out

    def months(self, today):
        """Month grids (Mon-first weeks) covering the program, like the PDF calendar."""
        out = []
        y, m = self.start.year, self.start.month
        while (y, m) <= (self.end.year, self.end.month):
            first = date(y, m, 1)
            nxt = date(y + (m == 12), m % 12 + 1, 1)
            cursor = first - timedelta(days=first.weekday())
            weeks = []
            while cursor < nxt:
                week = []
                for i in range(7):
                    d = cursor + timedelta(days=i)
                    week.append(None if d.month != m else {
                        'date': d, 'day': self.day_by_date.get(d), 'holiday': self.holidays.get(d),
                        'weekend': d.weekday() >= 5, 'today': d == today, 'past': d < today})
                weeks.append(week)
                cursor += timedelta(days=7)
            days_in = [x for x in self.days if x['date'].year == y and x['date'].month == m]
            out.append({'first': first, 'weeks': weeks,
                        'h_range': (days_in[0]['h'], days_in[-1]['h']) if days_in else None})
            y, m = (y + (m == 12), m % 12 + 1)
        return out

    # ------------------------------------------------------------------ per participant
    def done_codes(self, completed_rooms):
        keys = {norm(r.get('title')) for r in completed_rooms}
        return {r['code'] for r in self.rooms if r['key'] in keys}

    def progress(self, entry, today):
        completed = entry.get('completed_rooms', [])
        done = self.done_codes(completed)
        n = len(done)
        done_days, _ = self.day_index(today)
        expected = self.planned_by(today - timedelta(days=1))  # what should be finished by now
        today_day = self.day_by_date.get(today)
        behind = expected - n
        status = 'ok' if behind < BEHIND_WARNING else ('warning' if behind < BEHIND_CRITICAL else 'critical')

        days_left_end = self.working_days(today, self.end)
        remaining = self.total - n
        nm = self.next_milestone(today)
        milestone = None
        if nm:
            need = [r for r in self.rooms if r['section'] in nm['cum_sections'] and r['code'] not in done]
            dl = self.working_days(today, nm['date'])
            milestone = {'code': nm['code'], 'name': nm['name'], 'date': nm['date'], 'need': len(need),
                         'days_left': dl, 'pace': math.ceil(len(need) / dl) if dl else len(need),
                         'total': sum(r['section'] in nm['cum_sections'] for r in self.rooms), 'todo': need}

        sections = []
        for s in self.sections:
            codes = [r['code'] for r in s['rooms']]
            k = sum(c in done for c in codes)
            sections.append({'code': s['code'], 'title': s['title'], 'done': k, 'total': len(codes),
                             'pct': k / len(codes), 'start': _d(s['start']), 'end': _d(s['end'])})
        frontier = next((s for s in sections if s['done'] < s['total']), None)
        # The section the schedule says to work on today (or next program day).
        nd = self.next_day(today)
        scheduled = nd['sections'][-1] if nd else None

        milestones = []
        for m in self.milestones:
            ok = all(r['code'] in done for r in self.rooms if r['section'] in m['criteria_sections'])
            state = 'done' if ok else ('missed' if m['date'] < today else 'pending')
            milestones.append({'code': m['code'], 'name': m['name'], 'date': m['date'], 'state': state})

        # Average pace over finished program days. Rooms finished before the bootcamp are
        # included (THM gives no dates), so treat it as an optimistic estimate.
        pace_now = n / done_days if done_days else None
        projection = None
        if pace_now and remaining > 0:
            need_days = math.ceil(remaining / pace_now)
            future = [x['date'] for x in self.days if x['date'] >= today]
            projection = future[need_days - 1] if need_days <= len(future) else None
            projection = {'date': projection, 'late': projection is None}

        return {
            'done': n, 'done_codes': done, 'total': self.total, 'pct': n / self.total,
            'part_done': {p: sum(c.startswith(f'P{p}') for c in done) for p in (1, 2)},
            'expected': expected, 'behind': behind, 'status': status,
            'today_load': today_day['rooms'] if today_day else 0,
            'remaining': remaining, 'days_left_end': days_left_end,
            'pace_end': math.ceil(remaining / days_left_end) if days_left_end else remaining,
            'milestone': milestone, 'milestones': milestones, 'sections': sections,
            'frontier': frontier, 'scheduled': scheduled, 'pace_now': pace_now, 'projection': projection,
            'outside': max(len(completed) - n, 0),
            'history': self.history(entry, done, today),
        }

    def history(self, entry, done, today):
        """Cumulative curriculum rooms per calendar day, only from the first tracked sync on."""
        seen = entry.get('room_first_seen') or {}
        since = entry.get('tracking_since')
        if not since:
            return {'since': None, 'points': []}
        since_d = _local_date(since)
        title_day = {norm(t): _local_date(ts) for t, ts in seen.items()}
        room_day = [title_day.get(r['key']) for r in self.rooms if r['code'] in done]
        points = []
        d = max(since_d, self.start)
        while d <= min(today, self.end):
            points.append((d, sum(1 for x in room_day if x and x <= d)))
            d += timedelta(days=1)
        return {'since': since_d, 'points': points}


WIB = timezone(timedelta(hours=7))


def _local_date(iso):
    dt = datetime.fromisoformat(iso.replace('Z', '+00:00'))
    return dt.astimezone(WIB).date() if dt.tzinfo else dt.date()


# ---------------------------------------------------------------------- SVG chart geometry

def burnup(cur, history, today, width=320, height=120, pad=(8, 8, 18, 28)):
    """Plan (step) vs actual (line) on a calendar-date x axis. Returns coordinates for the template.
    pad = (top, right, bottom, left)."""
    top, right, bottom, left = pad
    x0, x1 = cur.start, cur.end
    span = (x1 - x0).days or 1
    pw, ph = width - left - right, height - top - bottom
    ymax = cur.total

    def X(d):
        return round(left + (d - x0).days / span * pw, 1)

    def Y(v):
        return round(top + ph - v / ymax * ph, 1)

    # Plan as a step line: flat across weekends/holidays, rising on each program day.
    pts, prev = [], 0
    d = x0
    while d <= x1:
        v = cur.planned_by(d)
        if v != prev:
            pts.append((X(d - timedelta(days=1)) if pts else X(d), Y(prev)))
            pts.append((X(d), Y(v)))
            prev = v
        d += timedelta(days=1)
    plan = 'M' + ' L'.join(f'{a},{b}' for a, b in pts)

    actual = history['points']
    actual_path = ('M' + ' L'.join(f'{X(d)},{Y(v)}' for d, v in actual)) if actual else ''
    last = actual[-1] if actual else None

    hits = []
    step = pw / (span + 1)
    act = dict(actual)
    d = x0
    while d <= x1:
        tip = f"{d.strftime('%d %b')}: rencana {cur.planned_by(d)}"
        if d in act:
            tip += f' · selesai {act[d]}'
        hits.append({'x': round(X(d) - step / 2, 1), 'w': round(step, 1), 'tip': tip})
        d += timedelta(days=1)

    milestones = [{'x': X(m['date']), 'code': m['code']} for m in cur.milestones]
    months = []
    d = date(x0.year, x0.month, 1)
    while d <= x1:
        if d >= x0:
            months.append({'x': X(d), 'label': d.strftime('%b')})
        d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return {
        'w': width, 'h': height, 'plan': plan, 'actual': actual_path,
        'last': {'x': X(last[0]), 'y': Y(last[1]), 'v': last[1]} if last else None,
        'today_x': X(min(max(today, x0), x1)) if x0 <= today <= x1 else None,
        'hits': hits, 'milestones': milestones, 'months': months,
        'y_top': top, 'y_base': top + ph, 'x_left': left, 'x_right': width - right,
        'y_mid': Y(ymax / 2), 'ymax': ymax, 'ymid': ymax // 2,
    }
