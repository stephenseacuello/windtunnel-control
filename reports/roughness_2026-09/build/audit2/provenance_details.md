# Provenance audit: specimen, print process, Jeong-lab context, Ra10 search, timeline

All claims below come from files I read, commands I ran, or Gmail, Calendar and Drive items I retrieved on 2026-09-30. Verbatim email excerpts with message IDs are in `build/provenance/email_evidence.txt`.

## 1. Rotor / specimen

| item | value | source |
|---|---|---|
| Type | Vertical-axis H-rotor, **3 blades** | docs/09_results.md; blades/v1.json `n_blades` |
| Radius R | **0.1016 m (4 in), "axis to blade attachment"**, listed as *Measured* | README.md:272, docs/09:141. Note: blades/v1.json still says `tip_radius_m: null`, "STILL UNKNOWN" (a stale note written in HAWT terms) |
| Span H | **0.2451 m**; STL bounding box 245.11 mm | verify_geometry.py on blades/v1.stl |
| Swept area | **2RH = 0.04980 m²**; πR² = 0.03243; ratio 1.536 | verify_geometry.py |
| Chord | **48.0 mm** (bounding box 48.03) | STL |
| Wall | **1.79 mm** (2V/A = 1.786; V = 31,014 mm³, A = 34,724 mm², 27,056 triangles) | STL (json: V = 31,015) |
| t/c | 0.04 in json; 0.037 computed | STL |
| Camber | depth 24.46 mm (bounding box). json says 42 % of chord with no definition given; the bounding box gives 51 % | STL / json |
| Other | turning 183°, square-cut edges, zero twist (prismatic, ±0.02 %); "thin cambered plate, not an airfoil" | blades/v1.json |
| Material | **PETG**. Appears only in the sweep `--notes`; the only email containing "PETG" is the CSVs attached to the Aug 26 logs email | logs headers; Gmail |
| Re_chord | **32,376 → 119,735**. Reproduced exactly with ν = 1.5033e-5 m²/s (≈20 °C) over 10.14–37.50 m/s. At 24.63 °C (the uncalibrated node reading on Sep 1): 31,435–116,254 | docs/09:145; verify_geometry.py |
| Geometry source | One blade. `~/Downloads/turbine_meters.stl` ← SolidWorks 2024 `turbine.STEP` (AP214, 2026-07-01) | blades/v1.json `_source` |
| v1 vs v2 | Aug 3: "The v2 Wind Turbines are much better matching to the original, but still not exact". Aug 4: "the Professors … would like us to go with the v1 of the turbine blades and not the v2" | Gmail 19fc82a5d2e58504, 19fce4aeab1f69a1 |

## 2. How each Ra level was produced

### What the documents say

| date | evidence (verbatim or near) | source |
|---|---|---|
| Jul 25 | Sodhi: PrusaSlicer fuzzy skin how-to. "Outside walls"; thickness default ~0.3 mm (0.5–0.8 mm for a texture you can feel); point distance default ~0.8 mm; "only affects vertical walls"; "Reprint the turbine with different levels of roughness on Monday ?" | 19f9b936be5bd8d7 |
| Aug 4 | Stephen → Andrew Muszynski: print v1 "with the below three different fuzzy texture settings using a 0.2mm nozzle and fine print layer settings". The image **IMG_8608.png** (decoded, `build/provenance/IMG_8608.png`) is a **ChatGPT screenshot**. Its table: **Target Ra 10 µm → point distance 0.20 mm, thickness 0.025 mm; 20 µm → 0.20 / 0.050; 40 µm → 0.20 / 0.101**, with estimated print times of 8–11 h. The text above the table mentions reducing from an "original 0.04-mm" point distance and "Bambu" | 19fcd30665189aff, 19fce4de995ff76b |
| Aug 5 | Andrew: "one of each of those (3 in total) would take about 36 hours … on the printer in the garage". Then: "**The printer in the garage only has the 0.4mm nozzle and a 0.4mm replacement nozzle.** I just emailed Sodhi asking him to order a full 0.2mm assembly" | 19fd251306bf78de, 19fd291ca634c02e |
| Aug 12 | Stephen: "What fuzzy texture setting did you use for the three prints you dropped off?" Andrew: "**I used the same fuzzy texture settings as the previous print but I didn't have access to a 0.2 mm nozzle head so the layer height is 0.08 mm.** I can send you the bambu plate file …" He attached Drive links `turbines_threeFuzzySettings_06mm.3mf` and `…_plate_2.gcode.3mf`, plus a **Claude**-generated table: no fuzzy skin ~4–8 µm; 0.8/0.02 ~6–10 µm; **"Your existing print" 0.2/0.05 → ~10–15 µm; "Mid (already printed)" 0.2/0.101 → ~20–35 µm**; "Roughest safe" 0.15/0.2 → ~35–55 µm | 19ff7e507ff031ce (image saved) |
| Aug 13 | Stephen: "**The two prints feel very different, maybe we should test/verify and/or standardize on the nozzle type.**" (no resolution found) | 19ffbc5c2fffd48b |
| Aug 17 | I²(s) Print Lab (coe3d@etal.uri.edu) sends `turbine_default.3mf`. Aug 25, Stephen to "Cam": "save an STL of each turbine blade with its fuzzy texture from this file?" Aug 26 reply: "I don't know a way" | 1a010bd8e6b65b66 |
| Aug 17 | Stephen → Taegu: "I have a few sets of new turbines ready" | 1a00f7c0da465d57 |
| Aug 20 | Stephen → Jeong et al.: "Next week we will complete recording data for surface roughnesses of **Ra 10, 40, & 80** micrometers." This is the first appearance of 80 | 1a0211ed22df050e |
| Sep 9 | Stephen: "Did we ever receive the small 3D printer nozzles so we could print the blades internally?" Sodhi: "**I ordered them but the .4mm were delivered. Have to order them again.**" | 1a087b7e6cc3b7bb |

### What the sweep headers say (operator `--notes`)

- v1_Ra20 (Aug 20): `PETG, 0.2mm, Ra 20`. Ambiguous: all IMG_8608 settings use a 0.20 mm point distance.
- v1_Ra80 (Aug 26): `PETG, 0.2mm layer, 0.2mm nozzle, Ra 80`. The Aug 25 plan (commit 9cae976) had suggested `PETG, 0.2mm, Ra 80`.
- v1_Ra40 (Sep 1): `PETG, 0.2mm layer, Ra 40`.
- Repo to-dos to record the slicer recipe (commits 4d28e0e, 8a1c477, 5bca021) were never completed; blades/v1.json has no print fields.

### Conclusions

1. **Nominal, not measured.** Ra 10/20/40 are ChatGPT *targets* for fuzzy-skin thickness 0.025/0.050/0.101 mm. A second LLM (Claude, via Andrew) put the two printed settings at about 10–15 and 20–35 µm, roughly half the labels. I found **no measurement**: the Keyence question (Jul 22) got no reply, the Hexagon arm case key was missing (Jul 27), and there is no profilometer mention anywhere.
2. **Ra 80 has no documented setting** in any table, email or repo file.
3. **Nozzle confound.** Every email says in-house prints used 0.4 mm nozzles, both before and after the campaign. Andrew's prints used a 0.08 mm layer. So the notes' "0.2mm layer" (Ra40, Ra80) and "0.2mm nozzle" (Ra80) are unsupported. They look like intent copied from the Aug 4 request ("0.2mm nozzle and fine print layer settings"), not settings read from the slicer. The Ra80 note can only be true if those blades came from a printer with a 0.2 mm nozzle. The I²(s) Print Lab is the only candidate, and I found no evidence either way.
4. **Who printed.** The Jul 13 replica (no texture) was announced by Stephen, with textured versions designed by Tim Richards and sent to "the shop", where "Cam" was printing. The fuzzy sets came from Andrew Muszynski (garage Bambu printer; three prints by Aug 12) and possibly the I²(s) Print Lab (turbine_default.3mf, Aug 17). **Which physical rotor was labelled Ra20, Ra40 or Ra80 is recorded nowhere.** It is plausible that Ra20 = thickness 0.050 and Ra40 = 0.101 from Andrew's set, but that is inference.
5. **To settle it:** open the three .3mf files locally. They are zips; read `Metadata/project_settings.config` for nozzle_diameter, layer_height, fuzzy_skin, fuzzy_skin_thickness, fuzzy_skin_point_distance, printer_model and filament_type. Then have Stephen and Andrew match each physical rotor set to a file. The Drive files are 45.2, 39.1 and 60.7 MB, and I did not download them. It is unexplained what "06mm" in the file names means.

## 3. Jeong-lab tests (email context)

| date | what | rotor | who | notes |
|---|---|---|---|---|
| Mar 16 | DAQ capture 16:55–16:59, 6 ch at 300 Hz ("Collected with Dr Jeong") | not stated | Stephen, Jeong | docs/08_march_daq.md |
| May 28 | Test: RPM steps; raw data, "measured RPMs from the rotation counter", average Vdc/Idc/Pdc per step (`05282026 test data2.xlsx`) | not stated. Jeong: "**generated power has increased compared to the previous wind turbine**" | Taegu (+Stephen) | Jeong asked to adjust the DAQ time-step for RPM, "verify the cause of the dip", and measure "load current variations under the same wind-speed conditions" |
| Jun 3 (Wed 10:30) | "**load variation test**" + "**constant RPM test**"; max-power curve (reported Jun 5) | not stated; presumably the original rotor, since the printed replicas were finished only Jul 13 (inference) | Taegu + Stephen | 13 set points 500–1700. Taegu: "one more experiment using **constant current (CC) and constant voltage (CV) modes**". Sodhi: "The dip is interesting … discuss this with Vahid for the power modeling" |
| Jun 8 12:30–13:30 | Lab session (calendar), CC/CV planned | not stated | Taegu + Stephen | **no results email found** |
| Jul 13–15 | Replicas done; Jeong: "As Prof. Jahangiri suggested, we will also begin considering the **fault scenarios** and develop a plan" | printed replicas | | 19f5c018da3cb3b2 |
| Jul 23 ~16:15 | Tunnel session | not stated | Taegu + Stephen | no data located |
| Jul 27 10:45–10:52 EDT | Test on "**the new blades which have no texture**" (Taegu to Jahangiri, who asked "which blade you used exactly?") | printed replica, no texture (probably v1 geometry, since the v1 STEP dates from Jul 1 and v2 appears ~Jul 30; inference) | Taegu + Stephen | 16 set points 500–2000; DAQ 360 Hz. Jeong: "**you need to compare the results with our initial test, which showed no significant differences. This will provide a good baseline for our evaluation.**" He does not say which two things were compared. "**we need to develop a plan for the fault testing … prepare various types of blades representing different fault conditions … finalize the test plan before proceeding with the next round of testing**" |
| Jul 28 ~15:45 | Session ("I need to collect more data") | not stated | Taegu + Stephen | no data located |
| Aug 13 | Jeong: "maximum power point tracking and other operating conditions … we will also need to control the electrical load" | | | 19ff68cacbd296e4 |
| Aug 21 | Jeong: "prepare **1–2 slides summarizing the experimental setup and another 1–2 slides summarizing the key data and results** … a clear record … for future reference" | | | No emailed reply found. docs/slides/jeong_setup_and_results_v1.pptx (Sep 24, untracked) exists |

Instruments named in email: the Jeong-lab DAQ, a proximity-sensor/magnet revolution counter (Apr–May), and the Chroma DC electronic load. The load mode is not stated for May or July. June was a "load variation" test with a CC/CV comparison proposed. The Aug campaign headers record Chroma 63004-150-60, S/N 630041501113, fw 2.01, and the ABB ACS550 drive via Modbus RS-485.

**Wind-axis caution:** the Jeong-lab `Wind_Speed_ms` column maps 500 rpm → 9.786 m/s, where the repo calibration gives 10.236 (−4.4 %). At 1700 rpm it is 35.9625 vs 35.82. Use fan set point as the common axis.

## 4. Definitive Ra10 search. Result: none exists

| place | query | result |
|---|---|---|
| repo tree (all files incl. logs/, data/, webapp/) | `Ra ?10\b\|v1_Ra10\|Ra_10` | only NEXT_SESSION.md (plan text) and HANDOFF.md |
| repo file names | `*ra10*` | none (apart from this audit's own script) |
| blade labels in logs/data/webapp/src/tests/docs | `v[0-9]_Ra[0-9]+…` | v1_Ra20, v1_Ra40, v1_Ra80, v2_Ra20 (historical), v1_Ra20_repeat (docs/tests only) |
| git (all refs; main + origin/main; no stash) | `log --all -S Ra10`, `-S 'Ra 10'`, `-G v1_Ra10`, `--stat \| grep -i ra10` | **no hits**. HEAD's NEXT_SESSION.md (Aug 27) has no "Ra 10"; the Ra10 plan exists only in the uncommitted copy, modified 2026-09-01 08:07 |
| ~/Downloads ~/Desktop ~/Documents | names plus content grep of local csv/txt/md/json/py/tex/log files under 50 MB (iCloud-evicted files skipped) | none |
| Spotlight (home) | `"Ra10"` | repo files and one unrelated 2025 wandb log (false positive) |
| ~/Projects | `sweep_v*` outside repo logs | none |
| Drive | titles fuzzy/turbine/3mf/Ra10/roughness | no Ra10 file |
| Gmail (incl. trash) | `Ra10 OR "Ra 10" OR v1_Ra10` | only the **Aug 20 plan** email |
| Gmail | `fuzzy`; `roughness after:2026/08/06`; `"wind tunnel" after:2026/08/27`; Taegu threads | nothing after Aug 26 about roughness; no Ra10 data |
| Calendar | search_events (empty); list_events fullText wind/tunnel/Taegu/turbine/Jeong/blade, May–Oct | May 27, Jun 8, Sep 1, **Oct 1 (scheduled)**; none mention Ra10 |

**Conclusion:** Ra10 was planned from the Aug 4 settings table onward (the 0.025 mm thickness row), announced Aug 20, and offered as "Ra 10 **or** Ra 40" on Sep 1. Ra 40 was run and Ra10 never was. An Ra10 rotor may physically exist among the Aug 12 prints, but that is undocumented. The Oct 1 session could produce new data.

## 5. Wind-tunnel sessions (all sources) and campaign timeline

Sessions (`sessions.csv`):
- Mar 16 DAQ capture.
- May 28 test.
- Jun 3 test.
- Jun 8 (planned CC/CV).
- Jul 23, Jul 27 (10:45–10:52), Jul 28.
- Aug 18 14:30 (meeting or test; no data found).
- **Aug 19** 17:36–17:54: first scripted control.
- **Aug 20** 13:41–14:48: steps, peaks, **Ra20** (closed 14:29:49), gusts.
- Aug 25: bench snapshots.
- **Aug 26** 14:40–15:32: gusts, then **Ra80** 15:24:10–15:32:01.
- Aug 29 (Sat) 10:56–11:32: fan step_up runs.
- Aug 31: bench snapshot.
- **Sep 1**: **Ra40** 15:04:25–15:12:50. The calendar event was 14:00–15:00; Taegu's invite is still unanswered.
- **Oct 1** 15:00–16:00: scheduled.

Timeline highlights (`timeline.csv`, 39 rows):
- Replicas finished Jul 13.
- Fuzzy-skin method Jul 25.
- v1 chosen, and the ChatGPT settings sent, Aug 4.
- 0.4 mm-only printer Aug 5.
- Prints handed over Aug 12 (0.08 mm layer).
- "Two prints feel very different" Aug 13.
- Print Lab file Aug 17.
- Automation Aug 19–20.
- Relabel v2 → v1 Aug 25 (data verified unchanged).
- Ra80 Aug 26.
- Ra40 Sep 1.
- 0.2 mm nozzles still absent Sep 9.

**Planned, not run:**
- v1_Ra20_repeat (remount), which Sep 1 ranked first.
- v1_Ra10.
- v1_Ra80_rpm.
- The June CC/CV test (outcome unknown).
- The slicer recipe written into blades/v1.json.
- Jeong's fault-testing plan and blades.

## Could not check
- Contents of the three .3mf files (39–61 MB). I did not download them, to keep the session safe.
- Message 19fd251306bf78de (9.6 MB, contains the original turbines_threeFuzzySettings.3mf).
- The May 28 xlsx.
- Message 19fa4b6458be5961: read only via get_thread PLAIN_TEXT, as instructed.
- Content of iCloud-evicted files in ~/Documents.

## Artifacts
All in `reports/roughness_2026-09/build/provenance/`:
- `IMG_8608.png` and `20260812_Muszynski_Ra_table__image.png`: the two settings tables, decoded from the emails.
- `email_evidence.txt`: verbatim excerpts with message IDs.
- `sessions.csv`, `timeline.csv`, `ra10_search_log.csv`: the three tables summarised above.
- `ra10_local_search.sh` and its output `ra10_local_search_output.txt`.
- `log_session_times.py` → `log_session_times.csv`: run times from the log files.
- `verify_geometry.py`: the geometry and Re check.
- `decode_mime.py`, `thread_dump.py`: helpers for reading the emails.