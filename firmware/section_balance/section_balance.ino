/*
 * section_balance.ino — two-axis force balance for the blade-section test.
 * Arduino Nano 33 BLE Sense, Rev1 (LSM9DS1) or Rev2 (BMI270), USB serial to the host.
 *
 *   2 x HX711 + bar load cells   drag and lift, at the HX711's own rate (10 or 80 Hz)
 *   on-board accelerometer       BURST mode, about 1 kHz, for vortex shedding
 *   LPS22HB                      barometric pressure, for air density
 *
 * Host side: scripts/section_balance_logger.py records sessions and keeps the
 * calibration; scripts/section_balance_analyze.py turns them into Cd and Cl.
 * Build, wiring photos-to-take and the procedure: firmware/section_balance/README.md.
 *
 * ── WHAT THIS BOARD TOUCHES ──────────────────────────────────────────────
 * Its USB cable and two HX711 modules, nothing else. It is not wired to the
 * PMC, the drive, the Chroma or the turbine. It cannot command the fan, and no
 * part of the rig's safety chain (E-stop, drive comm watchdog, PMC host
 * watchdog, load interlock) depends on it or is changed by it. The board, the
 * HX711 modules and their cables sit OUTSIDE the test section, tied down:
 * nothing of this assembly may be able to travel into the fan.
 *
 * ⚠ If this is the tunnel node's board, flashing this REPLACES tunnel_node.
 *   Re-flash firmware/tunnel_node/ afterwards for the turbine runs.
 *
 * ── WIRING ───────────────────────────────────────────────────────────────
 *     HX711 "drag"   VCC -> 3V3   GND -> GND   DT (DOUT) -> D2   SCK -> D3
 *     HX711 "lift"   VCC -> 3V3   GND -> GND   DT (DOUT) -> D4   SCK -> D5
 *     bar load cell -> HX711   E+ red, E- black, A- white, A+ green
 *                              (the common colour code; check the cell's sheet)
 *
 *   3V3, NOT 5 V. The nRF52840's pins are not 5 V tolerant, and on the common
 *   single-supply HX711 module DOUT swings to VCC. On a module with separate
 *   VDD (logic) and VCC (analog) pins, VDD must be 3V3. The Nano's +5V pin is
 *   not connected to USB 5 V unless its VUSB jumper is soldered, so 3V3 for
 *   both is also the only supply that is there without modifying the board.
 *
 *   A4/A5 (Wire) are left free for a pitot sensor (cfd/MEASUREMENTS_NEEDED.md
 *   §3), D0/D1 for Serial1. The on-board sensors are on Wire1.
 *
 *   Rate: the usual HX711 module ties RATE to GND, giving 10 Hz; RATE high
 *   gives 80 Hz. The firmware cannot set it. RATE? reports what is measured.
 *
 *   Sign and scale are not assumed anywhere: the calibration matrix carries
 *   both, including a cell mounted the other way round.
 *
 * ── PROTOCOL ─────────────────────────────────────────────────────────────
 * Same shape as the PMC and the tunnel node: one line in, one OK/ERR line out,
 * case-insensitive verbs, 115200 8N1, diagnostics prefixed '#'.
 *
 *   ID                 -> OK ID section-balance 1.0 drag=ok lift=ok imu=LSM9DS1 baro=LPS22HB
 *   START              -> OK START, then the header line H,... and one F,... row
 *                         per conversion pair (see ROWS)
 *   STOP               -> OK STOP rows <seq>
 *   RAW?               -> OK RAW <drag_counts> <lift_counts>     one fresh pair
 *   TARE [n]           -> OK TARE <drag> <lift> sd <sd_d> <sd_l> n <n_d> <n_l>
 *                         wind OFF, no load; sets the zero of the live N columns
 *   CAL D|L <g> [n]    -> OK CAL D k <k_dd> <k_ld> F_N <F> n <n>
 *                         <g> grams hanging on the +drag (or +lift) axis, after
 *                         TARE with no load; fills one column of K
 *   SCALE?             -> OK SCALE <k_dd> <k_dl> <k_ld> <k_ll> tare <d0> <l0>
 *   SCALE a b c d      -> set K (counts per newton) as the host recorded it
 *   ALPHA <deg>        -> OK ALPHA <deg>   label carried in every row; ALPHA? reads it
 *   MARK <label>       -> OK MARK <label> <micros>              time sync
 *   RATE?              -> OK RATE rows_hz <r> drag_hz <d> lift_hz <l> imu_hz <i>
 *   AMB?               -> OK AMB <board_degC> <Pa>
 *   BURST <n>          accelerometer capture, same format as tunnel_node
 *   HELP | ?           -> OK HELP ...
 *
 * K is the sensitivity matrix, counts per newton:
 *
 *     drag_counts - drag_tare = k_dd * F_drag + k_dl * F_lift
 *     lift_counts - lift_tare = k_ld * F_drag + k_ll * F_lift
 *
 * The off-diagonal terms are the cross-talk. The live N columns are
 * K^-1 (counts - tare): a convenience for the operator. THE RECORD IS THE RAW
 * COUNTS. The analysis fits K again from multi-point calibration dwells,
 * with its uncertainty, and takes zeros from wind-off dwells, not from TARE.
 *
 * ── ROWS ─────────────────────────────────────────────────────────────────
 *     H,t_us,seq,alpha_deg,drag_counts,lift_counts,drag_n,lift_n,flags
 *     F,<t_us>,<seq>,<alpha>,<drag>,<lift>,<drag_N>,<lift_N>,<flags>
 *
 *   t_us   micros() when the row was assembled; wraps every 71.6 min
 *   seq    row counter since boot; a reset means the board rebooted
 *   flags  1 drag fresh · 2 lift fresh · 4 drag saturated · 8 lift saturated
 *
 * A row is emitted when every present channel has a new conversion, or after
 * STALE_MS with whatever is fresh. The two HX711 run on their own oscillators,
 * so a pair is skewed by up to one conversion period (100 ms at 10 Hz). That is
 * irrelevant to a dwell mean and is why the load cells are not the vibration
 * sensor: the accelerometer is.
 *
 * ── CALIBRATION STORAGE: ON THE HOST ─────────────────────────────────────
 * K lives in RAM here and in data/section_balance.json on the host, which the
 * logger re-sends with SCALE on every connect, the same pattern tunnel_node.py
 * uses for its temperature OFFSET. Flash was considered and not used:
 * Arduino_KVStore has no nRF52840 implementation, and mbed's TDBStore on
 * internal flash would need a hand-picked region inside what the linker
 * script gives the sketch (FLASH 0x10000..0x100000), which a later, larger
 * sketch could silently overwrite. A calibration also needs a date, masses and
 * a method next to it, and a JSON file in the repo keeps those.
 *
 * ── I2C CLOCK: SET LAST ──────────────────────────────────────────────────
 * mbed's Wire1.begin() deletes and re-creates the bus object at the mbed
 * default of 100 kHz, and BARO.begin() and the BMI270 library both call it.
 * So setClock(400000) is the LAST thing setup() does to Wire1. (Read from the
 * core's Wire.cpp; tunnel_node.ino sets the clock before BARO.begin(), which
 * would put its IMU reads at 100 kHz. Not measured here.)
 *
 * Libraries: HX711 Arduino Library 0.7.5 (bogde), Arduino_LPS22HB 1.0.2,
 *            Arduino_BMI270_BMM150 1.2.3 (used on Rev2 boards only)
 * Board:     arduino:mbed_nano:nano33ble (core 4.6.0)
 */

#include <Wire.h>
#include <HX711.h>
#include <Arduino_LPS22HB.h>
#include <Arduino_BMI270_BMM150.h>

static const char *VERSION = "section-balance 1.0";

/* ── pins ─────────────────────────────────────────────────────────────── */
static const uint8_t PIN_DRAG_DOUT = 2;
static const uint8_t PIN_DRAG_SCK  = 3;
static const uint8_t PIN_LIFT_DOUT = 4;
static const uint8_t PIN_LIFT_SCK  = 5;

static const uint8_t  HX_GAIN   = 128;      // channel A, gain 128
static const uint32_t STALE_MS  = 400;      // emit with one channel stale after this
static const long     HX_SAT_HI = 8388607;  // 0x7FFFFF: the HX711 clips here
static const long     HX_SAT_LO = -8388608; // 0x800000
static const float    G_STD     = 9.80665f; // standard gravity, m/s^2 (assumed;
                                            // local g differs by ~0.04 %)

static const uint8_t FLAG_DRAG_FRESH = 1, FLAG_LIFT_FRESH = 2;
static const uint8_t FLAG_DRAG_SAT   = 4, FLAG_LIFT_SAT   = 8;

static const char *ROW_HEADER =
    "H,t_us,seq,alpha_deg,drag_counts,lift_counts,drag_n,lift_n,flags";

/* ── load-cell channels ───────────────────────────────────────────────── */
struct Chan {
  HX711    hx;
  uint8_t  dout, sck;
  bool     present;
  long     raw;        // last conversion, counts
  bool     fresh;      // new since the last row
  uint32_t lastUs;     // micros() of the last conversion
  float    periodUs;   // running mean of the conversion interval
  uint32_t count;
};

static Chan chD = {HX711(), PIN_DRAG_DOUT, PIN_DRAG_SCK, false, 0, false, 0, 0, 0};
static Chan chL = {HX711(), PIN_LIFT_DOUT, PIN_LIFT_SCK, false, 0, false, 0, 0, 0};

/* K, counts per newton, row = channel (drag, lift), column = force (drag, lift).
   All zero means "not calibrated": the live N columns then print nan, which is
   honest, rather than counts divided by a placeholder that look like newtons. */
static float K[2][2]    = {{0, 0}, {0, 0}};
static float Kinv[2][2] = {{0, 0}, {0, 0}};
static bool  haveK      = false;
static float tareCounts[2] = {0, 0};
static bool  haveTare   = false;

static bool     streaming    = false;
static uint32_t seq          = 0;
static uint32_t pendingSince = 0;     // millis() when the first fresh value arrived
static float    alphaDeg     = 0.0f;
static float    rowPeriodUs  = 0.0f;
static uint32_t lastRowUs    = 0;

/* ── on-board sensors (Wire1) ─────────────────────────────────────────── */
enum ImuKind { IMU_NONE, IMU_LSM9DS1, IMU_BMI270 };
static ImuKind imuKind = IMU_NONE;
static bool    baroOk  = false;
static float   imuHz   = 0.0f;        // measured at boot, not claimed

/* LSM9DS1 accel/gyro die. Accelerometer-only mode (gyro powered down), ODR
   952 Hz, +-4 g. One 7-byte read from STATUS_REG (0x27) returns the status
   byte and OUT_X_L_XL..OUT_Z_H_XL (0x28..0x2D), so a sample is stored only
   when XLDA says it is new: one stored sample per ODR period, no duplicates. */
static const uint8_t LSM_AG       = 0x6B;
static const uint8_t LSM_WHO_AM_I = 0x0F;      // expect 0x68
static const uint8_t LSM_CTRL1_G  = 0x10;
static const uint8_t LSM_CTRL6_XL = 0x20;
static const uint8_t LSM_CTRL8    = 0x22;
static const uint8_t LSM_STATUS   = 0x27;
static const float   LSM_G_PER_LSB = 0.000122f; // +-4 g

/* BMI270 (Rev2). The library uploads the 8 kB config file; this subclass
   replaces its sensor setup with accelerometer only, ODR 1600 Hz, +-4 g,
   performance mode, advanced power save off. Polled with one 15-byte read
   from STATUS (0x03) to ACC_Z_MSB (0x11); stored when drdy_acc is set. If the
   loop polls slower than 1600 Hz, samples are skipped, never duplicated, and
   the timestamps say so. */
static const uint8_t BMI_ADDR      = 0x68;
static const uint8_t BMI_CHIP_ID   = 0x00;     // expect 0x24
static const uint8_t BMI_STATUS    = 0x03;
static const float   BMI_G_PER_LSB = 1.0f / 8192.0f; // +-4 g

class BalanceBMI270 : public BoschSensorClass {
 public:
  explicit BalanceBMI270(TwoWire &w) : BoschSensorClass(w) {}
 protected:
  using BoschSensorClass::configure_sensor;
  int8_t configure_sensor(struct bmi2_dev *dev) override {
    struct bmi2_sens_config c;
    c.type = BMI2_ACCEL;
    c.cfg.acc.odr         = BMI2_ACC_ODR_1600HZ;
    c.cfg.acc.bwp         = BMI2_ACC_NORMAL_AVG4;
    c.cfg.acc.filter_perf = BMI2_PERF_OPT_MODE;
    c.cfg.acc.range       = BMI2_ACC_RANGE_4G;
    int8_t r = bmi2_set_sensor_config(&c, 1, dev);
    if (r != BMI2_OK) return r;
    uint8_t list[1] = {BMI2_ACCEL};
    r = bmi2_sensor_enable(list, 1, dev);
    if (r != BMI2_OK) return r;
    return bmi2_set_adv_power_save(BMI2_DISABLE, dev);
  }
};
static BalanceBMI270 bmi(Wire1);

/* Burst buffer: 10 bytes per sample. 4000 samples is about 4 s at 1 kHz,
   0.25 Hz resolution, and the same ceiling as tunnel_node so both feed the
   same host code. For a longer window take several bursts. */
#define BURST_MAX 4000
static int16_t  burstA[BURST_MAX][3];
static uint32_t burstT[BURST_MAX];

/* ── I2C helpers ──────────────────────────────────────────────────────── */
static int i2cRead1(uint8_t addr, uint8_t reg) {
  Wire1.beginTransmission(addr);
  Wire1.write(reg);
  if (Wire1.endTransmission(false) != 0) return -1;
  if (Wire1.requestFrom(addr, (uint8_t)1) != 1) return -1;
  return Wire1.read();
}

static bool i2cWrite1(uint8_t addr, uint8_t reg, uint8_t val) {
  Wire1.beginTransmission(addr);
  Wire1.write(reg);
  Wire1.write(val);
  return Wire1.endTransmission() == 0;
}

static bool i2cReadN(uint8_t addr, uint8_t reg, uint8_t *buf, uint8_t n) {
  Wire1.beginTransmission(addr);
  Wire1.write(reg);
  if (Wire1.endTransmission(false) != 0) return false;
  if (Wire1.requestFrom(addr, n) != n) return false;
  for (uint8_t i = 0; i < n; i++) buf[i] = (uint8_t)Wire1.read();
  return true;
}

/* Returns true and fills a[3] (board axes, raw LSB) only when the sensor has
   a sample that has not been returned before. */
static bool imuPoll(int16_t *a) {
  uint8_t b[15];
  if (imuKind == IMU_LSM9DS1) {
    if (!i2cReadN(LSM_AG, LSM_STATUS, b, 7)) return false;
    if (!(b[0] & 0x01)) return false;                       // XLDA
    for (uint8_t k = 0; k < 3; k++)
      a[k] = (int16_t)((b[2 + 2 * k] << 8) | b[1 + 2 * k]);
    return true;
  }
  if (imuKind == IMU_BMI270) {
    if (!i2cReadN(BMI_ADDR, BMI_STATUS, b, 15)) return false;
    if (!(b[0] & 0x80)) return false;                       // drdy_acc
    int16_t x = (int16_t)((b[10] << 8) | b[9]);
    int16_t y = (int16_t)((b[12] << 8) | b[11]);
    int16_t z = (int16_t)((b[14] << 8) | b[13]);
    /* The Arduino library's Nano 33 BLE remap (x = -y, y = -x), so both board
       revisions report the same axes. Taken from the library, not verified on
       a board. */
    a[0] = (int16_t)(-y);
    a[1] = (int16_t)(-x);
    a[2] = z;
    return true;
  }
  return false;
}

static float imuScale() {
  return imuKind == IMU_BMI270 ? BMI_G_PER_LSB : LSM_G_PER_LSB;
}

static const char *imuName() {
  return imuKind == IMU_LSM9DS1 ? "LSM9DS1" : imuKind == IMU_BMI270 ? "BMI270" : "none";
}

static void imuInit() {
  if (i2cRead1(LSM_AG, LSM_WHO_AM_I) == 0x68) {
    /* BDU stops a fast reader pairing the high byte of one sample with the
       low byte of the next; IF_ADD_INC enables the block read. */
    bool ok = i2cWrite1(LSM_AG, LSM_CTRL8, 0x44);           // BDU | IF_ADD_INC
    ok = ok && i2cWrite1(LSM_AG, LSM_CTRL1_G, 0x00);        // gyro off
    ok = ok && i2cWrite1(LSM_AG, LSM_CTRL6_XL, (0b110 << 5) | (0b10 << 3)); // 952 Hz, +-4 g
    delay(20);
    if (ok) imuKind = IMU_LSM9DS1;
    return;
  }
  if (i2cRead1(BMI_ADDR, BMI_CHIP_ID) == 0x24) {
    if (bmi.begin(BOSCH_ACCELEROMETER_ONLY)) imuKind = IMU_BMI270;
  }
}

/* Measure, do not predict: stored samples per second over 200 samples. */
static float imuBenchmark() {
  if (imuKind == IMU_NONE) return 0.0f;
  int16_t a[3];
  uint32_t t0 = micros(), got = 0, deadline = millis() + 2000;
  while (got < 200 && (int32_t)(deadline - millis()) > 0) {
    if (imuPoll(a)) got++;
  }
  uint32_t dt = micros() - t0;
  return (got && dt) ? got * 1e6f / (float)dt : 0.0f;
}

/* ── load cells ───────────────────────────────────────────────────────── */
static bool probe(Chan &c, uint32_t ms) {
  uint32_t t0 = millis();
  while (millis() - t0 < ms) {
    if (c.hx.is_ready()) return true;     // DOUT low = a conversion is waiting
    delay(1);
  }
  return false;                           // DOUT held high by the pull-up (setup): no module
}

static void pollChan(Chan &c) {
  if (!c.present || !c.hx.is_ready()) return;
  c.raw = c.hx.read();                    // returns at once: is_ready() was true
  uint32_t now = micros();
  if (c.count) {
    float dt = (float)(uint32_t)(now - c.lastUs);
    c.periodUs = c.periodUs > 0 ? 0.9f * c.periodUs + 0.1f * dt : dt;
  }
  c.lastUs = now;
  c.fresh = true;
  c.count++;
}

static bool saturated(long v) { return v >= HX_SAT_HI || v <= HX_SAT_LO; }

/* Mean and standard deviation of n fresh conversions per present channel.
   Blocks; false if a present channel stops converting before timeoutMs. */
static bool collect(uint16_t n, double mean[2], double sd[2], uint16_t got[2],
                    uint32_t timeoutMs) {
  double m[2] = {0, 0}, s2[2] = {0, 0};
  got[0] = got[1] = 0;
  Chan *ch[2] = {&chD, &chL};
  for (int k = 0; k < 2; k++) ch[k]->fresh = false;
  uint32_t t0 = millis();
  while (true) {
    bool done = true;
    for (int k = 0; k < 2; k++) {
      if (!ch[k]->present) continue;
      if (got[k] < n) {
        done = false;
        pollChan(*ch[k]);
        if (ch[k]->fresh) {
          ch[k]->fresh = false;
          got[k]++;
          double x = (double)ch[k]->raw, d = x - m[k];   // Welford
          m[k] += d / got[k];
          s2[k] += d * (x - m[k]);
        }
      }
    }
    if (done) break;
    if (millis() - t0 > timeoutMs) return false;
  }
  for (int k = 0; k < 2; k++) {
    mean[k] = m[k];
    sd[k] = got[k] > 1 ? sqrt(s2[k] / (got[k] - 1)) : 0.0;
  }
  return true;
}

static uint32_t collectTimeoutMs(uint16_t n) {
  /* 10 Hz is the slowest an HX711 runs; allow twice that plus a second. */
  return (uint32_t)n * 200UL + 1000UL;
}

static bool invertK() {
  float det = K[0][0] * K[1][1] - K[0][1] * K[1][0];
  float scale = fabsf(K[0][0] * K[1][1]) + fabsf(K[0][1] * K[1][0]);
  if (scale <= 0.0f || fabsf(det) < 1e-6f * scale) { haveK = false; return false; }
  Kinv[0][0] =  K[1][1] / det;
  Kinv[0][1] = -K[0][1] / det;
  Kinv[1][0] = -K[1][0] / det;
  Kinv[1][1] =  K[0][0] / det;
  haveK = true;
  return true;
}

static void liveForces(long rd, long rl, float *fd, float *fl) {
  if (!haveK) { *fd = NAN; *fl = NAN; return; }
  float dd = (float)rd - tareCounts[0], dl = (float)rl - tareCounts[1];
  *fd = Kinv[0][0] * dd + Kinv[0][1] * dl;
  *fl = Kinv[1][0] * dd + Kinv[1][1] * dl;
}

/* ── rows ─────────────────────────────────────────────────────────────── */
static void emitRow() {
  uint8_t flags = 0;
  if (chD.fresh) flags |= FLAG_DRAG_FRESH;
  if (chL.fresh) flags |= FLAG_LIFT_FRESH;
  if (chD.present && saturated(chD.raw)) flags |= FLAG_DRAG_SAT;
  if (chL.present && saturated(chL.raw)) flags |= FLAG_LIFT_SAT;
  float fd, fl;
  liveForces(chD.raw, chL.raw, &fd, &fl);
  uint32_t now = micros();
  if (seq) {
    float dt = (float)(uint32_t)(now - lastRowUs);
    rowPeriodUs = rowPeriodUs > 0 ? 0.9f * rowPeriodUs + 0.1f * dt : dt;
  }
  lastRowUs = now;
  seq++;
  Serial.print("F,");
  Serial.print(now);          Serial.print(',');
  Serial.print(seq);          Serial.print(',');
  Serial.print(alphaDeg, 2);  Serial.print(',');
  Serial.print(chD.raw);      Serial.print(',');
  Serial.print(chL.raw);      Serial.print(',');
  Serial.print(fd, 5);        Serial.print(',');
  Serial.print(fl, 5);        Serial.print(',');
  Serial.println(flags);
  chD.fresh = chL.fresh = false;
  pendingSince = 0;
}

static void serviceStream() {
  pollChan(chD);
  pollChan(chL);
  bool anyFresh = (chD.present && chD.fresh) || (chL.present && chL.fresh);
  bool allFresh = (!chD.present || chD.fresh) && (!chL.present || chL.fresh);
  if (!anyFresh) return;
  if (!pendingSince) pendingSince = millis();
  if (allFresh || millis() - pendingSince > STALE_MS) emitRow();
}

/* ── burst ────────────────────────────────────────────────────────────── */
static void doBurst(long n) {
  if (imuKind == IMU_NONE) { Serial.println("ERR imu not initialised"); return; }
  if (n < 1) n = 2000;
  if (n > BURST_MAX) { Serial.print("ERR max burst is "); Serial.println(BURST_MAX); return; }

  for (long i = 0; i < n; i++) {
    uint32_t give_up = millis() + 50;           // 50 ms without a sample = bus fault
    while (!imuPoll(burstA[i])) {
      if ((int32_t)(millis() - give_up) > 0) {
        Serial.println("ERR imu stopped answering mid-burst");
        return;
      }
    }
    burstT[i] = micros();
  }

  float hz = (n > 1) ? (n - 1) * 1e6f / (float)(uint32_t)(burstT[n - 1] - burstT[0]) : 0;
  Serial.print("OK BURST "); Serial.print(n);
  Serial.print(" rate_hz "); Serial.println(hz, 1);
  /* The tunnel node's header, gyro columns written as 0, so one host parser
     reads both. */
  Serial.println("us,ax_g,ay_g,az_g,gx_dps,gy_dps,gz_dps");
  float s = imuScale();
  for (long i = 0; i < n; i++) {
    Serial.print(burstT[i]);
    for (int k = 0; k < 3; k++) { Serial.print(','); Serial.print(burstA[i][k] * s, 4); }
    Serial.println(",0,0,0");
  }
  Serial.println("END BURST");
}

/* ── commands ─────────────────────────────────────────────────────────── */
static char *nextTok(char **p) {
  while (**p == ' ' || **p == '\t') (*p)++;
  if (!**p) return NULL;
  char *s = *p;
  while (**p && **p != ' ' && **p != '\t') (*p)++;
  if (**p) { **p = 0; (*p)++; }
  return s;
}

static void printScale(const char *prefix) {
  Serial.print(prefix);
  Serial.print(K[0][0], 3); Serial.print(' ');
  Serial.print(K[0][1], 3); Serial.print(' ');
  Serial.print(K[1][0], 3); Serial.print(' ');
  Serial.print(K[1][1], 3);
  Serial.print(" tare "); Serial.print(tareCounts[0], 1);
  Serial.print(' ');      Serial.println(tareCounts[1], 1);
}

static void handle(char *line) {
  char *p = line;
  char *verb = nextTok(&p);
  if (!verb) return;
  for (char *q = verb; *q; q++) *q = toupper(*q);

  if (!strcmp(verb, "ID")) {
    Serial.print("OK ID "); Serial.print(VERSION);
    Serial.print(" drag="); Serial.print(chD.present ? "ok" : "none");
    Serial.print(" lift="); Serial.print(chL.present ? "ok" : "none");
    Serial.print(" imu=");  Serial.print(imuName());
    Serial.print(" baro="); Serial.println(baroOk ? "LPS22HB" : "none");

  } else if (!strcmp(verb, "START")) {
    /* Re-probe, so a module plugged in after boot is found without a reset. */
    if (!chD.present) chD.present = probe(chD, 300);
    if (!chL.present) chL.present = probe(chL, 300);
    if (!chD.present && !chL.present) {
      Serial.println("ERR no HX711 answering on D2/D3 or D4/D5 - check 3V3, GND, DT, SCK");
      return;
    }
    chD.fresh = chL.fresh = false;
    pendingSince = 0;
    streaming = true;
    digitalWrite(LED_BUILTIN, HIGH);
    Serial.println("OK START");
    Serial.println(ROW_HEADER);

  } else if (!strcmp(verb, "STOP")) {
    streaming = false;
    digitalWrite(LED_BUILTIN, LOW);
    Serial.print("OK STOP rows "); Serial.println(seq);

  } else if (!strcmp(verb, "RAW?")) {
    double m[2], sd[2]; uint16_t got[2];
    if (!collect(1, m, sd, got, collectTimeoutMs(1))) {
      Serial.println("ERR a load cell stopped converting"); return;
    }
    Serial.print("OK RAW "); Serial.print((long)m[0]);
    Serial.print(' ');       Serial.println((long)m[1]);

  } else if (!strcmp(verb, "TARE")) {
    char *a = nextTok(&p);
    long n = a ? atol(a) : 20;
    if (n < 1 || n > 2000) { Serial.println("ERR TARE takes 1..2000 samples"); return; }
    double m[2], sd[2]; uint16_t got[2];
    if (!collect((uint16_t)n, m, sd, got, collectTimeoutMs(n))) {
      Serial.println("ERR a load cell stopped converting during TARE"); return;
    }
    tareCounts[0] = (float)m[0]; tareCounts[1] = (float)m[1];
    haveTare = true;
    Serial.print("OK TARE "); Serial.print(m[0], 1); Serial.print(' '); Serial.print(m[1], 1);
    Serial.print(" sd ");     Serial.print(sd[0], 1); Serial.print(' '); Serial.print(sd[1], 1);
    Serial.print(" n ");      Serial.print(got[0]);   Serial.print(' '); Serial.println(got[1]);

  } else if (!strcmp(verb, "CAL")) {
    char *ax = nextTok(&p), *g = nextTok(&p), *a = nextTok(&p);
    if (!ax || !g) { Serial.println("ERR CAL needs D|L <grams> [n]"); return; }
    char axis = toupper(ax[0]);
    float grams = atof(g);
    long n = a ? atol(a) : 20;
    if (axis != 'D' && axis != 'L') { Serial.println("ERR CAL axis is D or L"); return; }
    if (grams <= 0) { Serial.println("ERR CAL needs a positive mass in grams"); return; }
    if (n < 1 || n > 2000) { Serial.println("ERR CAL takes 1..2000 samples"); return; }
    if (!haveTare) { Serial.println("ERR TARE first, wind off and no load"); return; }
    double m[2], sd[2]; uint16_t got[2];
    if (!collect((uint16_t)n, m, sd, got, collectTimeoutMs(n))) {
      Serial.println("ERR a load cell stopped converting during CAL"); return;
    }
    float F = grams / 1000.0f * G_STD;
    float dd = (float)m[0] - tareCounts[0], dl = (float)m[1] - tareCounts[1];
    int col = (axis == 'D') ? 0 : 1;
    K[0][col] = dd / F;
    K[1][col] = dl / F;
    bool inv = (K[0][0] != 0 && K[1][1] != 0) ? invertK() : false;
    Serial.print("OK CAL "); Serial.print(axis);
    Serial.print(" k ");     Serial.print(K[col][col], 3);
    Serial.print(' ');       Serial.print(K[1 - col][col], 3);
    Serial.print(" F_N ");   Serial.print(F, 5);
    Serial.print(" n ");     Serial.print(got[col]);
    Serial.println(inv ? " live=on" : " live=off");

  } else if (!strcmp(verb, "SCALE?")) {
    printScale("OK SCALE ");

  } else if (!strcmp(verb, "SCALE")) {
    char *t[4];
    for (int i = 0; i < 4; i++) t[i] = nextTok(&p);
    if (!t[3]) { Serial.println("ERR SCALE needs k_dd k_dl k_ld k_ll (counts per N)"); return; }
    float old[2][2];
    memcpy(old, K, sizeof(K));
    K[0][0] = atof(t[0]); K[0][1] = atof(t[1]);
    K[1][0] = atof(t[2]); K[1][1] = atof(t[3]);
    if (!invertK()) {
      memcpy(K, old, sizeof(K));
      if (K[0][0] != 0 && K[1][1] != 0) invertK();
      Serial.println("ERR SCALE matrix is singular - kept the previous one");
      return;
    }
    printScale("OK SCALE ");

  } else if (!strcmp(verb, "ALPHA?")) {
    Serial.print("OK ALPHA "); Serial.println(alphaDeg, 2);

  } else if (!strcmp(verb, "ALPHA")) {
    char *a = nextTok(&p);
    if (!a) { Serial.print("OK ALPHA "); Serial.println(alphaDeg, 2); return; }
    alphaDeg = atof(a);
    Serial.print("OK ALPHA "); Serial.println(alphaDeg, 2);

  } else if (!strcmp(verb, "MARK")) {
    while (*p == ' ') p++;
    Serial.print("OK MARK "); Serial.print(*p ? p : "-");
    Serial.print(' ');        Serial.println(micros());

  } else if (!strcmp(verb, "RATE?")) {
    Serial.print("OK RATE rows_hz ");
    Serial.print(rowPeriodUs > 0 ? 1e6f / rowPeriodUs : 0.0f, 2);
    Serial.print(" drag_hz "); Serial.print(chD.periodUs > 0 ? 1e6f / chD.periodUs : 0.0f, 2);
    Serial.print(" lift_hz "); Serial.print(chL.periodUs > 0 ? 1e6f / chL.periodUs : 0.0f, 2);
    Serial.print(" imu_hz ");  Serial.println(imuHz, 0);

  } else if (!strcmp(verb, "AMB?")) {
    if (!baroOk) { Serial.println("ERR baro not initialised"); return; }
    /* Pressure first: it triggers the one-shot conversion that also updates
       the temperature register. The temperature is the BOARD's, which
       self-heats (about +20 C seen on the tunnel node), so the host takes the
       air temperature from a thermometer and only the pressure from here. */
    float kpa = BARO.readPressure();
    float t = BARO.readTemperature();
    Serial.print("OK AMB "); Serial.print(t, 2);
    Serial.print(' ');       Serial.println(kpa * 1000.0f, 0);

  } else if (!strcmp(verb, "BURST")) {
    char *a = nextTok(&p);
    bool was = streaming;
    streaming = false;
    doBurst(a ? atol(a) : 2000);
    /* Conversions taken during the burst were never read; drop any stale
       fresh flags so the next row pairs two new values. */
    chD.fresh = chL.fresh = false;
    pendingSince = 0;
    streaming = was;

  } else if (!strcmp(verb, "HELP") || !strcmp(verb, "?")) {
    Serial.println("OK HELP ID START STOP RAW? TARE[n] CAL<D|L><g>[n] SCALE? "
                   "SCALE<kdd kdl kld kll> ALPHA<deg> ALPHA? MARK<label> RATE? "
                   "AMB? BURST<n>");

  } else {
    Serial.print("ERR unknown command "); Serial.println(verb);
  }
}

/* ── setup / loop ─────────────────────────────────────────────────────── */
void setup() {
  Serial.begin(115200);
  uint32_t t0 = millis();
  while (!Serial && millis() - t0 < 3000) { }
  pinMode(LED_BUILTIN, OUTPUT);
  digitalWrite(LED_BUILTIN, LOW);

  chD.hx.begin(chD.dout, chD.sck, HX_GAIN);
  chL.hx.begin(chL.dout, chL.sck, HX_GAIN);
  /* HX711 0.7.5 sets DOUT to plain INPUT on every board: its
     `#ifdef ARCH_ESPRESSIF` tests a macro that is always defined. A missing
     module would then float instead of reading high, and probe() could call
     it present. The pull-up makes "none" mean no module. */
  pinMode(chD.dout, INPUT_PULLUP);
  pinMode(chL.dout, INPUT_PULLUP);
  chD.present = probe(chD, 600);    // first conversion takes up to 400 ms at 10 Hz
  chL.present = probe(chL, 600);

  Wire1.begin();                    // on-board sensors are on Wire1, not Wire
  imuInit();                        // the BMI270 path calls Wire1.begin() again
  baroOk = BARO.begin();            // calls Wire1.begin() again
  if (!baroOk) Wire1.begin();       // defensive: the bus object must exist
  Wire1.setClock(400000);           // LAST: every begin() above reset it to 100 kHz
  imuHz = imuBenchmark();

  Serial.print("# "); Serial.print(VERSION);
  Serial.print("  drag D2/D3 ");  Serial.print(chD.present ? "ok" : "NOT ANSWERING");
  Serial.print("  lift D4/D5 ");  Serial.print(chL.present ? "ok" : "NOT ANSWERING");
  Serial.print("  imu ");         Serial.print(imuName());
  if (imuKind != IMU_NONE) { Serial.print(" "); Serial.print(imuHz, 0); Serial.print(" Hz measured"); }
  Serial.print("  baro ");        Serial.println(baroOk ? "LPS22HB" : "none");
  Serial.print("# ");             Serial.println(ROW_HEADER);
  Serial.println("# K not set: the logger re-sends SCALE from data/section_balance.json");
}

void loop() {
  static char buf[96];
  static uint8_t len = 0;
  static bool overflow = false;
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\n' || c == '\r') {
      if (len && !overflow) { buf[len] = 0; handle(buf); }
      if (overflow) Serial.println("ERR line too long");
      len = 0; overflow = false;
    } else if (len < sizeof(buf) - 1) {
      buf[len++] = c;
    } else {
      overflow = true;
    }
  }
  if (streaming) serviceStream();
}
