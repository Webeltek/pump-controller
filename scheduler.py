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
from webhook import push_immediate, push_update

logger = logging.getLogger(__name__)

class PumpScheduler:
    def __init__(self, pump_controller, app=None):
        self.pump = pump_controller
        self.app = app  # Store Flask app instance
        
        # Get system timezone
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
        self.running_schedule_id = None
        self.last_trigger_check = None
        logger.info(f"Scheduler initialized with timezone: {self.local_tz}")
    
    def load_schedules_from_db(self):
        """Load all enabled schedules from database on startup"""
        logger.info("="*50)
        logger.info("LOADING SCHEDULES FROM DATABASE")
        logger.info("="*50)
        
        # Need app context to access database
        if not self.app:
            logger.warning("No app context available, cannot load schedules from DB")
            return 0
        
        try:
            with self.app.app_context():
                db_schedules = WateringSchedule.query.all()
                logger.info(f"Database query returned {len(db_schedules)} schedules")
                
                if len(db_schedules) == 0:
                    logger.info("No schedules found in database")
                    return 0
                
                for db_schedule in db_schedules:
                    logger.info(f"Found schedule in DB: ID={db_schedule.id}, hour={db_schedule.hour}, minute={db_schedule.minute}, duration={db_schedule.duration_seconds}, enabled={db_schedule.enabled}")
                    
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
                    
                    # Add to scheduler
                    self._add_schedule_from_db(
                        schedule_id=db_schedule.id,
                        hour=db_schedule.hour,
                        minute=db_schedule.minute,
                        duration_seconds=db_schedule.duration_seconds,
                        days=days,
                        enabled=db_schedule.enabled
                    )
                
                logger.info(f"Successfully loaded {len(db_schedules)} schedules from database")
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
                args=[duration_seconds, schedule_id],
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
        loaded_count = self.load_schedules_from_db()
        logger.info(f"Scheduler started with {loaded_count} schedules loaded from database")
    
    def add_schedule(self, hour, minute, duration_seconds, days=None):
        """Add watering schedule and save to database"""
        schedule_id = str(uuid.uuid4())[:8]
        
        logger.info("="*50)
        logger.info(f"ADDING NEW SCHEDULE: {schedule_id}")
        logger.info(f"  Time: {hour:02d}:{minute:02d}")
        logger.info(f"  Duration: {duration_seconds} seconds")
        logger.info(f"  Days: {days}")
        logger.info("="*50)
        
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
            args=[duration_seconds, schedule_id],
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
        
        # Save to database - need app context
        if self.app:
            try:
                with self.app.app_context():
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
                    logger.info(f"Schedule {schedule_id} SUCCESSFULLY saved to database")
            except Exception as e:
                logger.error(f"Error saving schedule to DB: {e}")
                db.session.rollback()
        else:
            logger.warning("No app context, schedule not saved to database")
        
        # Send webhook - schedule added
        schedules = self.get_schedules()
        next_run = self.get_next_run_time()
        push_immediate('schedule_added', {
            'schedule_id': schedule_id,
            'schedules': schedules,
            'next_run': next_run
        })
        
        logger.info(f"Schedule {schedule_id}: Water at {hour:02d}:{minute:02d} for {duration_seconds}s")
        return schedule_id
    
    def _watering_job(self, duration_seconds, schedule_id):
        """Run a scheduled watering job using LOW (on) / HIGH (off) states"""
        logger.info(f"SCHEDULE START: Watering for {duration_seconds} seconds (Schedule: {schedule_id})")
        
        # Track which schedule is running
        self.running_schedule_id = schedule_id
        
        try:
            # Start filling (pump on)
            self.pump.set_low()
            logger.info(f"Pump started - Water level set to LOW")
            
            # Send webhook - schedule started
            push_immediate('schedule_started', {
                'schedule_id': schedule_id,
                'duration': duration_seconds,
                'running': True
            })
            
            # Run for specified duration
            time.sleep(duration_seconds)
            
            # Stop filling (pump off)
            self.pump.set_high()
            logger.info(f"SCHEDULE COMPLETE: Watering finished - Pump stopped")
            
            # Send webhook - schedule completed
            schedules = self.get_schedules()
            next_run = self.get_next_run_time()
            push_immediate('schedule_completed', {
                'schedule_id': schedule_id,
                'duration': duration_seconds,
                'running': False,
                'schedules': schedules,
                'next_run': next_run
            })
            
        except Exception as e:
            logger.error(f"Error during watering job {schedule_id}: {e}")
            # Ensure pump stops on error
            self.pump.set_high()
            logger.info(f"Pump stopped due to error")
            
            # Send webhook - error
            push_immediate('error', {
                'schedule_id': schedule_id,
                'error': str(e)
            })
        finally:
            # Clear running schedule
            self.running_schedule_id = None
    
    def _stop_pump_if_running(self, schedule_id=None):
        """Emergency stop pump if it's running"""
        # Check if the pump is currently running (level is LOW)
        status = self.pump.get_status()
        is_pump_running = status.get('pump_should_run', False)
        
        if is_pump_running:
            logger.warning(f"STOPPING PUMP because schedule {schedule_id} is being removed/disabled")
            self.pump.set_high()
            self.running_schedule_id = None
            logger.info("Pump stopped - Level set to HIGH")
            
            # Send webhook - pump stopped
            push_immediate('pump_status', {
                'running': False,
                'level': 'HIGH',
                'level_state': 'HIGH',
                'source': 'stop_pump_if_running',
                'schedule_id': schedule_id
            })
            return True
        else:
            logger.info(f"No pump running to stop (schedule {schedule_id})")
            return False
    
    def _check_and_start_schedule(self, schedule_id):
        """Check if schedule should be running NOW and start if needed"""
        if schedule_id not in self.schedules:
            logger.warning(f"Schedule {schedule_id} not found")
            return False
        
        schedule = self.schedules[schedule_id]
        if not schedule['enabled']:
            logger.info(f"Schedule {schedule_id} is disabled, not starting")
            return False
        
        # Check if pump is already running
        status = self.pump.get_status()
        if status.get('pump_should_run', False):
            logger.info(f"Pump already running, not starting schedule {schedule_id}")
            return False
        
        # Get current time in local timezone
        now = datetime.now(self.local_tz)
        current_hour = now.hour
        current_minute = now.minute
        
        # Check if current time matches schedule time
        schedule_hour = schedule['hour']
        schedule_minute = schedule['minute']
        
        # Check if we should run (time matches and not already running)
        if current_hour == schedule_hour and current_minute == schedule_minute:
            logger.info(f"Schedule {schedule_id} should be running NOW! Starting pump...")
            duration = schedule['duration']
            
            # Start the pump in a background thread so it doesn't block
            import threading
            def start_schedule_immediately():
                logger.info(f"Starting immediate watering for schedule {schedule_id} ({duration}s)")
                self._watering_job(duration, schedule_id)
            
            thread = threading.Thread(target=start_schedule_immediately, daemon=True)
            thread.start()
            return True
        else:
            logger.info(f"Schedule {schedule_id} not due yet ({current_hour:02d}:{current_minute:02d} vs {schedule_hour:02d}:{schedule_minute:02d})")
            return False
    
    def remove_schedule(self, schedule_id):
        """Remove schedule from memory and database - ALWAYS stop pump if running"""
        logger.info(f"Removing schedule: {schedule_id}")
        
        # CRITICAL SAFETY: Stop pump if this schedule is running
        if self.running_schedule_id == schedule_id:
            logger.warning(f"REMOVING ACTIVE SCHEDULE {schedule_id} - Stopping pump NOW!")
            self.pump.set_high()
            self.running_schedule_id = None
            logger.info("Pump stopped immediately - Level set to HIGH")
            
            # Send webhook - emergency stop from removal
            push_immediate('pump_status', {
                'running': False,
                'level': 'HIGH',
                'level_state': 'HIGH',
                'source': 'schedule_removed',
                'schedule_id': schedule_id
            })
        else:
            # Check if pump is running anyway (safety check)
            self._stop_pump_if_running(schedule_id)
        
        try:
            self.scheduler.remove_job(schedule_id)
            logger.info(f"  Removed from scheduler")
        except JobLookupError:
            logger.warning(f"  Job not found in scheduler")
        
        if schedule_id in self.schedules:
            del self.schedules[schedule_id]
            logger.info(f"  Removed from memory")
        
        # Remove from database - need app context
        if self.app:
            try:
                with self.app.app_context():
                    schedule = WateringSchedule.query.get(schedule_id)
                    if schedule:
                        db.session.delete(schedule)
                        db.session.commit()
                        logger.info(f"Schedule {schedule_id} deleted from database")
                    else:
                        logger.warning(f"  Schedule not found in database")
            except Exception as e:
                logger.error(f"Error deleting schedule from DB: {e}")
                db.session.rollback()
        
        # Send webhook - schedule deleted
        schedules = self.get_schedules()
        next_run = self.get_next_run_time()
        push_immediate('schedule_deleted', {
            'schedule_id': schedule_id,
            'schedules': schedules,
            'next_run': next_run
        })
        
        logger.info(f"Schedule {schedule_id} removed")
    
    def toggle_schedule(self, schedule_id, enabled):
        """Enable or disable a schedule (sync with database)"""
        if schedule_id not in self.schedules:
            logger.warning(f"Schedule {schedule_id} not found")
            return
        
        logger.info(f"Toggling schedule {schedule_id} to enabled={enabled}")
        
        # If disabling and this schedule is running, stop pump immediately
        if not enabled and self.running_schedule_id == schedule_id:
            logger.warning(f"DISABLING ACTIVE SCHEDULE {schedule_id} - Stopping pump NOW!")
            self.pump.set_high()
            self.running_schedule_id = None
            logger.info("Pump stopped immediately - Level set to HIGH")
            
            # Send webhook - pump stopped from disable
            push_immediate('pump_status', {
                'running': False,
                'level': 'HIGH',
                'level_state': 'HIGH',
                'source': 'schedule_disabled',
                'schedule_id': schedule_id
            })
        elif not enabled:
            # Check if pump is running (safety check)
            self._stop_pump_if_running(schedule_id)
        
        # Update the enabled state in memory FIRST (before checking)
        self.schedules[schedule_id]['enabled'] = enabled
        
        # If enabling, check if schedule should run NOW
        if enabled:
            logger.info(f"Schedule {schedule_id} enabled - Checking if it should run NOW")
            self._check_and_start_schedule(schedule_id)
            
            # Send webhook - schedule enabled
            schedules = self.get_schedules()
            next_run = self.get_next_run_time()
            push_immediate('schedule_enabled', {
                'schedule_id': schedule_id,
                'enabled': True,
                'schedules': schedules,
                'next_run': next_run
            })
        else:
            # Send webhook - schedule disabled
            schedules = self.get_schedules()
            next_run = self.get_next_run_time()
            push_immediate('schedule_disabled', {
                'schedule_id': schedule_id,
                'enabled': False,
                'schedules': schedules,
                'next_run': next_run
            })
        
        # Now handle the scheduler job (pause/resume)
        if enabled:
            self.scheduler.resume_job(schedule_id)
            logger.info(f"  Job resumed")
        else:
            self.scheduler.pause_job(schedule_id)
            logger.info(f"  Job paused")
        
        # Update database
        if self.app:
            try:
                with self.app.app_context():
                    schedule = WateringSchedule.query.get(schedule_id)
                    if schedule:
                        schedule.enabled = enabled
                        db.session.commit()
                        logger.info(f"Schedule {schedule_id} {'enabled' if enabled else 'disabled'} in database")
                    else:
                        logger.warning(f"  Schedule not found in database")
            except Exception as e:
                logger.error(f"Error updating schedule in DB: {e}")
                db.session.rollback()
        
        logger.info(f"Schedule {schedule_id} {'enabled' if enabled else 'disabled'}")
    
    def emergency_stop_all(self):
        """Emergency stop - stop any running pump"""
        logger.warning("EMERGENCY STOP ALL - Stopping pump now!")
        self.pump.set_high()
        self.running_schedule_id = None
        logger.info("Emergency stop complete - Pump stopped")
        
        # Send webhook - emergency stop
        push_immediate('pump_status', {
            'running': False,
            'level': 'HIGH',
            'level_state': 'HIGH',
            'source': 'emergency_stop_all'
        })
    
    def get_schedules(self):
        """Get all schedules"""
        schedules_info = {}
        for schedule_id, info in self.schedules.items():
            try:
                job = self.scheduler.get_job(schedule_id)
                if job and job.next_run_time:
                    local_next_run = job.next_run_time.astimezone(self.local_tz)
                    schedules_info[schedule_id] = {
                        **info,
                        'next_run_time': local_next_run.strftime('%Y-%m-%d %H:%M:%S'),
                        'is_running': schedule_id == self.running_schedule_id
                    }
                else:
                    schedules_info[schedule_id] = {
                        **info, 
                        'next_run_time': None,
                        'is_running': schedule_id == self.running_schedule_id
                    }
            except:
                schedules_info[schedule_id] = {
                    **info, 
                    'next_run_time': None,
                    'is_running': schedule_id == self.running_schedule_id
                }
        
        return schedules_info
    
    def get_next_run_time(self):
        """Get next run time"""
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
        """Shutdown scheduler and stop pump"""
        self.emergency_stop_all()
        self.scheduler.shutdown()
        logger.info("Scheduler shutdown")