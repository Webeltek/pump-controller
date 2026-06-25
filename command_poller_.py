# command_poller.py
import requests
import threading
import time
import logging
from datetime import datetime
from webhook import push_immediate, push_update

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
        
        logger.info("Command handlers registered")
    
    def start(self):
        """Start the poller thread"""
        if self.running:
            logger.warning("Command poller already running")
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
        consecutive_failures = 0
        max_failures = 5
        
        while self.running:
            try:
                self._poll_for_commands()
                consecutive_failures = 0  # Reset on success
            except requests.exceptions.Timeout:
                logger.debug("Poll timeout - no commands pending")
            except requests.exceptions.ConnectionError as e:
                consecutive_failures += 1
                logger.warning(f"Connection error (attempt {consecutive_failures}/{max_failures}): {e}")
                if consecutive_failures >= max_failures:
                    logger.error("Multiple connection failures - check Express server")
                    consecutive_failures = 0
                    # Wait longer before retry
                    time.sleep(self.poll_interval * 2)
                    continue
            except Exception as e:
                logger.error(f"Polling error: {e}")
                consecutive_failures += 1
            
            time.sleep(self.poll_interval)
    
    def _poll_for_commands(self):
        """Poll Express for pending commands"""
        try:
            response = requests.get(
                f"{self.express_url}/api/commands/pending",
                timeout=5,
                headers={'X-Device-ID': 'pump-controller-001'}
            )
            
            if response.status_code == 200:
                data = response.json()
                commands = data.get('commands', [])
                if commands:
                    logger.info(f"Received {len(commands)} command(s)")
                    for command in commands:
                        self._execute_command(command)
                else:
                    logger.debug("No pending commands")
            elif response.status_code == 204:
                # No pending commands
                logger.debug("No pending commands (204)")
            else:
                logger.warning(f"Poll failed: {response.status_code} - {response.text}")
                
        except requests.exceptions.Timeout:
            logger.debug("Poll timeout - no commands pending")
            raise  # Re-raise for handling in _poll_loop
        except requests.exceptions.RequestException as e:
            logger.error(f"Poll request error: {e}")
            raise
    
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
                logger.info(f"Command {cmd_id} executed successfully")
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
                f"{self.express_url}/api/commands/result",
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
                logger.debug(f"Command result reported: {command_id} -> {'OK' if success else 'FAIL'}")
            else:
                logger.warning(f"Failed to report command result: {response.status_code}")
        except Exception as e:
            logger.error(f"Error reporting command result: {e}")
    
    # ===== COMMAND HANDLERS =====
    
    def _handle_pump_on(self, data):
        """Handle pump on command"""
        logger.info("Handling pump_on command")
        self.pump_controller.set_low()  # Webhook sent from pump_controller
        return {'status': 'on', 'level': 'LOW'}
    
    def _handle_pump_off(self, data):
        """Handle pump off command"""
        logger.info("Handling pump_off command")
        self.pump_controller.set_high()  # Webhook sent from pump_controller
        return {'status': 'off', 'level': 'HIGH'}
    
    def _handle_emergency_stop(self, data):
        """Handle emergency stop"""
        logger.warning("Handling emergency_stop command")
        self.pump_controller.emergency_stop()
        
        # Send webhook for emergency stop
        push_immediate('pump_status', {
            'running': False,
            'level': 'HIGH',
            'level_state': 'HIGH',
            'source': 'emergency_stop'
        })
        
        return {'status': 'emergency_stop', 'message': 'Pump stopped'}
    
    def _handle_add_schedule(self, data):
        """Handle add schedule command"""
        if not self.scheduler:
            raise Exception("Scheduler not available")
        
        logger.info(f"Handling add_schedule command: {data}")
        schedule_id = self.scheduler.add_schedule(
            hour=data['hour'],
            minute=data['minute'],
            duration_seconds=data['duration'],
            days=data.get('days')
        )
        
        # Send webhook for schedule added
        schedules = self.scheduler.get_schedules()
        next_run = self.scheduler.get_next_run_time()
        push_immediate('schedule_added', {
            'schedule_id': schedule_id,
            'schedules': schedules,
            'next_run': next_run
        })
        
        return {'schedule_id': schedule_id}
    
    def _handle_delete_schedule(self, data):
        """Handle delete schedule command"""
        if not self.scheduler:
            raise Exception("Scheduler not available")
        
        schedule_id = data['schedule_id']
        logger.info(f"Handling delete_schedule command: {schedule_id}")
        
        # If schedule is running, stop pump first
        if self.scheduler.running_schedule_id == schedule_id:
            logger.warning(f"Deleting active schedule {schedule_id} - stopping pump")
            self.pump_controller.set_high()
            push_immediate('pump_status', {
                'running': False,
                'level': 'HIGH',
                'level_state': 'HIGH',
                'source': 'schedule_deleted',
                'schedule_id': schedule_id
            })
        
        self.scheduler.remove_schedule(schedule_id)
        
        # Send webhook for schedule deleted
        schedules = self.scheduler.get_schedules()
        next_run = self.scheduler.get_next_run_time()
        push_immediate('schedule_deleted', {
            'schedule_id': schedule_id,
            'schedules': schedules,
            'next_run': next_run
        })
        
        return {'deleted': schedule_id}
    
    def _handle_toggle_schedule(self, data):
        """Handle toggle schedule command"""
        if not self.scheduler:
            raise Exception("Scheduler not available")
        
        schedule_id = data['schedule_id']
        enabled = data['enabled']
        logger.info(f"Handling toggle_schedule command: {schedule_id} -> enabled={enabled}")
        
        # If disabling and schedule is running, stop pump
        if not enabled and self.scheduler.running_schedule_id == schedule_id:
            logger.warning(f"Disabling active schedule {schedule_id} - stopping pump")
            self.pump_controller.set_high()
            push_immediate('pump_status', {
                'running': False,
                'level': 'HIGH',
                'level_state': 'HIGH',
                'source': 'schedule_toggled_off',
                'schedule_id': schedule_id
            })
        
        self.scheduler.toggle_schedule(schedule_id, enabled)
        
        # Send webhook for schedule toggled
        schedules = self.scheduler.get_schedules()
        next_run = self.scheduler.get_next_run_time()
        push_immediate('schedule_toggled', {
            'schedule_id': schedule_id,
            'enabled': enabled,
            'schedules': schedules,
            'next_run': next_run
        })
        
        return {'schedule_id': schedule_id, 'enabled': enabled}
    
    def _handle_get_status(self, data):
        """Handle get status command"""
        logger.info("Handling get_status command")
        return {'status': 'pong', 'time': datetime.utcnow().isoformat()}


# ===== GLOBAL POLLER INSTANCE =====
_command_poller = None


def init_command_poller(express_url, poll_interval=10):
    """
    Initialize the command poller singleton
    
    Args:
        express_url: URL of the Express server (e.g., 'https://your-express-app.com')
        poll_interval: How often to poll for commands (seconds)
    
    Returns:
        CommandPoller: The initialized poller instance
    """
    global _command_poller
    if _command_poller is None:
        _command_poller = CommandPoller(express_url, poll_interval)
        logger.info(f"Command poller initialized with URL: {express_url}")
    else:
        logger.warning("Command poller already initialized")
    return _command_poller


def get_command_poller():
    """Get the global command poller instance"""
    global _command_poller
    if _command_poller is None:
        logger.warning("Command poller not initialized - call init_command_poller first")
    return _command_poller


def start_command_poller():
    """Start the global command poller"""
    global _command_poller
    if _command_poller:
        _command_poller.start()
    else:
        logger.error("Cannot start poller - not initialized")


def stop_command_poller():
    """Stop the global command poller"""
    global _command_poller
    if _command_poller:
        _command_poller.stop()
    else:
        logger.warning("Command poller not initialized")