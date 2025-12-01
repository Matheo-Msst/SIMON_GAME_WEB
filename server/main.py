from flask import Flask, render_template, request, redirect, url_for, session
import sqlite3, json, threading, time, os
import paho.mqtt.client as mqtt
from werkzeug.security import generate_password_hash, check_password_hash

# --- Config ---
APP_SECRET = 'change-me'
MQTT_BROKER = '127.0.0.1'
MQTT_PORT = 1883
DB_FILE = 'users.db'
SCORES_DIR = './json'
SCORES_FILE = os.path.join(SCORES_DIR, 'scores.json')

# --- Flask app ---
app = Flask(__name__)
app.secret_key = APP_SECRET

# --- Jinja2 filter ---
@app.template_filter('timestamp_to_date')
def timestamp_to_date(timestamp):
    return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(timestamp))

# --- DB init ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY, 
        username TEXT UNIQUE, 
        password TEXT
    )''')
    conn.commit()
    conn.close()
init_db()

# --- MQTT ---
mqtt_client = mqtt.Client()

def on_connect(client, userdata, flags, rc):
    print(f"MQTT connected with code {rc}")
    client.subscribe("simon/scores")
    client.subscribe("simon/pair/ack")

def on_message(client, userdata, msg):
    payload = msg.payload.decode()
    try:
        data = json.loads(payload)
    except:
        return
    if msg.topic == "simon/scores":
        os.makedirs(SCORES_DIR, exist_ok=True)
        try:
            with open(SCORES_FILE, 'r') as f:
                scores = json.load(f)
        except FileNotFoundError:
            scores = []

        timestamp = int(time.time())
        scores.append({
            "ssid": data.get("ssid"),
            "username": data.get("username"),
            "score": data.get("score"),
            "ts": timestamp,
            "date": time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(timestamp))  # <-- date lisible
        })

        with open(SCORES_FILE, 'w') as f:
            json.dump(scores, f, indent=2)

    elif msg.topic == "simon/pair/ack":
        print(f"{data.get('ssid')} paired with {data.get('username')} - status: {data.get('status')}")

mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message
mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
threading.Thread(target=mqtt_client.loop_forever, daemon=True).start()

# --- Routes ---
@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/register', methods=['GET','POST'])
def register():
    if request.method=='POST':
        username = request.form['username']
        password = generate_password_hash(request.form['password'])
        conn = sqlite3.connect(DB_FILE)
        try:
            conn.execute("INSERT INTO users(username, password) VALUES(?,?)", (username,password))
            conn.commit()
        except sqlite3.IntegrityError:
            conn.close()
            return render_template('register.html', error="Ce nom d'utilisateur existe déjà")
        conn.close()
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method=='POST':
        username = request.form['username']
        password = request.form['password']
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT password FROM users WHERE username=?", (username,))
        r = c.fetchone()
        conn.close()
        if r and check_password_hash(r[0], password):
            session['username'] = username
            return redirect(url_for('dashboard'))
        return render_template('login.html', error="Identifiants incorrects")
    return render_template('login.html')

@app.route('/pair', methods=['GET','POST'])
def pair():
    if 'username' not in session:
        return redirect(url_for('login'))
    if request.method=='POST':
        ssid = request.form['ssid']
        pwd = request.form['password']
        mqtt_client.publish("simon/pair", json.dumps({
            "ssid": ssid,
            "password": pwd,
            "username": session['username']
        }))
        return render_template('pair.html', username=session['username'], success="Demande de pairing envoyée à l'ESP32")
    return render_template('pair.html', username=session['username'])

@app.route('/dashboard')
def dashboard():
    if 'username' not in session:
        return redirect(url_for('login'))
    try:
        with open(SCORES_FILE,'r') as f:
            scores = json.load(f)
    except:
        scores = []

    recent_scores = list(reversed(scores[-200:]))  # plus récent en premier
    return render_template('dashboard.html', username=session['username'], scores=recent_scores)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__=="__main__":
    os.makedirs(SCORES_DIR, exist_ok=True)
    app.run(host="0.0.0.0", port=5000, debug=True)
