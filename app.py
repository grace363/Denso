from flask import Flask, render_template, request, jsonify, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
import os
import uuid
import json
import re

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here-change-in-production'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///watch_earn.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB max file size

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
    total_earned = db.Column(db.Float, default=0.0)
    videos_watched = db.Column(db.Integer, default=0)
    ads_watched = db.Column(db.Integer, default=0)  # Track ads watched
    last_daily_bonus = db.Column(db.DateTime, default=None)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_admin = db.Column(db.Boolean, default=False)
    is_youtuber = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    referral_code = db.Column(db.String(10), unique=True, nullable=False)
    referred_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

class Video(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    url = db.Column(db.String(500), nullable=False)
    thumbnail = db.Column(db.String(500), nullable=True)
    reward_amount = db.Column(db.Float, default=0.1)
    watch_duration = db.Column(db.Integer, default=30)  # seconds
    uploaded_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    is_approved = db.Column(db.Boolean, default=False)
    video_type = db.Column(db.String(20), default='url')  # 'url' or 'file'
    category = db.Column(db.String(50), default='entertainment')
    views = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_featured = db.Column(db.Boolean, default=False)
    requires_ad_unlock = db.Column(db.Boolean, default=True)  # Requires watching ad to unlock

class Advertisement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    ad_type = db.Column(db.String(20), nullable=False)  # 'image', 'video', 'banner', 'clickable'
    content_url = db.Column(db.String(500), nullable=False)
    click_url = db.Column(db.String(500), nullable=True)  # For clickable ads
    reward_amount = db.Column(db.Float, default=0.05)
    watch_duration = db.Column(db.Integer, default=15)  # seconds for video ads
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    impressions = db.Column(db.Integer, default=0)
    clicks = db.Column(db.Integer, default=0)
    is_clickable = db.Column(db.Boolean, default=False)  # For clickable advertisements

class WatchHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    video_id = db.Column(db.Integer, db.ForeignKey('video.id'), nullable=False)
    watched_at = db.Column(db.DateTime, default=datetime.utcnow)
    earned_amount = db.Column(db.Float, nullable=False)
    watch_duration = db.Column(db.Integer, default=0)
    completed = db.Column(db.Boolean, default=False)
    ad_watched = db.Column(db.Boolean, default=False)  # Track if ad was watched to unlock

class AdInteraction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    ad_id = db.Column(db.Integer, db.ForeignKey('advertisement.id'), nullable=False)
    interaction_type = db.Column(db.String(20), nullable=False)  # 'view', 'click', 'unlock'
    earned_amount = db.Column(db.Float, default=0.0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    video_id = db.Column(db.Integer, db.ForeignKey('video.id'), nullable=True)  # For unlock ads

class Settings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), unique=True, nullable=False)
    value = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)

class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    transaction_type = db.Column(db.String(20), nullable=False)  # 'earn', 'withdrawal', 'bonus'
    description = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default='completed')

# Helper Functions
def generate_referral_code():
    return str(uuid.uuid4())[:8].upper()

def extract_youtube_id(url):
    """Extract YouTube video ID from URL"""
    youtube_regex = r'(?:youtube\.com\/(?:[^\/]+\/.+\/|(?:v|e(?:mbed)?)\/|.*[?&]v=)|youtu\.be\/)([^"&?\/\s]{11})'
    match = re.search(youtube_regex, url)
    return match.group(1) if match else None

def create_default_settings():
    settings = [
        ('video_watch_seconds', '30', 'Minimum seconds to watch video for reward'),
        ('daily_bonus_seconds', '60', 'Seconds to watch for daily bonus'),
        ('video_reward_amount', '0.1', 'Default reward amount per video'),
        ('ad_reward_amount', '0.05', 'Default reward amount per advertisement'),
        ('daily_bonus_amount', '1.0', 'Daily bonus amount'),
        ('min_withdrawal_amount', '10.0', 'Minimum withdrawal amount'),
        ('referral_bonus', '2.0', 'Bonus for successful referral'),
        ('max_videos_per_day', '50', 'Maximum videos user can watch per day'),
        ('site_name', 'WatchEarn', 'Website name'),
        ('site_description', 'Watch videos and earn money!', 'Website description'),
        ('ad_unlock_reward', '0.02', 'Reward for watching ad to unlock video'),
    ]
    
    for key, value, description in settings:
        if not Settings.query.filter_by(key=key).first():
            setting = Settings(key=key, value=value, description=description)
            db.session.add(setting)
    db.session.commit()

def get_setting(key, default=None):
    setting = Settings.query.filter_by(key=key).first()
    return setting.value if setting else default

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
        if not user or not user.is_admin:
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
        if not user or not user.is_youtuber:
            flash('Access denied. Content creator privileges required.', 'error')
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
            email='admin@watchearn.com',
            password_hash=generate_password_hash('admin123'),
            is_admin=True,
            referral_code=generate_referral_code()
        )
        db.session.add(admin)
        db.session.commit()

# Routes
@app.route('/')
def index():
    featured_videos = Video.query.filter_by(is_approved=True, is_featured=True).limit(6).all()
    recent_videos = Video.query.filter_by(is_approved=True).order_by(Video.created_at.desc()).limit(8).all()
    
    stats = {
        'total_users': User.query.count(),
        'total_videos': Video.query.filter_by(is_approved=True).count(),
        'total_earnings': db.session.query(db.func.sum(Transaction.amount)).filter_by(transaction_type='earn').scalar() or 0
    }
    
    return render_template('index.html', 
                         featured_videos=featured_videos,
                         recent_videos=recent_videos,
                         stats=stats,
                         site_name=get_setting('site_name'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username'].strip()
        email = request.form['email'].strip()
        password = request.form['password']
        user_type = request.form.get('user_type', 'user')
        referral_code = request.form.get('referral_code', '').strip()
        
        # Validation
        if len(username) < 3:
            flash('Username must be at least 3 characters long', 'error')
            return render_template('register.html')
        
        if len(password) < 6:
            flash('Password must be at least 6 characters long', 'error')
            return render_template('register.html')
        
        # Check if user already exists
        if User.query.filter_by(username=username).first():
            flash('Username already exists', 'error')
            return render_template('register.html')
        
        if User.query.filter_by(email=email).first():
            flash('Email already exists', 'error')
            return render_template('register.html')
        
        # Handle referral
        referrer = None
        if referral_code:
            referrer = User.query.filter_by(referral_code=referral_code).first()
            if not referrer:
                flash('Invalid referral code', 'error')
                return render_template('register.html')
        
        # Create new user
        user = User(
            username=username,
            email=email,
            password_hash=generate_password_hash(password),
            is_youtuber=(user_type == 'youtuber'),
            referral_code=generate_referral_code(),
            referred_by=referrer.id if referrer else None
        )
        
        db.session.add(user)
        db.session.commit()
        
        # Give referral bonus
        if referrer:
            bonus_amount = float(get_setting('referral_bonus', 2.0))
            referrer.balance += bonus_amount
            
            # Record transaction
            transaction = Transaction(
                user_id=referrer.id,
                amount=bonus_amount,
                transaction_type='bonus',
                description=f'Referral bonus for {username}'
            )
            db.session.add(transaction)
            db.session.commit()
        
        flash('Registration successful! Please login.', 'success')
        return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password_hash, password):
            if not user.is_active:
                flash('Account is deactivated. Please contact support.', 'error')
                return render_template('login.html')
            
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
    flash('You have been logged out successfully.', 'info')
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    user = User.query.get(session['user_id'])
    
    # Get available videos (not watched by user)
    watched_video_ids = db.session.query(WatchHistory.video_id).filter_by(user_id=user.id).subquery()
    available_videos = Video.query.filter(
        Video.is_approved == True,
        ~Video.id.in_(watched_video_ids)
    ).order_by(Video.created_at.desc()).all()
    
    # Get user's recent watch history
    recent_watches = db.session.query(WatchHistory, Video).join(Video).filter(
        WatchHistory.user_id == user.id
    ).order_by(WatchHistory.watched_at.desc()).limit(10).all()
    
    # Get recent transactions
    recent_transactions = Transaction.query.filter_by(user_id=user.id).order_by(
        Transaction.created_at.desc()
    ).limit(10).all()
    
    # Get active advertisements
    active_ads = Advertisement.query.filter_by(is_active=True).limit(5).all()
    
    # Check if user can claim daily bonus
    can_claim_daily = True
    if user.last_daily_bonus:
        can_claim_daily = user.last_daily_bonus.date() < datetime.utcnow().date()
    
    return render_template('user_dashboard.html',
                         user=user,
                         available_videos=available_videos,
                         recent_watches=recent_watches,
                         recent_transactions=recent_transactions,
                         active_ads=active_ads,
                         can_claim_daily=can_claim_daily,
                         video_watch_seconds=int(get_setting('video_watch_seconds', 30)),
                         daily_bonus_seconds=int(get_setting('daily_bonus_seconds', 60)))

@app.route('/youtuber_dashboard')
@youtuber_required
def youtuber_dashboard():
    user = User.query.get(session['user_id'])
    videos = Video.query.filter_by(uploaded_by=user.id).order_by(Video.created_at.desc()).all()
    
    # Calculate earnings from user's videos
    total_earnings = db.session.query(db.func.sum(WatchHistory.earned_amount)).join(Video).filter(
        Video.uploaded_by == user.id
    ).scalar() or 0
    
    return render_template('youtuber_dashboard.html',
                         user=user,
                         videos=videos,
                         total_earnings=total_earnings)

@app.route('/admin_panel')
@admin_required
def admin_panel():
    # Get statistics
    stats = {
        'total_users': User.query.count(),
        'total_videos': Video.query.count(),
        'pending_videos': Video.query.filter_by(is_approved=False).count(),
        'total_advertisements': Advertisement.query.count(),
        'total_earnings': db.session.query(db.func.sum(Transaction.amount)).filter_by(transaction_type='earn').scalar() or 0,
        'active_users': User.query.filter_by(is_active=True).count(),
    }
    
    # Get recent data
    recent_users = User.query.order_by(User.created_at.desc()).limit(10).all()
    pending_videos = Video.query.filter_by(is_approved=False).order_by(Video.created_at.desc()).limit(10).all()
    recent_videos = Video.query.order_by(Video.created_at.desc()).limit(10).all()
    advertisements = Advertisement.query.order_by(Advertisement.created_at.desc()).limit(10).all()
    settings = Settings.query.all()
    
    return render_template('admin_panel.html',
                         stats=stats,
                         recent_users=recent_users,
                         pending_videos=pending_videos,
                         recent_videos=recent_videos,
                         advertisements=advertisements,
                         settings=settings)

@app.route('/upload_video', methods=['POST'])
@youtuber_required
def upload_video():
    title = request.form['title'].strip()
    description = request.form.get('description', '').strip()
    video_url = request.form['video_url'].strip()
    category = request.form.get('category', 'entertainment')
    
    if not title or not video_url:
        flash('Title and video URL are required', 'error')
        return redirect(url_for('youtuber_dashboard'))
    
    # Extract thumbnail for YouTube videos
    thumbnail = None
    youtube_id = extract_youtube_id(video_url)
    if youtube_id:
        thumbnail = f"https://img.youtube.com/vi/{youtube_id}/maxresdefault.jpg"
    
    video = Video(
        title=title,
        description=description,
        url=video_url,
        thumbnail=thumbnail,
        category=category,
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
    title = request.form['title'].strip()
    description = request.form.get('description', '').strip()
    video_type = request.form['video_type']
    category = request.form.get('category', 'entertainment')
    reward_amount = float(request.form.get('reward_amount', get_setting('video_reward_amount', 0.1)))
    requires_ad_unlock = request.form.get('requires_ad_unlock') == 'on'
    
    if video_type == 'url':
        video_url = request.form['video_url'].strip()
        
        # Extract thumbnail for YouTube videos
        thumbnail = None
        youtube_id = extract_youtube_id(video_url)
        if youtube_id:
            thumbnail = f"https://img.youtube.com/vi/{youtube_id}/maxresdefault.jpg"
        
        video = Video(
            title=title,
            description=description,
            url=video_url,
            thumbnail=thumbnail,
            category=category,
            reward_amount=reward_amount,
            uploaded_by=session['user_id'],
            video_type='url',
            is_approved=True,
            requires_ad_unlock=requires_ad_unlock
        )
    else:  # file upload
        if 'video_file' not in request.files:
            flash('No file selected', 'error')
            return redirect(url_for('admin_panel'))
        
        file = request.files['video_file']
        if file.filename == '':
            flash('No file selected', 'error')
            return redirect(url_for('admin_panel'))
        
        # Validate file type
        allowed_extensions = {'mp4', 'avi', 'mov', 'wmv', 'flv', 'webm'}
        if not ('.' in file.filename and file.filename.rsplit('.', 1)[1].lower() in allowed_extensions):
            flash('Invalid file type. Please upload a video file.', 'error')
            return redirect(url_for('admin_panel'))
        
        filename = secure_filename(file.filename)
        unique_filename = f"{uuid.uuid4()}_{filename}"
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
        file.save(file_path)
        
        video = Video(
            title=title,
            description=description,
            url=f"/static/uploads/{unique_filename}",
            category=category,
            reward_amount=reward_amount,
            uploaded_by=session['user_id'],
            video_type='file',
            is_approved=True,
            requires_ad_unlock=requires_ad_unlock
        )
    
    db.session.add(video)
    db.session.commit()
    
    flash('Video uploaded successfully!', 'success')
    return redirect(url_for('admin_panel'))

@app.route('/admin_upload_advertisement', methods=['POST'])
@admin_required
def admin_upload_advertisement():
    title = request.form['title'].strip()
    description = request.form.get('description', '').strip()
    ad_type = request.form['ad_type']
    reward_amount = float(request.form.get('reward_amount', get_setting('ad_reward_amount', 0.05)))
    watch_duration = int(request.form.get('watch_duration', 15))
    click_url = request.form.get('click_url', '').strip()
    is_clickable = request.form.get('is_clickable') == 'on'
    
    if not title:
        flash('Title is required', 'error')
        return redirect(url_for('admin_panel'))
    
    if ad_type == 'url':
        content_url = request.form['content_url'].strip()
        if not content_url:
            flash('Content URL is required', 'error')
            return redirect(url_for('admin_panel'))
        
        advertisement = Advertisement(
            title=title,
            description=description,
            ad_type=ad_type,
            content_url=content_url,
            click_url=click_url if is_clickable else None,
            reward_amount=reward_amount,
            watch_duration=watch_duration,
            is_clickable=is_clickable
        )
    else:  # file upload
        if 'ad_file' not in request.files:
            flash('No file selected', 'error')
            return redirect(url_for('admin_panel'))
        
        file = request.files['ad_file']
        if file.filename == '':
            flash('No file selected', 'error')
            return redirect(url_for('admin_panel'))
        
        # Validate file type based on ad type
        allowed_extensions = {
            'image': {'jpg', 'jpeg', 'png', 'gif', 'webp'},
            'video': {'mp4', 'avi', 'mov', 'wmv', 'flv', 'webm'},
            'banner': {'jpg', 'jpeg', 'png', 'gif', 'webp', 'svg'}
        }
        
        file_extension = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
        if file_extension not in allowed_extensions.get(ad_type, set()):
            flash(f'Invalid file type for {ad_type} advertisement.', 'error')
            return redirect(url_for('admin_panel'))
        
        filename = secure_filename(file.filename)
        unique_filename = f"{uuid.uuid4()}_{filename}"
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
        file.save(file_path)
        
        advertisement = Advertisement(
            title=title,
            description=description,
            ad_type=ad_type,
            content_url=f"/static/uploads/{unique_filename}",
            click_url=click_url if is_clickable else None,
            reward_amount=reward_amount,
            watch_duration=watch_duration,
            is_clickable=is_clickable
        )
    
    db.session.add(advertisement)
    db.session.commit()
    
    flash('Advertisement uploaded successfully!', 'success')
    return redirect(url_for('admin_panel'))

@app.route('/watch/<int:video_id>')
@login_required
def watch(video_id):
    video = Video.query.get_or_404(video_id)
    user = User.query.get(session['user_id'])
    
    # Check if user has already watched this video
    watched = WatchHistory.query.filter_by(user_id=user.id, video_id=video_id).first()
    if watched:
        flash('You have already watched this video', 'info')
        return redirect(url_for('dashboard'))
    
    # Check if video requires ad unlock
    ad_watched = False
    unlock_ad = None
    if video.requires_ad_unlock:
        # Check if user has watched an ad for this video today
        today = datetime.utcnow().date()
        ad_interaction = AdInteraction.query.filter_by(
            user_id=user.id,
            video_id=video_id,
            interaction_type='unlock'
        ).filter(
            db.func.date(AdInteraction.created_at) == today
        ).first()
        
        if ad_interaction:
            ad_watched = True
        else:
            # Get a random unlock advertisement
            unlock_ad = Advertisement.query.filter_by(is_active=True).order_by(db.func.random()).first()
    
    return render_template('watch_video.html',
                         video=video,
                         user=user,
                         ad_watched=ad_watched,
                         unlock_ad=unlock_ad,
                         video_watch_seconds=int(get_setting('video_watch_seconds', 30)))

@app.route('/watch_ad_unlock', methods=['POST'])
@login_required
def watch_ad_unlock():
    data = request.get_json()
    video_id = data.get('video_id')
    ad_id = data.get('ad_id')
    
    video = Video.query.get_or_404(video_id)
    advertisement = Advertisement.query.get_or_404(ad_id)
    user = User.query.get(session['user_id'])
    
    # Check if user has already watched unlock ad for this video today
    today = datetime.utcnow().date()
    existing_interaction = AdInteraction.query.filter_by(
        user_id=user.id,
        video_id=video_id,
        interaction_type='unlock'
    ).filter(
        db.func.date(AdInteraction.created_at) == today
    ).first()
    
    if existing_interaction:
        return jsonify({'success': False, 'message': 'Already unlocked today'})
    
    # Record the ad interaction
    reward_amount = float(get_setting('ad_unlock_reward', 0.02))
    interaction = AdInteraction(
        user_id=user.id,
        ad_id=ad_id,
        video_id=video_id,
        interaction_type='unlock',
        earned_amount=reward_amount
    )
    
    # Update user balance
    user.balance += reward_amount
    user.total_earned += reward_amount
    user.ads_watched += 1
    
    # Update advertisement stats
    advertisement.impressions += 1
    
    # Record transaction
    transaction = Transaction(
        user_id=user.id,
        amount=reward_amount,
        transaction_type='earn',
        description=f'Watched ad to unlock video: {video.title}'
    )
    
    db.session.add(interaction)
    db.session.add(transaction)
    db.session.commit()
    
    return jsonify({'success': True, 'earned': reward_amount})

 @app.route('/complete_video_watch', methods=['POST'])
@login_required
def complete_video_watch():
    data = request.get_json()
    video_id = data.get('video_id')
    watch_duration = data.get('watch_duration', 0)
    
    video = Video.query.get_or_404(video_id)
    user = User.query.get(session['user_id'])
    
    # Check if user has already watched this video
    existing_watch = WatchHistory.query.filter_by(user_id=user.id, video_id=video_id).first()
    if existing_watch:
        return jsonify({'success': False, 'message': 'Already watched'})
    
    # Check if minimum watch duration is met
    min_watch_seconds = int(get_setting('video_watch_seconds', 30))
    if watch_duration < min_watch_seconds:
        return jsonify({'success': False, 'message': 'Not watched long enough'})
    
    # Record the watch
    watch_history = WatchHistory(
        user_id=user.id,
        video_id=video_id,
        watch_duration=watch_duration,
        earned_amount=video.reward_amount,
        completed=True
    )
    
    # Update user stats
    user.balance += video.reward_amount
    user.total_earned += video.reward_amount
    user.videos_watched += 1
    
    # Update video stats
    video.views += 1
    
    # Record transaction
    transaction = Transaction(
        user_id=user.id,
        amount=video.reward_amount,
        transaction_type='earn',
        description=f'Watched video: {video.title}'
    )
    
    db.session.add(watch_history)
    db.session.add(transaction)
    db.session.commit()
    
    return jsonify({'success': True, 'earned': video.reward_amount})

@app.route('/watch_advertisement', methods=['POST'])
@login_required
def watch_advertisement():
    data = request.get_json()
    ad_id = data.get('ad_id')
    interaction_type = data.get('interaction_type', 'view')
    
    advertisement = Advertisement.query.get_or_404(ad_id)
    user = User.query.get(session['user_id'])
    
    # Record the ad interaction
    interaction = AdInteraction(
        user_id=user.id,
        ad_id=ad_id,
        interaction_type=interaction_type,
        earned_amount=advertisement.reward_amount
    )
    
    # Update user balance
    user.balance += advertisement.reward_amount
    user.total_earned += advertisement.reward_amount
    user.ads_watched += 1
    
    # Update advertisement stats
    advertisement.impressions += 1
    if interaction_type == 'click':
        advertisement.clicks += 1
    
    # Record transaction
    transaction = Transaction(
        user_id=user.id,
        amount=advertisement.reward_amount,
        transaction_type='earn',
        description=f'Watched advertisement: {advertisement.title}'
    )
    
    db.session.add(interaction)
    db.session.add(transaction)
    db.session.commit()
    
    return jsonify({'success': True, 'earned': advertisement.reward_amount})

@app.route('/claim_daily_bonus', methods=['POST'])
@login_required
def claim_daily_bonus():
    user = User.query.get(session['user_id'])
    
    # Check if user can claim daily bonus
    if user.last_daily_bonus and user.last_daily_bonus.date() >= datetime.utcnow().date():
        return jsonify({'success': False, 'message': 'Already claimed today'})
    
    bonus_amount = float(get_setting('daily_bonus_amount', 1.0))
    
    # Update user
    user.balance += bonus_amount
    user.total_earned += bonus_amount
    user.last_daily_bonus = datetime.utcnow()
    
    # Record transaction
    transaction = Transaction(
        user_id=user.id,
        amount=bonus_amount,
        transaction_type='bonus',
        description='Daily bonus'
    )
    
    db.session.add(transaction)
    db.session.commit()
    
    return jsonify({'success': True, 'bonus': bonus_amount})

@app.route('/approve_video/<int:video_id>', methods=['POST'])
@admin_required
def approve_video(video_id):
    video = Video.query.get_or_404(video_id)
    video.is_approved = True
    
    # Optionally set as featured
    if request.form.get('featured') == 'on':
        video.is_featured = True
    
    db.session.commit()
    flash('Video approved successfully!', 'success')
    return redirect(url_for('admin_panel'))

@app.route('/reject_video/<int:video_id>', methods=['POST'])
@admin_required
def reject_video(video_id):
    video = Video.query.get_or_404(video_id)
    db.session.delete(video)
    db.session.commit()
    flash('Video rejected and deleted.', 'info')
    return redirect(url_for('admin_panel'))

@app.route('/delete_video/<int:video_id>', methods=['POST'])
@admin_required
def delete_video(video_id):
    video = Video.query.get_or_404(video_id)
    
    # Delete file if it's a file upload
    if video.video_type == 'file' and video.url.startswith('/static/uploads/'):
        file_path = video.url.replace('/static/uploads/', '')
        full_path = os.path.join(app.config['UPLOAD_FOLDER'], file_path)
        if os.path.exists(full_path):
            os.remove(full_path)
    
    db.session.delete(video)
    db.session.commit()
    flash('Video deleted successfully!', 'success')
    return redirect(url_for('admin_panel'))

@app.route('/toggle_ad_status/<int:ad_id>', methods=['POST'])
@admin_required
def toggle_ad_status(ad_id):
    advertisement = Advertisement.query.get_or_404(ad_id)
    advertisement.is_active = not advertisement.is_active
    db.session.commit()
    
    status = 'activated' if advertisement.is_active else 'deactivated'
    flash(f'Advertisement {status} successfully!', 'success')
    return redirect(url_for('admin_panel'))

@app.route('/delete_advertisement/<int:ad_id>', methods=['POST'])
@admin_required
def delete_advertisement(ad_id):
    advertisement = Advertisement.query.get_or_404(ad_id)
    
    # Delete file if it's a file upload
    if advertisement.content_url.startswith('/static/uploads/'):
        file_path = advertisement.content_url.replace('/static/uploads/', '')
        full_path = os.path.join(app.config['UPLOAD_FOLDER'], file_path)
        if os.path.exists(full_path):
            os.remove(full_path)
    
    db.session.delete(advertisement)
    db.session.commit()
    flash('Advertisement deleted successfully!', 'success')
    return redirect(url_for('admin_panel'))

@app.route('/toggle_user_status/<int:user_id>', methods=['POST'])
@admin_required
def toggle_user_status(user_id):
    user = User.query.get_or_404(user_id)
    user.is_active = not user.is_active
    db.session.commit()
    
    status = 'activated' if user.is_active else 'deactivated'
    flash(f'User {status} successfully!', 'success')
    return redirect(url_for('admin_panel'))

@app.route('/update_settings', methods=['POST'])
@admin_required
def update_settings():
    for key, value in request.form.items():
        if key != 'csrf_token':
            setting = Settings.query.filter_by(key=key).first()
            if setting:
                setting.value = value
    
    db.session.commit()
    flash('Settings updated successfully!', 'success')
    return redirect(url_for('admin_panel'))

@app.route('/videos')
def videos():
    category = request.args.get('category', 'all')
    page = request.args.get('page', 1, type=int)
    per_page = 12
    
    query = Video.query.filter_by(is_approved=True)
    
    if category != 'all':
        query = query.filter_by(category=category)
    
    videos = query.order_by(Video.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    
    categories = ['entertainment', 'education', 'music', 'sports', 'news', 'technology', 'gaming']
    
    return render_template('videos.html', 
                         videos=videos,
                         categories=categories,
                         current_category=category)

@app.route('/advertisements')
@login_required
def advertisements():
    ads = Advertisement.query.filter_by(is_active=True).order_by(Advertisement.created_at.desc()).all()
    return render_template('advertisements.html', ads=ads)

@app.route('/profile')
@login_required
def profile():
    user = User.query.get(session['user_id'])
    
    # Get user's watch history with video details
    watch_history = db.session.query(WatchHistory, Video).join(Video).filter(
        WatchHistory.user_id == user.id
    ).order_by(WatchHistory.watched_at.desc()).limit(20).all()
    
    # Get user's transaction history
    transactions = Transaction.query.filter_by(user_id=user.id).order_by(
        Transaction.created_at.desc()
    ).limit(20).all()
    
    # Calculate earnings by type
    earnings_by_type = db.session.query(
        Transaction.transaction_type,
        db.func.sum(Transaction.amount).label('total')
    ).filter_by(user_id=user.id).group_by(Transaction.transaction_type).all()
    
    earnings_dict = {t[0]: t[1] for t in earnings_by_type}
    
    return render_template('profile.html',
                         user=user,
                         watch_history=watch_history,
                         transactions=transactions,
                         earnings_dict=earnings_dict)

@app.route('/leaderboard')
def leaderboard():
    # Top earners
    top_earners = User.query.filter_by(is_active=True).order_by(
        User.total_earned.desc()
    ).limit(10).all()
    
    # Most active watchers
    most_active = User.query.filter_by(is_active=True).order_by(
        User.videos_watched.desc()
    ).limit(10).all()
    
    return render_template('leaderboard.html',
                         top_earners=top_earners,
                         most_active=most_active)

@app.route('/api/user_stats')
@login_required
def api_user_stats():
    user = User.query.get(session['user_id'])
    return jsonify({
        'balance': user.balance,
        'total_earned': user.total_earned,
        'videos_watched': user.videos_watched,
        'ads_watched': user.ads_watched
    })

@app.route('/api/video_stats/<int:video_id>')
@login_required
def api_video_stats(video_id):
    video = Video.query.get_or_404(video_id)
    return jsonify({
        'views': video.views,
        'reward_amount': video.reward_amount,
        'requires_ad_unlock': video.requires_ad_unlock
    })

@app.errorhandler(404)
def not_found(error):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return render_template('500.html'), 500

if __name__ == '__main__':
    with app.app_context():
        init_db()
    app.run(debug=True)
