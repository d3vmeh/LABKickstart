# Photogate Setup

Three views: wiring of one beam-break to one ESP32, the physical track with two
gates, and the end-to-end data flow.

## 1. Wiring — single beam-break (test rig)

This is the v0 you're building right now: one IR emitter aimed at one IR
receiver, with the receiver's output wired to the ESP32.

```
    IR EMITTER MODULE                       IR RECEIVER MODULE
    ┌───────────┐                              ┌───────────┐
    │  ●━━━━━━━━┿━━━━━━━━>>>>>>━━━━━━━━━━━━━━━━┿━━●        │
    │  IR LED   │   <-- IR beam, ~5–30 cm -->  │  PHOTODIODE
    │           │                              │           │
    │ VCC GND   │                              │ VCC GND OUT
    └──┬───┬────┘                              └──┬───┬───┬┘
       │   │                                      │   │   │
       │   │                                      │   │   │
   3.3V│   │GND                               3.3V│GND│   │GPIO 6
       │   │                                      │   │   │
       ▼   ▼                                      ▼   ▼   ▼
    ┌────────────────────────────────────────────────────────┐
    │                       ESP32                            │
    │  3V3   GND                            GND   3V3   GPIO6│
    │   ●─────●─────────────────────────────●─────●─────●    │
    │                                                        │
    │     USB-C (power + serial to your laptop)              │
    └────────────────────────────────────────────────────────┘

Notes:
  - GPIO 6 matches BEAM_PIN in photogate_test.ino.
  - The receiver's OUT pin is HIGH when the beam is intact and pulled
    LOW when the beam is broken (most modules behave this way).
  - Both modules share the ESP32's 3V3 and GND rails.
  - If you're using a 5V receiver module, power it from VIN (5V) and keep
    GPIO on a 3.3V tolerant pin or use a level shifter.
```

## 2. Physical layout — the eventual two-gate setup

Once the test rig works, the real lab uses two beam-breaks on a track. Each
gate is one emitter aimed at one receiver, with the cart's flag passing
between them.

```
                                 ┌──── d_AB ────┐
                                 │              │
   start                Gate A   │     Gate B   │
   ────●───────────────►●━━━━━━━●──────●━━━━━━━●─────────────►  end
                       (E)─►─►(R)    (E)─►─►(R)
                            ▲              ▲
                            │              │
                       beam break      beam break
                       starts t_A      starts t_B

   Cart with flag (width = flag_w):

         ┌──── flag_w ────┐
         │                │
       ──┴────────────────┴──   ←── moves left → right
            ●            ●
           ▲              ▲
           wheels         wheels

   The flag is what occludes each beam. Pi-side math:

       v_A   = flag_w / Δt_break_A      (if flag_w supplied)
       v_B   = flag_w / Δt_break_B
       v_avg = d_AB / (t_riseB - t_riseA)
       a     = (v_B² - v_A²) / (2·d_AB)
```

`d_AB` and `flag_w` are what the student types into the Kit panel before
arming. The ESP32 doesn't know either — it only reports beam-break
durations in microseconds.

## 3. End-to-end data flow

```
  ┌─────────────────────┐                ┌──────────────────────────────┐
  │   ESP32 (Gate A)    │                │   ESP32 (Gate B)             │
  │  photogate_test.ino │                │  photogate_test.ino          │
  │                     │                │  (same firmware,             │
  │  ISR on beam pin    │                │   GATE_LABEL="B" and a       │
  │  → break_us         │                │   different DEVICE_NAME)     │
  │  → BLE notify       │                │  → BLE notify                │
  └─────────┬───────────┘                └─────────┬────────────────────┘
            │ BLE notification                     │ BLE notification
            │ {"gate":"A","break_us":59917}        │ {"gate":"B","break_us":33219}
            ▼                                      ▼
  ┌───────────────────────────────────────────────────────────────────┐
  │                          Raspberry Pi                             │
  │                                                                   │
  │   bleak central        ─►   BLEPhotogateSensor                    │
  │   (subscribes to              ─► Sample(channel="gate_A_break_us")│
  │    both ESP32s)               ─► Sample(channel="gate_B_break_us")│
  │                                                                   │
  │                                       │                           │
  │                                       ▼                           │
  │                                   PhotogateKit.derive()           │
  │                                  uses d_AB, flag_w supplied by    │
  │                                  the student to compute:          │
  │                                   v_A, v_B, v_avg, a              │
  │                                       │                           │
  │                                       ▼                           │
  │                          ┌───────────┴───────────┐                │
  │                          ▼                       ▼                │
  │                     CSV writer              WebSocket fanout      │
  │                  data/runs/*.csv            ws://.../ws/stream    │
  └───────────────────────────────────────────────────┬───────────────┘
                                                      │
                                                      │ live samples (JSON)
                                                      ▼
  ┌───────────────────────────────────────────────────────────────────┐
  │                  Mac browser (or any device on Wi-Fi)             │
  │                  http://<pi-ip>:8000                              │
  │                                                                   │
  │        Devices  │  Kit (apply d_AB, flag_w)  │  Run (Arm/Stop)    │
  │                       Live chart of v_A, v_B, v_avg, a            │
  │                       Run history with CSV download              │
  └───────────────────────────────────────────────────────────────────┘
```

The boxes above the dashed line are hardware. Everything below the Pi is
software the Pi already has — no separate "controller" or "bridge" device
needed.
