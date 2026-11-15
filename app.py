from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
import subprocess
import sys
import time

import requests
from flask import Flask, jsonify, redirect, render_template, request, url_for

from curriculum import Curriculum, burnup

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(BASE_DIR, 'users.json')) as f:
    users_info = json.load(f)

# TryHackMe blocks datacenter IPs (Vercel included), so this app never calls THM itself.
# Data comes from collector.py, which runs on a host with a residential exit:
#   - COLLECTOR_URL set (Vercel): read/refresh through the collector API (collector_api.py)
#   - otherwise (collector host): read data/thm.json directly
COLLECTOR_URL = os.environ.get('COLLECTOR_URL', '').rstrip('/')
COLLECTOR_SECRET = os.environ.get('COLLECTOR_SECRET', '')
DATA_FILE = os.path.join(BASE_DIR, 'data', 'thm.json')
_REMOTE_CACHE = {'ts': 0, 'data': None, 'ok': False}
REMOTE_CACHE_TTL = 60  # seconds
STALE_AFTER = timedelta(hours=1)  # sync runs every 15 min; older than this means something is wrong
WIB = timezone(timedelta(hours=7))
CUR = Curriculum()
MONTHS_ID = ['Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni', 'Juli', 'Agustus', 'September',
             'Oktober', 'November', 'Desember']
DAYS_ID = ['Senin', 'Selasa', 'Rabu', 'Kamis', 'Jumat', 'Sabtu', 'Minggu']


def today_wib():
    return datetime.now(WIB).date()


# --------------------------------------------------------------------------- data source

def _collector(method, path, **kw):
    return requests.request(method, f'{COLLECTOR_URL}{path}', timeout=8,
                            headers={'X-Collector-Secret': COLLECTOR_SECRET}, **kw)


def _load_store():
    """Return (store, reachable)."""
    if COLLECTOR_URL:
        if _REMOTE_CACHE['data'] and time.time() - _REMOTE_CACHE['ts'] < REMOTE_CACHE_TTL:
            return _REMOTE_CACHE['data'], _REMOTE_CACHE['ok']
        try:
            r = _collector('GET', '/api/data')
            r.raise_for_status()
            _REMOTE_CACHE.update(ts=time.time(), data=r.json(), ok=True)
        except (requests.RequestException, ValueError):
            _REMOTE_CACHE.update(ts=time.time(), ok=False)  # serve the last copy we had, if any
        return _REMOTE_CACHE['data'] or {'users': {}}, _REMOTE_CACHE['ok']
    try:
        with open(DATA_FILE) as f:
            return json.load(f), True
    except (FileNotFoundError, ValueError):
        return {'users': {}}, True


# --------------------------------------------------------------------------- view model

def _parse_iso(iso):
    try:
        return datetime.fromisoformat(iso.replace('Z', '+00:00')) if iso else None
    except ValueError:
        return None


def _fmt_wib(iso, fmt='%d %b %Y, %H:%M WIB'):
    dt = _parse_iso(iso)
    return dt.astimezone(WIB).strftime(fmt) if dt else None


def activity_level(count):
    """Fixed thresholds (not per-user quantiles) so heatmaps are comparable across people.
    Calibrated on the cohort's active days: median ~40, p75 ~110, p90 ~210 activities/day."""
    if count <= 0:
        return 0
    if count <= 15:
        return 1
    if count <= 50:
        return 2
    if count <= 150:
        return 3
    return 4


def _activity_map(activity):
    return {a['date']: a['count'] for a in activity}


def _week_strip(amap, today):
    days = [today - timedelta(days=i) for i in range(6, -1, -1)]
    return [{'date': d.isoformat(), 'label': d.strftime('%a %d %b'), 'count': amap.get(d.isoformat(), 0),
             'level': activity_level(amap.get(d.isoformat(), 0))} for d in days]


def _days_since_active(amap, today):
    active_days = [d for d, c in amap.items() if c > 0 and d <= today.isoformat()]
    if not active_days:
        return None
    return (today - date.fromisoformat(max(active_days))).days


def _heatmap(amap, year, today):
    """GitHub-style calendar: list of week columns (Mon-first), each with 7 cells (None = outside year)."""
    start, end = date(year, 1, 1), date(year, 12, 31)
    cursor = start - timedelta(days=start.weekday())
    weeks, months = [], []
    while cursor <= end:
        col = []
        for i in range(7):
            d = cursor + timedelta(days=i)
            if d.year != year:
                col.append(None)
            else:
                c = amap.get(d.isoformat(), 0)
                col.append({'date': d.isoformat(), 'label': d.strftime('%d %b %Y'), 'count': c,
                            'level': activity_level(c), 'future': d > today})
        first_of_month = next((x for x in col if x and x['date'].endswith('-01')), None)
        if first_of_month:  # label the month above the week column that contains its 1st
            months.append({'label': date.fromisoformat(first_of_month['date']).strftime('%b'), 'col': len(weeks)})
        weeks.append(col)
        cursor += timedelta(days=7)
    return {'weeks': weeks, 'months': months}


def soc_status(certificates):
    l1 = l2 = None
    other = []
    for c in certificates:
        key = (c.get('name') or '').lower().replace('-', '').replace('_', '').replace(' ', '')
        if 'soclevel1' in key:
            l1 = c
        elif 'soclevel2' in key:
            l2 = c
        else:
            other.append(c)
    return {'l1': l1, 'l2': l2, 'count': (l1 is not None) + (l2 is not None), 'other': other}


def get_user_data(user_info, store):
    entry = store.get('users', {}).get(user_info['username'], {})
    p = entry.get('profile') or {}
    today = datetime.now(timezone.utc).date()
    amap = _activity_map(entry.get('activity', []))
    year = entry.get('activity_year', today.year)
    year_activity = {d: c for d, c in amap.items() if d <= today.isoformat()}
    week = _week_strip(amap, today)
    weekly = sum(d['count'] for d in week)
    days_idle = _days_since_active(amap, today)

    return {
        'username': user_info['username'],
        'name': user_info.get('full_name') or user_info['username'],
        'has_data': bool(p),
        'rank': p.get('rank'),
        'points': round(p.get('totalPoints') or 0),
        'level': p.get('level'),
        'top_percentage': p.get('topPercentage'),
        'rooms': p.get('completedRoomsNumber') or 0,
        'badges_number': p.get('badgesNumber') or 0,
        'avatar': p.get('avatar') or '',
        'country': (p.get('country') or '').upper(),
        'streak': p.get('streak') or 0,
        'completed_rooms': entry.get('completed_rooms', []),
        'badges': sorted(entry.get('badges', []), key=lambda b: b.get('earned_at') or '', reverse=True),
        'soc': soc_status(entry.get('certificates', [])),
        'week': week,
        'weekly': weekly,
        'active': weekly > 0,
        'days_idle': days_idle,
        'year': year,
        'year_total': sum(year_activity.values()),
        'year_active_days': sum(1 for c in year_activity.values() if c > 0),
        'heatmap': _heatmap(amap, year, today),
        'fetched_at': entry.get('fetched_at'),
        'fetched_at_fmt': _fmt_wib(entry.get('fetched_at')),
        'last_error': entry.get('last_error'),
        'cur': CUR.progress(entry, today_wib()),
    }


def sync_info(store, reachable):
    last = _parse_iso(store.get('last_run'))
    stale = last is None or datetime.now(timezone.utc) - last > STALE_AFTER
    return {'iso': store.get('last_run'), 'fmt': _fmt_wib(store.get('last_run')),
            'stale': stale, 'reachable': reachable}


def program_info(today):
    done_days, total_days = CUR.day_index(today)
    nd = CUR.next_day(today)
    part = next((p for p in CUR.parts if date.fromisoformat(p['start']) <= (nd['date'] if nd else today)
                 <= date.fromisoformat(p['end'])), None)
    return {
        'name': CUR.name, 'period': CUR.period, 'done_days': done_days, 'total_days': total_days,
        'started': today >= CUR.start, 'finished': today > CUR.end,
        'today': CUR.day_by_date.get(today), 'is_today': nd is not None and nd['date'] == today,
        'next_day': nd, 'part': part, 'milestone': CUR.next_milestone(today), 'em': CUR.next_em(today),
        'planned': CUR.planned_by(today - timedelta(days=1)), 'total_rooms': CUR.total,
        'week': CUR.week(today), 'today_date': today,
    }


def team_view(people, today):
    """Shared numbers for the curriculum blocks on the overview."""
    n = len(people) or 1
    for p in people:
        p['chart'] = burnup(CUR, p['cur']['history'], today)
    by_status = {k: sum(p['cur']['status'] == k for p in people) for k in ('ok', 'warning', 'critical')}
    milestones = []
    for i, m in enumerate(CUR.milestones):
        states = [p['cur']['milestones'][i]['state'] for p in people]
        milestones.append({'code': m['code'], 'name': m['name'], 'date': m['date'], 'criteria': m['criteria'],
                           'done': states.count('done'), 'missed': states.count('missed'),
                           'past': m['date'] < today, 'next': CUR.next_milestone(today) is m})
    scheduled = {c for d in CUR.days if d['date'] <= today for c in d['sections']}
    nd = CUR.next_day(today)
    current = set(nd['sections']) if nd else set()
    return {
        'status': by_status,
        'avg_done': round(sum(p['cur']['done'] for p in people) / n),
        'avg_pct': sum(p['cur']['pct'] for p in people) / n,
        'milestones': milestones,
        'sections': [dict(s, due=s['code'] in scheduled and date.fromisoformat(s['end']) < today,
                          current=s['code'] in current) for s in CUR.sections],
    }


@app.template_filter('idate')
def idate_filter(d, fmt='short'):
    """Indonesian dates: short '24 Nov', long 'Selasa, 24 November 2026', day 'Senin'."""
    if not d:
        return ''
    if isinstance(d, str):
        d = date.fromisoformat(d[:10])
    if fmt == 'day':
        return DAYS_ID[d.weekday()]
    if fmt == 'long':
        return f'{DAYS_ID[d.weekday()]}, {d.day} {MONTHS_ID[d.month - 1]} {d.year}'
    if fmt == 'month':
        return f'{MONTHS_ID[d.month - 1]} {d.year}'
    return f'{d.day} {MONTHS_ID[d.month - 1][:3]}'


@app.template_filter('wib')
def wib_filter(iso, fmt='%d %b %Y'):
    return _fmt_wib(iso, fmt) or ''


@app.template_filter('cert_title')
def cert_title_filter(cert):
    """Certificates sometimes come without a title, only a slug like 'pathway-introtocyber'."""
    if cert.get('title'):
        return cert['title']
    slug = (cert.get('name') or '').removeprefix('pathway-')
    known = {'introtocyber': 'Intro to Cyber Security', 'presecurity': 'Pre Security',
             'soclevel1': 'SOC Level 1', 'soclevel2': 'SOC Level 2', 'cybersecurity101': 'Cyber Security 101'}
    return known.get(slug, slug.replace('-', ' ').title() or 'Learning path')


@app.template_filter('thousands')
def thousands_filter(n):
    if n is None:
        return '–'
    if isinstance(n, float):
        n = round(n)  # THM sometimes returns points as a float (e.g. 15649.399999999987)
    return f'{n:,}'.replace(',', '.') if isinstance(n, int) else n


# --------------------------------------------------------------------------- routes

def _asset_version(*names):
    h = hashlib.sha1()
    for n in names:
        with open(os.path.join(BASE_DIR, 'static', n), 'rb') as f:
            h.update(f.read())
    return h.hexdigest()[:10]


ASSET_V = _asset_version('css/app.css', 'js/app.js')  # changes on every deploy that edits them


@app.context_processor
def inject_asset_version():
    return {'asset_v': ASSET_V}


@app.after_request
def cache_headers(resp):
    # Pages are the same for every visitor and data changes at most every 15 minutes, so let the
    # Vercel CDN serve them: fresh for 60 s, then stale copies are served instantly while one
    # request regenerates in the background. Visitors never wait for a cold start + collector fetch.
    if request.method == 'GET' and resp.status_code == 200 and resp.mimetype == 'text/html':
        resp.headers['Cache-Control'] = 'public, max-age=0, must-revalidate'
        resp.headers['CDN-Cache-Control'] = 'public, s-maxage=60, stale-while-revalidate=86400'
    elif request.path.startswith('/static/'):
        # css/js URLs carry ?v=<content hash>, so they can be cached for a long time.
        resp.headers['Cache-Control'] = 'public, max-age=31536000, immutable' if request.args.get('v') \
            else 'public, max-age=86400'
    return resp


@app.route('/favicon.ico')
def favicon():
    return redirect(url_for('static', filename='favicon-32.png'), code=301)


@app.route('/')
def index():
    store, reachable = _load_store()
    people = [get_user_data(u, store) for u in users_info]
    people.sort(key=lambda x: (x['cur']['done'], x['rooms'], x['points']), reverse=True)
    for i, person in enumerate(people, 1):
        person['position'] = i
    n = len(people)
    summary = {
        'total': n,
        'active': sum(p['active'] for p in people),
        'rooms_total': sum(p['rooms'] for p in people),
        'rooms_avg': round(sum(p['rooms'] for p in people) / n) if n else 0,
        'soc_l1': sum(p['soc']['l1'] is not None for p in people),
        'soc_l2': sum(p['soc']['l2'] is not None for p in people),
        'max_rooms': max((p['rooms'] for p in people), default=0) or 1,
    }
    today = today_wib()
    team = team_view(people, today)
    catchup = sorted(people, key=lambda p: (-p['cur']['behind'], p['name'].lower()))
    return render_template('index.html', people=people, summary=summary, sync=sync_info(store, reachable),
                           program=program_info(today), team=team, catchup=catchup, cur=CUR)


@app.route('/kurikulum')
def curriculum_page():
    store, reachable = _load_store()
    today = today_wib()
    people = [get_user_data(u, store) for u in users_info]
    team = team_view(people, today)
    return render_template('curriculum.html', people=people, cur=CUR, months=CUR.months(today), team=team,
                           program=program_info(today), sync=sync_info(store, reachable))


@app.route('/user/<username>')
def user_detail(username):
    user_info = next((u for u in users_info if u['username'] == username), None)
    store, reachable = _load_store()
    if not user_info:
        return render_template('user_detail.html', person=None, sync=sync_info(store, reachable)), 404
    person = get_user_data(user_info, store)
    today = today_wib()
    person['chart'] = burnup(CUR, person['cur']['history'], today, width=720, height=200)
    return render_template('user_detail.html', person=person, cur=CUR, program=program_info(today),
                           sync=sync_info(store, reachable))


def _trigger_refresh(username=None):
    if COLLECTOR_URL:
        try:
            r = _collector('POST', '/api/refresh', params={'username': username} if username else None)
            _REMOTE_CACHE['ts'] = 0  # next page load fetches fresh data
            return jsonify(r.json()), r.status_code
        except (requests.RequestException, ValueError):
            return jsonify({'status': 'error', 'message': 'Collector tidak bisa dihubungi'}), 502
    cmd = [sys.executable, os.path.join(BASE_DIR, 'collector.py')] + ([username] if username else [])
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    return jsonify({'status': 'started', 'eta_seconds': 10 if username else 120})


@app.route('/user/<username>/refresh', methods=['POST'])
def refresh_user(username):
    if not any(u['username'] == username for u in users_info):
        return jsonify({'status': 'error', 'message': 'User tidak ditemukan'}), 404
    return _trigger_refresh(username)


@app.route('/refresh_all', methods=['POST'])
def refresh_all():
    return _trigger_refresh()


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=int(os.environ.get('PORT', 8000)))
