from iara.domain import BBox
from iara.vision.tracker import IoUTracker
from iara.vision.zones import Zone

from .conftest import person_at


def test_zone_contains_square():
    z = Zone.from_points("z", [(0, 0), (0.5, 0), (0.5, 0.5), (0, 0.5)])
    assert z.contains((0.25, 0.25))
    assert not z.contains((0.75, 0.25))


def test_zone_contains_concave_polygon():
    # "L": o canto superior direito fica fora
    z = Zone.from_points("l", [(0, 0), (0.3, 0), (0.3, 0.7), (1, 0.7), (1, 1), (0, 1)])
    assert z.contains((0.1, 0.1))
    assert z.contains((0.9, 0.9))
    assert not z.contains((0.9, 0.1))


def test_empty_zone_contains_nothing():
    assert not Zone.from_points("vazia", []).contains((0.5, 0.5))


def test_bbox_iou_and_foot():
    a = BBox(0, 0, 0.5, 0.5)
    assert a.iou(a) == 1.0
    assert a.iou(BBox(0.6, 0.6, 1, 1)) == 0.0
    assert a.foot == (0.25, 0.5)


def test_tracker_keeps_id_while_person_walks():
    tr = IoUTracker(max_distance=0.15, max_missed_s=2.0)
    first = tr.update([person_at(0.9, 0.9)], ts=0.0)
    assert len(first.new) == 1
    tid = first.new[0].id
    for i, x in enumerate([0.82, 0.74, 0.66, 0.58]):  # passos de 0.08 a 2 fps
        upd = tr.update([person_at(x, 0.85)], ts=0.5 * (i + 1))
        assert [t.id for t in upd.active] == [tid]
        assert not upd.new


def test_tracker_two_people_and_removal():
    tr = IoUTracker(max_missed_s=1.0)
    upd = tr.update([person_at(0.2, 0.9), person_at(0.8, 0.9)], ts=0.0)
    assert len(upd.new) == 2
    upd = tr.update([person_at(0.21, 0.9)], ts=0.5)
    assert len(upd.active) == 2  # o segundo ainda dentro da tolerância
    upd = tr.update([person_at(0.22, 0.9)], ts=1.6)
    assert len(upd.active) == 1
    assert len(upd.removed) == 1


def test_tracker_far_jump_creates_new_track():
    tr = IoUTracker(max_distance=0.1)
    tr.update([person_at(0.1, 0.9)], ts=0.0)
    upd = tr.update([person_at(0.9, 0.9)], ts=0.5)
    assert len(upd.new) == 1
