/*
 * ============================================================================
 *  acs550_pmc.ino   -- v2
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
 *    ID            -> OK ID acs550-pmc 2.0
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
 *  Telemetry line:
 *    T,<t_ms>,<state>,<sp_hz>,<act_hz>,<amps>,<kw>,<sw_hex>,<settled>,<fault>,<errs>
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
  Serial.println(totalErrors);
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
    Serial.println("OK ID acs550-pmc 2.0");
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

  Serial.println("# acs550-pmc 2.0 ready");
  Serial.println("# T,t_ms,state,sp_hz,act_hz,amps,kw,sw,settled,fault,errs");

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
