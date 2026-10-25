"""Tracker guloso por IoU, com fallback por distância (a 1-3 fps a pessoa "pula" entre quadros)."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from iara.domain import Detection, Track

_HISTORY_S = 600.0


@dataclass(slots=True)
class TrackUpdate:
    active: list[Track]
    new: list[Track] = field(default_factory=list)
    removed: list[Track] = field(default_factory=list)


class IoUTracker:
    def __init__(
        self, iou_threshold: float = 0.25, max_distance: float = 0.15, max_missed_s: float = 2.5
    ) -> None:
        self._iou_threshold = iou_threshold
        self._max_distance = max_distance
        self._max_missed_s = max_missed_s
        self._tracks: dict[int, Track] = {}
        self._next_id = 1

    @property
    def tracks(self) -> list[Track]:
        return list(self._tracks.values())

    def update(self, detections: list[Detection], ts: float) -> TrackUpdate:
        candidates: list[tuple[float, int, int]] = []
        for tid, track in self._tracks.items():
            for di, det in enumerate(detections):
                iou = track.bbox.iou(det.bbox)
                if iou >= self._iou_threshold:
                    candidates.append((1.0 + iou, tid, di))
                    continue
                dist = math.dist(track.bbox.center, det.bbox.center)
                if dist <= self._max_distance:
                    candidates.append((1.0 - dist / self._max_distance, tid, di))
        candidates.sort(reverse=True)

        matched_tracks: set[int] = set()
        matched_dets: set[int] = set()
        for _, tid, di in candidates:
            if tid in matched_tracks or di in matched_dets:
                continue
            matched_tracks.add(tid)
            matched_dets.add(di)
            track = self._tracks[tid]
            track.bbox = detections[di].bbox
            track.last_seen = ts
            track.history.append((ts, track.bbox.foot))
            self._trim(track, ts)

        new: list[Track] = []
        for di, det in enumerate(detections):
            if di in matched_dets:
                continue
            track = Track(self._next_id, det.bbox, ts, ts, [(ts, det.bbox.foot)])
            self._next_id += 1
            self._tracks[track.id] = track
            new.append(track)

        removed = [t for t in self._tracks.values() if ts - t.last_seen > self._max_missed_s]
        for t in removed:
            del self._tracks[t.id]

        return TrackUpdate(active=self.tracks, new=new, removed=removed)

    @staticmethod
    def _trim(track: Track, ts: float) -> None:
        cutoff = ts - _HISTORY_S
        while track.history and track.history[0][0] < cutoff:
            track.history.pop(0)
