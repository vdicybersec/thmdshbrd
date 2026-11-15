"""
Collector API: runs on the collector host (residential exit available), exposed to the
Vercel dashboard via Tailscale Funnel. Only two endpoints, both require the shared secret:

    GET  /api/data                      -> contents of data/thm.json
    POST /api/refresh[?username=<u>]    -> start a background collector run (rate limited)

Run: gunicorn -b 127.0.0.1:8100 collector_api:app   (COLLECTOR_SECRET in the environment)
"""
import hmac
import json
import os
import subprocess
import sys
import time

from flask import Flask, Response, jsonify, request

import collector

app = Flask(__name__)
SECRET = os.environ.get('COLLECTOR_SECRET', '')
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Minimum seconds between refreshes, so a public refresh button can't hammer THM / the exit node.
MIN_INTERVAL_ALL = 120
MIN_INTERVAL_USER = 60
STATE_FILE = os.path.join(BASE_DIR, 'data', 'refresh_state.json')  # shared across gunicorn workers

with open(collector.USERS_FILE) as f:
    USERNAMES = {u['username'] for u in json.load(f)}


@app.before_request
def require_secret():
    given = request.headers.get('X-Collector-Secret', '')
    if not SECRET or not hmac.compare_digest(given, SECRET):
        return jsonify({'status': 'error', 'message': 'unauthorized'}), 401


@app.get('/api/data')
def data():
    try:
        with open(collector.DATA_FILE, 'rb') as f:
            return Response(f.read(), mimetype='application/json')
    except FileNotFoundError:
        return jsonify({'users': {}})


def _last_triggered(key):
    try:
        with open(STATE_FILE) as f:
            return json.load(f).get(key, 0)
    except (FileNotFoundError, ValueError):
        return 0


def _mark_triggered(key):
    try:
        with open(STATE_FILE) as f:
            state = json.load(f)
    except (FileNotFoundError, ValueError):
        state = {}
    state[key] = time.time()
    tmp = STATE_FILE + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(state, f)
    os.replace(tmp, STATE_FILE)


@app.post('/api/refresh')
def refresh():
    username = request.args.get('username')
    if username and username not in USERNAMES:
        return jsonify({'status': 'error', 'message': 'user not found'}), 404

    key, min_interval = (f'user:{username}', MIN_INTERVAL_USER) if username else ('all', MIN_INTERVAL_ALL)
    wait = int(min_interval - (time.time() - max(_last_triggered(key), _last_triggered('all'))))
    if wait > 0:
        return jsonify({'status': 'throttled', 'retry_after': wait}), 429

    _mark_triggered(key)
    cmd = [sys.executable, os.path.join(BASE_DIR, 'collector.py')] + ([username] if username else [])
    log = open(os.path.join(BASE_DIR, 'data', 'collector.log'), 'a')
    subprocess.Popen(cmd, cwd=BASE_DIR, stdout=log, stderr=log, start_new_session=True)
    return jsonify({'status': 'started', 'eta_seconds': 10 if username else 120})
