from flask import Flask, render_template, jsonify
import requests
from datetime import datetime
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

app = Flask(__name__)

# Updated users_info for Visionet L2 Bootcamp
users_info = [
    {'username': 'FakhriyAP', 'full_name': 'Fakhriy', 'learning_path': 'L2 Bootcamp', 'role': 'L2 Bootcamp'},
    {'username': 'MDN141', 'full_name': 'Andi M', 'learning_path': 'L2 Bootcamp', 'role': 'L2 Bootcamp'},
    {'username': 'baihaqikpc', 'full_name': 'Baihaqi', 'learning_path': 'L2 Bootcamp', 'role': 'L2 Bootcamp'},
    {'username': 'mahesa', 'full_name': 'Mahesa', 'learning_path': 'L2 Bootcamp', 'role': 'L2 Bootcamp'},
    {'username': 'Fikriboi', 'full_name': 'M Fikri Haikal', 'learning_path': 'L2 Bootcamp', 'role': 'L2 Bootcamp'},
    {'username': 'aerysh', 'full_name': 'Ahmad Azwar Annas', 'learning_path': 'L2 Bootcamp', 'role': 'L2 Bootcamp'},
    {'username': 'fuadganss', 'full_name': 'fuad bahreisy', 'learning_path': 'L2 Bootcamp', 'role': 'L2 Bootcamp'},
    {'username': 'kurniawanhanif63', 'full_name': 'Hanif Kurniawan', 'learning_path': 'L2 Bootcamp', 'role': 'L2 Bootcamp'},
    {'username': 'triassonn', 'full_name': 'Trias Wijaksono', 'learning_path': 'L2 Bootcamp', 'role': 'L2 Bootcamp'},
    {'username': 'arvindrasp', 'full_name': 'Arvindra', 'learning_path': 'L2 Bootcamp', 'role': 'L2 Bootcamp'},
    {'username': 'daffa.rizky90', 'full_name': 'Daffa', 'learning_path': 'L2 Bootcamp', 'role': 'L2 Bootcamp'},
    {'username': 'M.hafizd', 'full_name': 'Muhammad Hafizd', 'learning_path': 'L2 Bootcamp', 'role': 'L2 Bootcamp'}
]

## Simple in-memory cache to reduce repeated HTTP calls
CACHE = {}
# seconds
CACHE_TTL = 300

def _is_cache_valid(entry_ts):
    return (time.time() - entry_ts) < CACHE_TTL

def get_user_data(user_info, lightweight=False, force=False):
    """
    Fetch user data from TryHackMe. If `lightweight` is True, avoid heavy calls
    (completed rooms list, badges, yearly activity) and only parse summary fields.
    Results are cached in-memory for `CACHE_TTL` seconds.
    """
    username = user_info['username']
    cache_key = f"{username}:{'lite' if lightweight else 'full'}"
    # Return cached copy when valid (unless force refresh requested)
    if not force and cache_key in CACHE:
        entry = CACHE[cache_key]
        if _is_cache_valid(entry['ts']):
            return entry['data']

    profile_url = f'https://tryhackme.com/api/v2/public-profile?username={username}'
    response = requests.get(profile_url)
    if response.status_code == 200:
        data = response.json().get('data', {})
        user_id = data.get('_id')

        user_data = {
            'username': username,
            'user_id': user_id,
            'name': user_info.get('full_name', data.get('username')),
            'rank': data.get('rank'),
            'points': data.get('points'),
            'completed_rooms_number': data.get('completedRoomsNumber') or 0,
            'badges_number': data.get('badgesNumber') or 0,
            'avatar': data.get('avatar'),
            'country': data.get('country'),
            'streak': data.get('streak'),
            'badge_image_url': data.get('badgeImageURL'),
            'learning_path': user_info['learning_path'],
            'role': user_info['role']
        }

        # Only fetch heavy details when not in lightweight mode
        if not lightweight:
            user_data['completed_rooms'] = get_completed_rooms(user_id)
            current_year = datetime.now().year
            user_data['activity'] = get_yearly_activity(user_id, year=current_year)
            user_data['current_year'] = current_year
            user_data['badges'] = get_badges(user_id)
        else:
            user_data['completed_rooms'] = []
            user_data['activity'] = []
            user_data['current_year'] = ''
            user_data['badges'] = []

        # Add certificate logic
        if user_info['learning_path'] == 'L2 Bootcamp':
            user_data['certificate'] = 'L2 Bootcamp Certificate'
        else:
            user_data['certificate'] = 'General Certificate'

        # store in cache
        CACHE[cache_key] = {'ts': time.time(), 'data': user_data}
        return user_data
    else:
        user_data = {
            'username': username,
            'name': 'Data not found',
            'rank': 'N/A',
            'points': 0,
            'completed_rooms_number': 0,
            'badges_number': 0,
            'avatar': '',
            'country': '',
            'streak': 0,
            'badge_image_url': '',
            'learning_path': user_info['learning_path'],
            'role': user_info['role'],
            'completed_rooms': [],
            'activity': [],
            'current_year': '',
            'badges': []
        }

        # Add certificate logic in case of missing data
        user_data['certificate'] = 'Onprogress'

        CACHE[cache_key] = {'ts': time.time(), 'data': user_data}
        return user_data

def get_completed_rooms(user_id):
    rooms_url = f'https://tryhackme.com/api/v2/public-profile/completed-rooms?user={user_id}'
    completed_rooms = []
    page = 1  # Mulai dari halaman pertama

    while True:
        response = requests.get(f'{rooms_url}&page={page}&limit=100')
        if response.status_code == 200:
            data = response.json().get('data', {})
            rooms = data.get('docs', [])
            completed_rooms.extend([{
                'title': room.get('title'),
                'description': room.get('description'),
                'difficulty': room.get('difficulty'),
                'image_url': room.get('imageURL'),
                'type': room.get('type')
            } for room in rooms])

            # Jika tidak ada halaman berikutnya, hentikan loop
            if not data.get('hasNextPage', False):
                break

            page += 1
        else:
            break

    return completed_rooms

def get_yearly_activity(user_id, year):
    activity_url = f'https://tryhackme.com/api/v2/public-profile/yearly-activity?user={user_id}&year={year}'
    response = requests.get(activity_url)
    if response.status_code == 200:
        data = response.json().get('data', {})
        raw_activity = data.get('yearlyActivity', [])

        processed = []
        today = datetime.now()
        for item in raw_activity:
            # API may return dates like '2026-12' or '2026-12-01' etc.
            date_str = item.get('date') or item.get('day') or item.get('month')
            count = item.get('count', 0)
            if not date_str:
                continue

            # Normalize and parse date
            dt = None
            try:
                if len(date_str) == 7 and date_str[4] == '-':  # 'YYYY-MM'
                    dt = datetime.strptime(date_str, '%Y-%m')
                    dt = dt.replace(day=1)
                else:
                    # Try full date format 'YYYY-MM-DD' or ISO
                    dt = datetime.strptime(date_str[:10], '%Y-%m-%d')
            except Exception:
                try:
                    dt = datetime.fromisoformat(date_str)
                except Exception:
                    # skip unparseable
                    continue

            # Filter: only include dates within requested year and not in the future
            if dt.year != year:
                continue
            if dt > today:
                continue

            processed.append({'date': dt.strftime('%Y-%m-%d'), 'count': int(count)})

        # Sort ascending so data starts from January
        processed.sort(key=lambda x: x['date'])
        return processed
    else:
        return []

def get_badges(user_id):
    badges_url = f'https://tryhackme.com/api/v2/public-profile/badges?user={user_id}'
    response = requests.get(badges_url)
    if response.status_code == 200:
        data = response.json().get('data', {})
        badges = data.get('docs', [])
        user_badges = []
        for badge in badges:
            user_badges.append({
                'name': badge.get('name'),
                'title': badge.get('title'),
                'description': badge.get('description'),
                'image': badge.get('image')
            })
        return user_badges
    else:
        return []

@app.template_filter('datetimeformat')
def datetimeformat(value, format='%d-%m-%Y %H:%M'):
    if value:
        date = datetime.strptime(value, '%Y-%m-%dT%H:%M:%S.%fZ')
        return date.strftime(format)
    else:
        return ''

@app.route('/')
def index():
    # Use lightweight fetch for dashboard summary and run requests in parallel
    data_list = []
    current_year = datetime.now().year

    # parallelize network calls to reduce total wait time
    max_workers = min(10, len(users_info))
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(get_user_data, u, True): u for u in users_info}
        for fut in as_completed(futures):
            try:
                user_data = fut.result()
            except Exception:
                # In case of unexpected error, return a minimal placeholder
                u = futures[fut]
                user_data = {
                    'username': u['username'],
                    'name': u.get('full_name', 'Unknown'),
                    'completed_rooms_number': 0,
                    'badges_number': 0,
                    'avatar': '',
                    'learning_path': u.get('learning_path', ''),
                    'role': u.get('role', '')
                }
            data_list.append(user_data)

    # Sort by completed rooms number descending for ranking
    data_list.sort(key=lambda x: x.get('completed_rooms_number', 0), reverse=True)

    return render_template('index.html', data_list=data_list, current_year=current_year)

@app.route('/user/<username>')
def user_detail(username):
    user_info = next((u for u in users_info if u['username'] == username), None)
    if user_info:
        # full fetch (not lightweight) so we have rooms, badges, and activity
        user_data = get_user_data(user_info, lightweight=False)
        current_year = datetime.now().year
        return render_template('user_detail.html', user_data=user_data, rooms=user_data.get('completed_rooms', []), activity=user_data.get('activity', []), current_year=current_year)
    else:
        return render_template('user_detail.html', user_data=None)


@app.route('/user/<username>/refresh', methods=['POST'])
def refresh_user(username):
    user_info = next((u for u in users_info if u['username'] == username), None)
    if not user_info:
        return jsonify({'status': 'error', 'message': 'user not found'}), 404

    # Force full refresh and update cache
    try:
        get_user_data(user_info, lightweight=False, force=True)
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/refresh_all', methods=['POST'])
def refresh_all():
    # Refresh lightweight summary for all users in parallel (force)
    max_workers = min(10, len(users_info))
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [ex.submit(get_user_data, u, True, True) for u in users_info]
        # Wait for completion
        for f in as_completed(futures):
            try:
                f.result()
            except Exception:
                pass
    return jsonify({'status': 'ok'})

if __name__ == '__main__':
    # For local development
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 80)))
else:
    # For Vercel deployment
    app = app
