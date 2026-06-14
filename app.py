from flask import Flask, render_template, jsonify, request
from pump_controller import PumpController
from scheduler import PumpScheduler
from database import db, init_db
import logging
import platform
import os
from datetime import datetime

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
pump = PumpController(low_level_pin=18, high_level_pin=23)
scheduler = PumpScheduler(pump)

# Create tables
with app.app_context():
    db.create_all()
    logger.info("Database tables ready")

def get_system_info():
    """Get system information for dashboard"""
    try:
        cpu_temp = None
        if os.path.exists('/sys/class/thermal/thermal_zone0/temp'):
            with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
                cpu_temp = round(float(f.read()) / 1000.0, 1)
        
        return {
            'hostname': platform.node(),
            'cpu_temp': cpu_temp if cpu_temp else 'N/A',
            'ram_usage': 'N/A'
        }
    except Exception as e:
        logger.error(f"Error getting system info: {e}")
        return {
            'hostname': platform.node(),
            'cpu_temp': 'N/A',
            'ram_usage': 'N/A'
        }

@app.route('/')
def index():
    """Main dashboard page"""
    try:
        schedules = scheduler.get_schedules()
        
        template_data = {
            'title': 'Smart Water Pump Controller',
            'description': 'Level Sensor Simulation for INTIEL Panel',
            'system_info': get_system_info(),
            'pump_status': pump.get_status(),
            'pump_pin': f"Low: {pump.low_pin}, High: {pump.high_pin}",
            'schedules': schedules,
            'next_run': scheduler.get_next_run_time(),
            'stats': {'total_watering_today': 0, 'total_watering_week': 0},
            'update_interval': 2,
            'auto_refresh': True,
            'theme': {
                'primary_color': '#667eea',
                'secondary_color': '#764ba2'
            },
            'default_duration': 30,
            'default_time': '08:00'
        }
        
        return render_template('index.html', **template_data)
    
    except Exception as e:
        logger.error(f"Error rendering index: {e}")
        return f"Error: {e}", 500

@app.route('/api/status')
def get_status():
    """API: Get pump status"""
    try:
        return jsonify({
            'success': True,
            'pump_status': pump.get_status(),
            'schedules': scheduler.get_schedules(),
            'next_run': scheduler.get_next_run_time()
        })
    except Exception as e:
        logger.error(f"Status API error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/pump/on', methods=['POST'])
def pump_on():
    try:
        pump.set_empty()
        logger.info("Pump turned ON via API")
        return jsonify({'success': True, 'status': 'on', 'message': 'Pump turned on'})
    except Exception as e:
        logger.error(f"Pump on error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/pump/off', methods=['POST'])
def pump_off():
    try:
        pump.set_high()
        logger.info("Pump turned OFF via API")
        return jsonify({'success': True, 'status': 'off', 'message': 'Pump turned off'})
    except Exception as e:
        logger.error(f"Pump off error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/schedule', methods=['POST'])
def add_schedule():
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
    try:
        scheduler.remove_schedule(schedule_id)
        return jsonify({'success': True, 'message': 'Schedule deleted'})
    except Exception as e:
        logger.error(f"Remove schedule error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/schedule/<schedule_id>/toggle', methods=['POST'])
def toggle_schedule(schedule_id):
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

if __name__ == '__main__':
    try:
        scheduler.start()
        logger.info("Scheduler started successfully")
        logger.info("Starting Flask server on http://0.0.0.0:5000")
        logger.info(f"Pump Controller: Low GPIO {pump.low_pin}, High GPIO {pump.high_pin}")
        app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        scheduler.shutdown()
        pump.cleanup()