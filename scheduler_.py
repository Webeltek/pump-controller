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
    elif not enabled:
        # Check if pump is running (safety check)
        self._stop_pump_if_running(schedule_id)
    
    # Update the enabled state in memory FIRST (before checking)
    self.schedules[schedule_id]['enabled'] = enabled
    
    # If enabling, check if schedule should run NOW
    if enabled:
        logger.info(f"Schedule {schedule_id} enabled - Checking if it should run NOW")
        self._check_and_start_schedule(schedule_id)
    
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