"""
TryHackMe collector.

TryHackMe now sits behind Vercel's anti-bot challenge, which blocks datacenter IPs.
This script fetches through a residential exit (Tailscale exit node exposed as a local
SOCKS5 proxy) with a browser TLS fingerprint (curl_cffi), and writes the results to
data/thm.json. The Flask app only reads that file; it never calls TryHackMe itself.

Usage:
    python collector.py              # all users in users.json
    python collector.py FakhriyAP    # only the given usernames
"""
import fcntl
import json
import os
import sys
import time
from datetime import datetime, timezone

from curl_cffi import requests as cffi_requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, 'data', 'thm.json')
LOCK_FILE = DATA_FILE + '.lock'
USERS_FILE = os.path.join(BASE_DIR, 'users.json')

THM = 'https://tryhackme.com/api/v2'
PROXY = os.environ.get('THM_PROXY', 'socks5h://127.0.0.1:1055')
REQUEST_DELAY = float(os.environ.get('THM_REQUEST_DELAY', '1.0'))  # be gentle with THM


class FetchError(Exception):
    pass


def _session():
    proxies = {'http': PROXY, 'https': PROXY} if PROXY else None
    return cffi_requests.Session(impersonate='chrome', proxies=proxies, timeout=30)


def _get(session, path, params):
    time.sleep(REQUEST_DELAY)
    resp = session.get(f'{THM}{path}', params=params)
    if resp.status_code != 200:
        raise FetchError(f'{path} -> HTTP {resp.status_code}: {resp.text[:120]}')
    try:
        body = resp.json()
    except ValueError:
        raise FetchError(f'{path} -> non-JSON response (challenge page?)')
    if body.get('status') != 'success':
        raise FetchError(f'{path} -> {body.get("message", "unknown error")}')
    return body.get('data') or {}


def _get_all_pages(session, path, params):
    docs, page = [], 1
    while True:
        data = _get(session, path, {**params, 'page': page, 'limit': 100})
        docs.extend(data.get('docs', []))
        if not data.get('hasNextPage'):
            return docs
        page += 1


def fetch_user(session, username):
    """Fetch everything the dashboard needs for one user (5+ requests)."""
    q = {'username': username}
    year = datetime.now().year
    profile = _get(session, '/public-profile', q)
    rooms = _get_all_pages(session, '/public-profile/completed-rooms', q)
    badges = _get_all_pages(session, '/public-profile/badges', q)
    certificates = _get_all_pages(session, '/certificates/public-list', q)
    activity = _get(session, '/public-profile/yearly-activity', {**q, 'year': year}).get('yearlyActivity', [])

    return {
        'profile': profile,
        'completed_rooms': [{
            'title': r.get('title'),
            'description': r.get('description'),
            'difficulty': r.get('difficulty'),
            'image_url': r.get('imageURL'),
            'type': r.get('type'),
        } for r in rooms],
        'badges': [{
            'name': b.get('name'),
            'title': b.get('title'),
            'description': b.get('description'),
            'image': b.get('image'),
            'earned_at': b.get('earnedAt'),
        } for b in badges],
        'certificates': [{
            'name': c.get('name'),
            'title': c.get('title'),
            'achieved': c.get('achieved'),
        } for c in certificates],
        'activity_year': year,
        'activity': [{'date': a['date'], 'count': int(a.get('count') or 0)}
                     for a in activity if a.get('date')],
    }


def _load():
    try:
        with open(DATA_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return {'users': {}}


def _save(store):
    tmp = DATA_FILE + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(store, f, ensure_ascii=False)
    os.replace(tmp, DATA_FILE)  # atomic: readers never see a half-written file


def run(usernames=None):
    """Fetch the given users (default: all) and merge into data/thm.json.

    A user whose fetch fails keeps their previous data; only `last_error` is updated.
    Returns {username: error_or_None}.
    """
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(USERS_FILE) as f:
        all_users = [u['username'] for u in json.load(f)]
    targets = usernames or all_users

    results = {}
    with open(LOCK_FILE, 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)  # one collector at a time (cron vs. refresh button)
        session = _session()
        for username in targets:
            now = datetime.now(timezone.utc).isoformat(timespec='seconds')
            try:
                data = fetch_user(session, username)
                error = None
            except Exception as e:  # keep going for the other users
                data, error = None, str(e)

            store = _load()  # re-read so concurrent single-user refreshes aren't lost
            entry = store['users'].get(username, {})
            if data:
                entry.update(data)
                entry['fetched_at'] = now
            entry['last_attempt'] = now
            entry['last_error'] = error
            store['users'][username] = entry
            store['last_run'] = now
            _save(store)

            results[username] = error
            print(f'[{now}] {username}: {"OK" if not error else "FAIL " + error}', flush=True)
    return results


if __name__ == '__main__':
    res = run(sys.argv[1:] or None)
    failed = [u for u, e in res.items() if e]
    print(f'done: {len(res) - len(failed)} ok, {len(failed)} failed', flush=True)
    sys.exit(1 if failed and len(failed) == len(res) else 0)
