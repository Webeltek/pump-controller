import RPi.GPIO as GPIO
import time
import logging
from threading import Lock
from enum import Enum

logger = logging.getLogger(__name__)

class WaterLevel(Enum):
    LOW = "Low Level (Pump ON)"
    HIGH = "High Level (Pump OFF)"

class PumpController:
    """
    Controls INTIEL Pump Control panel by simulating water level sensors
    Uses relays to connect/disconnect level sensor inputs
    
    INTIEL Panel Logic:
    - When Low Level contact CLOSED and High Level OPEN: Pump RUNS
    - When High Level contact CLOSED: Pump STOPS
    - Common electrode must be connected to relay COM
    """
    
    def __init__(self, low_level_pin=18, high_level_pin=23, common_pin=None):
        """
        Args:
            low_level_pin: GPIO for Low Level relay (simulates low water)
            high_level_pin: GPIO for High Level relay (simulates high water)
            common_pin: Optional GPIO for Common electrode relay (if needed)
        """
        self.low_pin = low_level_pin
        self.high_pin = high_level_pin
        self.common_pin = common_pin
        
        self.current_level = WaterLevel.HIGH
        self.lock = Lock()
        
        # Setup GPIO
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.low_pin, GPIO.OUT)
        GPIO.setup(self.high_pin, GPIO.OUT)
        
        if common_pin:
            GPIO.setup(self.common_pin, GPIO.OUT)
            GPIO.output(self.common_pin, GPIO.LOW)  # Always keep common connected
        
        # Initialize both relays OFF (contacts OPEN)
        GPIO.output(self.low_pin, GPIO.HIGH)
        GPIO.output(self.high_pin, GPIO.HIGH)

        # Start with HIGH level (pump stopped)
        self._set_level(WaterLevel.HIGH)

        logger.info("INTIEL Pump Controller - Level Sensor Simulation initialized")
        logger.info(f"Low Level Relay: GPIO {low_level_pin}")
        logger.info(f"High Level Relay: GPIO {high_level_pin}")
        logger.info("Current state: HIGH - Pump should STOP")
    
    def _set_relay(self, pin, closed):
        """Set relay state (closed = contact connected)"""
        if closed:
            GPIO.output(pin, GPIO.LOW)   # Active LOW relay
            logger.debug(f"Relay on GPIO {pin} CLOSED")
        else:
            GPIO.output(pin, GPIO.HIGH)  # Relay open
            logger.debug(f"Relay on GPIO {pin} OPEN")
    
    def _set_level(self, level):
        """Set water level by controlling relays"""
        with self.lock:
            self.current_level = level
            if level == WaterLevel.LOW:
                # Low: Low level CLOSED, High level OPEN (pump ON)
                self._set_relay(self.low_pin, True)
                self._set_relay(self.high_pin, False)
                logger.info("Water level: LOW - Pump should RUN")

            elif level == WaterLevel.HIGH:
                # High: Low level CLOSED, High level CLOSED (pump OFF)
                self._set_relay(self.low_pin, True)
                self._set_relay(self.high_pin, True)
                logger.info("Water level: HIGH - Pump should STOP")
    
    def set_low(self):
        """Set level to LOW - pump should run"""
        self._set_level(WaterLevel.LOW)
    
    def set_high(self):
        """Set level to HIGH - pump should stop"""
        self._set_level(WaterLevel.HIGH)
    
    
    # Note: timed fill/drain helpers removed. Scheduling should use set_low()/set_high().
    
    def get_status(self):
        """Get current pump status"""
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
        """Emergency stop - set high level (pump off)"""
        self.set_high()
        logger.warning("EMERGENCY STOP - Pump forced OFF")
    
    def cleanup(self):
        """Cleanup GPIO on shutdown"""
        # Set to HIGH level (pump off) as safety
        self.set_high()
        GPIO.cleanup(self.low_pin)
        GPIO.cleanup(self.high_pin)
        if self.common_pin:
            GPIO.cleanup(self.common_pin)
        logger.info("GPIO cleaned up - System safe")