# command_poller.py - Add to your Flask project
import requests
import threading
import time
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class CommandPoller:
    """
    Polls Express server for pending commands
    """
    def __init__(self, express_url, poll_interval=10):
        self.express_url = express_url.rstrip('/')
        self.poll_interval = poll_interval
        self.running = False
        self.thread = None
        self.pump_controller = None
        self.scheduler = None
        self.command_handlers = {}
        
        logger.info(f"Command poller initialized with URL: {express_url}")
    
    def register_handlers(self, pump_controller, scheduler):
        """Register pump and scheduler for command execution"""
        self.pump_controller = pump_controller
        self.scheduler = scheduler
        
        # Register command handlers
        self.command_handlers = {
            'pump_on': self._handle_pump_on,
            'pump_off': self._handle_pump_off,
            'emergency_stop': self._handle_emergency_stop,
            'add_schedule': self._handle_add_schedule,
            'delete_schedule': self._handle_delete_schedule,
            'toggle_schedule': self._handle_toggle_schedule,
            'get_status': self._handle_get_status
        }
    
    def start(self):
        """Start the poller thread"""
        if self.running:
            return
        
        self.running = True
        self.thread = threading.Thread(target=self._poll_loop, daemon=True)
        self.thread.start()
        logger.info(f"Command poller started (interval: {self.poll_interval}s)")
    
    def stop(self):
        """Stop the poller"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("Command poller stopped")
    
    def _poll_loop(self):
        """Main polling loop"""
        while self.running:
            try:
                self._poll_for_commands()
            except Exception as e:
                logger.error(f"Polling error: {e}")
            
            time.sleep(self.poll_interval)
    
    def _poll_for_commands(self):
        """Poll Express for pending commands"""
        try:
            response = requests.get(
                f"{self.express_url}/commands/pending",
                timeout=5,
                headers={'X-Device-ID': 'pump-controller-001'}
            )
            
            if response.status_code == 200:
                commands = response.json().get('commands', [])
                if commands:
                    logger.info(f"Received {len(commands)} command(s)")
                    for command in commands:
                        self._execute_command(command)
            elif response.status_code == 204:
                # No pending commands
                pass
            else:
                logger.warning(f"Poll failed: {response.status_code}")
                
        except requests.exceptions.Timeout:
            logger.debug("Poll timeout - no commands pending")
        except requests.exceptions.RequestException as e:
            logger.error(f"Poll request error: {e}")
    
    def _execute_command(self, command):
        """Execute a command from Express"""
        cmd_type = command.get('type')
        cmd_id = command.get('id')
        data = command.get('data', {})
        
        logger.info(f"Executing command: {cmd_type} (id: {cmd_id})")
        
        handler = self.command_handlers.get(cmd_type)
        if handler:
            try:
                result = handler(data)
                self._report_command_result(cmd_id, True, result)
            except Exception as e:
                logger.error(f"Command execution failed: {e}")
                self._report_command_result(cmd_id, False, str(e))
        else:
            logger.warning(f"Unknown command type: {cmd_type}")
            self._report_command_result(cmd_id, False, f"Unknown command: {cmd_type}")
    
    def _report_command_result(self, command_id, success, result):
        """Report command result back to Express"""
        try:
            response = requests.post(
                f"{self.express_url}/commands/result",
                json={
                    'id': command_id,
                    'success': success,
                    'result': result,
                    'timestamp': datetime.utcnow().isoformat()
                },
                timeout=5,
                headers={'X-Device-ID': 'pump-controller-001'}
            )
            if response.status_code == 200:
                logger.info(f"Command result reported: {command_id} -> {'OK' if success else 'FAIL'}")
            else:
                logger.warning(f"Failed to report command result: {response.status_code}")
        except Exception as e:
            logger.error(f"Error reporting command result: {e}")
    
    # ===== Command Handlers =====
    
    def _handle_pump_on(self, data):
        """Handle pump on command"""
        self.pump_controller.set_low()
        return {'status': 'on', 'level': 'LOW'}
    
    def _handle_pump_off(self, data):
        """Handle pump off command"""
        self.pump_controller.set_high()
        return {'status': 'off', 'level': 'HIGH'}
    
    def _handle_emergency_stop(self, data):
        """Handle emergency stop"""
        if self.scheduler:
            self.scheduler.emergency_stop_all()
        return {'status': 'emergency_stop', 'message': 'Pump stopped'}
    
    def _handle_add_schedule(self, data):
        """Handle add schedule command"""
        if not self.scheduler:
            raise Exception("Scheduler not available")
        
        schedule_id = self.scheduler.add_schedule(
            hour=data['hour'],
            minute=data['minute'],
            duration_seconds=data['duration'],
            days=data.get('days')
        )
        return {'schedule_id': schedule_id}
    
    def _handle_delete_schedule(self, data):
        """Handle delete schedule command"""
        if not self.scheduler:
            raise Exception("Scheduler not available")
        
        self.scheduler.remove_schedule(data['schedule_id'])
        return {'deleted': data['schedule_id']}
    
    def _handle_toggle_schedule(self, data):
        """Handle toggle schedule command"""
        if not self.scheduler:
            raise Exception("Scheduler not available")
        
        self.scheduler.toggle_schedule(data['schedule_id'], data['enabled'])
        return {'schedule_id': data['schedule_id'], 'enabled': data['enabled']}
    
    def _handle_get_status(self, data):
        """Handle get status command (from command queue)"""
        return {'status': 'pong', 'time': datetime.utcnow().isoformat()}

# Global poller instance
command_poller = None

def init_command_poller(express_url, poll_interval=10):
    """Initialize the command poller"""
    global command_poller
    command_poller = CommandPoller(express_url, poll_interval)
    return command_poller