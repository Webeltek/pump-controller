# command_poller.py - Add to your Flask project
import requests
import threading
import time
import logging
from datetime import datetime, timezone
from webhook import push_immediate, _normalize_webhook_urls

logger = logging.getLogger(__name__)

class CommandPoller:
    """
    Polls Express server for pending commands
    """
    def __init__(self, webhook_urls, poll_interval=10):
        self.webhook_urls = _normalize_webhook_urls(webhook_urls)
        self.webhook_url = self.webhook_urls[0] if self.webhook_urls else None
        self.poll_interval = poll_interval
        self.running = False
        self.thread = None
        self.pump_controller = None
        self.scheduler = None
        self.command_handlers = {}
        
        logger.info(f"Command poller initialized with URL: {webhook_urls}")
    
    def register_handlers(self, pump_controller, scheduler, get_system_info):
        """Register pump and scheduler for command execution"""
        self.pump_controller = pump_controller
        self.scheduler = scheduler
        self.get_system_info = get_system_info

        # Register command handlers
        self.command_handlers = {
            'pump_on': self._handle_pump_on,
            'pump_off': self._handle_pump_off,
            'emergency_stop': self._handle_emergency_stop,
            'add_schedule': self._handle_add_schedule,
            'delete_schedule': self._handle_delete_schedule,
            'toggle_schedule': self._handle_toggle_schedule,
            'react_initial_full_status': self._handle_get_react_initial_full_status,
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
        for webhook_url in self.webhook_urls:
            try:
                response = requests.get(
                    f"{self.webhook_url}/commands/pending",
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
        for webhook_url in self.webhook_urls:
            try:
                response = requests.post(
                    f"{self.webhook_url}/commands/result",
                    json={
                        'id': command_id,
                        'success': success,
                        'result': result,
                        'timestamp': datetime.now(timezone.utc).isoformat()
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
        self.pump_controller.set_low()  # This triggers webhook via pump_controller
        # Webhook already sent from pump_controller.set_low()
        return {'status': 'on', 'level': 'LOW'}
    
    def _handle_pump_off(self, data):
        """Handle pump off command"""
        self.pump_controller.set_high()  # This triggers webhook via pump_controller
        # Webhook already sent from pump_controller.set_high()
        return {'status': 'off', 'level': 'HIGH'}
    
    def _handle_emergency_stop(self, data):
        """Handle emergency stop"""
        self.pump_controller.emergency_stop()
        # 🔥 SEND WEBHOOK - Emergency stop
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
        
        schedule_id = self.scheduler.add_schedule(
            hour=data['hour'],
            minute=data['minute'],
            duration_seconds=data['duration'],
            days=data.get('days')
        )
        
        # 🔥 SEND WEBHOOK - Schedule added
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
        
        # If schedule is running, stop pump first
        if self.scheduler.running_schedule_id == schedule_id:
            self.pump_controller.set_high()
            push_immediate('pump_status', {
                'running': False,
                'level': 'HIGH',
                'level_state': 'HIGH',
                'source': 'schedule_deleted',
                'schedule_id': schedule_id
            })
        
        self.scheduler.remove_schedule(schedule_id)
        
        # 🔥 SEND WEBHOOK - Schedule deleted
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
    
    def _handle_get_react_initial_full_status(self, data):
        """Handle get status command"""
        initial_status = self.pump_controller.get_status()
        logger.info(f"Initial pump status: {initial_status}")

        # Send initial status to Express via webhook
        push_immediate('full_status', {
            'pump': {
                'running': initial_status.get('pump_should_run', False),
                'water_level': initial_status.get('water_level', 'HIGH'),
                'level_state': initial_status.get('level_state', 'HIGH')
            },
            'schedules': self.scheduler.get_schedules(),
            'next_run': self.scheduler.get_next_run_time(),
            'system': self.get_system_info()
        })
        return {'react_initial_full_status': 'pong', 'time': datetime.now(timezone.utc).isoformat()}



# Global poller instance
command_poller = None

def init_command_poller(webhook_urls, poll_interval=10):
    """Initialize the command poller"""
    global command_poller
    command_poller = CommandPoller(webhook_urls, poll_interval)
    return command_poller