# Water pump controller Flask on Raspberry Pi
## Features
* pump schedule setting
* manual pump on/off
* locale setting
* increment setting

┌─────────────────────────────────────────────────────────────────────────┐
│                      WEBHOOK FLOW                                      │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  1. PUMP STATE CHANGES:                                                │
│     pump_controller._set_level()                                      │
│           ↓                                                            │
│     push_immediate('pump_status', data)                               │
│           ↓                                                            │
│     Flask → POST /webhook/pump-status                                 │
│           ↓                                                            │
│     Express → processWebhookEvent('pump_status')                      │
│           ↓                                                            │
│     io.emit('pump-update') ← React receives                          │
│     io.emit('full-update') ← React receives                          │
│                                                                         │
│  2. SCHEDULE CHANGES:                                                 │
│     scheduler.toggle_schedule() / add_schedule() / remove_schedule()  │
│           ↓                                                            │
│     push_immediate('schedule_*', data)                                │
│           ↓                                                            │
│     Flask → POST /webhook/pump-status                                 │
│           ↓                                                            │
│     Express → processWebhookEvent('schedule_*')                       │
│           ↓                                                            │
│     io.emit('schedule-update') ← React receives                      │
│     io.emit('full-update') ← React receives                          │
│                                                                         │
│  3. COMMAND RESULT:                                                   │
│     command_poller._execute_command()                                 │
│           ↓                                                            │
│     _report_command_result()                                          │
│           ↓                                                            │
│     Flask → POST /commands/result                                     │
│           ↓                                                            │
│     Express → io.emit('command-result') ← React receives             │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
