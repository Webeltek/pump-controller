from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.jobstores.base import JobLookupError
import logging
import uuid
from datetime import datetime
import pytz
import subprocess
import time
from database import db, WateringSchedule

logger = logging.getLogger(__name__)

class PumpScheduler:
    def __init__(self, pump_controller):
        self.pump = pump_controller
        
        # Get system timezone (YOUR EXISTING CODE - UNCHANGED)
        try:
            result = subprocess.run(['timedatectl', 'show', '--property=Timezone', '--value'], 
                                  capture_output=True, text=True)
            system_tz = result.stdout.strip()
            if system_tz:
                self.local_tz = pytz.timezone(system_tz)
            else:
                self.local_tz = pytz.UTC
        except:
            self.local_tz = pytz.UTC
            
        self.scheduler = BackgroundScheduler(timezone=self.local_tz)
        self.schedules = {}
        logger.info(f"Scheduler initialized with timezone: {self.local_tz}")
    
    def load_schedules_from_db(self):
        """Load all enabled schedules from database on startup"""
        try:
            db_schedules = WateringSchedule.query.all()
            
            for db_schedule in db_schedules:
                # Parse days
                days = db_schedule.days
                if days != 'daily' and days:
                    try:
                        import json
                        days = json.loads(days)
                    except:
                        days = None
                else:
                    days = None if days == 'daily' else days
                
                # Add to scheduler (skip saving to DB again - from_db flag)
                self._add_schedule_from_db(
                    schedule_id=db_schedule.id,
                    hour=db_schedule.hour,
                    minute=db_schedule.minute,
                    duration_seconds=db_schedule.duration_seconds,
                    days=days,
                    enabled=db_schedule.enabled
                )
            
            logger.info(f"Loaded {len(db_schedules)} schedules from database")
            return len(db_schedules)
        except Exception as e:
            logger.error(f"Error loading schedules from DB: {e}")
            return 0
    
    def _add_schedule_from_db(self, schedule_id, hour, minute, duration_seconds, days=None, enabled=True):
        """Internal method to add schedule from database (no double save)"""
        if days is None or days == 'daily':
            trigger = CronTrigger(hour=hour, minute=minute, timezone=self.local_tz)
            days_display = 'daily'
        else:
            trigger = CronTrigger(
                hour=hour, 
                minute=minute,
                day_of_week=','.join(map(str, days)),
                timezone=self.local_tz
            )
            days_display = days
        
        job = None
        if enabled:
            job = self.scheduler.add_job(
                func=self._watering_job,
                trigger=trigger,
                id=schedule_id,
                args=[duration_seconds],
                replace_existing=True
            )
        
        self.schedules[schedule_id] = {
            'hour': hour,
            'minute': minute,
            'duration': duration_seconds,
            'days': days_display,
            'enabled': enabled,
            'next_run_time': job.next_run_time if job else None
        }
        
        logger.info(f"Loaded schedule {schedule_id}: {hour:02d}:{minute:02d} for {duration_seconds}s (enabled={enabled})")
    
    def start(self):
        """Start the background scheduler and load schedules from database"""
        self.scheduler.start()
        self.load_schedules_from_db()  # Load persistent schedules on startup
        logger.info("Scheduler started with persistent database storage")
    
    def add_schedule(self, hour, minute, duration_seconds, days=None):
        """Add watering schedule and save to database"""
        schedule_id = str(uuid.uuid4())[:8]
        
        if days is None or days == 'daily':
            trigger = CronTrigger(hour=hour, minute=minute, timezone=self.local_tz)
            days_display = 'daily'
        else:
            trigger = CronTrigger(hour=hour, minute=minute, 
                                day_of_week=','.join(map(str, days)),
                                timezone=self.local_tz)
            days_display = days
        
        job = self.scheduler.add_job(
            func=self._watering_job,
            trigger=trigger,
            id=schedule_id,
            args=[duration_seconds],
            replace_existing=True
        )
        
        self.schedules[schedule_id] = {
            'hour': hour,
            'minute': minute,
            'duration': duration_seconds,
            'days': days_display,
            'enabled': True,
            'next_run_time': job.next_run_time
        }
        
        # Save to database
        try:
            days_for_db = days_display if days_display == 'daily' else __import__('json').dumps(days_display)
            new_schedule = WateringSchedule(
                id=schedule_id,
                hour=hour,
                minute=minute,
                duration_seconds=duration_seconds,
                days=days_for_db,
                enabled=True
            )
            db.session.add(new_schedule)
            db.session.commit()
            logger.info(f"Schedule {schedule_id} saved to database")
        except Exception as e:
            logger.error(f"Error saving schedule to DB: {e}")
            db.session.rollback()
        
        logger.info(f"Schedule {schedule_id}: Water at {hour:02d}:{minute:02d} for {duration_seconds}s")
        return schedule_id
    
    def _watering_job(self, duration_seconds):
        """Simulate filling tank for scheduled watering"""
        logger.info(f"SCHEDULE START: Watering for {duration_seconds} seconds")
        
        # Start filling (pump on)
        self.pump.start_filling()
        logger.info(f"Pump started - Water level set to FILLING")
        
        # Run for specified duration
        time.sleep(duration_seconds)
        
        # Stop filling (pump off)
        self.pump.set_high()
        logger.info(f"SCHEDULE COMPLETE: Watering finished - Pump stopped")
    
    def remove_schedule(self, schedule_id):
        """Remove schedule from memory and database"""
        try:
            self.scheduler.remove_job(schedule_id)
        except JobLookupError:
            pass
        
        if schedule_id in self.schedules:
            del self.schedules[schedule_id]
        
        # Remove from database
        try:
            schedule = WateringSchedule.query.get(schedule_id)
            if schedule:
                db.session.delete(schedule)
                db.session.commit()
                logger.info(f"Schedule {schedule_id} deleted from database")
        except Exception as e:
            logger.error(f"Error deleting schedule from DB: {e}")
            db.session.rollback()
        
        logger.info(f"Schedule {schedule_id} removed")
    
    def toggle_schedule(self, schedule_id, enabled):
        """Enable or disable a schedule (sync with database)"""
        if schedule_id not in self.schedules:
            logger.warning(f"Schedule {schedule_id} not found")
            return
        
        if enabled:
            self.scheduler.resume_job(schedule_id)
        else:
            self.scheduler.pause_job(schedule_id)
        
        self.schedules[schedule_id]['enabled'] = enabled
        
        # Update database
        try:
            schedule = WateringSchedule.query.get(schedule_id)
            if schedule:
                schedule.enabled = enabled
                db.session.commit()
                logger.info(f"Schedule {schedule_id} {'enabled' if enabled else 'disabled'} in database")
        except Exception as e:
            logger.error(f"Error updating schedule in DB: {e}")
            db.session.rollback()
        
        logger.info(f"Schedule {schedule_id} {'enabled' if enabled else 'disabled'}")
    
    def get_schedules(self):
        """Get all schedules (YOUR EXISTING CODE - UNCHANGED)"""
        schedules_info = {}
        for schedule_id, info in self.schedules.items():
            try:
                job = self.scheduler.get_job(schedule_id)
                if job and job.next_run_time:
                    local_next_run = job.next_run_time.astimezone(self.local_tz)
                    schedules_info[schedule_id] = {
                        **info,
                        'next_run_time': local_next_run.strftime('%Y-%m-%d %H:%M:%S')
                    }
                else:
                    schedules_info[schedule_id] = {**info, 'next_run_time': None}
            except:
                schedules_info[schedule_id] = {**info, 'next_run_time': None}
        
        return schedules_info
    
    def get_next_run_time(self):
        """Get next run time (YOUR EXISTING CODE - UNCHANGED)"""
        jobs = self.scheduler.get_jobs()
        if jobs:
            enabled_jobs = [job for job in jobs if job.id in self.schedules and self.schedules[job.id]['enabled']]
            if enabled_jobs:
                next_run = min((job.next_run_time for job in enabled_jobs if job.next_run_time), default=None)
                if next_run:
                    local_next_run = next_run.astimezone(self.local_tz)
                    return local_next_run.strftime('%Y-%m-%d %H:%M:%S')
        return None
    
    def shutdown(self):
        self.scheduler.shutdown()
        logger.info("Scheduler shutdown")