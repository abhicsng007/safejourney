"""Data repository — Firestore in production, in-memory for local dev/tests.

The interface is deliberately small (trips, snapshots, alerts, incidents, users, cache) so
the rest of the app never touches Firestore SDK types directly.
"""

from __future__ import annotations

import threading
import time
from typing import Optional

from safejourney_shared.models import (
    Alert,
    HazardSnapshot,
    Incident,
    Trip,
    TripStatus,
    UserProfile,
)

from .config import get_settings


class InMemoryRepo:
    """Thread-safe dict-backed repo. State lives only for the process lifetime."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._trips: dict[str, Trip] = {}
        self._snaps: dict[str, HazardSnapshot] = {}
        self._alerts: dict[str, Alert] = {}
        self._incidents: dict[str, Incident] = {}
        self._users: dict[str, UserProfile] = {}
        self._cache: dict[str, tuple[float, dict]] = {}

    # --- users ---
    def upsert_user(self, u: UserProfile) -> UserProfile:
        with self._lock:
            self._users[u.uid] = u
            return u

    def get_user(self, uid: str) -> Optional[UserProfile]:
        return self._users.get(uid)

    # --- trips ---
    def save_trip(self, t: Trip) -> Trip:
        with self._lock:
            self._trips[t.id] = t
            return t

    def get_trip(self, trip_id: str) -> Optional[Trip]:
        return self._trips.get(trip_id)

    def list_trips(self, uid: Optional[str] = None) -> list[Trip]:
        with self._lock:
            ts = list(self._trips.values())
        if uid:
            ts = [t for t in ts if t.uid == uid]
        return sorted(ts, key=lambda t: t.created_at, reverse=True)

    def due_active_trips(self, now: Optional[float] = None) -> list[Trip]:
        """Active trips whose next_check_at has passed — the dispatcher's query."""
        now = now or time.time()
        with self._lock:
            return [
                t
                for t in self._trips.values()
                if t.status == TripStatus.ACTIVE and t.next_check_at <= now
            ]

    # --- snapshots ---
    def save_snapshot(self, s: HazardSnapshot) -> HazardSnapshot:
        with self._lock:
            self._snaps[s.id] = s
            return s

    def get_snapshot(self, sid: str) -> Optional[HazardSnapshot]:
        return self._snaps.get(sid)

    # --- alerts ---
    def save_alert(self, a: Alert) -> Alert:
        with self._lock:
            self._alerts[a.id] = a
            return a

    def list_alerts(self, trip_id: str) -> list[Alert]:
        with self._lock:
            al = [a for a in self._alerts.values() if a.trip_id == trip_id]
        return sorted(al, key=lambda a: a.created_at, reverse=True)

    def ack_alert(self, alert_id: str) -> Optional[Alert]:
        with self._lock:
            a = self._alerts.get(alert_id)
            if a:
                a.acknowledged = True
            return a

    # --- incidents ---
    def add_incident(self, inc: Incident) -> Incident:
        with self._lock:
            self._incidents[inc.id] = inc
            return inc

    def incidents_in_cells(self, geohashes: set[str], prefix_len: int = 6) -> list[Incident]:
        """Incidents whose geohash shares a cell prefix with the corridor."""
        now = time.time()
        prefixes = {g[:prefix_len] for g in geohashes}
        out: list[Incident] = []
        with self._lock:
            for inc in self._incidents.values():
                if inc.expires_at and inc.expires_at < now:
                    continue
                if inc.geohash[:prefix_len] in prefixes:
                    out.append(inc)
        return out

    def delete_expired_incidents(self, now: Optional[float] = None) -> int:
        """Physically remove incidents past their expires_at. Returns how many were deleted."""
        now = now or time.time()
        with self._lock:
            stale = [i for i, inc in self._incidents.items() if inc.expires_at and inc.expires_at < now]
            for i in stale:
                self._incidents.pop(i, None)
        return len(stale)

    def delete_all_incidents(self) -> int:
        """Wipe every incident — a clean slate for a fresh demo run. Returns how many."""
        with self._lock:
            n = len(self._incidents)
            self._incidents.clear()
        return n

    def complete_all_active_trips(self) -> int:
        """Mark every active trip completed — stops the dispatcher churning on stale test
        trips after a demo reset. Returns how many were closed."""
        with self._lock:
            n = 0
            for t in self._trips.values():
                if t.status == TripStatus.ACTIVE:
                    t.status = TripStatus.COMPLETED
                    n += 1
        return n

    # --- hazard cache (geohash+type keyed, TTL) ---
    def cache_get(self, key: str) -> Optional[dict]:
        item = self._cache.get(key)
        if not item:
            return None
        exp, val = item
        if exp < time.time():
            self._cache.pop(key, None)
            return None
        return val

    def cache_set(self, key: str, val: dict, ttl_s: int) -> None:
        self._cache[key] = (time.time() + ttl_s, val)


class FirestoreRepo(InMemoryRepo):
    """Firestore-backed repo. Falls back to in-memory behaviour for the hazard cache.

    Collections: users, trips, snapshots, alerts, incidents.
    (Kept intentionally close to InMemoryRepo so behaviour is identical in tests.)
    """

    def __init__(self, project: str) -> None:
        super().__init__()
        from google.cloud import firestore  # imported lazily

        self.db = firestore.Client(project=project)

    def upsert_user(self, u: UserProfile) -> UserProfile:
        self.db.collection("users").document(u.uid).set(u.model_dump(mode="json"))
        return u

    def get_user(self, uid: str) -> Optional[UserProfile]:
        d = self.db.collection("users").document(uid).get()
        return UserProfile(**d.to_dict()) if d.exists else None

    def save_trip(self, t: Trip) -> Trip:
        self.db.collection("trips").document(t.id).set(t.model_dump(mode="json"))
        return t

    def get_trip(self, trip_id: str) -> Optional[Trip]:
        d = self.db.collection("trips").document(trip_id).get()
        return Trip(**d.to_dict()) if d.exists else None

    def list_trips(self, uid: Optional[str] = None) -> list[Trip]:
        col = self.db.collection("trips")
        q = col.where("uid", "==", uid) if uid else col
        return [Trip(**d.to_dict()) for d in q.stream()]

    def due_active_trips(self, now: Optional[float] = None) -> list[Trip]:
        now = now or time.time()
        q = (
            self.db.collection("trips")
            .where("status", "==", TripStatus.ACTIVE.value)
            .where("next_check_at", "<=", now)
        )
        return [Trip(**d.to_dict()) for d in q.stream()]

    def save_snapshot(self, s: HazardSnapshot) -> HazardSnapshot:
        self.db.collection("snapshots").document(s.id).set(s.model_dump(mode="json"))
        return s

    def get_snapshot(self, sid: str) -> Optional[HazardSnapshot]:
        d = self.db.collection("snapshots").document(sid).get()
        return HazardSnapshot(**d.to_dict()) if d.exists else None

    def save_alert(self, a: Alert) -> Alert:
        self.db.collection("alerts").document(a.id).set(a.model_dump(mode="json"))
        return a

    def list_alerts(self, trip_id: str) -> list[Alert]:
        q = self.db.collection("alerts").where("trip_id", "==", trip_id)
        al = [Alert(**d.to_dict()) for d in q.stream()]
        return sorted(al, key=lambda a: a.created_at, reverse=True)

    def add_incident(self, inc: Incident) -> Incident:
        self.db.collection("incidents").document(inc.id).set(inc.model_dump(mode="json"))
        return inc

    def incidents_in_cells(self, geohashes: set[str], prefix_len: int = 6) -> list[Incident]:
        prefixes = sorted({g[:prefix_len] for g in geohashes})
        now = time.time()
        out: list[Incident] = []
        col = self.db.collection("incidents")
        # Firestore range query per prefix (geohash prefix = [p, p + '~']).
        for p in prefixes:
            q = col.where("geohash", ">=", p).where("geohash", "<", p + "~")
            for d in q.stream():
                inc = Incident(**d.to_dict())
                if inc.expires_at and inc.expires_at < now:
                    continue
                out.append(inc)
        return out

    def delete_expired_incidents(self, now: Optional[float] = None) -> int:
        """Batch-delete incidents past their expires_at (a Cloud Scheduler cleanup target)."""
        now = now or time.time()
        col = self.db.collection("incidents")
        q = col.where("expires_at", "<", now).limit(400)  # bounded per run; scheduler drains over time
        batch = self.db.batch()
        count = 0
        for d in q.stream():
            batch.delete(d.reference)
            count += 1
        if count:
            batch.commit()
        return count

    def delete_all_incidents(self) -> int:
        """Wipe every incident — a clean slate for a fresh demo run. Returns how many."""
        col = self.db.collection("incidents")
        count = 0
        batch = self.db.batch()
        for d in col.limit(500).stream():
            batch.delete(d.reference)
            count += 1
        if count:
            batch.commit()
        return count

    def complete_all_active_trips(self) -> int:
        """Mark every active trip completed — stops the dispatcher churning on stale test
        trips after a demo reset. Returns how many were closed."""
        q = self.db.collection("trips").where("status", "==", TripStatus.ACTIVE.value).limit(500)
        count = 0
        batch = self.db.batch()
        for d in q.stream():
            batch.update(d.reference, {"status": TripStatus.COMPLETED.value})
            count += 1
        if count:
            batch.commit()
        return count


_repo: Optional[InMemoryRepo] = None


def get_repo() -> InMemoryRepo:
    global _repo
    if _repo is not None:
        return _repo
    s = get_settings()
    if s.use_firestore and s.firestore_project:
        try:
            _repo = FirestoreRepo(s.firestore_project)
        except Exception as e:  # pragma: no cover - depends on cloud creds
            print(f"[repo] Firestore unavailable ({e}); using in-memory repo.")
            _repo = InMemoryRepo()
    else:
        _repo = InMemoryRepo()
    return _repo
