/*
 * tunnel_node.ino — ambient + IMU for the wind tunnel.
 * Arduino Nano 33 BLE Sense **Lite** (Rev 1 sensor set), USB serial to host.
 *
 *   LPS22HB   pressure + temperature -> air density for run metadata
 *   LSM9DS1   accel + gyro           -> tower vibration, blade pass, gust response
 *
 * The Lite omits the HTS221, so there is no humidity. Density uses the dry-air
 * formula and reads ~1% high on a humid day. Recorded as a known bias rather
 * than pretended away.
 *
 * ⚠ THIS OVERWRITES THE BOARD. Yours was running a pitch controller that
 *   printed "STAT | Mode: MANUAL (Pot) Angle: 9". Save that source first.
 *
 * ── TWO THINGS THE BENCH RUN CHANGED ──────────────────────────────────────
 *
 * 1. The sensors are on **Wire1**. Wire is the external A4/A5 header, and
 *    scanning it finds nothing — which looks exactly like dead hardware.
 *
 * 2. The first version read gyro and accel as two separate I2C transactions
 *    and managed 504 Hz, not the 952 the registers were set to. The bus was
 *    not the limit: ~200 us of bus time per read against ~985 us measured.
 *    The rest was Arduino Wire library overhead per transaction.
 *
 *    So this version reads 0x18..0x2D in ONE 22-byte transaction — gyro in
 *    bytes 0..5, accel in bytes 16..21, control registers harmlessly in
 *    between. Halving the transaction count roughly doubles the rate.
 *
 *    And RATE? now reports what the board actually achieves, measured at
 *    startup, rather than repeating the number the registers were set to.
 *    A sketch that claims 952 while delivering 504 is worse than one that
 *    admits 504.
 *
 * ── PROTOCOL ──────────────────────────────────────────────────────────────
 * One line in, one line out. Same shape as the PMC so the host treats both
 * the same way. Diagnostics are prefixed '#'.
 *
 *   ID            -> OK ID tunnel-node 1.1 baro=.. imu=..
 *   READ          -> OK READ <degC> <Pa> <kg/m3>
 *   IMU           -> OK IMU <ax> <ay> <az> <gx> <gy> <gz>     g, dps
 *   BURST <n>     capture n samples flat out, then dump CSV
 *   MARK <label>  -> OK MARK <label> <micros>       time sync
 *   OFFSET <c>    temperature self-heating correction
 *   RATE?         -> OK RATE <measured Hz> ...
 *   STREAM 1|0    slow ambient stream, 'A,' lines
 *
 * ── TIME SYNC ─────────────────────────────────────────────────────────────
 * This board's crystal and the host's are unrelated: 50 ppm is 60 ms over
 * 20 minutes, ~30 samples, enough to smear the phase between "gust arrived"
 * and "tower responded" — which is the measurement. Host sends MARK at gust
 * start and end; two common events pin the mapping linearly.
 */

#include <Wire.h>
#include <Arduino_LPS22HB.h>

static const char *VERSION = "tunnel-node 1.2";

/* ── LSM9DS1, accel + gyro die ───────────────────────────────────────── */
static const uint8_t AG        = 0x6B;
static const uint8_t WHO_AM_I  = 0x0F;     // expect 0x68
static const uint8_t CTRL1_G   = 0x10;
static const uint8_t CTRL6_XL  = 0x20;
static const uint8_t CTRL8     = 0x22;

/* One contiguous read: 0x18 gyro X low .. 0x2D accel Z high = 22 bytes.
   Bytes 0-5 gyro, 6-15 control registers (ignored), 16-21 accel. */
static const uint8_t BLOCK_START = 0x18;      // OUT_X_L_G
static const uint8_t OUT_X_L_XL  = 0x28;

/* ODR 110 = 952 Hz. With the gyro on, CTRL1_G sets the rate for both. */
static const uint8_t ODR_952 = 0b110;

/* Gyro ±2000 dps. This saturates at 333 rpm, so it cannot measure rotor
   speed — that comes from blade pass in the accel spectrum. The range is for
   structural motion headroom. */
static const uint8_t GYRO_FS   = 0b11;
static const float   GYRO_SENS = 0.070f;          // dps per LSB

/* Accel ±4 g. Tower vibration is milli-g; this leaves room for a hand ping
   test without clipping the transient. */
static const uint8_t ACC_FS   = 0b10;
static const float   ACC_SENS = 0.000122f;        // g per LSB

/* ── burst buffer ─────────────────────────────────────────────────────────
   12 bytes of data + 4 of timestamp per sample. Mbed OS and the BLE stack
   claim a large share of the nRF52840's 256 KB, so this is deliberately
   conservative. For a longer window, halve the rate rather than grow this. */
#define BURST_MAX 4000
static int16_t  buf[BURST_MAX][6];
static uint32_t stamp[BURST_MAX];

float tempOffsetC = 0.0f;
bool  imuOk = false, baroOk = false;
bool  streaming = false;
unsigned long lastStream = 0;
float measuredHz = 0.0f;

/* ── I2C on Wire1 ────────────────────────────────────────────────────── */
static void wr(uint8_t reg, uint8_t val) {
  Wire1.beginTransmission(AG);
  Wire1.write(reg);
  Wire1.write(val);
  Wire1.endTransmission();
}

static uint8_t rd(uint8_t reg) {
  Wire1.beginTransmission(AG);
  Wire1.write(reg);
  Wire1.endTransmission(false);
  Wire1.requestFrom(AG, (uint8_t)1);
  return Wire1.available() ? Wire1.read() : 0;
}

/* ── read strategies ──────────────────────────────────────────────────────
   Measured on this board, not predicted:

     2 transactions, 12 bytes  ->  504 Hz   (1984 us/sample)
     1 transaction,  22 bytes  ->  399 Hz   (2506 us/sample)

   Fitting those gives ~424 us per transaction and ~95 us per BYTE. 95 us/byte
   is an effective bit rate near 10 kHz — nowhere close to the 400 kHz the bus
   is clocked at — so the cost is mbed Wire software overhead per byte, not
   the wire.

   The consequence is counterintuitive and cost me two wrong guesses:
   **reading fewer bytes beats reading fewer transactions.** Pulling gyro and
   accel in one 22-byte block moves 10 useless control registers and ends up
   SLOWER than two tight 6-byte reads.

   So burst capture reads accel only by default. The gyro saturates at 333 rpm
   and is useless for rotation anyway; tower motion is an accelerometer
   measurement. It stays available for single IMU reads where rate is
   irrelevant. */

static void readAccel(int16_t *out) {          // 6 bytes, one transaction
  Wire1.beginTransmission(AG);
  Wire1.write(OUT_X_L_XL);
  Wire1.endTransmission(false);
  Wire1.requestFrom(AG, (uint8_t)6);
  for (uint8_t k = 0; k < 3; k++) {
    uint8_t lo = Wire1.read(), hi = Wire1.read();
    out[k] = (int16_t)((hi << 8) | lo);
  }
}

static void readGyro(int16_t *out) {           // 6 bytes, one transaction
  Wire1.beginTransmission(AG);
  Wire1.write(BLOCK_START);
  Wire1.endTransmission(false);
  Wire1.requestFrom(AG, (uint8_t)6);
  for (uint8_t k = 0; k < 3; k++) {
    uint8_t lo = Wire1.read(), hi = Wire1.read();
    out[k] = (int16_t)((hi << 8) | lo);
  }
}

/* gyro XYZ then accel XYZ — order matches the CSV header */
static void readIMU(int16_t *out) {
  readGyro(out);
  readAccel(out + 3);
}

static bool imuInit() {
  if (rd(WHO_AM_I) != 0x68) return false;
  /* BDU stops a fast reader catching the high byte of one sample against the
     low byte of the next. Without it you get occasional wild spikes that look
     exactly like real impulse data. IF_INC enables the block read above. */
  wr(CTRL8,    0x44);                                  // BDU | IF_INC
  wr(CTRL1_G,  (ODR_952 << 5) | (GYRO_FS << 3));
  wr(CTRL6_XL, (ODR_952 << 5) | (ACC_FS  << 3));
  delay(20);
  return true;
}

/* Measure, do not predict. Both previous attempts to reason about this from
   bus bandwidth were wrong — once optimistic, once in the wrong direction. */
static float benchmark(void (*fn)(int16_t*), int words) {
  int16_t r[6];
  fn(r);                                               // warm the bus
  uint32_t t0 = micros();
  const int N = 200;
  for (int i = 0; i < N; i++) fn(r);
  uint32_t dt = micros() - t0;
  (void)words;
  return dt ? (N * 1e6f / (float)dt) : 0.0f;
}

float rateAccel = 0, rateBoth = 0;

/* ── ambient ─────────────────────────────────────────────────────────── */
static float density(float tC, float pPa) {
  return pPa / (287.05f * (tC + 273.15f));             // dry air
}

static void emitAmbient(const char *prefix) {
  float t = BARO.readTemperature() + tempOffsetC;
  float p = BARO.readPressure() * 1000.0f;             // library returns kPa
  Serial.print(prefix);
  Serial.print(t, 2); Serial.print(' ');
  Serial.print(p, 0); Serial.print(' ');
  Serial.println(density(t, p), 4);
}

/* ── burst ───────────────────────────────────────────────────────────── */
static void doBurst(long n) {
  if (!imuOk) { Serial.println("ERR imu not initialised"); return; }
  if (n < 1) n = 2000;
  if (n > BURST_MAX) {
    Serial.print("ERR max burst is "); Serial.println(BURST_MAX);
    return;
  }

  for (long i = 0; i < n; i++) {
    stamp[i] = micros();
    readAccel(buf[i]);          /* accel only: ~2x the rate, and the gyro adds
                                   nothing for structural work */
    /* Deliberately unpaced: the loop runs flat out and the timestamps record
       the true spacing. Pacing to a nominal interval would add jitter, not
       remove it — the host resamples onto a uniform grid before the FFT. */
  }

  float hz = (n > 1) ? (n - 1) * 1e6f / (float)(stamp[n-1] - stamp[0]) : 0;
  Serial.print("OK BURST "); Serial.print(n);
  Serial.print(" rate_hz "); Serial.println(hz, 1);

  /* Header keeps the gyro columns so burst_analyze.py needs no change; they
     are written as 0 rather than omitted. */
  Serial.println("us,ax_g,ay_g,az_g,gx_dps,gy_dps,gz_dps");
  for (long i = 0; i < n; i++) {
    Serial.print(stamp[i]);
    for (int k = 0; k < 3; k++) { Serial.print(','); Serial.print(buf[i][k] * ACC_SENS, 4); }
    Serial.print(",0,0,0");
    Serial.println();
  }
  Serial.println("END BURST");
}

/* ── commands ────────────────────────────────────────────────────────── */
static void handle(String cmd) {
  cmd.trim();
  if (!cmd.length()) return;
  String up = cmd; up.toUpperCase();

  if (up == "ID") {
    Serial.print("OK ID "); Serial.print(VERSION);
    Serial.print(" baro="); Serial.print(baroOk ? "LPS22HB" : "none");
    Serial.print(" imu=");  Serial.println(imuOk ? "LSM9DS1" : "none");

  } else if (up == "READ") {
    if (!baroOk) { Serial.println("ERR baro not initialised"); return; }
    emitAmbient("OK READ ");

  } else if (up == "IMU") {
    if (!imuOk) { Serial.println("ERR imu not initialised"); return; }
    int16_t r[6]; readIMU(r);
    Serial.print("OK IMU");
    for (int k = 3; k < 6; k++) { Serial.print(' '); Serial.print(r[k] * ACC_SENS, 4); }
    for (int k = 0; k < 3; k++) { Serial.print(' '); Serial.print(r[k] * GYRO_SENS, 2); }
    Serial.println();

  } else if (up.startsWith("BURST")) {
    doBurst(cmd.substring(5).toInt());

  } else if (up.startsWith("MARK")) {
    String lbl = cmd.length() > 5 ? cmd.substring(5) : "-";
    Serial.print("OK MARK "); Serial.print(lbl);
    Serial.print(' '); Serial.println(micros());

  } else if (up.startsWith("OFFSET")) {
    if (up == "OFFSET" || up == "OFFSET?") {
      Serial.print("OK OFFSET "); Serial.println(tempOffsetC, 2);
    } else {
      tempOffsetC = cmd.substring(6).toFloat();
      Serial.print("OK OFFSET "); Serial.println(tempOffsetC, 2);
    }

  } else if (up == "RATE?") {
    Serial.print("OK RATE accel_only "); Serial.print(rateAccel, 0);
    Serial.print(" accel_plus_gyro "); Serial.print(rateBoth, 0);
    Serial.print(" odr 952 accel_fs 4 gyro_fs 2000 burst_max ");
    Serial.println(BURST_MAX);

  } else if (up.startsWith("STREAM")) {
    streaming = cmd.substring(6).toInt() != 0;
    Serial.print("OK STREAM "); Serial.println(streaming ? 1 : 0);

  } else if (up == "HELP" || up == "?") {
    Serial.println("OK HELP ID READ IMU BURST<n> MARK<label> OFFSET<c> RATE? STREAM<0|1>");

  } else {
    Serial.print("ERR unknown command "); Serial.println(cmd);
  }
}

void setup() {
  Serial.begin(115200);
  unsigned long t0 = millis();
  while (!Serial && millis() - t0 < 3000) { }

  Wire1.begin();                   // onboard sensors are on Wire1, not Wire
  Wire1.setClock(400000);          // 100 kHz caps the sample loop far too low

  baroOk = BARO.begin();
  imuOk  = imuInit();
  if (imuOk) {
    rateAccel = benchmark(readAccel, 3);
    rateBoth  = benchmark(readIMU, 6);
    measuredHz = rateAccel;                            // burst uses accel only
  }

  Serial.print("# "); Serial.print(VERSION);
  Serial.print(" baro="); Serial.print(baroOk ? "ok" : "FAIL");
  Serial.print(" imu=");
  if (imuOk) {
    Serial.print("ok  accel-only "); Serial.print(rateAccel, 0);
    Serial.print(" Hz, accel+gyro "); Serial.print(rateBoth, 0);
    Serial.println(" Hz  (measured, not claimed)");
    Serial.println("# burst captures accel only - the gyro saturates at 333 rpm");
    Serial.println("# and tower motion is an accelerometer measurement");
  } else {
    Serial.println("FAIL - WHO_AM_I mismatch, check Wire1");
  }
}

void loop() {
  static String line;
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') { if (line.length()) { handle(line); line = ""; } }
    else if (line.length() < 64) line += c;
  }
  if (streaming && baroOk && millis() - lastStream >= 1000) {
    lastStream = millis();
    emitAmbient("A,");
  }
}
