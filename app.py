from flask import Flask, render_template, request, jsonify, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
import os
import uuid
import json

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///watch_earn.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'static/uploads'

db = SQLAlchemy(app)

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Database Models
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(120), nullable=False)
    balance = db.Column(db.Float, default=0.0)
    last_daily_bonus = db.Column(db.DateTime, default=None)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_admin = db.Column(db.Boolean, default=False)
    is_youtuber = db.Column(db.Boolean, default=False)

class Video(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    url = db.Column(db.String(500), nullable=False)
    reward_amount = db.Column(db.Float, default=0.1)
    watch_duration = db.Column(db.Integer, default=30)  # seconds
    uploaded_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    is_approved = db.Column(db.Boolean, default=False)
    video_type = db.Column(db.String(20), default='url')  # 'url' or 'file'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class WatchHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    video_id = db.Column(db.Integer, db.ForeignKey('video.id'), nullable=False)
    watched_at = db.Column(db.DateTime, default=datetime.utcnow)
    earned_amount = db.Column(db.Float, nullable=False)

class Settings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), unique=True, nullable=False)
    value = db.Column(db.String(100), nullable=False)

# Helper Functions
def create_default_settings():
    settings = [
        ('video_watch_seconds', '30'),
        ('daily_bonus_seconds', '60'),
        ('video_reward_amount', '0.1'),
        ('daily_bonus_amount', '1.0')
    ]
    
    for key, value in settings:
        if not Settings.query.filter_by(key=key).first():
            setting = Settings(key=key, value=value)
            db.session.add(setting)
    db.session.commit()

def get_setting(key):
    setting = Settings.query.filter_by(key=key).first()
    return setting.value if setting else None

def login_required(f):
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    decorated_function.__name__ = f.__name__
    return decorated_function

def admin_required(f):
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        user = User.query.get(session['user_id'])
        if not user.is_admin:
            flash('Access denied. Admin privileges required.', 'error')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    decorated_function.__name__ = f.__name__
    return decorated_function

def youtuber_required(f):
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        user = User.query.get(session['user_id'])
        if not user.is_youtuber:
            flash('Access denied. YouTuber privileges required.', 'error')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    decorated_function.__name__ = f.__name__
    return decorated_function

# Initialize database
def init_db():
    """Initialize database tables and default data."""
    db.create_all()
    create_default_settings()
    
    # Create admin user if doesn't exist
    if not User.query.filter_by(username='admin').first():
        admin = User(
            username='admin',
            email='admin@example.com',
            password_hash=generate_password_hash('admin123'),
            is_admin=True
        )
        db.session.add(admin)
        db.session.commit()

# Routes
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        user_type = request.form.get('user_type', 'user')
        
        # Check if user already exists
        if User.query.filter_by(username=username).first():
            flash('Username already exists', 'error')
            return render_template('register.html')
        
        if User.query.filter_by(email=email).first():
            flash('Email already exists', 'error')
            return render_template('register.html')
        
        # Create new user
        user = User(
            username=username,
            email=email,
            password_hash=generate_password_hash(password),
            is_youtuber=(user_type == 'youtuber')
        )
        
        db.session.add(user)
        db.session.commit()
        
        flash('Registration successful! Please login.', 'success')
        return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password_hash, password):
            session['user_id'] = user.id
            session['username'] = user.username
            session['is_admin'] = user.is_admin
            session['is_youtuber'] = user.is_youtuber
            
            if user.is_admin:
                return redirect(url_for('admin_panel'))
            elif user.is_youtuber:
                return redirect(url_for('youtuber_dashboard'))
            else:
                return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password', 'error')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    user = User.query.get(session['user_id'])
    videos = Video.query.filter_by(is_approved=True).all()
    
    # Get user's watch history
    watched_videos = db.session.query(WatchHistory.video_id).filter_by(user_id=user.id).all()
    watched_video_ids = [w.video_id for w in watched_videos]
    
    return render_template('user_dashboard.html', 
                         user=user, 
                         videos=videos, 
                         watched_video_ids=watched_video_ids,
                         video_watch_seconds=int(get_setting('video_watch_seconds')),
                         daily_bonus_seconds=int(get_setting('daily_bonus_seconds')))

@app.route('/youtuber_dashboard')
@youtuber_required
def youtuber_dashboard():
    user = User.query.get(session['user_id'])
    videos = Video.query.filter_by(uploaded_by=user.id).all()
    
    return render_template('youtuber_dashboard.html', user=user, videos=videos)

@app.route('/admin_panel')
@admin_required
def admin_panel():
    users = User.query.all()
    videos = Video.query.all()
    settings = Settings.query.all()
    
    return render_template('admin_panel.html', users=users, videos=videos, settings=settings)

@app.route('/upload_video', methods=['POST'])
@youtuber_required
def upload_video():
    title = request.form['title']
    video_url = request.form['video_url']
    
    video = Video(
        title=title,
        url=video_url,
        uploaded_by=session['user_id'],
        video_type='url'
    )
    
    db.session.add(video)
    db.session.commit()
    
    flash('Video uploaded successfully! Awaiting approval.', 'success')
    return redirect(url_for('youtuber_dashboard'))

@app.route('/admin_upload_video', methods=['POST'])
@admin_required
def admin_upload_video():
    title = request.form['title']
    video_type = request.form['video_type']
    
    if video_type == 'url':
        video_url = request.form['video_url']
        video = Video(
            title=title,
            url=video_url,
            uploaded_by=session['user_id'],
            video_type='url',
            is_approved=True
        )
    else:  # file upload
        if 'video_file' not in request.files:
            flash('No file selected', 'error')
            return redirect(url_for('admin_panel'))
        
        file = request.files['video_file']
        if file.filename == '':
            flash('No file selected', 'error')
            return redirect(url_for('admin_panel'))
        
        filename = secure_filename(file.filename)
        unique_filename = f"{uuid.uuid4()}_{filename}"
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
        file.save(file_path)
        
        video = Video(
            title=title,
            url=f"/static/uploads/{unique_filename}",
            uploaded_by=session['user_id'],
            video_type='file',
            is_approved=True
        )
    
    db.session.add(video)
    db.session.commit()
    
    flash('Video uploaded successfully!', 'success')
    return redirect(url_for('admin_panel'))

@app.route('/approve_video/<int:video_id>')
@admin_required
def approve_video(video_id):
    video = Video.query.get_or_404(video_id)
    video.is_approved = True
    db.session.commit()
    
    flash('Video approved successfully!', 'success')
    return redirect(url_for('admin_panel'))

@app.route('/delete_video/<int:video_id>')
@admin_required
def delete_video(video_id):
    video = Video.query.get_or_404(video_id)
    
    # Delete file if it's a file upload
    if video.video_type == 'file':
        file_path = os.path.join('static/uploads', os.path.basename(video.url))
        if os.path.exists(file_path):
            os.remove(file_path)
    
    db.session.delete(video)
    db.session.commit()
    
    flash('Video deleted successfully!', 'success')
    return redirect(url_for('admin_panel'))

@app.route('/api/watch_video', methods=['POST'])
@login_required
def watch_video():
    data = request.get_json()
    video_id = data.get('video_id')
    
    # Check if user already watched this video
    existing_watch = WatchHistory.query.filter_by(
        user_id=session['user_id'],
        video_id=video_id
    ).first()
    
    if existing_watch:
        return jsonify({'success': False, 'message': 'Video already watched'})
    
    video = Video.query.get_or_404(video_id)
    user = User.query.get(session['user_id'])
    
    # Add reward to user balance
    reward_amount = float(get_setting('video_reward_amount'))
    user.balance += reward_amount
    
    # Record watch history
    watch_history = WatchHistory(
        user_id=user.id,
        video_id=video.id,
        earned_amount=reward_amount
    )
    
    db.session.add(watch_history)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'new_balance': user.balance,
        'earned_amount': reward_amount
    })

@app.route('/api/daily_bonus', methods=['POST'])
@login_required
def daily_bonus():
    user = User.query.get(session['user_id'])
    now = datetime.utcnow()
    
    # Check if user already claimed daily bonus today
    if user.last_daily_bonus:
        if user.last_daily_bonus.date() == now.date():
            return jsonify({'success': False, 'message': 'Daily bonus already claimed today'})
    
    # Add daily bonus
    bonus_amount = float(get_setting('daily_bonus_amount'))
    user.balance += bonus_amount
    user.last_daily_bonus = now
    
    db.session.commit()
    
    return jsonify({
        'success': True,
        'new_balance': user.balance,
        'bonus_amount': bonus_amount
    })

@app.route('/api/get_balance')
@login_required
def get_balance():
    user = User.query.get(session['user_id'])
    return jsonify({'balance': user.balance})

@app.route('/update_settings', methods=['POST'])
@admin_required
def update_settings():
    video_watch_seconds = request.form['video_watch_seconds']
    daily_bonus_seconds = request.form['daily_bonus_seconds']
    video_reward_amount = request.form['video_reward_amount']
    daily_bonus_amount = request.form['daily_bonus_amount']
    
    settings_to_update = [
        ('video_watch_seconds', video_watch_seconds),
        ('daily_bonus_seconds', daily_bonus_seconds),
        ('video_reward_amount', video_reward_amount),
        ('daily_bonus_amount', daily_bonus_amount)
    ]
    
    for key, value in settings_to_update:
        setting = Settings.query.filter_by(key=key).first()
        if setting:
            setting.value = value
        else:
            setting = Settings(key=key, value=value)
            db.session.add(setting)
    
    db.session.commit()
    flash('Settings updated successfully!', 'success')
    return redirect(url_for('admin_panel'))

# Initialize database when app starts
with app.app_context():
    init_db()

if __name__ == '__main__':
    app.run(debug=True)
