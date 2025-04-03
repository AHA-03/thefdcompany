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

# Initialize Flask app
app = Flask(__name__)
CORS(app, supports_credentials=True, resources={
    r"/*": {
        "origins": ["http://localhost:5000", "https://your-render-app.onrender.com"],
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
    if all(key in os.environ for key in ['FIREBASE_TYPE', 'FIREBASE_PROJECT_ID']):
        return credentials.Certificate({
            "type": os.environ["FIREBASE_TYPE"],
            "project_id": os.environ["FIREBASE_PROJECT_ID"],
            "private_key": os.environ["FIREBASE_PRIVATE_KEY"].replace('\\n', '\n'),
            "client_email": os.environ["FIREBASE_CLIENT_EMAIL"],
            "token_uri": os.environ["FIREBASE_TOKEN_URI"]
        })
    elif os.path.exists("firebase-creds.json"):
        return credentials.Certificate("firebase-creds.json")
    raise ValueError("Missing Firebase config")

try:
    cred = init_firebase()
    firebase_admin.initialize_app(cred)
    db = firestore.client()
except Exception as e:
    print(f"Firebase init error: {str(e)}")
    db = None

# Helper Functions
def hash_password(password):
    return hashlib.sha256((password + "fixed_salt").encode()).hexdigest()

def validate_session():
    return 'username' in session and db is not None

# Routes
@app.route("/")
def home():
    return redirect(url_for('login_page'))

@app.route("/login", methods=['GET', 'POST'])
def login_page():
    if validate_session():
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        
        if not username or not password:
            flash('Credentials required', 'danger')
            return redirect(url_for('login_page'))
        
        try:
            user_ref = db.collection('users').document(username).get()
            if user_ref.exists and user_ref.to_dict().get('password') == hash_password(password):
                session['username'] = username
                return redirect(url_for('index'))
            flash('Invalid credentials', 'danger')
        except Exception as e:
            flash('Login error', 'danger')
    return render_template('login.html')

@app.route("/logout")
def logout():
    session.pop('username', None)
    return redirect(url_for('login_page'))

@app.route("/index")
def index():
    if not validate_session():
        return redirect(url_for('login_page'))
    return render_template('index.html', username=session['username'])

@app.route("/api/orders", methods=["POST"])
def create_order():
    if not validate_session():
        return jsonify({"error": "Unauthorized"}), 401
        
    try:
        data = request.get_json()
        
        # Validate input
        if not all(k in data for k in ['roll_number', 'phone_number', 'food_items']):
            return jsonify({"error": "Missing required fields"}), 400
            
        if not isinstance(data['food_items'], list) or len(data['food_items']) == 0:
            return jsonify({"error": "No food items selected"}), 400

        # Create order document
        order_ref = db.collection('orders').document()
        order_data = {
            "booking_id": order_ref.id[:8],  # Short 8-character ID
            "food_items": data['food_items'],
            "phone_number": data['phone_number'],
            "roll_number": data['roll_number'],
            "status": "pending",
            "created_at": datetime.now(),
            "username": session['username']
        }
        order_ref.set(order_data)
        
        # Generate QR code
        qr = qrcode.make(order_data['booking_id'])
        img_io = io.BytesIO()
        qr.save(img_io, 'PNG')
        qr_base64 = base64.b64encode(img_io.getvalue()).decode()
        
        return jsonify({
            "status": "success",
            "booking_id": order_data['booking_id'],
            "qr_code": qr_base64,
            "order_data": {
                "food_items": order_data['food_items'],
                "phone_number": order_data['phone_number'],
                "roll_number": order_data['roll_number']
            }
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))