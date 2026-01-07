from flask import Flask, render_template, jsonify
import requests
from datetime import datetime

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
    {'username': 'daffa.rizky90', 'full_name': 'Daffa', 'learning_path': 'L2 Bootcamp', 'role': 'L2 Bootcamp'}
]

def get_user_data(user_info):
    username = user_info['username']
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
            'completed_rooms_number': data.get('completedRoomsNumber'),
            'badges_number': data.get('badgesNumber'),
            'avatar': data.get('avatar'),
            'country': data.get('country'),
            'streak': data.get('streak'),
            'badge_image_url': data.get('badgeImageURL'),
            'learning_path': user_info['learning_path'],
            'role': user_info['role']
        }

        # Fetch completed rooms
        user_data['completed_rooms'] = get_completed_rooms(user_id)
        # Fetch yearly activity
        current_year = datetime.now().year
        user_data['activity'] = get_yearly_activity(user_id, year=current_year)
        user_data['current_year'] = current_year
        # Fetch badges
        user_data['badges'] = get_badges(user_id)

        # Add certificate logic
        if user_info['learning_path'] == 'L2 Bootcamp':
            user_data['certificate'] = 'L2 Bootcamp Certificate'
        else:
            user_data['certificate'] = 'General Certificate'

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
        activity = data.get('yearlyActivity', [])
        return activity
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
    data_list = []
    for user_info in users_info:
        user_data = get_user_data(user_info)
        data_list.append(user_data)

    # Sort by completed rooms number descending for ranking
    data_list.sort(key=lambda x: x['completed_rooms_number'], reverse=True)

    current_year = datetime.now().year

    return render_template('index.html', data_list=data_list, current_year=current_year)

@app.route('/user/<username>')
def user_detail(username):
    user_info = next((u for u in users_info if u['username'] == username), None)
    if user_info:
        user_data = get_user_data(user_info)
        current_year = datetime.now().year
        return render_template('user_detail.html', user_data=user_data, rooms=user_data['completed_rooms'], activity=user_data['activity'], current_year=current_year)
    else:
        return render_template('user_detail.html', user_data=None)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=80)
