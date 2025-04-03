from flask import Flask, request, jsonify, render_template, redirect, url_for, session, flash
import firebase_admin
from firebase_admin import credentials, firestore
import qrcode
import io
import base64
from flask_cors import CORS
import hashlib
from datetime import datetime
import os
import json

# Initialize Flask app
app = Flask(__name__)
CORS(app, supports_credentials=True, resources={
    r"/*": {
        "origins": [
            "http://localhost:5000",
            "https://39c4-2402-3a80-1824-1e9d-d23-3267-5717-624.ngrok-free.app",
            "https://thefdcomapany.onrender.com"  # Add your Render URL here
        ],
        "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization"],
        "supports_credentials": True
    }
})
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24))
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# Initialize Firebase
def init_firebase():
    # Try environment variables first (for Render)
    if all(key in os.environ for key in ['FIREBASE_TYPE', 'FIREBASE_PROJECT_ID']):
        firebase_config = {
            "type": os.environ.get("FIREBASE_TYPE"),
            "project_id": os.environ.get("FIREBASE_PROJECT_ID"),
            "private_key_id": os.environ.get("FIREBASE_PRIVATE_KEY_ID"),
            "private_key": os.environ.get("FIREBASE_PRIVATE_KEY").replace('\\n', '\n'),
            "client_email": os.environ.get("FIREBASE_CLIENT_EMAIL"),
            "client_id": os.environ.get("FIREBASE_CLIENT_ID"),
            "auth_uri": os.environ.get("FIREBASE_AUTH_URI"),
            "token_uri": os.environ.get("FIREBASE_TOKEN_URI"),
            "auth_provider_x509_cert_url": os.environ.get("FIREBASE_AUTH_PROVIDER_CERT_URL"),
            "client_x509_cert_url": os.environ.get("FIREBASE_CLIENT_CERT_URL")
        }
        return credentials.Certificate(firebase_config)
    # Fallback to credentials file (for local development)
    elif os.path.exists("FIREBASE_CREDENTIALS.json"):
        return credentials.Certificate("FIREBASE_CREDENTIALS.json")
    else:
        raise ValueError("No Firebase configuration found")

try:
    cred = init_firebase()
    firebase_admin.initialize_app(cred)
    db = firestore.client()
except Exception as e:
    print(f"Error initializing Firebase: {e}")
    db = None  # This will cause the app to fail on database operations

# Helper Functions (remain the same)
def hash_password(password):
    salt = "fixed_salt_for_hashing"
    return hashlib.sha256((password + salt).encode()).hexdigest()

def validate_session():
    if 'username' not in session:
        return False
    user_ref = db.collection('users').document(session['username']).get()
    return user_ref.exists

def calculate_order_total(items):
    total = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        price = item.get('price', 0)
        quantity = item.get('quantity', 0)
        if price < 0 or quantity < 0:
            return -1
        total += price * quantity
    return round(total, 2)

# Routes (all your existing routes remain exactly the same)
# ... [keep all your existing route functions unchanged] ...


# Routes
@app.route("/")
def login_page():
    if validate_session():
        return redirect(url_for('home'))
    return render_template('login.html')

@app.route("/login", methods=['GET', 'POST'])
def login():
    if validate_session():
        return redirect(url_for('home'))
    
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        
        if not username or not password:
            flash('Username and password are required', 'danger')
            return redirect(url_for('login'))
        
        try:
            user_ref = db.collection('users').document(username).get()
            if user_ref.exists:
                user_data = user_ref.to_dict()
                if user_data.get('password') == hash_password(password):
                    session['username'] = username
                    db.collection('users').document(username).update({
                        'last_login': datetime.now()
                    })
                    flash('Login successful!', 'success')
                    return redirect(url_for('home'))
            
            flash('Invalid username or password', 'danger')
        except Exception as e:
            flash('Login failed. Please try again.', 'danger')
    
    return render_template('login.html')

@app.route("/register", methods=['GET', 'POST'])
def register():
    if validate_session():
        return redirect(url_for('home'))
    
    if request.method == 'POST':
        # Handle both form and JSON data
        if request.is_json:
            data = request.get_json()
            username = data.get('username', '').strip()
            password = data.get('password', '').strip()
            confirm_password = data.get('confirm_password', '').strip()
        else:
            username = request.form.get('username', '').strip()
            password = request.form.get('password', '').strip()
            confirm_password = request.form.get('confirm_password', '').strip()
        
        errors = []
        if not username or not password:
            errors.append('Username and password are required')
        elif len(username) < 4:
            errors.append('Username must be at least 4 characters')
        elif len(password) < 8:
            errors.append('Password must be at least 8 characters')
        elif password != confirm_password:
            errors.append('Passwords do not match')
        
        if errors:
            if request.is_json:
                return jsonify({"status": "error", "errors": errors}), 400
            for error in errors:
                flash(error, 'danger')
        else:
            try:
                if db.collection('users').document(username).get().exists:
                    if request.is_json:
                        return jsonify({"status": "error", "message": "Username already exists"}), 400
                    flash('Username already exists', 'danger')
                else:
                    db.collection('users').document(username).set({
                        'username': username,
                        'password': hash_password(password),
                        'created_at': datetime.now(),
                        'last_login': None,
                        'role': 'user'
                    })
                    if request.is_json:
                        return jsonify({"status": "success", "message": "Registration successful! Please login."})
                    flash('Registration successful! Please login.', 'success')
                    return redirect(url_for('login'))
            except Exception as e:
                if request.is_json:
                    return jsonify({"status": "error", "message": "Registration failed. Please try again."}), 500
                flash('Registration failed. Please try again.', 'danger')
    
    return render_template('register.html')

@app.route("/logout")
def logout():
    session.pop('username', None)
    flash('You have been logged out successfully', 'info')
    return redirect(url_for('login_page'))

@app.route("/home")
def home():
    if not validate_session():
        return redirect(url_for('login'))
    
    try:
        username = session['username']
        # Get the 5 most recent orders
        orders_ref = db.collection("users").document(username).collection("bookings")\
                          .order_by("created_at", direction=firestore.Query.DESCENDING)\
                          .limit(5)
        orders = []
        for doc in orders_ref.stream():
            order = doc.to_dict()
            order['id'] = doc.id
            orders.append(order)
        
        return render_template('home.html', 
                            username=username,
                            orders=orders)
    except Exception as e:
        flash('Error loading dashboard', 'danger')
        return redirect(url_for('login'))

@app.route("/index")
def index():
    if not validate_session():
        return redirect(url_for('login'))
    return render_template('index.html', username=session['username'])

@app.route("/order_history")
def order_history():
    if not validate_session():
        return redirect(url_for('login'))
    
    try:
        username = session['username']
        orders_ref = db.collection("users").document(username).collection("bookings").order_by("created_at", direction=firestore.Query.DESCENDING)
        orders = []
        for doc in orders_ref.stream():
            order = doc.to_dict()
            order['id'] = doc.id
            orders.append(order)
        
        return render_template('order_history.html', 
                            username=username,
                            orders=orders)
    except Exception as e:
        flash('Error fetching order history', 'danger')
        return redirect(url_for('home'))

# ... [rest of your routes remain the same] ...

if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=5000)