"""Controllers and repair macros for the constrained-cable recovery task.

Every arm receives the identical declared observation, the identical action
authority and the identical repair library. Scripted programs exist for physical
controls; they are labelled as controls and never as a task solution.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np

#: Phase codes stored in the servo ledger.
PHASES = ("settle", "align", "insert", "retract", "repair", "hold", "program",
          "terminal", "deadline", "retries_exhausted", "clip_lost", "blind_insert")
PHASE_CODE = {name: i for i, name in enumerate(PHASES)}


@dataclass(frozen=True)
class RecoveryObservation:
    """Declared common interface. Identical content for every arm."""

    time_s: float
    tip_position: np.ndarray
    tip_rotation: np.ndarray
    seated_position: np.ndarray
    insertion_axis: np.ndarray
    wrist_force_world: np.ndarray
    precontact_bias_world: np.ndarray
    connector_contact_n: float
    clip_contact_n: float
    post_contact_n: float
    anchor_reaction_world: np.ndarray
    cable_centerline: np.ndarray
    clip_retained: bool
    clip_margin_m: float
    witnessed: bool


@dataclass(frozen=True)
class RepairMacro:
    """One validated parameterized repair over world-frame tip waypoints."""

    name: str
    offsets_m: tuple[tuple[float, float, float], ...]
    speed_m_per_s: float = 0.004
    description: str = ""

    def waypoints(self, tip, axis, side):
        """World waypoints from tip-relative offsets in the local repair frame.

        Local axes are the insertion axis, the declared cable run direction and
        their cross product, so one macro definition transfers across layouts.
        """
        axis = np.asarray(axis, dtype=float)
        run = np.asarray(side, dtype=float)
        run = run-axis*(run @ axis)
        run /= np.linalg.norm(run)
        lateral = np.cross(axis, run)
        basis = np.column_stack([run, lateral, axis])
        return [np.asarray(tip, dtype=float)+basis @ np.asarray(offset, dtype=float) for offset in self.offsets_m]


def parametric_macro(action: dict) -> RepairMacro:
    """One continuous repair action in the local repair frame.

    ``retreat_m`` is extra travel away from the port beyond the controller's own
    fixed retract, ``bearing_rad`` is the direction within the plane spanned by
    the cable run and its lateral, and ``excursion_m`` is the distance travelled
    in that direction. The three together are a cylinder of clearance motions
    around the retreat point, which is dense enough for a decision boundary to
    exist. The controller returns to the approach standoff afterwards, so the
    action is a detour and not a new goal.
    """
    import math

    bearing, excursion = float(action["bearing_rad"]), float(action["excursion_m"])
    offset = (excursion*math.cos(bearing), excursion*math.sin(bearing), -float(action["retreat_m"]))
    # Out and back at the clearance speed, so the detour is a detour: the slow
    # insertion approach is paid once, on the final approach, not twice.
    return RepairMacro("parametric", (offset, (0.0, 0.0, 0.0)),
                       float(action.get("speed_m_per_s", 0.02)),
                       "Parametric clearance detour: retreat along the insertion axis, move by the "
                       "declared excursion on the declared bearing, and return to the retreat point.")


def repair_library(cfg: dict) -> dict[str, RepairMacro]:
    """Shared physically validated repair library used by every arm."""
    return {name: RepairMacro(name, tuple(tuple(o) for o in spec["offsets_m"]),
                              spec.get("speed_m_per_s", 0.004), spec.get("description", ""))
            for name, spec in cfg.items()}


@dataclass
class SlewReference:
    """Rate-limited world reference. Target slew is not a force ceiling."""

    position: np.ndarray
    speed_m_per_s: float = 0.004

    def toward(self, goal, dt: float, speed: float | None = None) -> np.ndarray:
        delta = np.asarray(goal, dtype=float)-self.position
        distance = float(np.linalg.norm(delta))
        limit = (self.speed_m_per_s if speed is None else speed)*dt
        if distance > limit > 0:
            delta *= limit/distance
        self.position = self.position+delta
        return self.position


@dataclass
class ScriptedProgram:
    """Fixed offset program used for physical controls and negative controls."""

    steps: Sequence[dict]
    initial_tip: np.ndarray
    axis: np.ndarray
    run: np.ndarray
    reference: SlewReference = field(init=False)
    index: int = 0
    _entered: float | None = None

    def __post_init__(self):
        self.reference = SlewReference(np.asarray(self.initial_tip, dtype=float).copy())
        run = np.asarray(self.run, dtype=float)
        run = run-self.axis*(run @ self.axis)
        self.basis = np.column_stack([run/np.linalg.norm(run), np.cross(self.axis, run/np.linalg.norm(run)), self.axis])

    @property
    def finished(self) -> bool:
        return self.index >= len(self.steps)

    def step(self, time_s: float, tip, dt: float):
        if self.finished:
            return self.reference.position, "hold"
        spec = self.steps[self.index]
        goal = np.asarray(self.initial_tip, dtype=float)+self.basis @ np.asarray(spec["offset_m"], dtype=float)
        reached = float(np.linalg.norm(self.reference.position-goal)) <= 1e-9
        if reached:
            if self._entered is None:
                self._entered = time_s
            if time_s-self._entered >= spec.get("hold_s", 0.0):
                self.index += 1
                self._entered = None
        return self.reference.toward(goal, dt, spec.get("speed_m_per_s")), spec.get("label", "program")


class ForceGuidedInsertion:
    """Frozen competent first attempt: align to the observed port, then insert.

    Retreats on compensated axial load and retries a bounded number of times.
    This is the shared prefix of every arm and the zero-repair reference.
    """

    def __init__(self, cfg: dict, initial_tip, axis):
        self.cfg = cfg
        self.origin = np.asarray(initial_tip, dtype=float).copy()
        self.reference = SlewReference(np.asarray(initial_tip, dtype=float).copy(), cfg["speed_m_per_s"])
        self.axis = np.asarray(axis, dtype=float)
        self.phase = "align"
        self.retries = 0
        self.terminal = False
        self._retract_goal = None
        self._repair: list[np.ndarray] = []
        self._repair_name: str | None = None
        self._repair_speed = cfg["speed_m_per_s"]
        self._reference_arrived_s: float | None = None
        self.waypoint_lags = 0
        self.repairs_started = 0
        self.repair_log: list[dict] = []

    def request_repair(self, macro: RepairMacro, tip, run, time_s: float) -> bool:
        """Queue one repair macro; the retry budget is shared with plain retries."""
        if self.terminal or self.retries >= self.cfg["max_retries"]:
            return False
        self.retries += 1
        self.repairs_started += 1
        self.phase = "retract"
        self._retract_goal = np.asarray(tip, dtype=float)-self.axis*self.cfg["retract_distance_m"]
        self._repair = macro.waypoints(self._retract_goal, self.axis, run)
        self._repair_name = macro.name
        self._reference_arrived_s = None
        # A clearance detour is not an insertion approach. Until this line the
        # declared macro speed was carried and never applied, so every macro ran
        # at the base approach speed. Every v2 library macro declares exactly the
        # base speed, so no earlier result changes; large detours become affordable.
        self._repair_speed = macro.speed_m_per_s
        self.repair_log.append({"time_s": time_s, "macro": macro.name,
                                "speed_m_per_s": macro.speed_m_per_s})
        return True

    def _retry(self, tip):
        if self.retries >= self.cfg["max_retries"]:
            self.phase, self.terminal = "retries_exhausted", True
            return
        self.retries += 1
        self.phase = "retract"
        self._retract_goal = np.asarray(tip, dtype=float)-self.axis*self.cfg["retract_distance_m"]
        self._repair, self._repair_name = [], None
        self._repair_speed = self.cfg["speed_m_per_s"]
        self._reference_arrived_s = None

    def step(self, observation: RecoveryObservation, dt: float):
        cfg = self.cfg
        tip = np.asarray(observation.tip_position, dtype=float)
        seated = np.asarray(observation.seated_position, dtype=float)
        axial = float(abs((observation.wrist_force_world-observation.precontact_bias_world) @ self.axis))
        if not self.terminal:
            if not observation.clip_retained:
                self.phase, self.terminal = "clip_lost", True
            elif observation.time_s >= cfg["deadline_s"]:
                self.phase, self.terminal = "deadline", True
            elif self.phase in ("align", "insert") and axial >= cfg["retract_force_n"]:
                self._retry(tip)
        speed = cfg["speed_m_per_s"]
        goal = self.reference.position
        if not self.terminal:
            if self.phase == "retract":
                goal = self._retract_goal
                if float(np.linalg.norm(tip-goal)) <= cfg["position_tolerance_m"]:
                    self.phase = "repair" if self._repair else "align"
            elif self.phase == "repair":
                goal = self._repair[0]
                speed = self._repair_speed
                # A commanded detour is finished when the command is finished. The
                # tip is allowed a registered settling window to converge onto the
                # waypoint; if the cable holds it short the waypoint is still
                # retired and the lag is counted, so one unreachable waypoint
                # cannot silently consume the whole job deadline. Absent
                # ``repair_settle_s`` the rule is off and the v2 behaviour stands.
                if self._reference_arrived_s is None and float(
                        np.linalg.norm(self.reference.position-goal)) <= 1e-9:
                    self._reference_arrived_s = observation.time_s
                reached = float(np.linalg.norm(tip-goal)) <= cfg["position_tolerance_m"]
                settle_window = cfg.get("repair_settle_s")
                lagged = (settle_window is not None and self._reference_arrived_s is not None
                          and observation.time_s-self._reference_arrived_s >= settle_window)
                if reached or lagged:
                    self.waypoint_lags += 0 if reached else 1
                    self._repair.pop(0)
                    self._reference_arrived_s = None
                    if not self._repair:
                        self.phase = "align"
            elif self.phase == "align":
                distance = float((seated-tip) @ self.axis)
                goal = seated-self.axis*max(distance, cfg["alignment_standoff_m"])
                if float(np.linalg.norm(tip-goal)) <= cfg["position_tolerance_m"]:
                    self.phase = "insert"
            elif self.phase == "insert":
                goal = seated+self.axis*cfg["insertion_overtravel_m"]
                span = cfg["retract_force_n"]-cfg["slowdown_force_n"]
                speed *= float(np.clip((cfg["retract_force_n"]-axial)/span, 0.0, 1.0))
        return self.reference.toward(goal, dt, speed), self.phase, axial


class CableAwareRules(ForceGuidedInsertion):
    """Same insertion prefix plus visible cable and clip-aware repair selection.

    On a witnessed failure the rule set inspects the measured distal contact and
    anchor reaction and chooses a clearance macro that moves away from the loaded
    cable direction while keeping the commanded lift under the calibrated clip
    release margin. No learning and no simulator privilege beyond the shared
    observation are used.
    """

    def __init__(self, cfg: dict, initial_tip, axis, macros: dict[str, RepairMacro], rules: dict):
        super().__init__(cfg, initial_tip, axis)
        self.macros = macros
        self.rules = rules
        self._handled = False

    def on_witness(self, observation: RecoveryObservation, run, time_s: float) -> str | None:
        """Choose one repair macro for the first witnessed failure."""
        if self._handled:
            return None
        self._handled = True
        loaded = (observation.post_contact_n > self.rules["distal_contact_witness_n"]
                  or float(np.linalg.norm(observation.anchor_reaction_world)) > self.rules["distal_load_witness_n"])
        name = self.rules["distal_macro"] if loaded else self.rules["local_macro"]
        macro = self.macros[name]
        return macro.name if self.request_repair(macro, observation.tip_position, run, time_s) else None


class BlindThenRecover(CableAwareRules):
    """Disclosed retrofit: a blind nominal insertion routine plus a recovery supervisor.

    The first attempt is an existing local routine that drives to the *nominal*
    seated depth without using the measured mounting offset, so a real mounting
    tolerance produces a physically witnessed contact stall. Only after that
    witness does the recovery supervisor act, with the same observations, action
    authority and repair library as every other arm. This retrofit assumption is
    stated explicitly and is not a claim that prevention is impossible.
    """

    def __init__(self, cfg: dict, initial_tip, axis, macros, rules, blind: dict):
        super().__init__(cfg, initial_tip, axis, macros, rules)
        self.blind = blind
        self.phase = "blind_insert"
        self.handed_off = False

    def on_witness(self, observation: RecoveryObservation, run, time_s: float) -> str | None:
        self.handed_off = True
        return super().on_witness(observation, run, time_s)

    def step(self, observation: RecoveryObservation, dt: float):
        if not self.handed_off:
            axial = float(abs((observation.wrist_force_world-observation.precontact_bias_world) @ self.axis))
            goal = self.origin+self.axis*self.blind["depth_m"]
            return (self.reference.toward(goal, dt, self.blind["speed_m_per_s"]),
                    "blind_insert", axial)
        return super().step(observation, dt)
