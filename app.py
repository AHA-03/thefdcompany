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
    r"/api/*": {
        "origins": "http://localhost:5000",
        "supports_credentials": True
    }
})
app.secret_key = os.urandom(24)
app.config['SESSION_COOKIE_SECURE'] = False  # True in production
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# Initialize Firebase
cred = credentials.Certificate("FIREBASE_CREDENTIALS")
firebase_admin.initialize_app(cred)
db = firestore.client()

# Helper Functions
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
            for error in errors:
                flash(error, 'danger')
        else:
            try:
                if db.collection('users').document(username).get().exists:
                    flash('Username already exists', 'danger')
                else:
                    db.collection('users').document(username).set({
                        'username': username,
                        'password': hash_password(password),
                        'created_at': datetime.now(),
                        'last_login': None,
                        'role': 'user'
                    })
                    flash('Registration successful! Please login.', 'success')
                    return redirect(url_for('login'))
            except Exception as e:
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

@app.route("/api/orders", methods=["POST"])
def create_order():
    if not validate_session():
        return jsonify({"status": "error", "message": "Unauthorized - Please login first"}), 401
        
    try:
        data = request.get_json()
        if not data:
            return jsonify({"status": "error", "message": "No data provided"}), 400
        
        username = session.get('username')
        phone_number = data.get("phone_number", "").strip()
        roll_number = data.get("roll_number", "").strip()
        food_items = data.get("food_items", [])
        
        if not roll_number:
            return jsonify({"status": "error", "message": "Roll number is required"}), 400
            
        if not phone_number or len(phone_number) < 10:
            return jsonify({"status": "error", "message": "Valid phone number required"}), 400
        
        if not isinstance(food_items, list) or len(food_items) == 0:
            return jsonify({"status": "error", "message": "No food items selected"}), 400
        
        total_amount = calculate_order_total(food_items)
        if total_amount <= 0:
            return jsonify({"status": "error", "message": "Invalid order total"}), 400
        
        # Create booking document
        booking_data = {
            "username": username,
            "roll_number": roll_number,
            "phone_number": phone_number,
            "food_items": food_items,
            "amount": total_amount,
            "status": "confirmed",
            "created_at": datetime.now(),
            "updated_at": datetime.now()
        }
        
        # Add to main bookings collection
        booking_ref = db.collection("bookings").document()
        booking_id = booking_ref.id
        booking_ref.set(booking_data)
        
        # Add to user's bookings subcollection
        user_booking_ref = db.collection("users").document(username).collection("bookings").document(booking_id)
        user_booking_ref.set(booking_data)
        
        # Generate QR code with just the booking ID
        qr = qrcode.make(booking_id)
        buffer = io.BytesIO()
        qr.save(buffer, format="PNG")
        qr_base64 = base64.b64encode(buffer.getvalue()).decode()
        
        # Update both booking references with QR code
        booking_ref.update({"qr_code": qr_base64})
        user_booking_ref.update({"qr_code": qr_base64})
        
        return jsonify({
            "status": "success",
            "message": "Booking confirmed",
            "qr_code": qr_base64,
            "booking_id": booking_id
        })
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/verify_booking", methods=["POST"])
def verify_booking():
    try:
        booking_id = request.json.get('booking_id')
        if not booking_id:
            return jsonify({"status": "error", "message": "Booking ID required"}), 400
        
        booking_ref = db.collection("bookings").document(booking_id)
        booking = booking_ref.get()
        
        if not booking.exists:
            return jsonify({"status": "error", "message": "Invalid booking ID"}), 404
        
        booking_data = booking.to_dict()
        
        if booking_data.get('status') == 'collected':
            return jsonify({
                "status": "error",
                "message": f"Booking already collected at: {booking_data.get('collected_at').strftime('%Y-%m-%d %H:%M:%S')}"
            }), 400
            
        if booking_data.get('status') != 'confirmed':
            return jsonify({"status": "error", "message": "Booking not confirmed"}), 400
        
        # Update booking status
        collected_time = datetime.now()
        booking_ref.update({
            "status": "collected",
            "collected_at": collected_time,
            "updated_at": collected_time
        })
        
        # Update user's booking record
        username = booking_data.get('username')
        if username:
            db.collection("users").document(username).collection("bookings").document(booking_id).update({
                "status": "collected",
                "collected_at": collected_time,
                "updated_at": collected_time
            })
        
        return jsonify({
            "status": "success",
            "message": "Food collected successfully",
            "collection_time": collected_time.strftime("%Y-%m-%d %H:%M:%S"),
            "food_items": booking_data.get('food_items', [])
        })
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=5000)