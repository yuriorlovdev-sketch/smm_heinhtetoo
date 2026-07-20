from flask import Flask, request, jsonify, render_template, redirect, url_for, session, flash
from flask_cors import CORS
from flask_session import Session
from cachelib import FileSystemCache
import pymysql
import pymysql.cursors
import json
import hashlib
import secrets
import requests
from datetime import datetime, timedelta
import os
import re
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# Session Configuration
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'your-super-secret-key-change-this-in-production')
app.config['SESSION_TYPE'] = 'cachelib'
app.config['SESSION_CACHELIB'] = FileSystemCache(cache_dir='./flask_session', threshold=500)
app.config['SESSION_PERMANENT'] = False
app.config['SESSION_USE_SIGNER'] = True
app.config['SESSION_COOKIE_SECURE'] = False
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

Session(app)
CORS(app)

# ---------- Database Helper Functions (MySQL) ----------
def get_db():
    conn = pymysql.connect(
        host=os.getenv('DB_HOST', 'localhost'),
        user=os.getenv('DB_USER', 'root'),
        password=os.getenv('DB_PASSWORD', ''),
        database=os.getenv('DB_NAME', 'smm_panel'),
        port=int(os.getenv('DB_PORT', 3306)),
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False
    )
    return conn

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(password, hashed):
    return hash_password(password) == hashed

def generate_id(prefix='USR'):
    import random
    return f"{prefix}-{random.randint(1000, 9999)}"

def get_current_time():
    return datetime.now().isoformat()

# ---------- Helper: Parse ticket replies with datetime conversion ----------
def parse_ticket_replies(replies_json):
    if not replies_json:
        return []
    try:
        replies = json.loads(replies_json)
        for reply in replies:
            if 'time' in reply and isinstance(reply['time'], str):
                try:
                    reply['time'] = datetime.fromisoformat(reply['time'])
                except:
                    pass
        return replies
    except:
        return []

# ---------- Global Template Context ----------
@app.context_processor
def utility_processor():
    return dict(
        datetime=datetime,
        now=datetime.now()
    )

# ---------- Maintenance Mode ----------
def is_maintenance_mode():
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT value FROM settings WHERE `key` = 'maintenance'")
    result = cursor.fetchone()
    db.close()
    if result:
        return result['value'] == 'true'
    return False

@app.before_request
def before_request():
    if 'user_id' in session:
        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT tier FROM users WHERE id = %s", (session['user_id'],))
        user = cursor.fetchone()
        db.close()
        if user and user['tier'] in ['admin', 'super_admin']:
            pass
        else:
            if is_maintenance_mode():
                allowed_endpoints = ['login', 'register', 'static', 'maintenance']
                if request.endpoint not in allowed_endpoints:
                    return render_template('maintenance.html'), 503
            
            if 'user_id' in session:
                db = get_db()
                cursor = db.cursor()
                try:
                    cursor.execute("""
                        SELECT status FROM user_agreements 
                        WHERE user_id = %s AND status = 'approved' 
                        ORDER BY agreed_at DESC LIMIT 1
                    """, (session['user_id'],))
                    approved = cursor.fetchone()
                except:
                    approved = None
                db.close()
                
                allowed_endpoints = ['user_terms_agreement', 'logout', 'static', 'login', 'register', 'dashboard']
                if not approved and request.endpoint not in allowed_endpoints:
                    return redirect(url_for('user_terms_agreement'))
    else:
        if request.endpoint not in ['login', 'register', 'static']:
            return redirect(url_for('login'))
    return None

# ---------- MySQL Database Initialization (Run ONCE) ----------
def init_mysql_db():
    db = get_db()
    cursor = db.cursor()

    cursor.execute('''CREATE TABLE IF NOT EXISTS users (
        id VARCHAR(20) PRIMARY KEY,
        name VARCHAR(100) NOT NULL,
        username VARCHAR(50) UNIQUE NOT NULL,
        password VARCHAR(255) NOT NULL,
        email VARCHAR(100),
        phone VARCHAR(20),
        tier VARCHAR(20) DEFAULT 'user',
        balance DECIMAL(15,2) DEFAULT 0,
        spent DECIMAL(15,2) DEFAULT 0,
        earned DECIMAL(15,2) DEFAULT 0,
        status VARCHAR(20) DEFAULT 'active',
        api_key VARCHAR(64),
        created_at DATETIME,
        updated_at DATETIME,
        last_login DATETIME,
        deleted_at DATETIME
    )''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS login_history (
        id INT AUTO_INCREMENT PRIMARY KEY,
        user_id VARCHAR(20),
        username VARCHAR(50),
        login_time DATETIME,
        logout_time DATETIME,
        ip_address VARCHAR(45),
        user_agent TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS activity_logs (
        id INT AUTO_INCREMENT PRIMARY KEY,
        user_id VARCHAR(20),
        username VARCHAR(50),
        action VARCHAR(100),
        details TEXT,
        ip_address VARCHAR(45),
        created_at DATETIME,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS providers (
        id INT AUTO_INCREMENT PRIMARY KEY,
        name VARCHAR(100) NOT NULL,
        url VARCHAR(255) NOT NULL,
        api_key VARCHAR(255) NOT NULL,
        api_type VARCHAR(20) DEFAULT 'socpanel',
        balance DECIMAL(15,2) DEFAULT 0,
        status VARCHAR(20) DEFAULT 'active',
        sync_date DATETIME,
        created_at DATETIME,
        updated_at DATETIME,
        last_sync DATETIME,
        deleted_at DATETIME
    )''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS reseller_apis (
        id INT AUTO_INCREMENT PRIMARY KEY,
        user_id VARCHAR(20),
        api_key VARCHAR(64) UNIQUE NOT NULL,
        name VARCHAR(100),
        ip_whitelist TEXT,
        rate_limit INT DEFAULT 100,
        status VARCHAR(20) DEFAULT 'active',
        created_at DATETIME,
        last_used DATETIME,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS services (
        id INT AUTO_INCREMENT PRIMARY KEY,
        provider_id INT,
        provider_service_id VARCHAR(50),
        category VARCHAR(50) NOT NULL,
        name VARCHAR(255) NOT NULL,
        description TEXT,
        rate DECIMAL(10,4) DEFAULT 0,
        min_order INT DEFAULT 100,
        max_order INT DEFAULT 100000,
        markup DECIMAL(5,2) DEFAULT 15,
        service_type VARCHAR(20) DEFAULT 'standard',
        status VARCHAR(20) DEFAULT 'active',
        created_at DATETIME,
        updated_at DATETIME,
        deleted_at DATETIME,
        FOREIGN KEY(provider_id) REFERENCES providers(id)
    )''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS orders (
        id INT AUTO_INCREMENT PRIMARY KEY,
        user_id VARCHAR(20),
        service_id INT,
        provider_order_id VARCHAR(100),
        service_name VARCHAR(255),
        category VARCHAR(50),
        link TEXT,
        quantity INT,
        rate DECIMAL(10,4),
        cost DECIMAL(15,2),
        price DECIMAL(15,2),
        profit DECIMAL(15,2),
        status VARCHAR(20) DEFAULT 'pending',
        provider_response TEXT,
        api_order_id VARCHAR(100),
        source VARCHAR(20) DEFAULT 'web',
        created_at DATETIME,
        updated_at DATETIME,
        completed_at DATETIME,
        delivery_time DATETIME,
        notes TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id),
        FOREIGN KEY(service_id) REFERENCES services(id)
    )''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS api_logs (
        id INT AUTO_INCREMENT PRIMARY KEY,
        provider_id INT,
        endpoint VARCHAR(100),
        method VARCHAR(10),
        request TEXT,
        response TEXT,
        status_code INT,
        created_at DATETIME,
        FOREIGN KEY(provider_id) REFERENCES providers(id)
    )''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS payment_methods (
        id INT AUTO_INCREMENT PRIMARY KEY,
        name VARCHAR(100) NOT NULL,
        type VARCHAR(20) NOT NULL,
        account_name VARCHAR(100),
        account_number VARCHAR(50),
        phone VARCHAR(20),
        instructions TEXT,
        is_active TINYINT(1) DEFAULT 1,
        created_at DATETIME,
        updated_at DATETIME
    )''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS payment_requests (
        id INT AUTO_INCREMENT PRIMARY KEY,
        user_id VARCHAR(20),
        user_name VARCHAR(100),
        method_id INT,
        method_name VARCHAR(100),
        amount DECIMAL(15,2),
        sender_name VARCHAR(100),
        sender_phone VARCHAR(20),
        transaction_id VARCHAR(100),
        reference_image VARCHAR(255),
        status VARCHAR(20) DEFAULT 'pending',
        admin_notes TEXT,
        created_at DATETIME,
        approved_at DATETIME,
        FOREIGN KEY(user_id) REFERENCES users(id),
        FOREIGN KEY(method_id) REFERENCES payment_methods(id)
    )''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS withdraw_requests (
        id INT AUTO_INCREMENT PRIMARY KEY,
        user_id VARCHAR(20),
        user_name VARCHAR(100),
        method VARCHAR(50),
        amount DECIMAL(15,2),
        bank_name VARCHAR(100),
        account_number VARCHAR(50),
        account_name VARCHAR(100),
        status VARCHAR(20) DEFAULT 'pending',
        admin_notes TEXT,
        created_at DATETIME,
        approved_at DATETIME,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS tickets (
        id INT AUTO_INCREMENT PRIMARY KEY,
        user_id VARCHAR(20),
        user_name VARCHAR(100),
        subject VARCHAR(255),
        category VARCHAR(50),
        message TEXT,
        priority VARCHAR(20) DEFAULT 'normal',
        status VARCHAR(20) DEFAULT 'open',
        replies JSON,
        created_at DATETIME,
        updated_at DATETIME,
        assigned_to VARCHAR(20),
        FOREIGN KEY(user_id) REFERENCES users(id)
    )''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS settings (
        `key` VARCHAR(50) PRIMARY KEY,
        value TEXT,
        updated_at DATETIME
    )''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS user_agreements (
        id INT AUTO_INCREMENT PRIMARY KEY,
        user_id VARCHAR(20) NOT NULL,
        username VARCHAR(50) NOT NULL,
        agreed_at DATETIME NOT NULL,
        ip_address VARCHAR(45),
        user_agent TEXT,
        status VARCHAR(20) DEFAULT 'pending',
        FOREIGN KEY (user_id) REFERENCES users(id)
    )''')

    now = datetime.now().isoformat()

    super_hash = hash_password('super123')
    cursor.execute('''INSERT IGNORE INTO users 
        (id, name, username, password, tier, balance, status, api_key, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)''',
        ('SUPER-001', 'Super Admin', 'superadmin', super_hash, 'super_admin', 999999, 'active',
         secrets.token_hex(16), now, now))

    admin_hash = hash_password('admin123')
    cursor.execute('''INSERT IGNORE INTO users 
        (id, name, username, password, tier, balance, status, api_key, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)''',
        ('ADMIN-001', 'Master Admin', 'admin', admin_hash, 'admin', 99999, 'active',
         secrets.token_hex(16), now, now))

    reseller_hash = hash_password('agent123')
    cursor.execute('''INSERT IGNORE INTO users 
        (id, name, username, password, tier, balance, status, api_key, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)''',
        ('RES-1001', 'SMM Kings Agency', 'kings', reseller_hash, 'reseller', 5410.25, 'active',
         secrets.token_hex(16), now, now))

    user_hash = hash_password('user123')
    cursor.execute('''INSERT IGNORE INTO users 
        (id, name, username, password, tier, balance, status, api_key, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)''',
        ('USR-2001', 'Social Media User', 'user', user_hash, 'user', 100.00, 'active',
         secrets.token_hex(16), now, now))

    cursor.execute("SELECT COUNT(*) as cnt FROM providers")
    if cursor.fetchone()['cnt'] == 0:
        cursor.execute('''INSERT INTO providers (name, url, api_key, api_type, balance, status, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)''',
            ('PeakSMM API', 'https://api.peaksmm.com/v2', secrets.token_hex(16), 'peaksmm', 5000, 'active', now, now))
        cursor.execute('''INSERT INTO providers (name, url, api_key, api_type, balance, status, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)''',
            ('SocPanel API', 'https://socpanel.com', 'W0kCR9DQloZONg2vQyco8YmocYhOvaHOIzjbkiH0WXscavfkXXXHXx9OMKrF', 'socpanel', 0, 'active', now, now))
        cursor.execute('''INSERT INTO providers (name, url, api_key, api_type, balance, status, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)''',
            ('JustAnotherPanel', 'https://justanotherpanel.com/api/v2', secrets.token_hex(16), 'custom', 0, 'active', now, now))
        cursor.execute('''INSERT INTO providers (name, url, api_key, api_type, balance, status, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)''',
            ('PanelKing', 'https://panelking.com/api', secrets.token_hex(16), 'custom', 0, 'active', now, now))

    cursor.execute("SELECT COUNT(*) as cnt FROM services")
    if cursor.fetchone()['cnt'] == 0:
        services_data = [
            (1, 'FB-101', 'Facebook', 'Facebook Page Likes', 'Get real Facebook page likes', 1.50, 100, 100000, 15, 'standard'),
            (1, 'IG-101', 'Instagram', 'Instagram Followers', 'Get real Instagram followers', 2.00, 100, 100000, 15, 'express'),
            (2, 'SOC-101', 'Instagram', 'Instagram Followers [SocPanel]', 'Get Instagram followers via SocPanel', 2.20, 100, 100000, 15, 'standard'),
            (2, 'SOC-201', 'Facebook', 'Facebook Page Likes [SocPanel]', 'Get Facebook page likes via SocPanel', 1.80, 100, 100000, 15, 'standard'),
            (1, 'YT-101', 'YouTube', 'YouTube Subscribers', 'Get YouTube channel subscribers', 10.00, 50, 5000, 20, 'premium'),
            (1, 'TT-101', 'TikTok', 'TikTok Followers', 'Get TikTok followers', 2.50, 100, 50000, 15, 'standard'),
            (3, 'JAP-101', 'Instagram', 'Instagram Followers [JAP]', 'Get Instagram followers via JustAnotherPanel', 2.10, 100, 100000, 15, 'standard'),
            (4, 'PK-101', 'Instagram', 'Instagram Followers [PanelKing]', 'Get Instagram followers via PanelKing', 2.30, 100, 100000, 15, 'express'),
        ]
        for data in services_data:
            cursor.execute('''INSERT INTO services 
                (provider_id, provider_service_id, category, name, description, rate, min_order, max_order, markup, service_type, status, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)''',
                (data[0], data[1], data[2], data[3], data[4], data[5], data[6], data[7], data[8], data[9], 'active', now, now))

    cursor.execute("SELECT COUNT(*) as cnt FROM payment_methods")
    if cursor.fetchone()['cnt'] == 0:
        cursor.execute('''INSERT INTO payment_methods (name, type, account_name, phone, instructions, is_active, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)''',
            ('KPay', 'kpay', 'SMM Master Admin', '09-771234567', 'ငွေလွှဲပြီးပါက Transaction ID ကို ဖြည့်ပါ။', 1, now, now))
        cursor.execute('''INSERT INTO payment_methods (name, type, account_name, account_number, instructions, is_active, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)''',
            ('Wave Money', 'wavemoney', 'SMM Master Admin', '09-771234567', 'ငွေလွှဲပြီးပါက Transaction ID ကို ဖြည့်ပါ။', 1, now, now))
        cursor.execute('''INSERT INTO payment_methods (name, type, account_name, account_number, instructions, is_active, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)''',
            ('Bank Transfer (CB Bank)', 'bank', 'SMM Master Admin', '1234567890', 'CB Bank သို့ ငွေလွှဲပြီးပါက အကောင့်နံပါတ်ကို ဖြည့်ပါ။', 1, now, now))

    cursor.execute("SELECT COUNT(*) as cnt FROM settings WHERE `key` = 'maintenance'")
    if cursor.fetchone()['cnt'] == 0:
        cursor.execute("INSERT INTO settings (`key`, value, updated_at) VALUES (%s, %s, %s)", ('maintenance', 'false', now))
        cursor.execute("INSERT INTO settings (`key`, value, updated_at) VALUES (%s, %s, %s)", ('default_markup', '15', now))
        cursor.execute("INSERT INTO settings (`key`, value, updated_at) VALUES (%s, %s, %s)", ('currency', 'USD', now))
        cursor.execute("INSERT INTO settings (`key`, value, updated_at) VALUES (%s, %s, %s)", ('min_deposit_mmk', '5000', now))
        cursor.execute("INSERT INTO settings (`key`, value, updated_at) VALUES (%s, %s, %s)", ('min_withdraw_mmk', '10000', now))
        cursor.execute("INSERT INTO settings (`key`, value, updated_at) VALUES (%s, %s, %s)", ('kpay_name', 'SMM Master Admin', now))
        cursor.execute("INSERT INTO settings (`key`, value, updated_at) VALUES (%s, %s, %s)", ('kpay_phone', '09-771234567', now))
        cursor.execute("INSERT INTO settings (`key`, value, updated_at) VALUES (%s, %s, %s)", ('api_base_url', 'https://yourpanel.com/api/v2', now))
        cursor.execute("INSERT INTO settings (`key`, value, updated_at) VALUES (%s, %s, %s)", ('exchange_rate', os.getenv('EXCHANGE_RATE', '4000'), now))
        cursor.execute("INSERT INTO settings (`key`, value, updated_at) VALUES (%s, %s, %s)", ('display_currency', 'MMK', now))
        cursor.execute("INSERT INTO settings (`key`, value, updated_at) VALUES (%s, %s, %s)", ('user_default_markup', '20', now))
        cursor.execute("INSERT INTO settings (`key`, value, updated_at) VALUES (%s, %s, %s)", ('reseller_default_markup', '10', now))
        cursor.execute("INSERT INTO settings (`key`, value, updated_at) VALUES (%s, %s, %s)", ('user_discount', '0', now))
        cursor.execute("INSERT INTO settings (`key`, value, updated_at) VALUES (%s, %s, %s)", ('reseller_discount', '0', now))
        cursor.execute("INSERT INTO settings (`key`, value, updated_at) VALUES (%s, %s, %s)", ('order_bonus', '0', now))
        cursor.execute("INSERT INTO settings (`key`, value, updated_at) VALUES (%s, %s, %s)", ('bonus_type', 'fixed', now))

    db.commit()
    db.close()
    print("✅ MySQL Database initialized successfully!")

# ---------- Uncomment this line ONLY ONCE to create tables, then comment it out again ----------
# init_mysql_db()

# ---------- Helper Functions ----------
def require_login(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def require_super_admin(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT tier FROM users WHERE id = %s", (session['user_id'],))
        user = cursor.fetchone()
        db.close()
        if user and user['tier'] == 'super_admin':
            return f(*args, **kwargs)
        flash('Super Admin access required', 'error')
        return redirect(url_for('dashboard'))
    return decorated_function

def require_admin(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT tier FROM users WHERE id = %s", (session['user_id'],))
        user = cursor.fetchone()
        db.close()
        if user and user['tier'] in ['super_admin', 'admin']:
            return f(*args, **kwargs)
        flash('Admin access required', 'error')
        return redirect(url_for('dashboard'))
    return decorated_function

def log_activity(user_id, username, action, details=''):
    db = get_db()
    cursor = db.cursor()
    cursor.execute('''INSERT INTO activity_logs (user_id, username, action, details, ip_address, created_at)
        VALUES (%s, %s, %s, %s, %s, %s)''',
        (user_id, username, action, details, request.remote_addr, get_current_time()))
    db.commit()
    db.close()

def log_login(user_id, username):
    db = get_db()
    cursor = db.cursor()
    cursor.execute('''INSERT INTO login_history (user_id, username, login_time, ip_address, user_agent)
        VALUES (%s, %s, %s, %s, %s)''',
        (user_id, username, get_current_time(), request.remote_addr, request.headers.get('User-Agent', 'Unknown')))
    db.commit()
    db.close()

def log_logout(user_id, username):
    db = get_db()
    try:
        cursor = db.cursor()
        cursor.execute('''SELECT id FROM login_history 
            WHERE user_id = %s AND logout_time IS NULL 
            ORDER BY login_time DESC LIMIT 1''', (user_id,))
        record = cursor.fetchone()
        if record:
            cursor.execute('''UPDATE login_history 
                SET logout_time = %s 
                WHERE id = %s''', (get_current_time(), record['id']))
            db.commit()
    except Exception as e:
        print(f"Error logging logout: {e}")
    finally:
        db.close()

def log_api_call(provider_id, endpoint, method, request_data, response_data, status_code):
    db = get_db()
    cursor = db.cursor()
    cursor.execute('''INSERT INTO api_logs 
        (provider_id, endpoint, method, request, response, status_code, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s)''',
        (provider_id, endpoint, method, json.dumps(request_data), json.dumps(response_data), status_code, get_current_time()))
    db.commit()
    db.close()

# ---------- MULTI-PROVIDER API FUNCTIONS ----------
def call_provider_api(provider_id, endpoint, method='GET', data=None):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM providers WHERE id = %s", (provider_id,))
    provider = cursor.fetchone()
    db.close()
    if not provider:
        return {'error': 'Provider not found'}
    try:
        api_type = provider.get('api_type', 'socpanel')
        if api_type == 'socpanel':
            return call_socpanel_api(provider_id, endpoint, method, data)
        elif api_type == 'peaksmm':
            return call_peaksmm_api(provider_id, endpoint, method, data)
        else:
            headers = {
                'Authorization': f'Bearer {provider["api_key"]}',
                'Content-Type': 'application/json'
            }
            url = f"{provider['url']}/{endpoint}"
            if method.upper() == 'GET':
                response = requests.get(url, headers=headers, timeout=30)
            else:
                response = requests.post(url, headers=headers, json=data, timeout=30)
            log_api_call(provider_id, endpoint, method, data, response.text, response.status_code)
            if response.status_code == 200:
                return response.json()
            else:
                return {'error': f'API Error: {response.status_code}', 'response': response.text}
    except requests.exceptions.RequestException as e:
        log_api_call(provider_id, endpoint, method, data, str(e), 500)
        return {'error': str(e)}

def call_socpanel_api(provider_id, endpoint='getServices', method='GET', data=None):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM providers WHERE id = %s", (provider_id,))
    provider = cursor.fetchone()
    db.close()
    if not provider:
        return {'error': 'Provider not found'}
    try:
        api_key = provider['api_key']
        api_url = provider['url']
        if api_url.endswith('/privateApi'):
            api_url = api_url.replace('/privateApi', '')
        
        private_url = f"{api_url}/privateApi/{endpoint}"
        params = {'token': api_key}
        if data:
            params.update(data)
        
        if method.upper() == 'GET':
            response = requests.get(private_url, params=params, timeout=30)
        else:
            response = requests.post(private_url, data=params, timeout=30)
            
        log_api_call(provider_id, endpoint, method, params, response.text, response.status_code)
        if response.status_code == 200:
            try:
                return response.json()
            except:
                return {'response': response.text}
        else:
            return {'error': f'API Error: {response.status_code}', 'response': response.text}
    except requests.exceptions.RequestException as e:
        log_api_call(provider_id, endpoint, method, data, str(e), 500)
        return {'error': str(e)}

def call_peaksmm_api(provider_id, endpoint, method='GET', data=None):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM providers WHERE id = %s", (provider_id,))
    provider = cursor.fetchone()
    db.close()
    if not provider:
        return {'error': 'Provider not found'}
    try:
        headers = {
            'Authorization': f'Bearer {provider["api_key"]}',
            'Content-Type': 'application/json'
        }
        url = f"{provider['url']}/{endpoint}"
        if method.upper() == 'GET':
            response = requests.get(url, headers=headers, timeout=30)
        else:
            response = requests.post(url, headers=headers, json=data, timeout=30)
        log_api_call(provider_id, endpoint, method, data, response.text, response.status_code)
        if response.status_code == 200:
            return response.json()
        else:
            return {'error': f'API Error: {response.status_code}', 'response': response.text}
    except requests.exceptions.RequestException as e:
        log_api_call(provider_id, endpoint, method, data, str(e), 500)
        return {'error': str(e)}




# ===== FIXED: sync_provider_services (ဒေါ်လာသင်္ကေတဖယ်ရှားရန်) =====
def sync_provider_services(provider_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM providers WHERE id = %s", (provider_id,))
    provider = cursor.fetchone()
    if not provider:
        db.close()
        return {'error': 'Provider not found'}
    db.close()
    
    result = call_provider_api(provider_id, 'getServices', 'GET')
    if 'error' in result:
        return {'error': result['error'], 'response': result.get('response', '')}
    
    services_data = result.get('services', [])
    if not services_data:
        services_data = result if isinstance(result, list) else []
    if not services_data:
        return {'error': 'No services found', 'response': result}
    
    db = get_db()
    cursor = db.cursor()
    added = 0
    updated = 0
    for service in services_data:
        try:
            service_id = service.get('id') or service.get('service_id')
            name = service.get('name') or service.get('service_name')
            category = service.get('category') or 'General'
            
            # ===== FIX: Rate ကို $ ဖယ်ရှားပြီး numeric အနေနဲ့ သိမ်းပါ =====
            rate = 0
            for key in ['price', 'rate', 'price_per_k', 'price_per_1000', 'service_rate', 'provider_price', 'price_per_1k']:
                if key in service and service[key] is not None:
                    try:
                        rate_val = service[key]
                        if isinstance(rate_val, str):
                            # Remove $, commas, and extra spaces
                            rate_val = rate_val.replace('$', '').replace(',', '').strip()
                        rate = float(rate_val)
                        break
                    except:
                        pass
            
            min_order = int(service.get('min', service.get('min_order', 100)))
            max_order = int(service.get('max', service.get('max_order', 100000)))
            description = service.get('description', '')
            if not service_id or not name:
                continue
            cursor.execute("SELECT id FROM services WHERE provider_id = %s AND provider_service_id = %s", (provider['id'], str(service_id)))
            existing = cursor.fetchone()
            if existing:
                cursor.execute('''UPDATE services 
                    SET name = %s, category = %s, description = %s, rate = %s, min_order = %s, max_order = %s, updated_at = %s
                    WHERE provider_id = %s AND provider_service_id = %s''',
                    (name, category, description, rate, min_order, max_order, get_current_time(), provider['id'], str(service_id)))
                updated += 1
            else:
                cursor.execute('''INSERT INTO services 
                    (provider_id, provider_service_id, category, name, description, rate, min_order, max_order, markup, service_type, status, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)''',
                    (provider['id'], str(service_id), category, name, description, 
                     rate, min_order, max_order, 15, 'standard', 'active', get_current_time(), get_current_time()))
                added += 1
        except Exception as e:
            print(f"Error adding service: {e}")
    cursor.execute("UPDATE providers SET last_sync = %s, updated_at = %s WHERE id = %s", (get_current_time(), get_current_time(), provider['id']))
    db.commit()
    db.close()
    return {'success': True, 'added': added, 'updated': updated}

def sync_order_to_provider(order_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM orders WHERE id = %s", (order_id,))
    order = cursor.fetchone()
    if not order:
        db.close()
        return {'error': 'Order not found'}
    cursor.execute("SELECT * FROM services WHERE id = %s", (order['service_id'],))
    service = cursor.fetchone()
    if not service or not service['provider_id']:
        db.close()
        return {'error': 'No provider configured'}
    cursor.execute("SELECT * FROM providers WHERE id = %s", (service['provider_id'],))
    provider = cursor.fetchone()
    if not provider:
        db.close()
        return {'error': 'Provider not found'}
    cost_usd = float(order['cost'])
    if float(provider['balance']) < cost_usd:
        db.close()
        return {'error': 'Provider balance insufficient'}
    provider_data = {
        'service_id': service['provider_service_id'],
        'link': order['link'],
        'quantity': order['quantity']
    }
    result = call_provider_api(service['provider_id'], 'order', 'POST', provider_data)
    if 'error' in result:
        db.close()
        return {'error': result['error']}
    cursor.execute("UPDATE providers SET balance = balance - %s WHERE id = %s", (cost_usd, provider['id']))
    cursor.execute("UPDATE orders SET provider_order_id = %s, status = 'processing', updated_at = %s WHERE id = %s",
                  (result.get('order_id', 'N/A'), get_current_time(), order_id))
    db.commit()
    db.close()
    return {'success': True, 'order_id': result.get('order_id')}

# ---------- PUBLIC ROUTES ----------
@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        if not username or not password:
            return render_template('login.html', error='ကျေးဇူးပြု၍ အချက်အလက်အားလုံးကို ဖြည့်ပါ။')
        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
        user = cursor.fetchone()
        db.close()
        if user and verify_password(password, user['password']):
            if user['status'] != 'active':
                return render_template('login.html', error='သင့်အကောင့်ကို ပိတ်ထားပါသည်။')
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['tier'] = user['tier']
            session['name'] = user['name']
            db = get_db()
            cursor = db.cursor()
            cursor.execute("UPDATE users SET last_login = %s WHERE id = %s", (get_current_time(), user['id']))
            db.commit()
            db.close()
            log_login(user['id'], user['username'])
            log_activity(user['id'], user['username'], 'login', 'User logged in successfully')
            flash('မင်္ဂလာပါ ပြန်လာပါ!', 'success')
            return redirect(url_for('dashboard'))
        else:
            return render_template('login.html', error='အသုံးပြုသူအမည် သို့မဟုတ် စကားဝှက် မှားယွင်းနေပါသည်။')
    return render_template('login.html')

@app.route('/logout')
def logout():
    user_id = session.get('user_id')
    username = session.get('username')
    if user_id:
        log_logout(user_id, username)
        log_activity(user_id, username, 'logout', 'User logged out')
    session.clear()
    flash('အောင်မြင်စွာ ထွက်ခဲ့ပါပြီ။', 'info')
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        email = request.form.get('email', '').strip()
        phone = request.form.get('phone', '').strip()
        if not all([name, username, password]):
            return render_template('register.html', error='ကျေးဇူးပြု၍ လိုအပ်သော အချက်အလက်များကို ဖြည့်ပါ။')
        if len(password) < 6:
            return render_template('register.html', error='စကားဝှက်သည် အနည်းဆုံး ၆ လုံးရှိရပါမည်။')
        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
        if cursor.fetchone():
            db.close()
            return render_template('register.html', error='ဤအသုံးပြုသူအမည်ကို အခြားသူက သုံးထားပြီးဖြစ်သည်။')
        if email:
            cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
            if cursor.fetchone():
                db.close()
                return render_template('register.html', error='ဤအီးမေးလ်ကို အခြားသူက သုံးထားပြီးဖြစ်သည်။')
        user_id = generate_id('USR')
        hashed_password = hash_password(password)
        cursor.execute('''INSERT INTO users 
            (id, name, username, password, email, phone, tier, balance, status, api_key, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)''',
            (user_id, name, username, hashed_password, email or None, phone or None, 
             'user', 0, 'active', secrets.token_hex(16), get_current_time(), get_current_time()))
        db.commit()
        db.close()
        flash('အကောင့် အောင်မြင်စွာ ဖွင့်ပြီးပါပြီ။ ကျေးဇူးပြု၍ ဝင်ရောက်ပါ။', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/dashboard')
@require_login
def dashboard():
    tier = session.get('tier', 'user')
    if tier == 'super_admin':
        return redirect(url_for('super_admin_dashboard'))
    elif tier == 'admin':
        return redirect(url_for('admin_dashboard'))
    elif tier == 'reseller':
        return redirect(url_for('reseller_dashboard'))
    else:
        return redirect(url_for('user_dashboard'))

# ========== USER AGREEMENT ROUTE ==========
@app.route('/user/terms-agreement', methods=['GET', 'POST'])
@require_login
def user_terms_agreement():
    user_id = session['user_id']
    db = get_db()
    cursor = db.cursor()

    cursor.execute("SELECT * FROM user_agreements WHERE user_id = %s AND status = 'approved' ORDER BY agreed_at DESC LIMIT 1", (user_id,))
    existing = cursor.fetchone()
    if existing:
        db.close()
        flash('သင်သည် မူဝါဒကို အတည်ပြုပြီးဖြစ်သည်။', 'info')
        return redirect(url_for('user_dashboard'))

    if request.method == 'POST':
        agree = request.form.get('agree')
        if agree:
            cursor.execute('''INSERT INTO user_agreements (user_id, username, agreed_at, ip_address, user_agent, status)
                VALUES (%s, %s, %s, %s, %s, %s)''',
                (user_id, session['username'], get_current_time(), 
                 request.remote_addr, request.headers.get('User-Agent', ''), 'pending'))
            db.commit()
            db.close()
            flash('မူဝါဒသဘောတူချက် အောင်မြင်စွာ ပို့ပြီးပါပြီ။ Admin အတည်ပြုချက်ကို စောင့်ပါ။', 'success')
            log_activity(user_id, session['username'], 'terms_agreement', 'User agreed to terms and policies')
            return redirect(url_for('user_dashboard'))
        else:
            flash('ကျေးဇူးပြု၍ သဘောတူညီချက်ကို အမှန်ခြစ်ပါ။', 'error')
    db.close()
    
    return render_template('user/terms_agreement.html')

# ========== SUPER ADMIN ROUTES ==========
@app.route('/super-admin')
@require_super_admin
def super_admin_dashboard():
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT COUNT(*) as count FROM users")
    total_users = cursor.fetchone()['count']
    cursor.execute("SELECT COUNT(*) as count FROM orders")
    total_orders = cursor.fetchone()['count']
    cursor.execute("SELECT SUM(price) as total FROM orders WHERE status='completed'")
    total_revenue = cursor.fetchone()['total'] or 0
    cursor.execute("SELECT SUM(profit) as total FROM orders WHERE status='completed'")
    total_profit = cursor.fetchone()['total'] or 0
    cursor.execute("SELECT COUNT(*) as count FROM orders WHERE status='pending'")
    pending_orders = cursor.fetchone()['count']
    cursor.execute("SELECT COUNT(*) as count FROM payment_requests WHERE status='pending'")
    pending_payments = cursor.fetchone()['count']
    cursor.execute('''SELECT o.*, u.name as user_name 
        FROM orders o JOIN users u ON o.user_id = u.id 
        ORDER BY o.created_at DESC LIMIT 10''')
    recent_orders = cursor.fetchall()
    db.close()
    return render_template('super_admin/dashboard.html',
        total_users=total_users, total_orders=total_orders,
        total_revenue=total_revenue, total_profit=total_profit,
        pending_orders=pending_orders, pending_payments=pending_payments,
        recent_orders=recent_orders)

@app.route('/super-admin/users')
@require_super_admin
def super_admin_users():
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM users ORDER BY created_at DESC")
    users = cursor.fetchall()
    db.close()
    return render_template('super_admin/users.html', users=users)

@app.route('/super-admin/users/<user_id>', methods=['GET', 'PUT', 'DELETE'])
@require_super_admin
def super_admin_user_manage(user_id):
    db = get_db()
    cursor = db.cursor()
    if request.method == 'GET':
        cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()
        db.close()
        return jsonify(user) if user else (jsonify({'error': 'User not found'}), 404)
    elif request.method == 'PUT':
        data = request.json
        updates, params = [], []
        for field in ['name', 'username', 'email', 'phone', 'tier', 'balance', 'status']:
            if field in data:
                updates.append(f"{field}=%s")
                params.append(data[field])
        if 'password' in data and data['password']:
            updates.append("password=%s")
            params.append(hash_password(data['password']))
        if updates:
            params.extend([get_current_time(), user_id])
            cursor.execute(f"UPDATE users SET {', '.join(updates)}, updated_at=%s WHERE id=%s", params)
            db.commit()
            log_activity(session['user_id'], session['username'], 'user_update', f"Updated user {user_id}")
        db.close()
        return jsonify({'success': True})
    elif request.method == 'DELETE':
        if user_id == session['user_id']:
            db.close()
            return jsonify({'error': 'Cannot delete yourself'}), 403
        cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
        db.commit()
        log_activity(session['user_id'], session['username'], 'user_delete', f"Deleted user {user_id}")
        db.close()
        return jsonify({'success': True})

@app.route('/super-admin/users', methods=['POST'])
@require_super_admin
def super_admin_create_user():
    data = request.json
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM users WHERE username = %s", (data['username'],))
    if cursor.fetchone():
        db.close()
        return jsonify({'error': 'Username already exists'}), 400
    user_id = generate_id('USR')
    cursor.execute('''INSERT INTO users 
        (id, name, username, password, tier, balance, status, api_key, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)''',
        (user_id, data['name'], data['username'], hash_password(data['password']), 
         data.get('tier', 'user'), data.get('balance', 0), 'active', 
         secrets.token_hex(16), get_current_time(), get_current_time()))
    db.commit()
    db.close()
    return jsonify({'success': True, 'user_id': user_id})

@app.route('/super-admin/login-history')
@require_super_admin
def super_admin_login_history():
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM login_history ORDER BY login_time DESC LIMIT 100")
    history = cursor.fetchall()
    db.close()
    for record in history:
        if record.get('login_time'):
            if hasattr(record['login_time'], 'strftime'):
                record['login_time'] = record['login_time'].strftime('%Y-%m-%d %H:%M:%S')
            else:
                record['login_time'] = str(record['login_time'])
        if record.get('logout_time'):
            if hasattr(record['logout_time'], 'strftime'):
                record['logout_time'] = record['logout_time'].strftime('%Y-%m-%d %H:%M:%S')
            else:
                record['logout_time'] = str(record['logout_time'])
    return render_template('super_admin/login_history.html', history=history)

@app.route('/super-admin/activity-logs')
@require_super_admin
def super_admin_activity_logs():
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM activity_logs ORDER BY created_at DESC LIMIT 100")
    logs = cursor.fetchall()
    db.close()
    for log in logs:
        if log.get('created_at'):
            if hasattr(log['created_at'], 'strftime'):
                log['created_at'] = log['created_at'].strftime('%Y-%m-%d %H:%M:%S')
            else:
                log['created_at'] = str(log['created_at'])
    return render_template('super_admin/activity_logs.html', logs=logs)

# ========== ADMIN ROUTES ==========
@app.route('/admin')
@require_admin
def admin_dashboard():
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT value FROM settings WHERE `key` = 'exchange_rate'")
    setting = cursor.fetchone()
    exchange_rate = float(setting['value']) if setting else 4000.0

    cursor.execute('''
        SELECT 
            COUNT(*) as total_orders,
            SUM(price) as total_revenue,
            SUM(cost) as total_cost,
            SUM(profit) as total_profit
        FROM orders WHERE status = 'completed'
    ''')
    stats = cursor.fetchone()
    total_revenue = float(stats['total_revenue'] or 0)
    total_cost = float(stats['total_cost'] or 0)
    total_profit = float(stats['total_profit'] or 0)
    total_orders = int(stats['total_orders'] or 0)

    cursor.execute('''
        SELECT 
            DATE_FORMAT(created_at, '%Y-%m') as month,
            COUNT(*) as orders,
            SUM(price) as revenue,
            SUM(cost) as cost,
            SUM(profit) as profit
        FROM orders 
        WHERE status = 'completed' AND YEAR(created_at) = YEAR(NOW())
        GROUP BY DATE_FORMAT(created_at, '%Y-%m')
        ORDER BY month
    ''')
    monthly_stats = cursor.fetchall()
    for m in monthly_stats:
        m['revenue'] = float(m['revenue'] or 0)
        m['cost'] = float(m['cost'] or 0)
        m['profit'] = float(m['profit'] or 0)

    cursor.execute('''
        SELECT 
            YEAR(created_at) as year,
            COUNT(*) as orders,
            SUM(price) as revenue,
            SUM(cost) as cost,
            SUM(profit) as profit
        FROM orders WHERE status = 'completed'
        GROUP BY YEAR(created_at)
        ORDER BY year
    ''')
    yearly_stats = cursor.fetchall()
    for y in yearly_stats:
        y['revenue'] = float(y['revenue'] or 0)
        y['cost'] = float(y['cost'] or 0)
        y['profit'] = float(y['profit'] or 0)

    cursor.execute('''
        SELECT 
            service_name,
            COUNT(*) as orders,
            SUM(price) as revenue,
            SUM(profit) as profit
        FROM orders WHERE status = 'completed'
        GROUP BY service_name
        ORDER BY revenue DESC LIMIT 5
    ''')
    top_services = cursor.fetchall()
    for s in top_services:
        s['revenue'] = float(s['revenue'] or 0)
        s['profit'] = float(s['profit'] or 0)

    cursor.execute('''
        SELECT 
            p.name as provider_name,
            COUNT(o.id) as orders,
            SUM(o.cost) as total_cost
        FROM orders o
        JOIN services s ON o.service_id = s.id
        JOIN providers p ON s.provider_id = p.id
        WHERE o.status = 'completed'
        GROUP BY p.id
        ORDER BY total_cost DESC
    ''')
    provider_costs = cursor.fetchall()
    for p in provider_costs:
        p['total_cost'] = float(p['total_cost'] or 0)

    cursor.execute('''
        SELECT o.*, u.name as user_name 
        FROM orders o 
        JOIN users u ON o.user_id = u.id 
        WHERE o.status = 'completed'
        ORDER BY o.created_at DESC LIMIT 10
    ''')
    recent_orders = cursor.fetchall()
    for order in recent_orders:
        order['cost'] = float(order['cost'] or 0)
        order['price'] = float(order['price'] or 0)
        order['profit'] = float(order['profit'] or 0)

    # ===== SocPanel Summary =====
    cursor.execute("SELECT id FROM providers WHERE name LIKE '%SocPanel%' LIMIT 1")
    soc_provider = cursor.fetchone()
    socpanel_summary = {
        'total_orders': 0,
        'total_revenue_usd': 0,
        'total_cost_usd': 0,
        'total_profit_usd': 0,
        'total_revenue_mmk': 0,
        'total_cost_mmk': 0,
        'total_profit_mmk': 0,
        'total_revenue': 0,
        'total_cost': 0,
        'total_profit': 0,
        'profit_percent': 0,
    }
    if soc_provider:
        provider_id = soc_provider['id']
        cursor.execute("""
            SELECT 
                COUNT(*) as total_orders,
                SUM(price) as total_revenue,
                SUM(cost) as total_cost,
                SUM(profit) as total_profit
            FROM orders o
            JOIN services s ON o.service_id = s.id
            WHERE s.provider_id = %s AND o.status = 'completed'
        """, (provider_id,))
        stats_soc = cursor.fetchone()
        if stats_soc:
            socpanel_summary['total_orders'] = int(stats_soc['total_orders'] or 0)
            socpanel_summary['total_revenue_usd'] = float(stats_soc['total_revenue'] or 0)
            socpanel_summary['total_cost_usd'] = float(stats_soc['total_cost'] or 0)
            socpanel_summary['total_profit_usd'] = float(stats_soc['total_profit'] or 0)
            socpanel_summary['total_revenue_mmk'] = socpanel_summary['total_revenue_usd'] * exchange_rate
            socpanel_summary['total_cost_mmk'] = socpanel_summary['total_cost_usd'] * exchange_rate
            socpanel_summary['total_profit_mmk'] = socpanel_summary['total_profit_usd'] * exchange_rate
            socpanel_summary['total_revenue'] = socpanel_summary['total_revenue_mmk']
            socpanel_summary['total_cost'] = socpanel_summary['total_cost_mmk']
            socpanel_summary['total_profit'] = socpanel_summary['total_profit_mmk']
            if socpanel_summary['total_revenue'] > 0:
                socpanel_summary['profit_percent'] = (socpanel_summary['total_profit'] / socpanel_summary['total_revenue']) * 100

    db.close()

    stats_dict = {
        'total_orders': total_orders,
        'total_revenue_usd': total_revenue,
        'total_cost_usd': total_cost,
        'total_profit_usd': total_profit,
        'total_revenue_mmk': total_revenue * exchange_rate,
        'total_cost_mmk': total_cost * exchange_rate,
        'total_profit_mmk': total_profit * exchange_rate,
    }
    if stats_dict['total_revenue_mmk'] > 0:
        stats_dict['profit_percentage'] = (stats_dict['total_profit_mmk'] / stats_dict['total_revenue_mmk']) * 100
    else:
        stats_dict['profit_percentage'] = 0

    recent_summary = {
        'total_price': sum(o['price'] for o in recent_orders),
        'total_cost': sum(o['cost'] for o in recent_orders),
        'total_profit': sum(o['profit'] for o in recent_orders),
    }
    if recent_summary['total_price'] > 0:
        recent_summary['profit_percentage'] = (recent_summary['total_profit'] / recent_summary['total_price']) * 100
    else:
        recent_summary['profit_percentage'] = 0

    current_year = datetime.now().year
    current_year_stats = {'year': current_year, 'orders': 0, 'revenue': 0, 'cost': 0, 'profit': 0}
    total_year_stats = {'orders': 0, 'revenue': 0, 'cost': 0, 'profit': 0}
    for y in yearly_stats:
        total_year_stats['orders'] += y['orders']
        total_year_stats['revenue'] += y['revenue']
        total_year_stats['cost'] += y['cost']
        total_year_stats['profit'] += y['profit']
        if int(y['year']) == current_year:
            current_year_stats['orders'] = y['orders']
            current_year_stats['revenue'] = y['revenue']
            current_year_stats['cost'] = y['cost']
            current_year_stats['profit'] = y['profit']
    if current_year_stats['revenue'] > 0:
        current_year_stats['profit_percentage'] = (current_year_stats['profit'] / current_year_stats['revenue']) * 100
    else:
        current_year_stats['profit_percentage'] = 0
    if total_year_stats['revenue'] > 0:
        total_year_stats['profit_percentage'] = (total_year_stats['profit'] / total_year_stats['revenue']) * 100
    else:
        total_year_stats['profit_percentage'] = 0

    months = [m['month'] for m in monthly_stats]
    monthly_revenue = [m['revenue'] * exchange_rate for m in monthly_stats]
    monthly_profit = [m['profit'] * exchange_rate for m in monthly_stats]
    monthly_orders = [m['orders'] for m in monthly_stats]
    years = [y['year'] for y in yearly_stats]
    yearly_revenue = [y['revenue'] * exchange_rate for y in yearly_stats]
    yearly_profit = [y['profit'] * exchange_rate for y in yearly_stats]
    top_service_names = [s['service_name'] for s in top_services]
    top_service_revenues = [s['revenue'] * exchange_rate for s in top_services]
    top_service_orders = [s['orders'] for s in top_services]
    top_service_profits = [s['profit'] * exchange_rate for s in top_services]
    provider_names = [p['provider_name'] for p in provider_costs]
    provider_totals = [p['total_cost'] * exchange_rate for p in provider_costs]

    return render_template('admin/dashboard.html',
        stats=stats_dict,
        monthly_stats=monthly_stats,
        yearly_stats=yearly_stats,
        top_services=top_services,
        provider_costs=provider_costs,
        recent_orders=recent_orders,
        recent_summary=recent_summary,
        current_year_stats=current_year_stats,
        total_year_stats=total_year_stats,
        exchange_rate=exchange_rate,
        months=json.dumps(months),
        monthly_revenue=json.dumps(monthly_revenue),
        monthly_profit=json.dumps(monthly_profit),
        monthly_orders=json.dumps(monthly_orders),
        years=json.dumps(years),
        yearly_revenue=json.dumps(yearly_revenue),
        yearly_profit=json.dumps(yearly_profit),
        top_service_names=json.dumps(top_service_names),
        top_service_revenues=json.dumps(top_service_revenues),
        top_service_orders=json.dumps(top_service_orders),
        top_service_profits=json.dumps(top_service_profits),
        provider_names=json.dumps(provider_names),
        provider_totals=json.dumps(provider_totals),
        socpanel_summary=socpanel_summary
    )

@app.route('/admin/users')
@require_admin
def admin_users():
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM users WHERE tier != 'super_admin' ORDER BY created_at DESC")
    users = cursor.fetchall()
    db.close()
    return render_template('admin/users.html', users=users)

@app.route('/admin/users/<user_id>', methods=['GET', 'PUT'])
@require_admin
def admin_user_manage(user_id):
    db = get_db()
    cursor = db.cursor()
    if request.method == 'GET':
        cursor.execute("SELECT * FROM users WHERE id = %s AND tier != 'super_admin'", (user_id,))
        user = cursor.fetchone()
        db.close()
        return jsonify(user) if user else (jsonify({'error': 'User not found'}), 404)
    elif request.method == 'PUT':
        data = request.json
        updates, params = [], []
        for field in ['name', 'username', 'email', 'phone', 'tier', 'balance', 'status']:
            if field in data:
                updates.append(f"{field}=%s")
                params.append(data[field])
        if 'password' in data and data['password']:
            updates.append("password=%s")
            params.append(hash_password(data['password']))
        if updates:
            params.extend([get_current_time(), user_id])
            cursor.execute(f"UPDATE users SET {', '.join(updates)}, updated_at=%s WHERE id=%s AND tier != 'super_admin'", params)
            db.commit()
            log_activity(session['user_id'], session['username'], 'user_update', f"Updated user {user_id}")
        db.close()
        return jsonify({'success': True})

@app.route('/admin/users', methods=['POST'])
@require_admin
def admin_create_user():
    data = request.json
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM users WHERE username = %s", (data['username'],))
    if cursor.fetchone():
        db.close()
        return jsonify({'error': 'Username already exists'}), 400
    user_id = generate_id('USR')
    cursor.execute('''INSERT INTO users 
        (id, name, username, password, tier, balance, status, api_key, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)''',
        (user_id, data['name'], data['username'], hash_password(data['password']), 
         data.get('tier', 'user'), data.get('balance', 0), 'active', 
         secrets.token_hex(16), get_current_time(), get_current_time()))
    db.commit()
    db.close()
    return jsonify({'success': True, 'user_id': user_id})

@app.route('/admin/users/<user_id>', methods=['DELETE'])
@require_admin
def admin_delete_user(user_id):
    if user_id == session['user_id']:
        return jsonify({'error': 'Cannot delete yourself'}), 403
    db = get_db()
    cursor = db.cursor()
    cursor.execute("DELETE FROM users WHERE id = %s AND tier != 'super_admin'", (user_id,))
    db.commit()
    log_activity(session['user_id'], session['username'], 'user_delete', f"Deleted user {user_id}")
    db.close()
    return jsonify({'success': True})

@app.route('/admin/orders')
@require_admin
def admin_orders():
    db = get_db()
    cursor = db.cursor()
    status_filter = request.args.get('status', 'all')
    search = request.args.get('search', '')
    query = '''SELECT o.*, u.name as user_name FROM orders o JOIN users u ON o.user_id = u.id WHERE 1=1'''
    params = []
    if status_filter != 'all':
        query += ' AND o.status = %s'
        params.append(status_filter)
    if search:
        query += ' AND (o.id LIKE %s OR o.link LIKE %s OR o.service_name LIKE %s)'
        search_term = f'%{search}%'
        params.extend([search_term, search_term, search_term])
    query += ' ORDER BY o.created_at DESC'
    cursor.execute(query, params)
    orders = cursor.fetchall()
    cursor.execute("SELECT id, name FROM users ORDER BY name")
    users = cursor.fetchall()
    db.close()
    return render_template('admin/orders.html', orders=orders, users=users, 
                          status_filter=status_filter, search=search)

@app.route('/admin/orders/<int:order_id>/status', methods=['PUT'])
@require_admin
def admin_update_order_status(order_id):
    data = request.json
    db = get_db()
    cursor = db.cursor()
    cursor.execute("UPDATE orders SET status = %s, updated_at = %s WHERE id = %s",
               (data.get('status'), get_current_time(), order_id))
    db.commit()
    log_activity(session['user_id'], session['username'], 'order_status_update', f"Updated order {order_id} to {data.get('status')}")
    db.close()
    return jsonify({'success': True})

@app.route('/admin/orders/<int:order_id>', methods=['DELETE'])
@require_admin
def admin_delete_order(order_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("DELETE FROM orders WHERE id = %s", (order_id,))
    db.commit()
    log_activity(session['user_id'], session['username'], 'order_delete', f"Deleted order {order_id}")
    db.close()
    return jsonify({'success': True})

@app.route('/admin/services')
@require_admin
def admin_services():
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM services ORDER BY category, name")
    services = cursor.fetchall()
    cursor.execute("SELECT * FROM providers WHERE status='active'")
    providers = cursor.fetchall()
    cursor.execute("SELECT value FROM settings WHERE `key` = 'exchange_rate'")
    setting = cursor.fetchone()
    exchange_rate = float(setting['value']) if setting else 4000.0
    
    cursor.execute("SELECT * FROM providers WHERE name LIKE '%SocPanel%' LIMIT 1")
    provider = cursor.fetchone()
    
    db.close()
    for service in services:
        service['rate'] = float(service['rate'])
    return render_template('admin/services.html', 
                          services=services, 
                          providers=providers, 
                          exchange_rate=exchange_rate,
                          provider=provider)

@app.route('/admin/services', methods=['POST'])
@require_admin
def admin_create_service():
    data = request.json
    db = get_db()
    cursor = db.cursor()
    cursor.execute('''INSERT INTO services 
        (provider_id, provider_service_id, category, name, description, rate, min_order, max_order, markup, service_type, status, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)''',
        (data.get('provider_id'), data.get('provider_service_id'), 
         data['category'], data['name'], data.get('description', ''),
         data['rate'], data['min_order'], data['max_order'],
         data.get('markup', 15), data.get('service_type', 'standard'),
         'active', get_current_time(), get_current_time()))
    db.commit()
    log_activity(session['user_id'], session['username'], 'service_create', f"Created service {data['name']}")
    db.close()
    return jsonify({'success': True})

@app.route('/admin/services/<int:service_id>', methods=['PUT', 'DELETE'])
@require_admin
def admin_service_manage(service_id):
    db = get_db()
    cursor = db.cursor()
    if request.method == 'PUT':
        data = request.json
        updates, params = [], []
        for field in ['provider_id', 'provider_service_id', 'category', 'name', 'description', 'rate', 'min_order', 'max_order', 'markup', 'service_type', 'status']:
            if field in data:
                updates.append(f"{field}=%s")
                params.append(data[field])
        if updates:
            params.extend([get_current_time(), service_id])
            cursor.execute(f"UPDATE services SET {', '.join(updates)}, updated_at=%s WHERE id=%s", params)
            db.commit()
            log_activity(session['user_id'], session['username'], 'service_update', f"Updated service {service_id}")
        db.close()
        return jsonify({'success': True})
    elif request.method == 'DELETE':
        cursor.execute("SELECT COUNT(*) as count FROM orders WHERE service_id = %s", (service_id,))
        count = cursor.fetchone()['count']
        if count > 0:
            db.close()
            return jsonify({'error': f'Cannot delete service because there are {count} orders linked to it.'}), 400
        cursor.execute("DELETE FROM services WHERE id = %s", (service_id,))
        db.commit()
        log_activity(session['user_id'], session['username'], 'service_delete', f"Deleted service {service_id}")
        db.close()
        return jsonify({'success': True})

@app.route('/admin/services/<int:service_id>/edit', methods=['GET'])
@require_admin
def admin_service_edit(service_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM services WHERE id = %s", (service_id,))
    service = cursor.fetchone()
    db.close()
    if not service:
        return jsonify({'error': 'Service not found'}), 404
    return jsonify(service)

@app.route('/admin/services/delete-all', methods=['DELETE'])
@require_admin
def admin_delete_all_services():
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("SELECT COUNT(*) as count FROM orders")
        orders_count = cursor.fetchone()['count']
        if orders_count > 0:
            db.close()
            return jsonify({'success': False, 'error': f'Cannot delete services because there are {orders_count} orders linked to them.'}), 400
        cursor.execute("DELETE FROM services")
        db.commit()
        count = cursor.rowcount
        log_activity(session['user_id'], session['username'], 'delete_all_services', f"Deleted all {count} services")
        db.close()
        return jsonify({'success': True, 'message': f'Successfully deleted {count} services.'})
    except Exception as e:
        db.rollback()
        db.close()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/admin/payment_methods')
@require_admin
def admin_payment_methods():
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM payment_methods ORDER BY name")
    methods = cursor.fetchall()
    db.close()
    return render_template('admin/payment_methods.html', methods=methods)

@app.route('/admin/payment_methods', methods=['POST'])
@require_admin
def admin_add_payment_method():
    data = request.json
    db = get_db()
    cursor = db.cursor()
    cursor.execute('''INSERT INTO payment_methods 
        (name, type, account_name, account_number, phone, instructions, is_active, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)''',
        (data['name'], data['type'], data.get('account_name', ''), data.get('account_number', ''),
         data.get('phone', ''), data.get('instructions', ''), data.get('is_active', 1), 
         get_current_time(), get_current_time()))
    db.commit()
    log_activity(session['user_id'], session['username'], 'payment_method_add', f"Added payment method {data['name']}")
    db.close()
    return jsonify({'success': True})

@app.route('/admin/payment_methods/<int:method_id>', methods=['GET', 'PUT', 'DELETE'])
@require_admin
def admin_payment_method_manage(method_id):
    db = get_db()
    cursor = db.cursor()
    if request.method == 'GET':
        cursor.execute("SELECT * FROM payment_methods WHERE id = %s", (method_id,))
        method = cursor.fetchone()
        db.close()
        return jsonify(method) if method else (jsonify({'error': 'Method not found'}), 404)
    elif request.method == 'PUT':
        data = request.json
        updates, params = [], []
        for field in ['name', 'type', 'account_name', 'account_number', 'phone', 'instructions', 'is_active']:
            if field in data:
                updates.append(f"{field}=%s")
                params.append(data[field])
        if updates:
            params.extend([get_current_time(), method_id])
            cursor.execute(f"UPDATE payment_methods SET {', '.join(updates)}, updated_at=%s WHERE id=%s", params)
            db.commit()
            log_activity(session['user_id'], session['username'], 'payment_method_update', f"Updated payment method {method_id}")
        db.close()
        return jsonify({'success': True})
    elif request.method == 'DELETE':
        cursor.execute("DELETE FROM payment_methods WHERE id = %s", (method_id,))
        db.commit()
        log_activity(session['user_id'], session['username'], 'payment_method_delete', f"Deleted payment method {method_id}")
        db.close()
        return jsonify({'success': True})

@app.route('/admin/payments')
@require_admin
def admin_payments():
    db = get_db()
    cursor = db.cursor()
    cursor.execute('''SELECT p.*, u.name as user_name, pm.name as method_name
        FROM payment_requests p 
        JOIN users u ON p.user_id = u.id 
        LEFT JOIN payment_methods pm ON p.method_id = pm.id
        WHERE p.status='pending' 
        ORDER BY p.created_at DESC''')
    pending = cursor.fetchall()
    cursor.execute('''SELECT p.*, u.name as user_name, pm.name as method_name
        FROM payment_requests p 
        JOIN users u ON p.user_id = u.id 
        LEFT JOIN payment_methods pm ON p.method_id = pm.id
        WHERE p.status='approved' 
        ORDER BY p.approved_at DESC LIMIT 50''')
    approved = cursor.fetchall()
    cursor.execute('''SELECT p.*, u.name as user_name, pm.name as method_name
        FROM payment_requests p 
        JOIN users u ON p.user_id = u.id 
        LEFT JOIN payment_methods pm ON p.method_id = pm.id
        WHERE p.status='rejected' 
        ORDER BY p.created_at DESC LIMIT 50''')
    rejected = cursor.fetchall()
    db.close()
    
    for payment_list in [pending, approved, rejected]:
        for payment in payment_list:
            if payment.get('created_at') and hasattr(payment['created_at'], 'strftime'):
                payment['created_at'] = payment['created_at'].strftime('%Y-%m-%d %H:%M:%S')
            if payment.get('approved_at') and hasattr(payment['approved_at'], 'strftime'):
                payment['approved_at'] = payment['approved_at'].strftime('%Y-%m-%d %H:%M:%S')
    
    return render_template('admin/payments.html', pending=pending, approved=approved, rejected=rejected)

@app.route('/admin/payments/<int:payment_id>/approve', methods=['POST'])
@require_admin
def admin_approve_payment(payment_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM payment_requests WHERE id = %s", (payment_id,))
    payment = cursor.fetchone()
    if not payment:
        flash('မတွေ့ရှိပါ', 'error')
        return redirect(url_for('admin_payments'))
    cursor.execute("UPDATE users SET balance = balance + %s WHERE id = %s", (payment['amount'], payment['user_id']))
    cursor.execute('''UPDATE payment_requests SET status='approved', approved_at=%s, admin_notes=%s WHERE id=%s''',
               (get_current_time(), request.form.get('admin_notes', ''), payment_id))
    db.commit()
    log_activity(session['user_id'], session['username'], 'payment_approve', f"Approved payment #{payment_id}")
    db.close()
    flash(f'✅ ${payment["amount"]} ငွေသွင်းမှုကို အတည်ပြုပြီးပါပြီ။', 'success')
    return redirect(url_for('admin_payments'))

@app.route('/admin/payments/<int:payment_id>/reject', methods=['POST'])
@require_admin
def admin_reject_payment(payment_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM payment_requests WHERE id = %s", (payment_id,))
    payment = cursor.fetchone()
    if not payment:
        flash('မတွေ့ရှိပါ', 'error')
        return redirect(url_for('admin_payments'))
    cursor.execute('''UPDATE payment_requests SET status='rejected', admin_notes=%s WHERE id=%s''',
               (request.form.get('admin_notes', ''), payment_id))
    db.commit()
    log_activity(session['user_id'], session['username'], 'payment_reject', f"Rejected payment #{payment_id}")
    db.close()
    flash(f'❌ ${payment["amount"]} ငွေသွင်းမှုကို ပယ်ချပြီးပါပြီ။', 'error')
    return redirect(url_for('admin_payments'))

@app.route('/admin/withdraws')
@require_admin
def admin_withdraws():
    db = get_db()
    cursor = db.cursor()
    cursor.execute('''SELECT w.*, u.name as user_name 
        FROM withdraw_requests w JOIN users u ON w.user_id = u.id 
        WHERE w.status='pending' ORDER BY w.created_at DESC''')
    pending = cursor.fetchall()
    cursor.execute('''SELECT w.*, u.name as user_name 
        FROM withdraw_requests w JOIN users u ON w.user_id = u.id 
        WHERE w.status='approved' ORDER BY w.approved_at DESC LIMIT 50''')
    approved = cursor.fetchall()
    db.close()
    return render_template('admin/withdraws.html', pending=pending, approved=approved)

@app.route('/admin/withdraws/<int:withdraw_id>/approve', methods=['POST'])
@require_admin
def admin_approve_withdraw(withdraw_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM withdraw_requests WHERE id = %s", (withdraw_id,))
    withdraw = cursor.fetchone()
    if not withdraw:
        flash('မတွေ့ရှိပါ', 'error')
        return redirect(url_for('admin_withdraws'))
    cursor.execute("SELECT balance FROM users WHERE id = %s", (withdraw['user_id'],))
    user = cursor.fetchone()
    if user['balance'] < withdraw['amount']:
        flash('သုံးစွဲသူ၏ ငွေလက်ကျန် မလုံလောက်ပါ။', 'error')
        return redirect(url_for('admin_withdraws'))
    cursor.execute("UPDATE users SET balance = balance - %s WHERE id = %s", (withdraw['amount'], withdraw['user_id']))
    cursor.execute('''UPDATE withdraw_requests SET status='approved', approved_at=%s, admin_notes=%s WHERE id=%s''',
               (get_current_time(), request.form.get('admin_notes', ''), withdraw_id))
    db.commit()
    log_activity(session['user_id'], session['username'], 'withdraw_approve', f"Approved withdraw #{withdraw_id}")
    db.close()
    flash(f'✅ ${withdraw["amount"]} ငွေထုတ်မှုကို အတည်ပြုပြီးပါပြီ။', 'success')
    return redirect(url_for('admin_withdraws'))

@app.route('/admin/withdraws/<int:withdraw_id>/reject', methods=['POST'])
@require_admin
def admin_reject_withdraw(withdraw_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM withdraw_requests WHERE id = %s", (withdraw_id,))
    withdraw = cursor.fetchone()
    if not withdraw:
        flash('မတွေ့ရှိပါ', 'error')
        return redirect(url_for('admin_withdraws'))
    cursor.execute('''UPDATE withdraw_requests SET status='rejected', admin_notes=%s WHERE id=%s''',
               (request.form.get('admin_notes', ''), withdraw_id))
    db.commit()
    log_activity(session['user_id'], session['username'], 'withdraw_reject', f"Rejected withdraw #{withdraw_id}")
    db.close()
    flash(f'❌ ${withdraw["amount"]} ငွေထုတ်မှုကို ပယ်ချပြီးပါပြီ။', 'error')
    return redirect(url_for('admin_withdraws'))

@app.route('/admin/settings')
@require_admin
def admin_settings():
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM settings")
    settings = {row['key']: row['value'] for row in cursor.fetchall()}
    cursor.execute("SELECT * FROM providers ORDER BY name")
    providers = cursor.fetchall()
    db.close()
    return render_template('admin/settings.html', settings=settings, providers=providers)

@app.route('/admin/settings', methods=['POST'])
@require_admin
def admin_update_settings():
    data = request.json
    db = get_db()
    cursor = db.cursor()
    for key, value in data.items():
        cursor.execute("INSERT INTO settings (`key`, value, updated_at) VALUES (%s, %s, %s) ON DUPLICATE KEY UPDATE value=%s, updated_at=%s",
                   (key, str(value), get_current_time(), str(value), get_current_time()))
    db.commit()
    log_activity(session['user_id'], session['username'], 'settings_update', 'Updated system settings')
    db.close()
    return jsonify({'success': True})

@app.route('/admin/providers')
@require_admin
def admin_providers():
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM providers ORDER BY name")
    providers = cursor.fetchall()
    db.close()
    for provider in providers:
        if provider.get('last_sync'):
            if hasattr(provider['last_sync'], 'strftime'):
                provider['last_sync'] = provider['last_sync'].strftime('%Y-%m-%d %H:%M:%S')
            else:
                provider['last_sync'] = str(provider['last_sync'])
        if provider.get('created_at'):
            if hasattr(provider['created_at'], 'strftime'):
                provider['created_at'] = provider['created_at'].strftime('%Y-%m-%d %H:%M:%S')
            else:
                provider['created_at'] = str(provider['created_at'])
        if provider.get('updated_at'):
            if hasattr(provider['updated_at'], 'strftime'):
                provider['updated_at'] = provider['updated_at'].strftime('%Y-%m-%d %H:%M:%S')
            else:
                provider['updated_at'] = str(provider['updated_at'])
    return render_template('admin/providers.html', providers=providers)

@app.route('/admin/providers', methods=['POST'])
@require_admin
def admin_add_provider():
    data = request.json
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT id FROM providers WHERE name = %s", (data['name'],))
    if cursor.fetchone():
        db.close()
        return jsonify({'error': 'Provider name already exists'}), 400
    cursor.execute('''INSERT INTO providers 
        (name, url, api_key, api_type, balance, status, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)''',
        (data['name'], data['url'], data['api_key'], 
         data.get('api_type', 'socpanel'), data.get('balance', 0),
         data.get('status', 'active'), get_current_time(), get_current_time()))
    db.commit()
    log_activity(session['user_id'], session['username'], 'provider_add', f"Added provider {data['name']}")
    db.close()
    return jsonify({'success': True})

@app.route('/admin/providers/<int:provider_id>', methods=['GET', 'PUT', 'DELETE'])
@require_admin
def admin_provider_manage(provider_id):
    db = get_db()
    cursor = db.cursor()
    if request.method == 'GET':
        cursor.execute("SELECT * FROM providers WHERE id = %s", (provider_id,))
        provider = cursor.fetchone()
        db.close()
        return jsonify(provider) if provider else (jsonify({'error': 'Provider not found'}), 404)
    elif request.method == 'PUT':
        data = request.json
        updates, params = [], []
        for field in ['name', 'url', 'api_key', 'api_type', 'balance', 'status']:
            if field in data:
                updates.append(f"{field}=%s")
                params.append(data[field])
        if updates:
            params.extend([get_current_time(), provider_id])
            cursor.execute(f"UPDATE providers SET {', '.join(updates)}, updated_at=%s WHERE id=%s", params)
            db.commit()
            log_activity(session['user_id'], session['username'], 'provider_update', f"Updated provider {provider_id}")
        db.close()
        return jsonify({'success': True})
    elif request.method == 'DELETE':
        cursor.execute("SELECT COUNT(*) as count FROM services WHERE provider_id = %s", (provider_id,))
        count = cursor.fetchone()['count']
        if count > 0:
            db.close()
            return jsonify({'error': f'Cannot delete provider with {count} services'}), 400
        cursor.execute("DELETE FROM providers WHERE id = %s", (provider_id,))
        db.commit()
        log_activity(session['user_id'], session['username'], 'provider_delete', f"Deleted provider {provider_id}")
        db.close()
        return jsonify({'success': True})

@app.route('/admin/providers/<int:provider_id>/sync', methods=['POST'])
@require_admin
def admin_sync_provider_services(provider_id):
    result = sync_provider_services(provider_id)
    if 'error' in result:
        return jsonify({'success': False, 'error': result['error']})
    return jsonify({'success': True, 'message': f"{result.get('added', 0)} added, {result.get('updated', 0)} updated"})

@app.route('/admin/providers/<int:provider_id>/test', methods=['POST'])
@require_admin
def admin_test_provider(provider_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM providers WHERE id = %s", (provider_id,))
    provider = cursor.fetchone()
    db.close()
    if not provider:
        return jsonify({'error': 'Provider not found'}), 404
    try:
        result = call_provider_api(provider_id, 'getServices', 'GET')
        if 'error' in result:
            return jsonify({'success': False, 'error': result['error'], 'response': result.get('response', '')})
        return jsonify({'success': True, 'message': 'Connection successful!'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/admin/sync-socpanel-services', methods=['POST'])
@require_admin
def admin_sync_socpanel_services():
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM providers WHERE name = 'SocPanel API'")
    provider = cursor.fetchone()
    if not provider:
        db.close()
        return jsonify({'error': 'SocPanel Provider not found'}), 404
    db.close()
    result = sync_provider_services(provider['id'])
    if 'error' in result:
        return jsonify({'success': False, 'error': result['error']})
    return jsonify({'success': True, 'message': f"{result.get('added', 0)} SocPanel services added, {result.get('updated', 0)} updated"})

@app.route('/admin/tickets')
@require_admin
def admin_tickets():
    db = get_db()
    cursor = db.cursor()
    
    cursor.execute('''SELECT t.*, u.name as user_name, u.username 
        FROM tickets t 
        JOIN users u ON t.user_id = u.id 
        ORDER BY 
            CASE WHEN t.status = 'open' THEN 1 
                 WHEN t.status = 'replied' THEN 2 
                 ELSE 3 END, 
            t.created_at DESC''')
    tickets = cursor.fetchall()
    
    cursor.execute("SELECT COUNT(*) as count FROM tickets")
    total_tickets = cursor.fetchone()['count']
    cursor.execute("SELECT COUNT(*) as count FROM tickets WHERE status='open'")
    open_tickets = cursor.fetchone()['count']
    cursor.execute("SELECT COUNT(*) as count FROM tickets WHERE status='replied'")
    replied_tickets = cursor.fetchone()['count']
    cursor.execute("SELECT COUNT(*) as count FROM tickets WHERE status='closed'")
    closed_tickets = cursor.fetchone()['count']
    
    cursor.execute('''SELECT a.*, u.name as user_name, u.email, u.tier 
        FROM user_agreements a 
        JOIN users u ON a.user_id = u.id 
        ORDER BY a.agreed_at DESC''')
    agreements = cursor.fetchall()
    
    db.close()
    
    for ag in agreements:
        if ag.get('agreed_at') and hasattr(ag['agreed_at'], 'strftime'):
            ag['agreed_at'] = ag['agreed_at'].strftime('%Y-%m-%d %H:%M:%S')
    
    return render_template('admin/tickets.html', 
        tickets=tickets,
        total_tickets=total_tickets,
        open_tickets=open_tickets,
        replied_tickets=replied_tickets,
        closed_tickets=closed_tickets,
        agreements=agreements
    )

@app.route('/admin/tickets/<int:ticket_id>', methods=['GET', 'POST'])
@require_admin
def admin_ticket_detail(ticket_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute('''SELECT t.*, u.name as user_name, u.username 
        FROM tickets t 
        JOIN users u ON t.user_id = u.id 
        WHERE t.id = %s''', (ticket_id,))
    ticket = cursor.fetchone()
    if not ticket:
        flash('မတွေ့ရှိပါ', 'error')
        return redirect(url_for('admin_tickets'))
    
    replies = parse_ticket_replies(ticket['replies'])
    
    if request.method == 'POST':
        admin_reply = request.form.get('admin_reply', '').strip()
        status = request.form.get('status', 'replied')
        if not admin_reply:
            flash('ကျေးဇူးပြု၍ ပြန်ကြားချက်ကို ရေးပါ။', 'error')
            return redirect(url_for('admin_ticket_detail', ticket_id=ticket_id))
        replies.append({
            'sender': 'admin',
            'sender_name': session.get('name', 'Admin'),
            'message': admin_reply,
            'time': get_current_time()
        })
        cursor.execute('''UPDATE tickets 
            SET status = %s, replies = %s, updated_at = %s 
            WHERE id = %s''',
            (status, json.dumps(replies), get_current_time(), ticket_id))
        db.commit()
        log_activity(session['user_id'], session['username'], 'ticket_reply', f"Replied to ticket #{ticket_id}")
        db.close()
        flash('✅ ပြန်ကြားချက် အောင်မြင်စွာ ပို့ပြီးပါပြီ။', 'success')
        return redirect(url_for('admin_ticket_detail', ticket_id=ticket_id))
    db.close()
    return render_template('admin/ticket_detail.html', ticket=ticket, replies=replies)

@app.route('/admin/tickets/<int:ticket_id>/close', methods=['POST'])
@require_admin
def admin_ticket_close(ticket_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("UPDATE tickets SET status='closed', updated_at=%s WHERE id=%s", (get_current_time(), ticket_id))
    db.commit()
    log_activity(session['user_id'], session['username'], 'ticket_close', f"Closed ticket #{ticket_id}")
    db.close()
    flash('✅ Ticket ကို ပိတ်ပြီးပါပြီ။', 'success')
    return redirect(url_for('admin_tickets'))

@app.route('/admin/tickets/broadcast', methods=['GET', 'POST'])
@require_admin
def admin_ticket_broadcast():
    if request.method == 'POST':
        subject = request.form.get('subject', '').strip()
        message = request.form.get('message', '').strip()
        send_to = request.form.get('send_to', 'all')
        if not subject or not message:
            flash('ကျေးဇူးပြု၍ ခေါင်းစဉ်နှင့် မက်ဆေ့ခ်ျကို ဖြည့်ပါ။', 'error')
            return redirect(url_for('admin_ticket_broadcast'))
        db = get_db()
        cursor = db.cursor()
        if send_to == 'all':
            cursor.execute("SELECT id, name FROM users WHERE status='active'")
        elif send_to == 'reseller':
            cursor.execute("SELECT id, name FROM users WHERE tier='reseller' AND status='active'")
        elif send_to == 'user':
            cursor.execute("SELECT id, name FROM users WHERE tier='user' AND status='active'")
        else:
            users = []
        users = cursor.fetchall()
        success_count = 0
        for user in users:
            cursor.execute('''INSERT INTO tickets 
                (user_id, user_name, subject, category, message, priority, status, created_at, updated_at, replies)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)''',
                (user['id'], user['name'], subject, 'Broadcast', message, 'high', 'open', 
                 get_current_time(), get_current_time(), json.dumps([])))
            success_count += 1
        db.commit()
        log_activity(session['user_id'], session['username'], 'ticket_broadcast', 
                    f"Sent broadcast to {success_count} users")
        db.close()
        flash(f'✅ Broadcast ကို သုံးစွဲသူ {success_count} ဦးထံ ပို့ပြီးပါပြီ။', 'success')
        return redirect(url_for('admin_tickets'))
    return render_template('admin/ticket_broadcast.html')

# ===== ADMIN USER AGREEMENTS =====
@app.route('/admin/user-agreements')
@require_admin
def admin_user_agreements():
    db = get_db()
    cursor = db.cursor()
    cursor.execute('''SELECT a.*, u.name as user_name, u.email, u.tier 
        FROM user_agreements a 
        JOIN users u ON a.user_id = u.id 
        ORDER BY a.agreed_at DESC''')
    agreements = cursor.fetchall()
    db.close()
    
    for ag in agreements:
        if ag.get('agreed_at') and hasattr(ag['agreed_at'], 'strftime'):
            ag['agreed_at'] = ag['agreed_at'].strftime('%Y-%m-%d %H:%M:%S')
    
    return render_template('admin/user_agreements.html', agreements=agreements)

@app.route('/admin/user-agreements/<int:agreement_id>/status', methods=['POST'])
@require_admin
def admin_update_agreement_status(agreement_id):
    data = request.json
    status = data.get('status')
    if status not in ['approved', 'rejected']:
        return jsonify({'error': 'Invalid status'}), 400
    
    db = get_db()
    cursor = db.cursor()
    cursor.execute("UPDATE user_agreements SET status = %s WHERE id = %s", (status, agreement_id))
    db.commit()
    db.close()
    log_activity(session['user_id'], session['username'], 'agreement_status_update', f"Updated agreement #{agreement_id} to {status}")
    return jsonify({'success': True})

# ===== SOCPANEL DEBUG ROUTES =====
@app.route('/admin/debug-socpanel')
@require_admin
def debug_socpanel():
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM providers WHERE name LIKE '%SocPanel%' LIMIT 1")
    provider = cursor.fetchone()
    db.close()
    
    if not provider:
        flash('SocPanel Provider မတွေ့ပါ', 'error')
        return redirect(url_for('admin_services'))
    
    result = call_provider_api(provider['id'], 'getServices', 'GET')
    
    sample = None
    services = []
    if result and isinstance(result, dict):
        services = result.get('services', [])
        if services and len(services) > 0:
            sample = services[0]
    
    return render_template('admin/debug_socpanel.html', 
                         provider=provider, 
                         full_response=result,
                         sample=sample,
                         services=services)

@app.route('/admin/debug-socpanel-data')
@require_admin
def debug_socpanel_data():
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM providers WHERE name LIKE '%SocPanel%' LIMIT 1")
    provider = cursor.fetchone()
    db.close()
    
    if not provider:
        return jsonify({'error': 'SocPanel Provider not found'}), 404
    
    result = call_provider_api(provider['id'], 'getServices', 'GET')
    return jsonify(result)

# ===== SOCPANEL ANALYTICS =====
@app.route('/admin/socpanel-analytics')
@require_admin
def admin_socpanel_analytics():
    db = get_db()
    cursor = db.cursor()
    
    cursor.execute("SELECT id FROM providers WHERE name LIKE '%SocPanel%' LIMIT 1")
    provider = cursor.fetchone()
    if not provider:
        flash('SocPanel Provider မတွေ့ပါ', 'error')
        return redirect(url_for('admin_dashboard'))
    provider_id = provider['id']
    
    cursor.execute("SELECT value FROM settings WHERE `key` = 'exchange_rate'")
    setting = cursor.fetchone()
    exchange_rate = float(setting['value']) if setting else 4000.0
    
    cursor.execute("""
        SELECT 
            o.id,
            o.service_name,
            o.quantity,
            o.link,
            o.cost AS cost_usd,
            o.price AS price_mmk,
            o.profit AS profit_mmk,
            o.created_at,
            o.status,
            s.rate AS socpanel_rate
        FROM orders o
        JOIN services s ON o.service_id = s.id
        WHERE s.provider_id = %s AND o.status = 'completed'
        ORDER BY o.created_at DESC
    """, (provider_id,))
    orders = cursor.fetchall()
    
    for order in orders:
        order['cost_usd'] = float(order['cost_usd'] or 0)
        order['price_mmk'] = float(order['price_mmk'] or 0)
        order['profit_mmk'] = float(order['profit_mmk'] or 0)
        order['cost_mmk'] = order['cost_usd'] * exchange_rate
        if order['price_mmk'] > 0:
            order['profit_percent'] = (order['profit_mmk'] / order['price_mmk']) * 100
        else:
            order['profit_percent'] = 0
        if order.get('created_at') and hasattr(order['created_at'], 'strftime'):
            order['created_at'] = order['created_at'].strftime('%Y-%m-%d %H:%M:%S')
        else:
            order['created_at'] = str(order['created_at'])
    
    total_revenue_mmk = sum(o['price_mmk'] for o in orders)
    total_cost_usd = sum(o['cost_usd'] for o in orders)
    total_cost_mmk = total_cost_usd * exchange_rate
    total_profit_mmk = sum(o['profit_mmk'] for o in orders)
    total_profit_percent = (total_profit_mmk / total_revenue_mmk * 100) if total_revenue_mmk > 0 else 0
    
    monthly_data = {}
    yearly_data = {}
    for o in orders:
        month_key = o['created_at'][:7]
        year_key = o['created_at'][:4]
        if month_key not in monthly_data:
            monthly_data[month_key] = {'revenue': 0, 'cost': 0, 'profit': 0, 'count': 0}
        monthly_data[month_key]['revenue'] += o['price_mmk']
        monthly_data[month_key]['cost'] += o['cost_mmk']
        monthly_data[month_key]['profit'] += o['profit_mmk']
        monthly_data[month_key]['count'] += 1
        
        if year_key not in yearly_data:
            yearly_data[year_key] = {'revenue': 0, 'cost': 0, 'profit': 0, 'count': 0}
        yearly_data[year_key]['revenue'] += o['price_mmk']
        yearly_data[year_key]['cost'] += o['cost_mmk']
        yearly_data[year_key]['profit'] += o['profit_mmk']
        yearly_data[year_key]['count'] += 1
    
    months_sorted = sorted(monthly_data.keys())
    monthly_revenues = [monthly_data[m]['revenue'] for m in months_sorted]
    monthly_costs = [monthly_data[m]['cost'] for m in months_sorted]
    monthly_profits = [monthly_data[m]['profit'] for m in months_sorted]
    
    years_sorted = sorted(yearly_data.keys())
    yearly_revenues = [yearly_data[y]['revenue'] for y in years_sorted]
    yearly_costs = [yearly_data[y]['cost'] for y in years_sorted]
    yearly_profits = [yearly_data[y]['profit'] for y in years_sorted]
    
    db.close()
    
    return render_template('admin/socpanel_analytics.html',
        orders=orders,
        total_revenue_mmk=total_revenue_mmk,
        total_cost_usd=total_cost_usd,
        total_cost_mmk=total_cost_mmk,
        total_profit_mmk=total_profit_mmk,
        total_profit_percent=total_profit_percent,
        exchange_rate=exchange_rate,
        months=json.dumps(months_sorted),
        monthly_revenues=json.dumps(monthly_revenues),
        monthly_costs=json.dumps(monthly_costs),
        monthly_profits=json.dumps(monthly_profits),
        years=json.dumps(years_sorted),
        yearly_revenues=json.dumps(yearly_revenues),
        yearly_costs=json.dumps(yearly_costs),
        yearly_profits=json.dumps(yearly_profits),
        total_orders=len(orders)
    )

# ========== RESELLER ROUTES ==========
@app.route('/reseller')
@require_login
def reseller_dashboard():
    if session.get('tier') not in ['reseller', 'admin', 'super_admin']:
        return redirect(url_for('user_dashboard'))
    db = get_db()
    cursor = db.cursor()
    user_id = session['user_id']
    cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    user = cursor.fetchone()
    cursor.execute("SELECT COUNT(*) as count FROM orders WHERE user_id = %s", (user_id,))
    total_orders = cursor.fetchone()['count']
    cursor.execute("SELECT COUNT(*) as count FROM orders WHERE user_id = %s AND status='pending'", (user_id,))
    pending_orders = cursor.fetchone()['count']
    cursor.execute("SELECT * FROM orders WHERE user_id = %s ORDER BY created_at DESC LIMIT 10", (user_id,))
    recent_orders = cursor.fetchall()
    db.close()
    return render_template('reseller/dashboard.html',
        user=user, total_orders=total_orders, pending_orders=pending_orders,
        recent_orders=recent_orders)

@app.route('/reseller/services')
@require_login
def reseller_services():
    if session.get('tier') not in ['reseller', 'admin', 'super_admin']:
        return redirect(url_for('user_dashboard'))
    db = get_db()
    cursor = db.cursor()
    user_tier = session.get('tier', 'user')
    cursor.execute("SELECT `key`, value FROM settings")
    settings = {row['key']: row['value'] for row in cursor.fetchall()}
    exchange_rate = float(settings.get('exchange_rate', 4000))
    
    if user_tier == 'reseller':
        reseller_markup = float(settings.get('reseller_default_markup', 10))
    else:
        reseller_markup = float(settings.get('user_default_markup', 20))
    
    cursor.execute("SELECT * FROM services WHERE status='active' ORDER BY category, name")
    services = cursor.fetchall()
    db.close()
    
    for service in services:
        service['rate'] = float(service['rate'])
        service['markup'] = reseller_markup
        service['display_price_mmk'] = service['rate'] * exchange_rate * (1 + reseller_markup / 100)
    
    return render_template('reseller/services.html', 
                           services=services, 
                           exchange_rate=exchange_rate,
                           tier=user_tier)

@app.route('/reseller/place-order')
@require_login
def reseller_place_order():
    if session.get('tier') not in ['reseller', 'admin', 'super_admin']:
        return redirect(url_for('user_dashboard'))
    db = get_db()
    cursor = db.cursor()
    user_tier = session.get('tier', 'user')
    cursor.execute("SELECT `key`, value FROM settings")
    settings = {row['key']: row['value'] for row in cursor.fetchall()}
    exchange_rate = float(settings.get('exchange_rate', 4000))
    
    if user_tier == 'reseller':
        reseller_markup = float(settings.get('reseller_default_markup', 10))
    else:
        reseller_markup = float(settings.get('user_default_markup', 20))
    
    cursor.execute("SELECT * FROM services WHERE status='active' ORDER BY category, name")
    services = cursor.fetchall()
    cursor.execute("SELECT balance FROM users WHERE id = %s", (session['user_id'],))
    user_data = cursor.fetchone()
    balance = float(user_data['balance']) if user_data else 0
    db.close()
    
    for service in services:
        service['rate'] = float(service['rate'])
        service['markup'] = reseller_markup
        service['display_price_mmk'] = service['rate'] * exchange_rate * (1 + reseller_markup / 100)
    
    return render_template('reseller/place_order.html', 
                           services=services, 
                           balance=balance,
                           exchange_rate=exchange_rate,
                           tier=user_tier)

@app.route('/api/reseller/place-order', methods=['POST'])
@require_login
def api_place_order():
    data = request.json
    user_id = session['user_id']
    db = get_db()
    cursor = db.cursor()

    cursor.execute("SELECT balance, name, tier FROM users WHERE id = %s", (user_id,))
    user = cursor.fetchone()
    if not user:
        db.close()
        return jsonify({'error': 'User not found'}), 404

    cursor.execute("SELECT * FROM services WHERE id = %s", (data['service_id'],))
    service = cursor.fetchone()
    if not service:
        db.close()
        return jsonify({'error': 'Service not found'}), 404
    
    service['rate'] = float(service['rate'])
    service['markup'] = float(service['markup']) if service['markup'] else 15.0

    cursor.execute("SELECT `key`, value FROM settings")
    settings = {row['key']: row['value'] for row in cursor.fetchall()}
    exchange_rate = float(settings.get('exchange_rate', 4000))

    if user['tier'] == 'reseller':
        default_markup = float(settings.get('reseller_default_markup', 10))
        discount_pct = float(settings.get('reseller_discount', 0))
    else:
        default_markup = float(settings.get('user_default_markup', 20))
        discount_pct = float(settings.get('user_discount', 0))
    
    service_markup = service['markup'] if service['markup'] else default_markup

    quantity = int(data['quantity'])
    rate = service['rate']

    cost_usd = (quantity / 1000) * rate
    price_mmk = cost_usd * exchange_rate * (1 + service_markup / 100)

    discount_amount = 0
    if discount_pct > 0:
        discount_amount = price_mmk * (discount_pct / 100)
        price_mmk = price_mmk - discount_amount

    if user['balance'] < price_mmk:
        db.close()
        return jsonify({'error': 'Insufficient balance'}), 400

    cursor.execute('''INSERT INTO orders 
        (user_id, service_id, service_name, category, link, quantity, rate, cost, price, profit, status, created_at, updated_at, source)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)''',
        (user_id, service['id'], service['name'], service['category'], data['link'],
         quantity, rate, cost_usd, price_mmk, price_mmk - (cost_usd * exchange_rate), 
         'pending', get_current_time(), get_current_time(), 'web'))

    cursor.execute("UPDATE users SET balance = balance - %s, spent = spent + %s WHERE id = %s", 
                   (price_mmk, price_mmk, user_id))
    order_id = cursor.lastrowid
    db.commit()

    sync_result = sync_order_to_provider(order_id)
    
    if sync_result and 'error' in sync_result:
        db = get_db()
        cursor = db.cursor()
        cursor.execute("UPDATE users SET balance = balance + %s WHERE id = %s", (price_mmk, user_id))
        cursor.execute("UPDATE orders SET status = 'failed', notes = %s WHERE id = %s", (sync_result['error'][:500], order_id))
        db.commit()
        db.close()
        log_activity(user_id, session['username'], 'order_failed_refund', f"Order #{order_id} failed, refunded {price_mmk} MMK. Error: {sync_result['error']}")
        return jsonify({'success': False, 'message': 'Provider error, amount refunded.', 'error': sync_result['error']}), 400

    db.close()
    log_activity(user_id, session['username'], 'order_place', f"Placed order for {service['name']} x {quantity}")

    if sync_result and 'error' not in sync_result:
        return jsonify({'success': True, 'message': 'Order placed and synced successfully', 'order_id': order_id})
    else:
        return jsonify({'success': True, 'message': 'Order placed but sync failed', 'order_id': order_id})

@app.route('/reseller/orders')
@require_login
def reseller_orders():
    if session.get('tier') not in ['reseller', 'admin', 'super_admin']:
        return redirect(url_for('user_dashboard'))
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM orders WHERE user_id = %s ORDER BY created_at DESC", (session['user_id'],))
    orders = cursor.fetchall()
    db.close()
    for order in orders:
        if order.get('created_at'):
            if hasattr(order['created_at'], 'strftime'):
                order['created_at'] = order['created_at'].strftime('%Y-%m-%d %H:%M:%S')
            else:
                order['created_at'] = str(order['created_at'])
        if order.get('updated_at'):
            if hasattr(order['updated_at'], 'strftime'):
                order['updated_at'] = order['updated_at'].strftime('%Y-%m-%d %H:%M:%S')
            else:
                order['updated_at'] = str(order['updated_at'])
    return render_template('reseller/orders.html', orders=orders)

@app.route('/reseller/deposit', methods=['GET', 'POST'])
@require_login
def reseller_deposit():
    if session.get('tier') not in ['reseller', 'admin', 'super_admin']:
        return redirect(url_for('user_dashboard'))
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT value FROM settings WHERE `key` = 'min_deposit_mmk'")
    setting = cursor.fetchone()
    min_deposit = float(setting['value']) if setting else 5000.0
    cursor.execute("SELECT value FROM settings WHERE `key` = 'exchange_rate'")
    setting = cursor.fetchone()
    exchange_rate = float(setting['value']) if setting else 4000.0
    cursor.execute("SELECT * FROM payment_methods WHERE is_active=1 ORDER BY name")
    methods = cursor.fetchall()
    db.close()

    if request.method == 'POST':
        data = request.form
        user_id = session['user_id']
        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT name FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()
        method_id = int(data.get('method_id', 0))
        amount = float(data.get('amount', 0))
        if amount < min_deposit:
            flash(f'ငွေပမာဏသည် အနည်းဆုံး {int(min_deposit)} MMK ရှိရပါမည်။', 'error')
            return redirect(url_for('reseller_deposit'))
        cursor.execute("SELECT name FROM payment_methods WHERE id = %s", (method_id,))
        method = cursor.fetchone()
        method_name = method['name'] if method else 'Unknown'
        cursor.execute('''INSERT INTO payment_requests 
            (user_id, user_name, method_id, method_name, amount, sender_name, sender_phone, transaction_id, status, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)''',
            (user_id, user['name'], method_id, method_name, amount, data.get('sender_name'),
             data.get('sender_phone'), data.get('transaction_id'), 'pending', get_current_time()))
        db.commit()
        log_activity(user_id, session['username'], 'deposit_request', f"Requested deposit of {amount} MMK via {method_name}")
        db.close()
        flash('ငွေသွင်းလျှောက်လွှာ အောင်မြင်စွာ တင်ပြီးပါပြီ။', 'success')
        return redirect(url_for('reseller_deposit'))

    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM payment_requests WHERE user_id = %s ORDER BY created_at DESC", (session['user_id'],))
    payments = cursor.fetchall()
    db.close()
    return render_template('reseller/deposit.html', 
        payments=payments, 
        min_deposit=min_deposit,
        methods=methods,
        exchange_rate=exchange_rate)

@app.route('/reseller/withdraw', methods=['GET', 'POST'])
@require_login
def reseller_withdraw():
    if session.get('tier') not in ['reseller', 'admin', 'super_admin']:
        return redirect(url_for('user_dashboard'))
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT value FROM settings WHERE `key` = 'min_withdraw_mmk'")
    setting = cursor.fetchone()
    min_withdraw = float(setting['value']) if setting else 10000.0
    db.close()

    if request.method == 'POST':
        data = request.form
        user_id = session['user_id']
        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT name, balance FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()
        amount = float(data.get('amount', 0))
        if amount < min_withdraw:
            flash(f'ငွေပမာဏသည် အနည်းဆုံး {int(min_withdraw)} MMK ရှိရပါမည်။', 'error')
            return redirect(url_for('reseller_withdraw'))
        if amount > user['balance']:
            flash('သင့်ငွေလက်ကျန်ထက် ပိုမိုတောင်းဆိုနေပါသည်။', 'error')
            return redirect(url_for('reseller_withdraw'))
        cursor.execute('''INSERT INTO withdraw_requests 
            (user_id, user_name, method, amount, bank_name, account_number, account_name, status, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)''',
            (user_id, user['name'], 'Bank Transfer', amount, data.get('bank_name'),
             data.get('account_number'), data.get('account_name'), 'pending', get_current_time()))
        db.commit()
        log_activity(user_id, session['username'], 'withdraw_request', f"Requested withdraw of {amount} MMK")
        db.close()
        flash('ငွေထုတ်လျှောက်လွှာ အောင်မြင်စွာ တင်ပြီးပါပြီ။ Admin အတည်ပြုချက်ကို စောင့်ပါ။', 'success')
        return redirect(url_for('reseller_withdraw'))

    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM withdraw_requests WHERE user_id = %s ORDER BY created_at DESC", (session['user_id'],))
    withdraws = cursor.fetchall()
    cursor.execute("SELECT balance FROM users WHERE id = %s", (session['user_id'],))
    user = cursor.fetchone()
    db.close()
    return render_template('reseller/withdraw.html', withdraws=withdraws, balance=user['balance'], min_withdraw=min_withdraw)

@app.route('/reseller/tickets', methods=['GET', 'POST'])
@require_login
def reseller_tickets():
    if session.get('tier') not in ['reseller', 'admin', 'super_admin']:
        return redirect(url_for('user_dashboard'))
    user_id = session['user_id']

    if request.method == 'POST':
        data = request.form
        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT name FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()
        cursor.execute('''INSERT INTO tickets 
            (user_id, user_name, subject, category, message, priority, status, created_at, updated_at, replies)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)''',
            (user_id, user['name'], data['subject'], data['category'], data['message'],
             'normal', 'open', get_current_time(), get_current_time(), json.dumps([])))
        db.commit()
        log_activity(user_id, session['username'], 'ticket_create', f"Created ticket: {data['subject']}")
        db.close()
        flash('အကူအညီတောင်းခံချက် အောင်မြင်စွာ တင်ပြီးပါပြီ။', 'success')
        return redirect(url_for('reseller_tickets'))

    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM tickets WHERE user_id = %s ORDER BY created_at DESC", (user_id,))
    tickets = cursor.fetchall()
    for ticket in tickets:
        ticket['parsed_replies'] = parse_ticket_replies(ticket['replies'])
    db.close()
    return render_template('reseller/tickets.html', tickets=tickets)

# ========== USER ROUTES ==========
@app.route('/user')
@require_login
def user_dashboard():
    db = get_db()
    cursor = db.cursor()
    user_id = session['user_id']
    cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    user = cursor.fetchone()
    cursor.execute("SELECT COUNT(*) as count FROM orders WHERE user_id = %s", (user_id,))
    total_orders = cursor.fetchone()['count']
    cursor.execute("SELECT * FROM orders WHERE user_id = %s ORDER BY created_at DESC LIMIT 10", (user_id,))
    recent_orders = cursor.fetchall()
    db.close()
    return render_template('user/dashboard.html', user=user, total_orders=total_orders, recent_orders=recent_orders)

@app.route('/user/services')
@require_login
def user_services():
    db = get_db()
    cursor = db.cursor()
    user_tier = session.get('tier', 'user')
    cursor.execute("SELECT `key`, value FROM settings")
    settings = {row['key']: row['value'] for row in cursor.fetchall()}
    exchange_rate = float(settings.get('exchange_rate', 4000))
    
    if user_tier == 'reseller':
        user_markup = float(settings.get('reseller_default_markup', 10))
    else:
        user_markup = float(settings.get('user_default_markup', 20))
    
    cursor.execute("SELECT * FROM services WHERE status='active' ORDER BY category, name")
    services = cursor.fetchall()
    db.close()
    
    for service in services:
        service['rate'] = float(service['rate'])
        service['markup'] = user_markup
        service['display_price_mmk'] = service['rate'] * exchange_rate * (1 + user_markup / 100)
    
    return render_template('user/services.html', 
                           services=services, 
                           exchange_rate=exchange_rate,
                           tier=user_tier)

@app.route('/user/place-order')
@require_login
def user_place_order():
    db = get_db()
    cursor = db.cursor()
    user_tier = session.get('tier', 'user')
    cursor.execute("SELECT `key`, value FROM settings")
    settings = {row['key']: row['value'] for row in cursor.fetchall()}
    exchange_rate = float(settings.get('exchange_rate', 4000))
    
    if user_tier == 'reseller':
        user_markup = float(settings.get('reseller_default_markup', 10))
    else:
        user_markup = float(settings.get('user_default_markup', 20))
    
    cursor.execute("SELECT * FROM services WHERE status='active' ORDER BY category, name")
    services = cursor.fetchall()
    cursor.execute("SELECT balance FROM users WHERE id = %s", (session['user_id'],))
    user_data = cursor.fetchone()
    balance = float(user_data['balance']) if user_data else 0
    db.close()
    
    for service in services:
        service['rate'] = float(service['rate'])
        service['markup'] = user_markup
        service['display_price_mmk'] = service['rate'] * exchange_rate * (1 + user_markup / 100)
    
    return render_template('user/place_order.html', 
                           services=services, 
                           balance=balance,
                           exchange_rate=exchange_rate,
                           tier=user_tier)

@app.route('/user/deposit', methods=['GET', 'POST'])
@require_login
def user_deposit():
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT value FROM settings WHERE `key` = 'min_deposit_mmk'")
    setting = cursor.fetchone()
    min_deposit = float(setting['value']) if setting else 5000.0
    cursor.execute("SELECT value FROM settings WHERE `key` = 'exchange_rate'")
    setting = cursor.fetchone()
    exchange_rate = float(setting['value']) if setting else 4000.0
    cursor.execute("SELECT * FROM payment_methods WHERE is_active=1 ORDER BY name")
    methods = cursor.fetchall()
    db.close()

    if request.method == 'POST':
        data = request.form
        user_id = session['user_id']
        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT name FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()
        method_id = int(data.get('method_id', 0))
        amount = float(data.get('amount', 0))
        if amount < min_deposit:
            flash(f'ငွေပမာဏသည် အနည်းဆုံး {int(min_deposit)} MMK ရှိရပါမည်။', 'error')
            return redirect(url_for('user_deposit'))
        cursor.execute("SELECT name FROM payment_methods WHERE id = %s", (method_id,))
        method = cursor.fetchone()
        method_name = method['name'] if method else 'Unknown'
        cursor.execute('''INSERT INTO payment_requests 
            (user_id, user_name, method_id, method_name, amount, sender_name, sender_phone, transaction_id, status, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)''',
            (user_id, user['name'], method_id, method_name, amount, data.get('sender_name'),
             data.get('sender_phone'), data.get('transaction_id'), 'pending', get_current_time()))
        db.commit()
        log_activity(user_id, session['username'], 'deposit_request', f"Requested deposit of {amount} MMK via {method_name}")
        db.close()
        flash('ငွေသွင်းလျှောက်လွှာ အောင်မြင်စွာ တင်ပြီးပါပြီ။', 'success')
        return redirect(url_for('user_deposit'))

    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM payment_requests WHERE user_id = %s ORDER BY created_at DESC", (session['user_id'],))
    payments = cursor.fetchall()
    db.close()
    return render_template('user/deposit.html', 
        payments=payments, 
        min_deposit=min_deposit,
        methods=methods,
        exchange_rate=exchange_rate)

@app.route('/user/tickets', methods=['GET', 'POST'])
@require_login
def user_tickets():
    user_id = session['user_id']

    if request.method == 'POST':
        data = request.form
        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT name FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()
        cursor.execute('''INSERT INTO tickets 
            (user_id, user_name, subject, category, message, priority, status, created_at, updated_at, replies)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)''',
            (user_id, user['name'], data['subject'], data['category'], data['message'],
             'normal', 'open', get_current_time(), get_current_time(), json.dumps([])))
        db.commit()
        log_activity(user_id, session['username'], 'ticket_create', f"Created ticket: {data['subject']}")
        db.close()
        flash('အကူအညီတောင်းခံချက် အောင်မြင်စွာ တင်ပြီးပါပြီ။', 'success')
        return redirect(url_for('user_tickets'))

    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM tickets WHERE user_id = %s ORDER BY created_at DESC", (user_id,))
    tickets = cursor.fetchall()
    for ticket in tickets:
        ticket['parsed_replies'] = parse_ticket_replies(ticket['replies'])
    db.close()
    return render_template('user/tickets.html', tickets=tickets)

# ========== API ROUTES ==========
@app.route('/api/v2/services', methods=['GET'])
def api_get_services():
    api_key = request.headers.get('Authorization', '').replace('Bearer ', '')
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM reseller_apis WHERE api_key = %s AND status='active'", (api_key,))
    reseller = cursor.fetchone()
    if not reseller:
        db.close()
        return jsonify({'error': 'Invalid API key'}), 401
    cursor.execute("UPDATE reseller_apis SET last_used = %s WHERE id = %s", (get_current_time(), reseller['id']))
    db.commit()
    cursor.execute("SELECT id, category, name, description, rate, min_order, max_order FROM services WHERE status='active'")
    services = cursor.fetchall()
    db.close()
    return jsonify({'success': True, 'services': services})

@app.route('/api/v2/order', methods=['POST'])
def api_place_order_v2():
    api_key = request.headers.get('Authorization', '').replace('Bearer ', '')
    data = request.json
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM reseller_apis WHERE api_key = %s AND status='active'", (api_key,))
    reseller = cursor.fetchone()
    if not reseller:
        db.close()
        return jsonify({'error': 'Invalid API key'}), 401
    user_id = reseller['user_id']
    cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    user = cursor.fetchone()
    if not user:
        db.close()
        return jsonify({'error': 'User not found'}), 404
    cursor.execute("SELECT * FROM services WHERE id = %s AND status='active'", (data.get('service_id'),))
    service = cursor.fetchone()
    if not service:
        db.close()
        return jsonify({'error': 'Service not found'}), 404
    quantity = int(data.get('quantity', 0))
    if quantity < service['min_order'] or quantity > service['max_order']:
        db.close()
        return jsonify({'error': 'Quantity out of range'}), 400
    rate = float(service['rate'])
    markup = float(service['markup'])
    price = (quantity / 1000) * rate * (1 + markup / 100)
    cost = (quantity / 1000) * rate
    if user['balance'] < price:
        db.close()
        return jsonify({'error': 'Insufficient balance'}), 400
    cursor.execute('''INSERT INTO orders 
        (user_id, service_id, service_name, category, link, quantity, rate, cost, price, profit, status, created_at, updated_at, source)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)''',
        (user['id'], service['id'], service['name'], service['category'], data.get('link'),
         quantity, rate, cost, price, price - cost, 'pending', get_current_time(), get_current_time(), 'api'))
    cursor.execute("UPDATE users SET balance = balance - %s, spent = spent + %s WHERE id = %s", (price, price, user['id']))
    order_id = cursor.lastrowid
    db.commit()
    db.close()
    return jsonify({'success': True, 'order_id': order_id, 'status': 'pending'})

@app.route('/api/v2/order/<int:order_id>/status', methods=['GET'])
def api_get_order_status(order_id):
    api_key = request.headers.get('Authorization', '').replace('Bearer ', '')
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM reseller_apis WHERE api_key = %s AND status='active'", (api_key,))
    reseller = cursor.fetchone()
    if not reseller:
        db.close()
        return jsonify({'error': 'Invalid API key'}), 401
    cursor.execute("SELECT id, status, link, quantity, price, created_at FROM orders WHERE id = %s AND user_id = %s",
                  (order_id, reseller['user_id']))
    order = cursor.fetchone()
    db.close()
    if not order:
        return jsonify({'error': 'Order not found'}), 404
    return jsonify({'success': True, 'order': order})

@app.route('/api/v2/balance', methods=['GET'])
def api_get_balance():
    api_key = request.headers.get('Authorization', '').replace('Bearer ', '')
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM reseller_apis WHERE api_key = %s AND status='active'", (api_key,))
    reseller = cursor.fetchone()
    if not reseller:
        db.close()
        return jsonify({'error': 'Invalid API key'}), 401
    cursor.execute("SELECT balance FROM users WHERE id = %s", (reseller['user_id'],))
    user = cursor.fetchone()
    db.close()
    return jsonify({'success': True, 'balance': user['balance']})

@app.route('/api/user/settings')
@require_login
def api_user_settings():
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT tier FROM users WHERE id = %s", (session['user_id'],))
    user = cursor.fetchone()
    cursor.execute("SELECT `key`, value FROM settings")
    settings = {row['key']: row['value'] for row in cursor.fetchall()}
    db.close()
    
    if user and user['tier'] == 'reseller':
        discount_str = settings.get('reseller_discount', '0')
        discount = float(discount_str) if discount_str and discount_str.strip() else 0.0
    else:
        discount_str = settings.get('user_discount', '0')
        discount = float(discount_str) if discount_str and discount_str.strip() else 0.0
    
    return jsonify({
        'success': True,
        'discount': discount,
        'tier': user['tier'] if user else 'user'
    })

@app.route('/api/admin/sync-order/<int:order_id>', methods=['POST'])
@require_admin
def admin_sync_order_to_provider(order_id):
    result = sync_order_to_provider(order_id)
    if 'error' in result:
        return jsonify({'success': False, 'message': result['error']})
    return jsonify({'success': True, 'message': 'Order synced successfully'})

# ---------- ERROR HANDLERS ----------
@app.errorhandler(404)
def not_found(error):
    return render_template('error.html', error='စာမျက်နှာ မတွေ့ပါ'), 404

@app.errorhandler(500)
def server_error(error):
    return render_template('error.html', error='ဆာဗာ အမှားအယွင်းရှိပါသည်'), 500

if __name__ == '__main__':
    os.makedirs('flask_session', exist_ok=True)
    app.run(debug=True, host='0.0.0.0', port=5000)