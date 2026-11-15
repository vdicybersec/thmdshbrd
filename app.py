from flask import Flask, render_template, jsonify
from datetime import datetime, timedelta, timezone
import json
import os
import subprocess
import sys
import time

import requests

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
_REMOTE_CACHE = {'ts': 0, 'data': None}
REMOTE_CACHE_TTL = 30  # seconds


def _collector(method, path, **kw):
    return requests.request(method, f'{COLLECTOR_URL}{path}', timeout=8,
                            headers={'X-Collector-Secret': COLLECTOR_SECRET}, **kw)


def _load_store():
    if COLLECTOR_URL:
        if _REMOTE_CACHE['data'] and time.time() - _REMOTE_CACHE['ts'] < REMOTE_CACHE_TTL:
            return _REMOTE_CACHE['data']
        try:
            r = _collector('GET', '/api/data')
            r.raise_for_status()
            _REMOTE_CACHE.update(ts=time.time(), data=r.json())
        except (requests.RequestException, ValueError):
            pass  # collector unreachable: serve the last copy we had, if any
        return _REMOTE_CACHE['data'] or {'users': {}}
    try:
        with open(DATA_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return {'users': {}}


def _weekly_count(activity):
    """Total activity over the last 7 days (including today)."""
    today = datetime.now().date()
    week_ago = today - timedelta(days=6)
    total = 0
    for item in activity:
        try:
            d = datetime.strptime(item['date'], '%Y-%m-%d').date()
        except (KeyError, ValueError):
            continue
        if week_ago <= d <= today:
            total += item.get('count', 0)
    return total


def _fmt_ts(iso):
    """ISO UTC timestamp -> 'dd-mm-YYYY HH:MM WIB'."""
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso).astimezone(timezone(timedelta(hours=7)))
        return dt.strftime('%d-%m-%Y %H:%M WIB')
    except ValueError:
        return iso


def get_user_data(user_info, store=None):
    store = store if store is not None else _load_store()
    entry = store.get('users', {}).get(user_info['username'], {})
    p = entry.get('profile') or {}
    today = datetime.now().strftime('%Y-%m-%d')
    activity = [a for a in entry.get('activity', []) if a['date'] <= today]  # API returns the whole year

    return {
        'username': user_info['username'],
        'name': user_info.get('full_name') if p else 'Data not found',
        'rank': p.get('rank', 'N/A'),
        'points': p.get('totalPoints', 0),
        'level': p.get('level'),
        'top_percentage': p.get('topPercentage'),
        'league_tier': p.get('leagueTier'),
        'completed_rooms_number': p.get('completedRoomsNumber') or 0,
        'badges_number': p.get('badgesNumber') or 0,
        'avatar': p.get('avatar', ''),
        'country': p.get('country', ''),
        'streak': p.get('streak', 0),
        'badge_image_url': p.get('badgeImageURL', ''),
        'learning_path': user_info['learning_path'],
        'role': user_info['role'],
        'completed_rooms': entry.get('completed_rooms', []),
        'badges': entry.get('badges', []),
        'certificates': entry.get('certificates', []),
        'activity': activity,
        'current_year': entry.get('activity_year', datetime.now().year),
        'weekly_activity_count': _weekly_count(activity),
        'fetched_at': _fmt_ts(entry.get('fetched_at')),
        'last_error': entry.get('last_error'),
    }


@app.template_filter('datetimeformat')
def datetimeformat(value, format='%d-%m-%Y %H:%M'):
    if value:
        date = datetime.strptime(value, '%Y-%m-%dT%H:%M:%S.%fZ')
        return date.strftime(format)
    else:
        return ''

# Mapping untuk nama path yang lebih rapi
PATH_NAME_MAP = {
    'pathway-soclevel1': 'SOC Level 1',
    'pathway-soclevel2': 'SOC Level 2',
    'soc-level-1': 'SOC Level 1',
    'soc-level-2': 'SOC Level 2',
    'soclevel1': 'SOC Level 1',
    'soclevel2': 'SOC Level 2',
    'pathway-soclevel2-legacy': 'SOC Level 2 (Legacy)',
}

@app.template_filter('format_path_name')
def format_path_name(value):
    """Format path name to be more readable."""
    if not value:
        return 'Path'

    # Cek di mapping
    value_lower = value.lower().replace(' ', '-').replace('_', '-')
    if value_lower in PATH_NAME_MAP:
        return PATH_NAME_MAP[value_lower]

    # Jika tidak ada di mapping, format manual
    # Contoh: "pathway-soclevel1" -> "Pathway Soclevel1"
    formatted = value.replace('-', ' ').replace('_', ' ').title()
    return formatted

def check_soc_completion(certificates):
    """Check if SOC Level 1 and SOC Level 2 are completed."""
    soc_l1_done = False
    soc_l2_done = False
    other_paths = []

    for cert in certificates:
        path_name = cert.get('pathName') or cert.get('name') or ''
        path_lower = path_name.lower().replace(' ', '').replace('-', '').replace('_', '')

        if 'soclevel1' in path_lower or 'socl1' in path_lower or 'soc1' in path_lower:
            soc_l1_done = True
        elif 'soclevel2' in path_lower or 'socl2' in path_lower or 'soc2' in path_lower:
            soc_l2_done = True
        else:
            other_paths.append(path_name)

    return {
        'soc_l1': soc_l1_done,
        'soc_l2': soc_l2_done,
        'soc_count': (1 if soc_l1_done else 0) + (1 if soc_l2_done else 0),
        'all_complete': soc_l1_done and soc_l2_done,
        'other_paths': other_paths
    }

app.jinja_env.globals['check_soc_completion'] = check_soc_completion

@app.route('/')
def index():
    store = _load_store()
    data_list = [get_user_data(u, store) for u in users_info]
    data_list.sort(key=lambda x: x.get('completed_rooms_number', 0), reverse=True)
    return render_template('index.html', data_list=data_list, current_year=datetime.now().year,
                           last_sync=_fmt_ts(store.get('last_run')))


@app.route('/user/<username>')
def user_detail(username):
    user_info = next((u for u in users_info if u['username'] == username), None)
    if not user_info:
        return render_template('user_detail.html', user_data=None)
    user_data = get_user_data(user_info)
    return render_template('user_detail.html', user_data=user_data, rooms=user_data['completed_rooms'],
                           activity=user_data['activity'], current_year=user_data['current_year'])


def _trigger_refresh(username=None):
    if COLLECTOR_URL:
        try:
            r = _collector('POST', '/api/refresh', params={'username': username} if username else None)
            _REMOTE_CACHE['ts'] = 0  # next page load fetches fresh data
            return jsonify(r.json()), r.status_code
        except (requests.RequestException, ValueError):
            return jsonify({'status': 'error', 'message': 'collector tidak bisa dihubungi'}), 502
    cmd = [sys.executable, os.path.join(BASE_DIR, 'collector.py')] + ([username] if username else [])
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    return jsonify({'status': 'started', 'eta_seconds': 10 if username else 120})


@app.route('/user/<username>/refresh', methods=['POST'])
def refresh_user(username):
    if not any(u['username'] == username for u in users_info):
        return jsonify({'status': 'error', 'message': 'user not found'}), 404
    return _trigger_refresh(username)


@app.route('/refresh_all', methods=['POST'])
def refresh_all():
    return _trigger_refresh()


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=int(os.environ.get('PORT', 8000)))
