# /home/willy/pump-controller/database.py
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import json

db = SQLAlchemy()

class WateringSchedule(db.Model):
    """Store watering schedules persistently"""
    __tablename__ = 'watering_schedules'
    
    id = db.Column(db.String(8), primary_key=True)
    hour = db.Column(db.Integer, nullable=False)
    minute = db.Column(db.Integer, nullable=False)
    duration_seconds = db.Column(db.Integer, nullable=False)
    days = db.Column(db.String(100), default='daily')
    enabled = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        days_data = self.days
        if days_data != 'daily' and days_data:
            try:
                days_data = json.loads(days_data)
            except:
                pass
        
        return {
            'id': self.id,
            'hour': self.hour,
            'minute': self.minute,
            'duration': self.duration_seconds,
            'days': days_data,
            'enabled': self.enabled
        }

class WateringEvent(db.Model):
    """Store watering history"""
    __tablename__ = 'watering_events'
    
    id = db.Column(db.Integer, primary_key=True)
    schedule_id = db.Column(db.String(8), nullable=True)
    duration_seconds = db.Column(db.Integer, nullable=False)
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default='completed')

def init_db(app):
    """Initialize database"""
    db.init_app(app)
    with app.app_context():
        db.create_all()
        print("Database tables created")