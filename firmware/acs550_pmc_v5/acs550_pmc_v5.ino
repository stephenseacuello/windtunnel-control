/*
 * ============================================================================
 *  acs550_pmc_v5.ino   -- v5, adds turbine RPM from a magnet + reed switch
 *
 *  Derived from acs550_pmc_v3.ino, UNTOUCHED at firmware/acs550_pmc_v3/.
 *  The Modbus loop, both watchdogs, the control-word handshake, RD/WR and
 *  every existing telemetry field are unchanged. v5 only ADDS.
 *
 *  Numbered 5, not 4. firmware/acs550_pmc_v4/ was written to publish FAN rpm
 *  to a separate DAQ and is abandoned now that rotor rpm comes in here
 *  instead. It was never flashed, but a version number is a promise: if a
 *  board ever answers ID with 4.0 that must mean exactly one thing forever.
 *
 *  ---------------------------------------------------------------------------
 *  WIRING -- the rotor speed sensor  (the v5 addition)
 *  ---------------------------------------------------------------------------
 *  Sensor: DIGITEN VJ12-D10K, a 2-wire DRY CONTACT (reed switch). One magnet
 *  on one blade, so ONE PULSE PER REVOLUTION. No supply, no polarity.
 *
 *      reed wire A  ---->  PMC  ENC0 A   (PJ_8, encoder connector)
 *      reed wire B  ---->  PMC  GND
 *
 *  NOT AI0. The analog inputs are an ADC behind SPI and one read is a
 *  blocking transaction of order a millisecond. At 2400 rpm the magnet is in
 *  front of the sensor for about 390 us and at 3600 rpm about 260 us, so
 *  polling an ADC would drop pulses -- worst at high speed, which biases rotor
 *  rpm LOW exactly where the rotor makes most power. PJ_8 is a real MCU pin,
 *  so a hardware interrupt catches the edge whatever else the loop is doing.
 *
 *  The pin is configured INPUT_PULLUP, so the contact simply shorts it to
 *  ground. Nothing can be damaged by getting the two wires the wrong way
 *  round; there is no wrong way round.
 *
 *  RECOMMENDED, not required: a 4.7k pull-up to 3V3 and 10 nF to GND at the
 *  PMC end, with the run in shielded twisted pair. The internal pull-up is
 *  about 40k, which is a high-impedance node next to a 15 HP motor and a VFD.
 *  Firmware debouncing will cope either way; the resistor just means fewer
 *  rejected edges to explain later.
 *
 *  ---------------------------------------------------------------------------
 *  WHAT THIS SENSOR CANNOT DO, AND HOW YOU WILL KNOW
 *  ---------------------------------------------------------------------------
 *  The ZX-5H counter this reed ships with is rated "20 Hz, or 20 times/s".
 *  At one pulse per revolution that is 1200 rpm. We do not use that counter --
 *  the reed comes straight in here -- but the reed's OWN frequency limit is
 *  undocumented, and 20 Hz is the only number in the box.
 *
 *  The rotor is expected to reach 50-75 Hz at the top of the wind range. That
 *  is inside what a healthy reed manages and outside what its packaging
 *  claims, so it MUST be validated rather than assumed.
 *
 *  The validation is free and it is exact. Open-circuit voltage is
 *  proportional to rotor speed through the generator constant, so
 *
 *      K = rotor_rpm / V_oc
 *
 *  must be CONSTANT across the wind range. If the reed starts missing pulses
 *  at speed, K falls away at high wind while V_oc keeps climbing. A drooping
 *  K is the signature of a sensor running out of bandwidth, and it cannot be
 *  mistaken for anything aerodynamic.
 *
 *  Bounce is handled the other way: a reed rings for a few hundred
 *  microseconds when it closes, which would count several times per pass and
 *  read rpm HIGH. RPM_MIN_GAP_US rejects any edge closer than 2 ms to the
 *  last, a ceiling of 30000 rpm -- far above anything real here, far below
 *  the bounce it is rejecting. Rejected edges are counted and reported, so a
 *  sensor that is chattering says so instead of inflating the answer.
 *
 *  Arduino Portenta Machine Control  ->  ABB ACS550-U1-046A-2 (fw 3.13)
 *  Aerolab wind tunnel fan drive, Modbus RTU over the PMC's onboard RS-485.
 *
 *  The PMC owns the real-time Modbus loop and the safety watchdog. A PC runs
 *  tunnel.py and speaks a line protocol over USB serial. Every command gets
 *  exactly one OK/ERR line back, so the host never has to guess.
 *
 *  ---------------------------------------------------------------------------
 *  WIRING -- ACS550 terminal block X1 (verified against ABB ACS550 manual)
 *  ---------------------------------------------------------------------------
 *      X1-28  SCR   shield  (land shield here at ONE end of the run only)
 *      X1-29  B     ------> PMC RS-485  B
 *      X1-30  A     ------> PMC RS-485  A
 *      X1-31  AGND  ------> PMC RS-485  GND / ISOGND   (signal common - use it)
 *      X1-32  SCR   shield  (other end of a daisy chain)
 *
 *  Cable: Belden 9842 / 3105A or equivalent 120R shielded twisted pair.
 *  ABB's note: do not ground the RS-485 network at any point other than the
 *  drives' own earth terminals.
 *
 *  Termination: 120R at both physical ends only. Drive end = its DIP switch.
 *  PMC end = setABTerm(true) below. With only two nodes, both are ends.
 *
 *  A/B labelling is inconsistent across vendors. If everything else checks out
 *  and you get nothing but timeouts, swap 29 and 30. It cannot damage anything.
 *
 *  ---------------------------------------------------------------------------
 *  DRIVE PARAMETERS  (keypad, drive stopped; power-cycle after 9802 / group 53)
 *  ---------------------------------------------------------------------------
 *    9802 COMM PROT SEL   = 1 (STD MODBUS)
 *    5302 EFB STATION ID  = 1        -> SLAVE_ID
 *    5303 EFB BAUD RATE   = 19.2     -> BAUD
 *    5304 EFB PARITY      = 8E1      -> SERIAL_CFG
 *    5305 EFB CTRL PROFILE= 0 (ABB DRV LIM)
 *
 *    5310 EFB PAR 10 = 103   -> 0103 OUTPUT FREQ lands in 40005
 *    5311 EFB PAR 11 = 104   -> 0104 CURRENT     lands in 40006
 *    5312 EFB PAR 12 = 106   -> 0106 POWER       lands in 40007
 *      (this is why one 7-register read gets everything -- see POLL below)
 *
 *    3018 COMM FAULT FUNC = 1 (FAULT)   <-- drive-side watchdog. Set it.
 *    3019 COMM FAULT TIME = 3.0 s
 *
 *    2202/2203 ACCEL/DECEL TIME -- the tunnel's ramp lives here, not in code.
 *
 *  Control location: prefer keeping the Aerolab panel on EXT1 and putting
 *  Modbus on EXT2 so manual control still works --
 *    1002 EXT2 COMMANDS = 10 (COMM), 1106 REF2 SELECT = 8 (COMM),
 *    1102 EXT1/EXT2 SEL = a spare DI used as a selector switch.
 *  If you do that, set USE_REF2 to 1 below (different register AND scale).
 *
 *  ---------------------------------------------------------------------------
 *  HOST LINE PROTOCOL  (115200 8N1, '\n' terminated, case-insensitive verbs)
 *  ---------------------------------------------------------------------------
 *    ID            -> OK ID acs550-pmc 5.0 RD/WR RPM
 *    RPM?          -> OK RPM <pulses> <last_us> <rpm> <raw> <rejected> <rev>
 *                     pin is the LIVE input level: pass the magnet past the
 *                     sensor by hand and watch it toggle 1 -> 0. That proves
 *                     the whole signal path with the tunnel switched off.
 *    RD <par>      -> read any drive parameter
 *    WR <par> <v>  -> write one (needs UNLOCK; see writeRefusal)
 *    UNLOCK/LOCK   -> arm/disarm writes
 *    HZ <float>    -> OK HZ <clamped>
 *    PCT <float>   -> OK HZ <clamped>
 *    RUN           -> OK RUN            | ERR <reason>
 *    STOP          -> OK STOP
 *    COAST         -> OK COAST
 *    RESET         -> OK RESET
 *    STAT          -> OK STAT  (followed by one T, line)
 *    PING          -> OK PING           (feeds the host watchdog)
 *    STREAM <ms>   -> OK STREAM <ms>    (0 disables periodic telemetry)
 *    LIMIT <hz>    -> OK LIMIT <hz>     (software ceiling, cannot exceed MAX_HZ)
 *    WD <ms>       -> OK WD <ms>        (0 disables host watchdog - bench only)
 *
 *  Telemetry line (v5 APPENDS three fields; older hosts zip-truncate and are
 *  unaffected):
 *    T,<t_ms>,<state>,<sp_hz>,<act_hz>,<amps>,<kw>,<sw_hex>,<settled>,<fault>,
 *      <errs>,<rpm_pulses>,<rpm_last_us>,<rotor_rpm>
 *
 *  rpm_pulses and rpm_last_us are the RECORD. rotor_rpm is a convenience for
 *  humans reading a terminal, computed from the single most recent interval
 *  and therefore jittery at one pulse per revolution.
 *
 *  A host wanting an accurate figure over any window differences the other
 *  two:
 *
 *      rotor_rpm = 60e6 * (pulses2 - pulses1) / (last_us2 - last_us1)
 *
 *  which is exactly that many whole revolutions over exactly the time they
 *  took, timed by the PMC rather than by the host's scheduler. Both are
 *  unsigned and wrap correctly.
 *
 *  Anything starting '#' is a human-readable comment; hosts should ignore it.
 *
 *  Libraries: Arduino_PortentaMachineControl, ArduinoRS485, ArduinoModbus
 *  Board:     Arduino Portenta H7 (M7 core)
 * ============================================================================
 */

#include <Arduino_PortentaMachineControl.h>
#include <ArduinoRS485.h>
#include <ArduinoModbus.h>

// ===========================================================================
// Configuration
// ===========================================================================
#define USE_REF2   0        // 0 = EXT1/REF1 (40002, +/-20000 scaled to par 1105)
                            // 1 = EXT2/REF2 (40003, +/-10000 scaled to par 1108)

static const int      SLAVE_ID    = 1;
static const uint32_t BAUD        = 19200;
static const uint16_t SERIAL_CFG  = SERIAL_8E1;

#if USE_REF2
  static const int      REG_REF      = 2;        // 40003
  static const float    REF_FULLSCALE= 10000.0f;
  static const float    REF_MAX_HZ   = 60.0f;    // par 1108 REF2 MAX
#else
  static const int      REG_REF      = 1;        // 40002
  static const float    REF_FULLSCALE= 20000.0f;
  static const float    REF_MAX_HZ   = 60.0f;    // par 1105 REF1 MAX
#endif

static const float    MAX_HZ        = 60.0f;   // hard ceiling, never exceeded
static float          limitHz       = 60.0f;   // soft ceiling, settable at runtime

// RS-485 driver-enable guard time, microseconds, either side of the frame.
static const int      PRE_DELAY_US  = 500;
static const int      POST_DELAY_US = 500;

// ---- v5: rotor speed, magnet + reed on the encoder-0 A input ---------
// PJ_8 is a real MCU pin (see pins_mc.h, MC_ENC_0A_PIN), so mbed::InterruptIn
// gives a hardware edge interrupt. EXTI lines are shared by pin NUMBER, so
// PJ_8 claims EXTI8; nothing else in this sketch attaches an interrupt, and
// the only other pin-8 in the PMC map is PA_8, an analog-mux OUTPUT.
static const uint32_t RPM_PPR         = 1;      // one magnet, one blade
static const uint32_t RPM_STALE_MS    = 2000;   // no pulse this long -> 0 rpm

static const uint32_t POLL_MS         = 100;
static const uint32_t MODBUS_TIMEOUT  = 200;
static const uint8_t  MAX_COMM_ERRORS = 10;    // consecutive, then declare loss

static uint32_t       streamMs        = 250;   // 0 = telemetry on request only
static uint32_t       watchdogMs      = 3000;  // 0 = disabled

// Settle detection -- how tunnel.py knows a setpoint has taken hold
static const float    SETTLE_TOL_HZ   = 0.3f;
static const uint32_t SETTLE_DWELL_MS = 2000;

// ===========================================================================
// ACS550 Modbus map. Zero-based on the wire: 40001 -> address 0.
// ===========================================================================
static const int REG_CONTROL_WORD = 0;    // 40001
static const int REG_STATUS_WORD  = 3;    // 40004
static const int REG_ACT_FREQ     = 4;    // 40005 <- par 5310 = 103
static const int REG_ACT_CURRENT  = 5;    // 40006 <- par 5311 = 104
static const int REG_ACT_POWER    = 6;    // 40007 <- par 5312 = 106
static const int REG_LAST_FAULT   = 400;  // 40401, par 0401 LAST FAULT

// ABB Drives profile control word
//  b0 OFF1  b1 OFF2  b2 OFF3  b3 RUN  b4 RAMP_OUT_ZERO  b5 RAMP_HOLD
//  b6 RAMP_IN_ZERO  b7 RESET  b10 REMOTE_CMD
static const uint16_t CW_PREPARE = 0x0476;
static const uint16_t CW_STOP    = 0x047E;
static const uint16_t CW_RUN     = 0x047F;
static const uint16_t CW_COAST   = 0x047C;
static const uint16_t CW_RESET   = 0x04FF;

// Status word
static const uint16_t SW_RDY_ON      = 1 << 0;
static const uint16_t SW_RDY_RUN     = 1 << 1;
static const uint16_t SW_RDY_REF     = 1 << 2;
static const uint16_t SW_TRIPPED     = 1 << 3;
static const uint16_t SW_ALARM       = 1 << 7;
static const uint16_t SW_AT_SETPOINT = 1 << 8;
static const uint16_t SW_REMOTE      = 1 << 9;

// ===========================================================================
// State
// ===========================================================================
enum State { ST_INIT, ST_IDLE, ST_STARTING, ST_RUNNING, ST_STOPPING,
             ST_FAULT, ST_COMM_LOST };

static State      state       = ST_INIT;
static float      setpointHz  = 0.0f;
static uint16_t   statusWord  = 0;
static float      actualHz    = 0.0f;
static float      actualAmps  = 0.0f;
static float      actualKw    = 0.0f;
static uint16_t   faultCode   = 0;
static uint8_t    commErrors  = 0;
static uint32_t   totalErrors = 0;
static bool       settled     = false;
static uint32_t   inBandSince = 0;
static uint32_t   lastPoll    = 0;
static uint32_t   lastStream  = 0;
static uint32_t   lastHostMsg = 0;
static uint32_t   startedAt   = 0;
static char       rxBuf[80];
static uint8_t    rxLen       = 0;


// ── rotor speed via the library's OWN encoder ────────────────────────────
//
// v5.0 and v5.1 created an mbed::InterruptIn on PJ_8 and hung the board, which
// stopped the Modbus loop, which tripped the drive's comm watchdog 3 s later.
// The symptom read as "the VFD keeps faulting" and had nothing to do with the
// drive: par 3018/3019 were doing exactly their job.
//
// The cause: Arduino_PortentaMachineControl.h declares
//
//     extern EncoderClass MachineControl_Encoders;
//
// a GLOBAL whose QEI constructor already claims MC_ENC_0A_PIN (PJ_8),
// MC_ENC_0B_PIN and MC_ENC_0I_PIN. That object exists in v3 too, which is why
// v3 is fine — v3 simply never touched those pins. An InterruptIn on PJ_8 was
// a SECOND claim on a pin mbed already owned.
//
// So: use the encoder instead of fighting it. No ISR of ours, no second
// claim, nothing to storm.
//
// X1_ENCODING counts one edge per cycle (QEI.cpp:269-275): with state
// (A<<1)|B, it increments on 0x3 and decrements on 0x2. So channel B decides
// the SIGN and must be strapped to a rail — either one. Tied high the count
// runs up, tied low it runs down; the host uses the magnitude of the change,
// so both work. A FLOATING B is the one thing that does not: the count then
// wanders both ways, which rpmReversals makes visible instead of silent.
static const int      RPM_ENC_CH   = 0;
static const uint32_t RPM_MIN_GAP_US = 2000;   // reed debounce -> 30000 rpm

static int32_t  rpmRaw       = 0;   // last value read from the encoder
static uint32_t rpmPulses    = 0;   // accepted changes, monotonic
static uint32_t rpmLastUs    = 0;   // micros() when the count last changed
static uint32_t rpmPrevUs    = 0;
static uint32_t rpmRejected  = 0;   // changes inside the debounce window
static uint32_t rpmReversals = 0;   // direction flips: B is floating
static int      rpmLastDir   = 0;

// Called from loop() on every pass, not from an interrupt. loop() returns
// early until POLL_MS elapses, so this runs thousands of times a second and
// timestamps a change to within tens of microseconds -- ample against a
// magnet that arrives every 13 ms at the top of the range.
static void rpmSample() {
  int32_t now_raw = (int32_t)MachineControl_Encoders.getPulses(RPM_ENC_CH);
  if (now_raw == rpmRaw) return;

  int32_t d = now_raw - rpmRaw;
  rpmRaw = now_raw;
  int dir = (d > 0) ? 1 : -1;
  if (rpmLastDir && dir != rpmLastDir) rpmReversals++;
  rpmLastDir = dir;

  uint32_t now = micros();
  if (rpmPulses && (uint32_t)(now - rpmLastUs) < RPM_MIN_GAP_US) {
    rpmRejected++;                  // reed bounce, or noise on a floating A
    return;
  }
  rpmPrevUs = rpmLastUs;
  rpmLastUs = now;
  rpmPulses += (uint32_t)(d < 0 ? -d : d);
}

static void rpmRead(uint32_t *pulses, uint32_t *lastUs, uint32_t *prevUs,
                    uint32_t *rejected) {
  // No interrupt writes these any more, so no lock and no masking.
  *pulses = rpmPulses; *lastUs = rpmLastUs;
  *prevUs = rpmPrevUs; *rejected = rpmRejected;
}

// Instantaneous rotor rpm from the most recent interval. Jittery at one pulse
// per revolution -- blade imbalance and wobble are real period modulation --
// so this is for a human watching a terminal. The recorded figure comes from
// differencing pulses and last_us over a whole dwell.
static float rpmInstant() {
  uint32_t p, last, prev, rej;
  rpmRead(&p, &last, &prev, &rej);
  if (p < 2) return 0.0f;
  if ((uint32_t)(micros() - last) > RPM_STALE_MS * 1000UL) return 0.0f;
  uint32_t dt = (uint32_t)(last - prev);
  if (!dt) return 0.0f;
  return 60000000.0f / ((float)dt * (float)RPM_PPR);
}

static const char* stateName(State s) {
  switch (s) {
    case ST_INIT:      return "INIT";
    case ST_IDLE:      return "IDLE";
    case ST_STARTING:  return "STARTING";
    case ST_RUNNING:   return "RUNNING";
    case ST_STOPPING:  return "STOPPING";
    case ST_FAULT:     return "FAULT";
    case ST_COMM_LOST: return "COMM_LOST";
  }
  return "?";
}

// ===========================================================================
// Modbus helpers
// ===========================================================================
static void noteComms(bool ok) {
  if (ok) { commErrors = 0; if (state == ST_COMM_LOST) state = ST_IDLE; }
  else {
    totalErrors++;
    if (commErrors < 255) commErrors++;
    if (commErrors >= MAX_COMM_ERRORS && state != ST_COMM_LOST) {
      state   = ST_COMM_LOST;
      settled = false;
    }
  }
}

static uint16_t hzToRef(float hz) {
  if (hz < 0) hz = 0;
  if (hz > limitHz) hz = limitHz;
  float v = (hz / REF_MAX_HZ) * REF_FULLSCALE;
  if (v > REF_FULLSCALE) v = REF_FULLSCALE;
  return (uint16_t)(v + 0.5f);
}

// Write control word + reference as ONE FC16 transaction. They are adjacent
// registers, so this is atomic from the drive's point of view -- the drive
// never sees a new control word paired with a stale reference.
// (With USE_REF2 the pair is 40001+40003, so it takes 3 registers; 40002 is
//  written as 0 which is harmless because REF1 is not the active reference.)
static bool writeCommand(uint16_t cw, uint16_t ref) {
#if USE_REF2
  const int count = 3;
#else
  const int count = 2;
#endif
  if (!ModbusRTUClient.beginTransmission(SLAVE_ID, HOLDING_REGISTERS,
                                         REG_CONTROL_WORD, count)) return false;
  ModbusRTUClient.write(cw);
#if USE_REF2
  ModbusRTUClient.write((uint16_t)0);
#endif
  ModbusRTUClient.write(ref);
  return ModbusRTUClient.endTransmission() == 1;
}

// One FC3 pulls status word and all three actuals in a single frame.
static bool readBlock() {
  if (!ModbusRTUClient.requestFrom(SLAVE_ID, HOLDING_REGISTERS,
                                   REG_STATUS_WORD, 4)) return false;
  uint16_t v[4] = {0, 0, 0, 0};
  for (int i = 0; i < 4 && ModbusRTUClient.available(); i++)
    v[i] = (uint16_t)ModbusRTUClient.read();

  statusWord = v[0];
  // Group 01 operating data is scaled x100 for frequency, x10 for current and
  // power on this firmware. Verify against the keypad on first bring-up.
  actualHz   = (int16_t)v[1] / 100.0f;
  actualAmps = (int16_t)v[2] / 10.0f;
  actualKw   = (int16_t)v[3] / 10.0f;
  return true;
}

// ===========================================================================
// Commands
// ===========================================================================
static void doStop() {
  state   = ST_STOPPING;
  settled = false;
}

static bool doRun(const char **why) {
  if (state == ST_FAULT)     { *why = "drive tripped, send RESET"; return false; }
  if (state == ST_COMM_LOST) { *why = "no Modbus link to drive";   return false; }
  if (!(statusWord & SW_REMOTE)) {
    *why = "drive not in REMOTE (check keypad LOC/REM and par 1001/1102)";
    return false;
  }
  state     = ST_STARTING;
  startedAt = millis();
  settled   = false;
  return true;
}

static void doReset() {
  writeCommand(CW_RESET, 0);
  delay(50);
  writeCommand(CW_PREPARE, 0);
  faultCode  = 0;
  commErrors = 0;
  state      = ST_IDLE;
  settled    = false;
}

static void printTelemetry() {
  Serial.print("T,");
  Serial.print(millis());          Serial.print(',');
  Serial.print(stateName(state));  Serial.print(',');
  Serial.print(setpointHz, 2);     Serial.print(',');
  Serial.print(actualHz, 2);       Serial.print(',');
  Serial.print(actualAmps, 2);     Serial.print(',');
  Serial.print(actualKw, 2);       Serial.print(',');
  Serial.print(statusWord, HEX);   Serial.print(',');
  Serial.print(settled ? 1 : 0);   Serial.print(',');
  Serial.print(faultCode);         Serial.print(',');
  Serial.print(totalErrors);       Serial.print(',');
  // v5 additions, APPENDED so a v2/v3 host truncates rather than misparses.
  uint32_t p, last, prev, rej;
  rpmRead(&p, &last, &prev, &rej);
  Serial.print(p);                 Serial.print(',');
  Serial.print(last);              Serial.print(',');
  Serial.println(rpmInstant(), 1);
}

// ===========================================================================
// PARAMETER ACCESS  --  RD / WR / UNLOCK
// ===========================================================================
//
// The host's line protocol was command-shaped (HZ, RUN, STAT) and could not
// reach a drive parameter at all. That blocked selftest, the ramp-time slew
// check, the comm counters, and reading par 1105 -- the parameter whose
// misreading makes every commanded speed wrong by exactly ten.
//
// READS are unconditional. A read cannot change anything.
//
// WRITES are persistent and have no undo -- identical to editing on the
// keypad. So the allowlist lives HERE, in firmware, not in the host. A host
// config file can be copied, edited in a hurry and applied without being
// read; firmware cannot be talked out of a refusal.
//
// Three groups are refused outright, at any time, with no unlock:
//
//   group 53 (5302-5399)  The serial settings of the very bus this command
//                         arrives on. Write parity wrong and the link dies
//                         mid-write -- and group 53 is read at boot only, so
//                         the damage surfaces at the next power cycle, from
//                         a drive that can then only be reached by keypad.
//
//   3018 / 3019           The comm-loss watchdog. This is the mechanism that
//                         makes a laptop commanding a 15 HP fan acceptable.
//                         It is exactly the parameter somebody disables "just
//                         for testing" and never restores.
//
//   group 99 (9900-9999)  The motor model. A wrong nominal current disables
//                         the drive's thermal protection: hardware damage,
//                         not bad data.
//
// Everything else needs an explicit UNLOCK first, which lapses on a timer and
// on any RUN. Arming and firing should not be the same keystroke.

static const uint32_t UNLOCK_MS = 120000;   // 2 minutes, then re-arm
static uint32_t       unlockedAt = 0;

static bool writeUnlocked() {
  return unlockedAt && (millis() - unlockedAt) < UNLOCK_MS;
}

// Returns NULL if the parameter may be written, else the reason it may not.
static const char *writeRefusal(int par) {
  if (par >= 5302 && par <= 5399)
    return "group 53 is the serial config of this very link - keypad only";
  if (par == 3018 || par == 3019)
    return "3018/3019 are the comm-loss watchdog - keypad only";
  if (par >= 9900 && par <= 9999)
    return "group 99 is the motor model - keypad only, wrong values damage it";
  if (par < 100 || par > 9999)
    return "parameter out of range";
  if (par < 500)
    return "groups 01-04 are read-only (operating data and fault history)";
  if (!writeUnlocked())
    return "locked - send UNLOCK first (lapses after 120 s and on RUN)";
  return NULL;
}

static void doRead(const char *arg) {
  if (!arg) { Serial.println("ERR RD needs a parameter number"); return; }
  int par = atoi(arg);
  if (par < 100 || par > 9999) { Serial.println("ERR parameter out of range"); return; }
  // Parameter N lives at holding register N-1.
  long v = ModbusRTUClient.holdingRegisterRead(SLAVE_ID, par - 1);
  noteComms(v >= 0);
  if (v < 0) { Serial.println("ERR read failed"); return; }
  Serial.print("OK RD "); Serial.print(par); Serial.print(' '); Serial.println(v);
}

static void doWrite(const char *arg) {
  if (!arg) { Serial.println("ERR WR needs <par> <value>"); return; }
  char *sp = strchr((char *)arg, ' ');
  if (!sp) { Serial.println("ERR WR needs <par> <value>"); return; }
  *sp = 0;
  int par = atoi(arg);
  long val = atol(sp + 1);

  const char *no = writeRefusal(par);
  if (no) { Serial.print("ERR refused "); Serial.print(par); Serial.print(" - ");
            Serial.println(no); return; }
  if (state == ST_RUNNING) {
    Serial.println("ERR refused - the fan is running; stop it first");
    return;
  }
  if (val < 0 || val > 65535) { Serial.println("ERR value out of range"); return; }

  long before = ModbusRTUClient.holdingRegisterRead(SLAVE_ID, par - 1);
  int  okw    = ModbusRTUClient.holdingRegisterWrite(SLAVE_ID, par - 1,
                                                     (uint16_t)val);
  long after  = ModbusRTUClient.holdingRegisterRead(SLAVE_ID, par - 1);
  noteComms(okw == 1 && after >= 0);
  if (okw != 1) { Serial.println("ERR write failed"); return; }

  // Always read back. A drive silently clamps out-of-range values and
  // refuses some parameters while running, both of which look like success
  // on the wire. The host is told what the drive is ACTUALLY holding.
  Serial.print("OK WR "); Serial.print(par); Serial.print(' ');
  Serial.print(before); Serial.print(" -> "); Serial.println(after);
  if (after != val) {
    Serial.print("# WARNING par "); Serial.print(par);
    Serial.print(" holds "); Serial.print(after);
    Serial.print(", not the "); Serial.print(val); Serial.println(" requested");
  }
}

static void handleLine(char *line) {
  // trim
  while (*line == ' ' || *line == '\t') line++;
  int n = strlen(line);
  while (n > 0 && (line[n-1] == ' ' || line[n-1] == '\r')) line[--n] = 0;
  if (!n) return;

  lastHostMsg = millis();

  char *sp = strchr(line, ' ');
  char *arg = NULL;
  if (sp) { *sp = 0; arg = sp + 1; }
  for (char *p = line; *p; p++) *p = toupper(*p);

  if (!strcmp(line, "PING")) {
    Serial.println("OK PING");
  }
  else if (!strcmp(line, "ID")) {
    Serial.println("OK ID acs550-pmc 5.2 RD/WR RPM");
  }
  else if (!strcmp(line, "HZ") || !strcmp(line, "PCT")) {
    if (!arg) { Serial.println("ERR missing argument"); return; }
    float v = atof(arg);
    if (!strcmp(line, "PCT")) v = v / 100.0f * REF_MAX_HZ;
    if (v < 0)        v = 0;
    if (v > limitHz)  v = limitHz;
    if (fabs(v - setpointHz) > 0.005f) { settled = false; inBandSince = 0; }
    setpointHz = v;
    Serial.print("OK HZ "); Serial.println(setpointHz, 2);
  }
  else if (!strcmp(line, "RUN")) {
    unlockedAt = 0;             // arming and running are not the same session
    const char *why = "";
    if (doRun(&why)) Serial.println("OK RUN");
    else { Serial.print("ERR "); Serial.println(why); }
  }
  else if (!strcmp(line, "STOP"))  { doStop();  Serial.println("OK STOP"); }
  else if (!strcmp(line, "COAST")) {
    state = ST_STOPPING; settled = false;
    writeCommand(CW_COAST, 0);
    Serial.println("OK COAST");
  }
  else if (!strcmp(line, "RESET")) { doReset(); Serial.println("OK RESET"); }
  else if (!strcmp(line, "STAT"))  { Serial.println("OK STAT"); printTelemetry(); }
  else if (!strcmp(line, "STREAM")) {
    streamMs = arg ? (uint32_t)atol(arg) : 0;
    Serial.print("OK STREAM "); Serial.println(streamMs);
  }
  else if (!strcmp(line, "LIMIT")) {
    float v = arg ? atof(arg) : MAX_HZ;
    if (v < 0)      v = 0;
    if (v > MAX_HZ) v = MAX_HZ;
    limitHz = v;
    if (setpointHz > limitHz) setpointHz = limitHz;
    Serial.print("OK LIMIT "); Serial.println(limitHz, 2);
  }
  else if (!strcmp(line, "RPM?")) {
    uint32_t p, last, prev, rej;
    rpmRead(&p, &last, &prev, &rej);
    Serial.print("OK RPM ");   Serial.print(p);
    Serial.print(' ');         Serial.print(last);
    Serial.print(' ');         Serial.print(rpmInstant(), 1);
    // The live pin level, for proving the wiring by hand with the tunnel off.
    Serial.print(' ');         Serial.print(rpmRaw);
    Serial.print(' ');         Serial.print(rej);
    Serial.print(' ');         Serial.print(rpmReversals);
    Serial.println(rpmReversals > 4 ? "  <-- ENC0-B IS FLOATING, strap it "
                                      "to a rail" : "");
  }
  else if (!strcmp(line, "RD")) { doRead(arg); }
  else if (!strcmp(line, "WR")) { doWrite(arg); }
  else if (!strcmp(line, "UNLOCK")) {
    unlockedAt = millis();
    Serial.println("OK UNLOCK writes enabled for 120 s");
  }
  else if (!strcmp(line, "LOCK")) {
    unlockedAt = 0;
    Serial.println("OK LOCK");
  }
  else if (!strcmp(line, "WD")) {
    watchdogMs = arg ? (uint32_t)atol(arg) : 0;
    Serial.print("OK WD "); Serial.println(watchdogMs);
  }
  else {
    Serial.print("ERR unknown command "); Serial.println(line);
  }
}

// ===========================================================================
void setup() {
  Serial.begin(115200);
  uint32_t t0 = millis();
  while (!Serial && millis() - t0 < 3000) { }   // don't block if headless

  MachineControl_RS485Comm.setModeRS232(false);   // RS-485, not RS-232
  MachineControl_RS485Comm.setFullDuplex(false);  // 2-wire half duplex
  MachineControl_RS485Comm.setABTerm(true);       // 120R on; PMC is a bus end
  MachineControl_RS485Comm.setYZTerm(false);
  MachineControl_RS485Comm.setSlew(false);
  MachineControl_RS485Comm.begin(BAUD, SERIAL_CFG, PRE_DELAY_US, POST_DELAY_US);

  if (!ModbusRTUClient.begin(MachineControl_RS485Comm, BAUD, SERIAL_CFG)) {
    Serial.println("# FATAL Modbus RTU client failed to start");
    while (1) delay(1000);
  }
  ModbusRTUClient.setTimeout(MODBUS_TIMEOUT);

  // v5: rotor speed. X1 counts one edge per cycle, which is what a single
  // magnet gives. We claim no pins — the library's global EncoderClass owns
  // them already, and claiming them twice is what hung 5.0 and 5.1.
  MachineControl_Encoders.setEncoding(RPM_ENC_CH, QEI::X1_ENCODING);
  MachineControl_Encoders.reset(RPM_ENC_CH);
  rpmRaw = 0;

  Serial.println("# acs550-pmc 5.2 ready (RD/WR, rotor rpm on ENC0-A)");
  Serial.println("# T,t_ms,state,sp_hz,act_hz,amps,kw,sw,settled,fault,errs,"
                 "rpm_pulses,rpm_last_us,rotor_rpm");
  Serial.println("# rotor: 1 magnet/rev on PJ_8, INPUT_PULLUP, "
                 "2 ms debounce. Send RPM? and pass the magnet by hand.");

  writeCommand(CW_PREPARE, 0);
  state       = ST_IDLE;
  lastHostMsg = millis();
}

void loop() {
  // ---- host intake (non-blocking) ----
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\n') { rxBuf[rxLen] = 0; handleLine(rxBuf); rxLen = 0; }
    else if (rxLen < sizeof(rxBuf) - 1) rxBuf[rxLen++] = c;
  }

  uint32_t now = millis();

  // ---- host watchdog: laptop dies -> tunnel ramps down ----
  if (watchdogMs && (state == ST_RUNNING || state == ST_STARTING) &&
      (now - lastHostMsg > watchdogMs)) {
    Serial.println("# host watchdog expired, ramping down");
    doStop();
  }

  // Sample the encoder on EVERY pass, before the poll gate. The gate makes
  // loop() return early most of the time, so this runs thousands of times a
  // second; putting it after the gate would sample at 10 Hz and miss magnets.
  rpmSample();

  if (now - lastPoll < POLL_MS) return;
  lastPoll = now;

  // ---- decide control word + reference for this cycle ----
  uint16_t cw;
  bool running = (state == ST_RUNNING || state == ST_STARTING);
  switch (state) {
    case ST_STARTING:
      // Hold CW_STOP for the first cycle so the drive passes cleanly through
      // "ready to operate" before we assert RUN. No blocking delay needed.
      cw = (now - startedAt < POLL_MS) ? CW_STOP : CW_RUN;
      if (now - startedAt > 500) state = ST_RUNNING;
      break;
    case ST_RUNNING:   cw = CW_RUN;     break;
    case ST_STOPPING:  cw = CW_STOP;    break;
    case ST_FAULT:     cw = CW_STOP;    break;
    default:           cw = CW_PREPARE; break;
  }

  bool ok = writeCommand(cw, hzToRef(running ? setpointHz : 0.0f));
  ok = readBlock() && ok;
  noteComms(ok);

  // ---- interpret ----
  if (ok) {
    if (statusWord & SW_TRIPPED) {
      if (state != ST_FAULT) {
        state   = ST_FAULT;
        settled = false;
        long f = ModbusRTUClient.holdingRegisterRead(SLAVE_ID, REG_LAST_FAULT);
        faultCode = (f < 0) ? 0 : (uint16_t)f;
        Serial.print("# drive tripped, last fault "); Serial.println(faultCode);
      }
    }
    if (state == ST_STOPPING && actualHz < 0.2f) { state = ST_IDLE; }

    // settle detection: in band continuously for SETTLE_DWELL_MS
    if (state == ST_RUNNING && fabs(actualHz - setpointHz) <= SETTLE_TOL_HZ) {
      if (!inBandSince) inBandSince = now;
      if (now - inBandSince >= SETTLE_DWELL_MS) settled = true;
    } else {
      inBandSince = 0;
      settled     = false;
    }
  }

  if (streamMs && (now - lastStream >= streamMs)) {
    lastStream = now;
    printTelemetry();
  }
}
