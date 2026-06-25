# pump_controller.py
import RPi.GPIO as GPIO
import time
import logging
from threading import Lock
from enum import Enum
from webhook import push_immediate

logger = logging.getLogger(__name__)

class WaterLevel(Enum):
    LOW = "Low Level (Pump ON)"
    HIGH = "High Level (Pump OFF)"

class PumpController:
    def __init__(self, low_level_pin=18, high_level_pin=23, common_pin=None):
        self.low_pin = low_level_pin
        self.high_pin = high_level_pin
        self.common_pin = common_pin
        
        self.current_level = WaterLevel.HIGH
        self.lock = Lock()
        
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.low_pin, GPIO.OUT)
        GPIO.setup(self.high_pin, GPIO.OUT)
        
        if common_pin:
            GPIO.setup(self.common_pin, GPIO.OUT)
            GPIO.output(self.common_pin, GPIO.LOW)
        
        GPIO.output(self.low_pin, GPIO.HIGH)
        GPIO.output(self.high_pin, GPIO.HIGH)

        self._set_level(WaterLevel.HIGH)
        logger.info("Pump Controller initialized - State: HIGH (OFF)")
    
    def _set_relay(self, pin, closed):
        if closed:
            GPIO.output(pin, GPIO.LOW)
            logger.debug(f"Relay on GPIO {pin} CLOSED")
        else:
            GPIO.output(pin, GPIO.HIGH)
            logger.debug(f"Relay on GPIO {pin} OPEN")
    
    def _set_level(self, level):
        with self.lock:
            self.current_level = level
            if level == WaterLevel.LOW:
                self._set_relay(self.low_pin, True)
                self._set_relay(self.high_pin, False)
                logger.info("Water level: LOW - Pump should RUN")
                
                # 🔥 SEND WEBHOOK - Pump turned ON
                push_immediate('pump_status', {
                    'running': True,
                    'level': 'LOW',
                    'level_state': 'LOW',
                    'water_level': level.value,
                    'source': 'pump_controller'
                })
                
            elif level == WaterLevel.HIGH:
                self._set_relay(self.low_pin, True)
                self._set_relay(self.high_pin, True)
                logger.info("Water level: HIGH - Pump should STOP")
                
                # 🔥 SEND WEBHOOK - Pump turned OFF
                push_immediate('pump_status', {
                    'running': False,
                    'level': 'HIGH',
                    'level_state': 'HIGH',
                    'water_level': level.value,
                    'source': 'pump_controller'
                })
    
    def set_low(self):
        self._set_level(WaterLevel.LOW)
    
    def set_high(self):
        self._set_level(WaterLevel.HIGH)
    
    def get_status(self):
        return {
            'water_level': self.current_level.value,
            'level_state': self.current_level.name,
            'pump_should_run': self.current_level == WaterLevel.LOW,
            'low_relay_closed': self.current_level in [WaterLevel.LOW, WaterLevel.HIGH],
            'high_relay_closed': self.current_level == WaterLevel.HIGH,
            'control_mode': 'Level Sensor Simulation (Relay Output)',
            'low_level_pin': self.low_pin,
            'high_level_pin': self.high_pin
        }
    
    def emergency_stop(self):
        self.set_high()
        logger.warning("EMERGENCY STOP - Pump forced OFF")
    
    def cleanup(self):
        self.set_high()
        GPIO.cleanup(self.low_pin)
        GPIO.cleanup(self.high_pin)
        if self.common_pin:
            GPIO.cleanup(self.common_pin)
        logger.info("GPIO cleaned up")