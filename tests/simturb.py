"""Simulated turbine + generator, to exercise the sweep and the stall guard."""
import math, time
import numpy as np

class SimTurbine:
    """
    Rotor with a Cp(lambda) curve, driving a DC generator into whatever the
    load presents. Integrates J*dw/dt = T_aero - T_gen so the CC-vs-CR
    stability difference is a genuine consequence, not something faked.
    """
    def __init__(self, radius=0.30, J=0.004, kv=0.25, R_int=1.2,
                 cp_peak=0.42, lam_peak=5.5, rho=1.195):
        self.R, self.J, self.kv, self.Ri = radius, J, kv, R_int
        self.cp_peak, self.lam_peak, self.rho = cp_peak, lam_peak, rho
        self.omega = 5.0
        self.wind = 0.0
        self.R_load = 1e6           # open circuit until told otherwise
        self.mode = "CR"
        self.i_cmd = 0.0
        self.t = time.monotonic()

    def cp(self, lam):
        if lam <= 0.05 or lam > 2.4*self.lam_peak: return 0.0
        return max(0.0, self.cp_peak*math.exp(-((lam-self.lam_peak)/2.8)**2))

    def spin_to(self, wind, frac=0.75):
        self.wind = wind
        self.omega = max(self.omega, frac*self.lam_peak*wind/self.R)

    def step(self, dt=None):
        """
        Integrate one tick.

        `dt=None` uses wall clock, which is what the live rig does. Pass an
        explicit dt for tests: a physics assertion that depends on scheduler
        timing is not testing physics.
        """
        if dt is None:
            now = time.monotonic(); dt = min(now-self.t, 0.25); self.t = now
        if dt <= 0: return
        A = math.pi*self.R**2
        lam = self.omega*self.R/self.wind if self.wind > 0.1 else 0.0
        P_aero = 0.5*self.rho*A*self.wind**3*self.cp(lam)
        T_aero = P_aero/max(self.omega, 0.5)
        emf = self.kv*self.omega
        if self.mode == "CR":
            i = emf/(self.Ri+self.R_load)
        else:
            i = min(self.i_cmd, emf/self.Ri) if emf > 0 else 0.0
        T_gen = self.kv*i
        self.omega += dt*(T_aero - T_gen - 0.0004*self.omega)/self.J
        self.omega = max(self.omega, 0.0)
        self.i = i; self.v = max(emf - i*self.Ri, 0.0)

    def rpm(self):
        self.step(); return self.omega*60/(2*math.pi)

class SimLoad:
    def __init__(self, turb): self.t=turb; self._on=False
    @property
    def is_on(self): return self._on
    def on(self): self._on=True
    def off(self): self._on=False; self.t.R_load=1e6
    def set_mode_cr(self, ohms): self.t.mode="CR"; self.t.R_load=ohms
    def set_mode_cc(self, amps): self.t.mode="CC"; self.t.i_cmd=amps
    def measure(self):
        self.t.step()
        return (self.t.v, self.t.i, self.t.v*self.t.i) if self._on else (0,0,0)
