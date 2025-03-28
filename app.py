from flask import Flask, request, jsonify, render_template, send_from_directory
import firebase_admin
from firebase_admin import credentials, firestore
import qrcode
import io
import base64
import razorpay
from flask_cors import CORS
import os
import json
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Initialize Flask app with template and static folders
app = Flask(__name__, 
            template_folder='flask-api/templates',
            static_folder='flask-api/static')
CORS(app)

# Initialize Firebase only ONCE
if not firebase_admin._apps:
    firebase_credentials = json.loads(os.getenv("FIREBASE_CREDENTIALS"))
    cred = credentials.Certificate(firebase_credentials)
    firebase_admin.initialize_app(cred)

db = firestore.client()

# Initialize Razorpay
RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET")
razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

# Serve main frontend
@app.route("/")
def home():
    return render_template("index.html")

# Serve static files
@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_from_directory(app.static_folder, filename)

# Authentication routes
@app.route("/login")
def login():
    return render_template("login.html")

@app.route("/register")
def register():
    return render_template("register.html")

# API Endpoints (keep your existing functionality)
@app.route("/test_firebase", methods=["GET"])
def test_firebase():
    try:
        test_ref = db.collection("test").document("connection").get()
        if test_ref.exists:
            return jsonify({"status": "connected", "message": "Firebase is working!"})
        else:
            return jsonify({"status": "connected", "message": "Connected, but no test data found."})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/book_food", methods=["POST"])
def book_food():
    try:
        data = request.json
        phone_number = data.get("phone_number")
        food_items = data.get("food_items")
        payment_id = data.get("payment_id")

        if not phone_number or not food_items or not payment_id:
            return jsonify({"status": "error", "message": "Missing required fields"}), 400

        payment = razorpay_client.payment.fetch(payment_id)
        if payment["status"] != "captured":
            return jsonify({"status": "error", "message": "Payment not successful"}), 400

        booking_ref = db.collection("bookings").add({
            "phone_number": phone_number,
            "food_items": food_items,
            "payment_id": payment_id,
            "status": "pending"
        })
        booking_id = booking_ref[1].id

        qr_data = json.dumps({
            "booking_id": booking_id,
            "phone_number": phone_number,
        })
        qr = qrcode.make(qr_data)
        buffer = io.BytesIO()
        qr.save(buffer, format="PNG")
        qr_base64 = base64.b64encode(buffer.getvalue()).decode()

        return jsonify({
            "status": "success",
            "qr_code": qr_base64,
            "booking_id": booking_id
        })
    
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/verify_qr", methods=["POST"])
def verify_qr():
    try:
        data = request.json
        scanned_qr = data.get("scanned_qr")

        if not scanned_qr:
            return jsonify({"status": "error", "message": "No QR code provided"}), 400

        try:
            decoded_qr_data = json.loads(scanned_qr)
        except json.JSONDecodeError:
            return jsonify({"status": "error", "message": "Invalid QR data format"}), 400

        booking_id = decoded_qr_data.get("booking_id")

        if not booking_id:
            return jsonify({"status": "error", "message": "Invalid QR data"}), 400

        booking_ref = db.collection("bookings").document(booking_id).get()
        
        if not booking_ref.exists:
            return jsonify({"status": "rejected", "message": "Invalid QR code"})

        booking_data = booking_ref.to_dict()
        return jsonify({
            "status": "approved",
            "food_items": booking_data["food_items"],
            "phone_number": booking_data["phone_number"]
        })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)