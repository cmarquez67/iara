from iara.config import DetectionConfig
from iara.domain import (
    CounterOccupied,
    CounterVacated,
    CustomerWaitingUnattended,
    PeopleCountChanged,
    PersonEntered,
    PersonLeft,
    PersonLingering,
)
from iara.vision.events import EventDetector
from iara.vision.tracker import IoUTracker

from .conftest import ZONES, person_at

CFG = DetectionConfig(counter_vacate_s=2.0, unattended_s=10.0, lingering_s=20.0, track_max_missed_s=1.0)


class Scene:
    """Alimenta tracker + detector de eventos com detecções sintéticas a 2 fps."""

    def __init__(self, cfg: DetectionConfig = CFG) -> None:
        self.tracker = IoUTracker(max_distance=0.15, max_missed_s=cfg.track_max_missed_s)
        self.events = EventDetector(ZONES, cfg)
        self.ts = 0.0
        self.log: list = []

    def step(self, *people, dt: float = 0.5) -> list:
        self.ts += dt
        out = self.events.update(self.tracker.update(list(people), self.ts), self.ts)
        self.log.extend(out)
        return out

    def of(self, kind) -> list:
        return [e for e in self.log if isinstance(e, kind)]


def walk(scene: Scene, points: list[tuple[float, float]]) -> None:
    for x, y in points:
        scene.step(person_at(x, y))


DOOR_TO_COUNTER = [
    (0.9, 0.9),
    (0.82, 0.88),
    (0.74, 0.86),
    (0.66, 0.84),
    (0.58, 0.82),
    (0.5, 0.8),
    (0.42, 0.8),
]


def test_person_entering_through_door_emits_entered_once():
    s = Scene()
    walk(s, DOOR_TO_COUNTER)
    assert len(s.of(PersonEntered)) == 1
    assert s.of(PeopleCountChanged)[0].count == 1


def test_person_appearing_inside_is_not_greeted():
    s = Scene()
    walk(s, [(0.4, 0.5), (0.42, 0.5), (0.44, 0.5)])
    assert s.of(PersonEntered) == []


def test_passerby_at_door_is_neither_entered_nor_left():
    s = Scene()
    walk(s, [(0.9, 0.9), (0.92, 0.9)])
    for _ in range(4):
        s.step()
    assert s.of(PersonEntered) == []
    assert s.of(PersonLeft) == []


def test_person_leaving_through_door_emits_left():
    s = Scene()
    walk(s, list(reversed(DOOR_TO_COUNTER)))
    for _ in range(4):
        s.step()
    assert s.of(PersonEntered) == []
    assert len(s.of(PersonLeft)) == 1
    assert s.of(PeopleCountChanged)[-1].count == 0


def test_counter_occupied_then_vacated_with_debounce():
    s = Scene()
    s.step(person_at(0.3, 0.8))
    assert s.of(CounterOccupied)
    # sumiu por um quadro (falha do detector): ainda ocupado
    s.step()
    s.step(person_at(0.3, 0.8))
    assert not s.of(CounterVacated)
    # saiu do balcão de verdade
    for _ in range(6):
        s.step(person_at(0.6, 0.4))
    assert len(s.of(CounterVacated)) == 1
    assert len(s.of(CounterOccupied)) == 1


def test_unattended_customer_alert_when_no_staff():
    s = Scene()
    for _ in range(25):  # 12.5 s no balcão
        s.step(person_at(0.3, 0.8))
    alerts = s.of(CustomerWaitingUnattended)
    assert len(alerts) == 1
    assert alerts[0].seconds >= 10.0


def test_no_unattended_alert_when_staff_present():
    s = Scene()
    for _ in range(30):
        s.step(person_at(0.3, 0.8), person_at(0.12, 0.4))
    assert s.of(CustomerWaitingUnattended) == []
    assert s.events.status.staff_present


def test_staff_alone_does_not_occupy_counter():
    s = Scene()
    s.step(person_at(0.12, 0.4))
    assert s.of(CounterOccupied) == []


def test_lingering_person_reported_once():
    s = Scene()
    for _ in range(50):  # 25 s parado no meio da loja
        s.step(person_at(0.6, 0.5))
    assert len(s.of(PersonLingering)) == 1


def test_person_moving_around_is_not_lingering():
    s = Scene()
    for i in range(50):
        s.step(person_at(0.55 + 0.1 * ((i // 4) % 2), 0.5))
    assert s.of(PersonLingering) == []


def test_feet_on_bottom_edge_count_as_inside_counter():
    # webcam perto: a caixa encosta na borda de baixo (y = 1.0)
    s = Scene()
    s.step(person_at(0.3, 1.0))
    assert s.of(CounterOccupied)


APPEAR = DetectionConfig(entry_mode="appear", entry_confirm_s=1.0, track_max_missed_s=1.0)


def test_appear_mode_greets_anyone_who_stays_visible():
    s = Scene(APPEAR)
    s.step(person_at(0.5, 1.0))
    s.step(person_at(0.5, 1.0))
    assert s.of(PersonEntered) == []  # ainda não confirmou 1 s
    s.step(person_at(0.51, 1.0))
    s.step(person_at(0.5, 1.0))
    assert len(s.of(PersonEntered)) == 1
    for _ in range(4):
        s.step()
    assert len(s.of(PersonLeft)) == 1


def test_appear_mode_ignores_single_frame_false_positive():
    s = Scene(APPEAR)
    s.step(person_at(0.5, 0.8))
    for _ in range(4):
        s.step()
    assert s.of(PersonEntered) == []
    assert s.of(PersonLeft) == []
