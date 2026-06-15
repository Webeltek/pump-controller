#!/home/willy/pump-controller/venv/bin/python
import RPi.GPIO as GPIO
import time

GPIO.setwarnings(False)

LOW_PIN = 18
HIGH_PIN = 23

GPIO.setmode(GPIO.BCM)
GPIO.setup(LOW_PIN, GPIO.OUT)
GPIO.setup(HIGH_PIN, GPIO.OUT)

GPIO.output(LOW_PIN, GPIO.HIGH)
GPIO.output(HIGH_PIN, GPIO.HIGH)

print("="*50)
print("INTIEL Pump Controller Test")
print("="*50)

print("\nTest 1: LOW - Pump should RUN")
input("Press Enter to continue...")
GPIO.output(LOW_PIN, GPIO.LOW)
GPIO.output(HIGH_PIN, GPIO.HIGH)
print("  Low: CLOSED, High: OPEN")
print("  Waiting 5 seconds...")
time.sleep(5)

print("\nTest 2: HIGH - Pump should STOP")
input("Press Enter to continue...")
GPIO.output(LOW_PIN, GPIO.LOW)
GPIO.output(HIGH_PIN, GPIO.LOW)
print("  Low: CLOSED, High: CLOSED")
print("  Waiting 3 seconds...")
time.sleep(3)

GPIO.cleanup()
print("\n" + "="*50)
print("Test complete! Pump STOPPED")
print("="*50)