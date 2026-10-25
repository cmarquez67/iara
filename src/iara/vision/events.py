"""Transforma tracks + zonas em eventos de cena. Usa só os timestamps dos quadros (testável)."""

from __future__ import annotations

import math
from dataclasses import dataclass

from iara.config import DetectionConfig, ZonesConfig
from iara.domain import (
    CounterOccupied,
    CounterVacated,
    CustomerWaitingUnattended,
    PeopleCountChanged,
    PersonEntered,
    PersonLeft,
    PersonLingering,
    SceneEvent,
    Track,
)
from iara.vision.tracker import TrackUpdate
from iara.vision.zones import Zone


@dataclass(slots=True)
class _TrackState:
    born_in_door: bool
    entered: bool = False
    lingering_reported: bool = False


@dataclass(frozen=True, slots=True)
class SceneStatus:
    people: int
    counter_occupied: bool
    staff_present: bool


class EventDetector:
    def __init__(self, zones: ZonesConfig, cfg: DetectionConfig) -> None:
        self.door = Zone.from_points("door", zones.door)
        self.counter = Zone.from_points("counter", zones.counter)
        self.staff = Zone.from_points("staff", zones.staff)
        self._cfg = cfg
        self._states: dict[int, _TrackState] = {}
        self._people = 0
        self._counter_occupied = False
        self._counter_last_seen: float | None = None
        self._counter_since: float | None = None
        self._unattended_reported = False
        self._staff_present = False

    @property
    def status(self) -> SceneStatus:
        return SceneStatus(self._people, self._counter_occupied, self._staff_present)

    def update(self, upd: TrackUpdate, ts: float) -> list[SceneEvent]:
        events: list[SceneEvent] = []

        for track in upd.new:
            self._states[track.id] = _TrackState(born_in_door=self.door.contains(track.bbox.foot))

        for track in upd.active:
            state = self._states.setdefault(track.id, _TrackState(born_in_door=False))
            if not state.entered and self._has_entered(track, state, ts):
                state.entered = True
                events.append(PersonEntered(track.id))
            if not state.lingering_reported and self._is_lingering(track, ts):
                state.lingering_reported = True
                events.append(PersonLingering(track.id, ts - track.first_seen))

        for track in upd.removed:
            state = self._states.pop(track.id, None)
            if self._cfg.entry_mode == "appear":
                if state is not None and state.entered:
                    events.append(PersonLeft(track.id))
                continue
            # Só conta saída quem passou pelo interior; quem só cruzou a frente da porta não.
            leaving_from_inside = state is None or state.entered or not state.born_in_door
            if self.door.contains(track.bbox.foot) and leaving_from_inside:
                events.append(PersonLeft(track.id))

        customers = [t for t in upd.active if not self.staff.contains(t.bbox.foot)]
        self._staff_present = len(customers) < len(upd.active)

        people = len(upd.active)
        if people != self._people:
            self._people = people
            events.append(PeopleCountChanged(people))

        events.extend(self._update_counter(customers, ts))
        return events

    def _update_counter(self, customers: list[Track], ts: float) -> list[SceneEvent]:
        events: list[SceneEvent] = []
        someone_at_counter = any(self.counter.contains(t.bbox.foot) for t in customers)
        if someone_at_counter:
            self._counter_last_seen = ts
            if not self._counter_occupied:
                self._counter_occupied = True
                self._counter_since = ts
                self._unattended_reported = False
                events.append(CounterOccupied())
        elif self._counter_occupied:
            last = self._counter_last_seen or ts
            if ts - last >= self._cfg.counter_vacate_s:
                self._counter_occupied = False
                self._counter_since = None
                events.append(CounterVacated())

        if self._counter_occupied and self._staff_present:
            # Atendente apareceu: o relógio de espera recomeça.
            self._counter_since = ts
            self._unattended_reported = False
        elif self._counter_occupied and not self._unattended_reported:
            waited = ts - (self._counter_since or ts)
            if waited >= self._cfg.unattended_s:
                self._unattended_reported = True
                events.append(CustomerWaitingUnattended(waited))
        return events

    def _has_entered(self, track: Track, state: _TrackState, ts: float) -> bool:
        foot = track.bbox.foot
        if self._cfg.entry_mode == "appear":
            confirmed = ts - track.first_seen >= self._cfg.entry_confirm_s and len(track.history) >= 2
            return confirmed and not self.staff.contains(foot)
        return state.born_in_door and not self.door.contains(foot)

    def _is_lingering(self, track: Track, ts: float) -> bool:
        window = self._cfg.lingering_s
        if ts - track.first_seen < window:
            return False
        foot = track.bbox.foot
        if self.counter.contains(foot) or self.staff.contains(foot):
            return False
        recent = [p for t, p in track.history if ts - t <= window]
        if not recent:
            return False
        max_disp = max(math.dist(p, foot) for p in recent)
        return max_disp <= self._cfg.lingering_max_displacement
