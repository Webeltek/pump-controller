from flask import Flask, render_template, jsonify, request
from pump_controller import PumpController
from scheduler import PumpScheduler
from database import db, init_db
from webhook import init_webhook, push_update, push_immediate
from command_poller import init_command_poller, start_command_poller, stop_command_poller
import logging
import platform
import os
from datetime import datetime
import threading
import time

# Try to import psutil
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    print("Warning: psutil not installed. System info will be limited.")

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)

# Database configuration (use PostgreSQL or SQLite for testing)
# For SQLite (no extra setup needed):
# app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///pump_controller.db'
# For PostgreSQL (uncomment if you have PostgreSQL):
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'postgresql://willy:your_password@localhost:5432/pump_controller')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', 'your_secret_key')

# Initialize database
db.init_app(app)

# Initialize controllers
pump = PumpController(
    low_level_pin=18,
    high_level_pin=23,
    common_pin=None
)
scheduler = PumpScheduler(pump, app=app)

# ===== INITIALIZE WEBHOOK =====
EXPRESS_URL = os.environ.get('EXPRESS_URL', 'https://your-express-app.com')
init_webhook(EXPRESS_URL, app=app)
logger.info(f"Webhook initialized with URL: {EXPRESS_URL}")

# ===== INITIALIZE COMMAND POLLER =====
POLL_INTERVAL = int(os.environ.get('POLL_INTERVAL', 10))
command_poller = init_command_poller(EXPRESS_URL, POLL_INTERVAL)
command_poller.register_handlers(pump, scheduler)
logger.info(f"Command poller initialized with interval: {POLL_INTERVAL}s")

# Configuration
app.config.update(
    UPDATE_INTERVAL=2,
    AUTO_REFRESH=True,
    THEME_PRIMARY_COLOR='#667eea',
    THEME_SECONDARY_COLOR='#764ba2',
    DEFAULT_DURATION=30,
    DEFAULT_TIME='08:00'
)

def get_system_info():
    """Get system information for dashboard"""
    try:
        cpu_temp = None
        if os.path.exists('/sys/class/thermal/thermal_zone0/temp'):
            with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
                cpu_temp = round(float(f.read()) / 1000.0, 1)
        
        ram_usage = 'N/A'
        if PSUTIL_AVAILABLE:
            memory = psutil.virtual_memory()
            ram_usage = memory.percent
        
        return {
            'hostname': platform.node(),
            'cpu_temp': cpu_temp if cpu_temp else 'N/A',
            'ram_usage': ram_usage,
            'platform': platform.platform()
        }
    except Exception as e:
        logger.error(f"Error getting system info: {e}")
        return {
            'hostname': platform.node(),
            'cpu_temp': 'N/A',
            'ram_usage': 'N/A',
            'platform': platform.platform()
        }

@app.route('/')
def index():
    """Main dashboard page"""
    try:
        schedules = scheduler.get_schedules()
        
        # Add next run time to each schedule
        for schedule_id in schedules:
            try:
                job = scheduler.scheduler.get_job(schedule_id)
                if job and job.next_run_time:
                    schedules[schedule_id]['next_run_time'] = job.next_run_time.strftime('%Y-%m-%d %H:%M:%S')
            except:
                pass
        
        # Get pump status to determine if it's running
        pump_status = pump.get_status()
        is_running = pump_status.get('pump_should_run', False)
        
        template_data = {
            'title': 'Smart Water Pump Controller',
            'description': 'Level Sensor Simulation for INTIEL Panel',
            'system_info': get_system_info(),
            'pump_status': {'running': is_running},  # This is what the template expects
            'pump_details': pump_status,  # Full status for debugging
            'pump_pin': f"Low: {pump.low_pin}, High: {pump.high_pin}",
            'schedules': schedules,
            'next_run': scheduler.get_next_run_time(),
            'stats': {'total_watering_today': 0, 'total_watering_week': 0},
            'update_interval': app.config['UPDATE_INTERVAL'],
            'auto_refresh': app.config['AUTO_REFRESH'],
            'theme': {
                'primary_color': app.config['THEME_PRIMARY_COLOR'],
                'secondary_color': app.config['THEME_SECONDARY_COLOR']
            },
            'default_duration': app.config['DEFAULT_DURATION'],
            'default_time': app.config['DEFAULT_TIME']
        }
        
        return render_template('index.html', **template_data)
    
    except Exception as e:
        logger.error(f"Error rendering index: {e}")
        return f"Error: {e}", 500

@app.route('/api/status')
def get_status():
    """API: Get pump status"""
    try:
        pump_status = pump.get_status()
        is_running = pump_status.get('pump_should_run', False)
        
        return jsonify({
            'success': True,
            'pump_status': {
                'running': is_running,
                'water_level': pump_status.get('water_level', 'Unknown'),
                'level_state': pump_status.get('level_state', 'Unknown'),
                'low_relay_closed': pump_status.get('low_relay_closed', False),
                'high_relay_closed': pump_status.get('high_relay_closed', False)
            },
            'schedules': scheduler.get_schedules(),
            'next_run': scheduler.get_next_run_time()
        })
    except Exception as e:
        logger.error(f"Status API error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/pump/on', methods=['POST'])
def pump_on():
    """Turn pump on (set LOW level)"""
    try:
        # Represent manual ON as LOW level
        pump.set_low()
        logger.info("Pump turned ON via API - Level set to LOW")
        
        # Verify the state
        status = pump.get_status()
        logger.info(f"Pump status after ON: {status}")
        
        return jsonify({
            'success': True, 
            'status': 'on', 
            'message': 'Pump turned on - Level set to LOW',
            'water_level': status.get('water_level'),
            'pump_running': status.get('pump_should_run')
        })
    except Exception as e:
        logger.error(f"Pump on error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/pump/off', methods=['POST'])
def pump_off():
    """Turn pump off (set high level)"""
    try:
        pump.set_high()  # High level = pump stops
        logger.info("Pump turned OFF via API - Level set to HIGH")
        
        # Verify the state
        status = pump.get_status()
        logger.info(f"Pump status after OFF: {status}")
        
        return jsonify({
            'success': True, 
            'status': 'off', 
            'message': 'Pump turned off - Level set to HIGH',
            'water_level': status.get('water_level'),
            'pump_running': status.get('pump_should_run')
        })
    except Exception as e:
        logger.error(f"Pump off error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/pump/status', methods=['GET'])
def pump_status():
    """Get current pump status"""
    try:
        status = pump.get_status()
        return jsonify({
            'success': True,
            'running': status.get('pump_should_run', False),
            'water_level': status.get('water_level'),
            'level_state': status.get('level_state'),
            'low_relay': 'CLOSED' if status.get('low_relay_closed') else 'OPEN',
            'high_relay': 'CLOSED' if status.get('high_relay_closed') else 'OPEN'
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/schedule', methods=['POST'])
def add_schedule():
    """API: Add schedule"""
    try:
        if not request.is_json:
            return jsonify({'success': False, 'error': 'Content-Type must be application/json'}), 400
            
        data = request.get_json()
        hour = data.get('hour')
        minute = data.get('minute')
        duration = data.get('duration')
        days = data.get('days')
        
        if hour is None or minute is None or duration is None:
            return jsonify({'success': False, 'error': 'Missing required fields'}), 400
        
        schedule_id = scheduler.add_schedule(hour, minute, duration, days)
        return jsonify({'success': True, 'schedule_id': schedule_id})
    except Exception as e:
        logger.error(f"Add schedule error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/schedule/<schedule_id>', methods=['DELETE'])
def remove_schedule(schedule_id):
    """API: Remove schedule"""
    try:
        scheduler.remove_schedule(schedule_id)
        return jsonify({'success': True, 'message': 'Schedule deleted'})
    except Exception as e:
        logger.error(f"Remove schedule error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/schedule/<schedule_id>/toggle', methods=['POST'])
def toggle_schedule(schedule_id):
    """API: Toggle schedule"""
    try:
        if not request.is_json:
            return jsonify({'success': False, 'error': 'Content-Type must be application/json'}), 400
            
        data = request.get_json()
        enabled = data.get('enabled')
        
        if enabled is None:
            return jsonify({'success': False, 'error': 'Missing enabled field'}), 400
            
        scheduler.toggle_schedule(schedule_id, enabled)
        return jsonify({'success': True, 'message': f'Schedule {"enabled" if enabled else "disabled"}'})
    except Exception as e:
        logger.error(f"Toggle schedule error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# Manual level control endpoints
@app.route('/api/level/empty', methods=['POST'])
def set_empty():
    # Deprecated: treat EMPTY as LOW for compatibility
    try:
        pump.set_low()
        return jsonify({'success': True, 'level': 'LOW', 'pump': 'RUNNING'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/level/low', methods=['POST'])
def set_low():
    try:
        pump.set_low()
        return jsonify({'success': True, 'level': 'LOW', 'pump': 'RUNNING'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/level/high', methods=['POST'])
def set_high():
    try:
        pump.set_high()
        return jsonify({'success': True, 'level': 'HIGH', 'pump': 'STOPPED'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/pump/emergency', methods=['POST'])
def emergency_stop():
    """Emergency stop - immediately stop pump"""
    try:
        scheduler.emergency_stop_all()
        logger.warning("EMERGENCY STOP triggered via API")
        
        # Send immediate webhook
        push_immediate('pump_status', {
            'running': False,
            'level': 'HIGH',
            'level_state': 'HIGH',
            'source': 'api_emergency_stop'
        })
        
        return jsonify({
            'success': True, 
            'message': 'Emergency stop activated - Pump stopped'
        })
    except Exception as e:
        logger.error(f"Emergency stop error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/test/water', methods=['POST'])
def test_water():
    try:
        data = request.get_json(silent=True) or {}
        duration = int(data.get('duration', 10))

        def run_temp_cycle(sec):
            logger.info(f"Test watering: starting for {sec} seconds")
            try:
                # Use LOW to represent pump running for test watering
                pump.set_low()
                # Push webhook for test start
                push_immediate('pump_status', {
                    'running': True,
                    'level': 'LOW',
                    'level_state': 'LOW',
                    'source': 'test_watering'
                })
                # sleep locally so we don't block the Flask worker
                time.sleep(sec)
                pump.set_high()
                # Push webhook for test stop
                push_immediate('pump_status', {
                    'running': False,
                    'level': 'HIGH',
                    'level_state': 'HIGH',
                    'source': 'test_watering'
                })
                logger.info("Test watering: completed, pump stopped")
            except Exception as ee:
                logger.error(f"Error during test watering: {ee}")

        thread = threading.Thread(target=run_temp_cycle, args=(duration,), daemon=True)
        thread.start()

        return jsonify({'success': True, 'message': f'Test watering started for {duration} seconds'})
    except Exception as e:
        logger.error(f"Test water error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.errorhandler(404)
def not_found(error):
    return jsonify({'success': False, 'error': 'Endpoint not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'success': False, 'error': 'Internal server error'}), 500

if __name__ == '__main__':
    try:
        # Create tables
        with app.app_context():
            db.create_all()
            logger.info("Database tables ready")
        
        # Start the scheduler
        scheduler.start()
        logger.info("Scheduler started successfully")
        
        # Start the command poller
        start_command_poller()
        logger.info("Command poller started")
        
        logger.info("Starting Flask server on http://0.0.0.0:5000")
        logger.info("Pump Controller initialized with:")
        logger.info(f"  - Low Level Relay: GPIO {pump.low_pin}")
        logger.info(f"  - High Level Relay: GPIO {pump.high_pin}")
        
        # Log initial status
        initial_status = pump.get_status()
        logger.info(f"Initial pump status: {initial_status}")
        
        # Send initial status to Express via webhook
        push_immediate('full_status', {
            'pump': {
                'running': initial_status.get('pump_should_run', False),
                'water_level': initial_status.get('water_level', 'HIGH'),
                'level_state': initial_status.get('level_state', 'HIGH')
            },
            'schedules': scheduler.get_schedules(),
            'next_run': scheduler.get_next_run_time(),
            'system': get_system_info()
        })
        logger.info("Initial status sent to Express webhook")
        
        app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        stop_command_poller()
        scheduler.shutdown()
        pump.cleanup()