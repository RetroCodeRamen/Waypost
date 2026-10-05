# Scout firmware — architecture review and redesign

**Status:** approved 2026-10-05. The human chose a **fresh firmware alongside** the old one
(`firmware/scout`; `firmware/pocket` stays until scout does everything it does) and **LovyanGFX**.
Milestone 1 (steps A, C, D and the net task from B, with a test screen instead of apps) is built:
see §6.
**Why now:** a day of chasing symptoms (frozen logo, lost keys, a "dead" keyboard, partial and
stale screen updates, lag) kept uncovering new ones. They share causes in how the firmware is
built, not in single lines. This review states those causes with the evidence, looks at how two
mature T-Deck firmwares solve the same problems, and proposes a structure that removes them.

References read (cloned 2026-10-05):
- **Meshtastic** (`meshtastic/firmware`): the most-used T-Deck firmware. `src/graphics/TFTDisplay.cpp`,
  `src/mesh/RadioLibInterface.{h,cpp}`, `src/mesh/SX126xInterface.cpp`, `src/concurrency/*`,
  `variants/esp32s3/t-deck/variant.h`.
- **LilyGO's T-Deck repository** (`Xinyuan-LilyGO/T-Deck`): `examples/UnitTest/UnitTest.ino`,
  `lib/TFT_eSPI/User_Setups/Setup210_LilyGo_T_Deck.h`.

## 1. What went wrong, and why (evidence from 2026-10-05)

| Symptom | Measured cause | Root |
|---|---|---|
| Keys lost, "frozen", laggy | Every Station/peer request **blocks the main loop** 1–15 s (`station_link::request` spins until a reply); the keyboard controller holds one key | **Blocking I/O on the UI thread** |
| Everything sluggish even when idle | Loop ran **~5 passes/s**: reachability checks read microReticulum's flash-backed path/identity stores (~45 ms) several times per pass. Cached → 160/s (`5381bf4`) | **Expensive calls in a hot loop**, no budget |
| Frozen on the logo after a warm reset | Radio task (core 0) and boot screen (core 1) used the shared SPI bus at the same time | **Two owners of one bus**, no shared lock |
| Screen shows stale/partial frames, worse when the radio is busy; panel sometimes needed a full power-off | The canvas held the right picture while the panel didn't (USB screenshot vs photo). Display (TFT_eSPI, direct register writes) and radio (RadioLib via Arduino `SPI`) share a bus with no common lock; frames pushed from a 150 KB PSRAM canvas | **Unlocked shared bus**; display driver chosen without the radio in mind |
| "Keyboard dead" | Our own experiment: power-cycling the peripheral rail at boot restarted the keyboard's controller badly | Peripheral bring-up not owned by one place |
| Many small loops (certs, sync, catch-up, outbox, Beacon, identity) with their own timers, each able to block | Grew feature by feature | **No scheduler / no work budget** |

The protocol, storage formats, crypto and sync engine are sound and shared with the Outpost
(`firmware/common/waypost_core`) — they are **not** the problem and are kept.

## 2. How Meshtastic and LilyGO do it

**Meshtastic (T-Deck):**
- **Nothing blocks.** A cooperative scheduler (`concurrency::OSThread`): every subsystem is a
  `runOnce()` that does a little work and returns how long until it wants to run again.
- **Radio is interrupt-driven.** SX1262 DIO1 → ISR → notifies the radio worker
  (`RadioLibInterface : NotifiedWorkerThread`, `isrLevel0Common`). Transmit is *started*
  (`startTransmit`) and completes by interrupt; nobody waits on the air.
- **One bus lock for everything on the SPI bus** (`spiLock`): the radio takes it in its RadioLib HAL
  around every transaction (`LockingArduinoHal::spiBeginTransaction/EndTransaction`), the display
  around every flush (`TFTDisplay::display`), file writes too.
- **Display:** LovyanGFX on `SPI2_HOST`, 40 MHz, transaction locking, DMA; the frame is diffed and
  only changed rows are sent, from **internal-RAM** chunk buffers.
- **Screen refresh is its own job** at a fixed rate (`SCREEN_TRANSITION_FRAMERATE 30`), decoupled
  from input and radio.

**LilyGO's examples:** one FreeRTOS binary semaphore guards both the LVGL flush and every radio
operation; all chip-selects high and MISO pulled up before `SPI.begin`; display at 40 MHz.

## 3. Proposed structure

```text
 core 0                                   core 1
┌───────────────────────────┐            ┌──────────────────────────────────┐
│ net task                  │  commands  │ ui task (~30 Hz frame tick)       │
│  Reticulum + LoRa (IRQ)   │◄──queue────│  input → active app → render      │
│  request/reply table      │            │  apps never call the radio;       │
│  jobs: sync, certs,       │──events───►│  they post commands and get       │
│   catch-up, outbox, beacon│  queue     │  events (reply, push, beacon, …)  │
│  (each a runOnce with a   │            │  display flush: dirty rows,       │
│   budget, never blocks)   │            │  internal-RAM chunks              │
└────────────┬──────────────┘            └──────────────┬───────────────────┘
             │          ┌────────────────────┐          │
             └─────────►│ bus: one SPI mutex │◄─────────┘
                        │ radio HAL + display│
                        └────────────────────┘
  storage service: one owner of LittleFS (files written from the net task, read via cache)
```

1. **Two tasks, two queues.** The **net task** owns Reticulum, the radio, Station/peer requests and
   all background jobs. The **UI task** owns input, apps and the display. They talk only through
   queues: apps post commands ("send this", "fetch conversations") and receive events ("reply
   arrived", "message pushed", "Beacon"). **No app ever waits on the radio** — a pending request
   shows a spinner and the app stays responsive.
2. **Interrupt-driven radio** (Meshtastic's pattern): DIO1 ISR → notify the net task; transmit
   started, not waited on. Our CSMA/split-frame logic in `lora_interface` is kept, made
   non-blocking.
3. **One SPI bus lock** taken by a RadioLib HAL subclass around every radio transaction and by
   the display flush — exactly Meshtastic's `LockingArduinoHal` + `spiLock`.
4. **Display driver: LovyanGFX** (as Meshtastic on this board) with bus locking and DMA,
   **dirty-row diff**, flush from internal-RAM chunks at a fixed frame rate. Our own small
   widget set (title bar, list, prompt, reader) is kept — it's what makes the Scout look like a
   Waypost device — ported onto the new driver. (Alternative: LVGL as LilyGO does — richer,
   heavier, a larger rewrite of every screen.)
5. **Input:** keyboard + trackball read by the UI task every frame into a queue (no loss), never
   from inside a radio wait.
6. **Jobs with a budget:** sync, certificates, catch-up, outbox, Beacon check, identity become net
   task jobs with explicit "next run" times and a per-pass time budget; expensive look-ups
   (path/identity) are cached in RAM.
7. **Storage:** one owner (net task) writes LittleFS; the UI reads from RAM caches the net task
   updates. Ends the "two tasks on the filesystem" class of bugs for good.
8. **Bring-up in one place:** power, chip-selects, MISO pull-up, bus, display, keyboard
   (500 ms), radio — in that order, before any task starts (LilyGO's order).

**Kept as is:** `firmware/common/waypost_core` (Waylink codec, certificates, signed objects, sync
engine), `store.*` formats, `certs.*` logic, `kdf.*`, the protocol, Station, the Outpost.

## 4. How we'd get there (each step flashable and testable on its own)

| Step | What | Done when |
|---|---|---|
| A | Bring-up order + **SPI bus lock in the radio HAL and the display** (Meshtastic's pattern) | screen stays correct while the network is busy (the human's test) |
| B | **Net task + queues**; `station_link::request` becomes asynchronous (command → event); apps converted one by one, Dispatch first | no key lost, UI never waits on the radio |
| C | **Interrupt-driven radio** (DIO1), non-blocking transmit | radio work never stalls either task |
| D | **LovyanGFX** display with dirty-row flush and DMA, widgets ported | full-screen redraws in a frame, no tearing |
| E | Background jobs moved into the net task with budgets; storage single-owner | steady 30 Hz UI with sync running |

Step A alone may fix the screen; B fixes lag and lost keys; C–E make it robust. A–B are the
priority.

## 5. Risks

- Step B touches every app (they all call the radio today). Done app by app behind the same
  `station_link` API name, so the device keeps working between steps.
- The RF question isn't settled: if the Scout's own transmissions disturb the panel (antenna a few
  cm above the display), the bus lock won't fix that. A 2 dBm transmit test answers it in minutes
  and is worth running during step A.

## 6. Progress

**Milestone 1 — foundation (2026-10-05, `firmware/scout`).** `board` (LilyGO bring-up order),
`bus` (recursive SPI lock + RadioLib `LockingHal`), `display` (LovyanGFX ST7789, PSRAM canvas,
dirty-rectangle flush in 8-row pieces from internal RAM, under the lock), `input` (trackball ISRs +
keyboard into one queue), `radio` (`AsyncLoRa`: DIO1 interrupt, queued sends, CAD listen-before-talk
with non-blocking back-off, `startTransmit`/TX_DONE, RNode split framing unchanged), `net` (task on
core 0 owning Reticulum; Station PING test; commands in by queue, status out by snapshot), and a
test screen on a 30 Hz UI task (core 1) with a sweeping bar that shows any stall.
Measured on the device: steady 31 fps; net passes ~0 ms except Reticulum's own crypto (~55 ms,
off the UI core); Station heard the announce over its RNode. Same partitions and file names as
pocket, so the identity is kept.
Next: the human's busy-network test (F = PING flood), then apps on the async command/event API,
Dispatch first.
