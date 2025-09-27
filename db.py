import json
import os

DB_FILE = 'user_db.json'

def initialize_db():
    if not os.path.exists(DB_FILE):
        with open(DB_FILE, 'w') as f:
            json.dump({'users': []}, f)

def add_user(user_id: int):
    with open(DB_FILE, 'r+') as f:
        db = json.load(f)
        if user_id not in db['users']:
            db['users'].append(user_id)
            f.seek(0)
            json.dump(db, f)

def get_all_users() -> list:
    with open(DB_FILE, 'r') as f:
        db = json.load(f)
        return db.get('users', [])