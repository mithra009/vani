"""Timeline document, operations and layout (design §10.1–10.2). Pure functions, no I/O.

Two clocks: source time `s` (seconds into the original video, where chunk anchors live) and
timeline time `t` (seconds in the edited output). The video track maps one to the other; its
clips are contiguous (deleting a clip ripples later clips left, D2).

The document keeps tracks keyed by kind (one track of each) rather than the illustrative list
in §10.1; voice clips are keyed by chunk id and default to "at the anchor, untrimmed".

Every op is validated; apply() returns (new_doc, inverse_op). An op that can't apply raises
InputInvalid — never a silent no-op. The browser runs the same rules (frontend/src/lib/timeline.js).
"""

from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, field

from .errors import InputInvalid

MIN_CLIP_S = 0.1
GAIN_MIN_DB, GAIN_MAX_DB = -60.0, 12.0
EPS = 1e-6


def new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:10]}"


def default_doc(duration_s: float) -> dict:
    return {
        "video": [{"id": "vc0", "src_in": 0.0, "src_out": round(float(duration_s), 3)}],
        "original_audio": {"gain_db": -12.0, "muted": False, "auto_duck": True},   # C8: linked to video
        "voice": {"gain_db": 0.0, "clips": {}},
        "music": {"gain_db": -18.0, "clips": []},
        "captions": {"enabled": False},
    }


# ------------------------------------------------------------------ mapping

def video_layout(doc: dict) -> list[dict]:
    """Video clips with their timeline start `t` (contiguous from 0)."""
    out, t = [], 0.0
    for c in doc["video"]:
        out.append({**c, "t": round(t, 6)})
        t += c["src_out"] - c["src_in"]
    return out


def duration_t(doc: dict) -> float:
    return round(sum(c["src_out"] - c["src_in"] for c in doc["video"]), 6)


def src_to_t(doc: dict, s: float) -> float | None:
    """Timeline time of source moment `s`, or None when that moment was cut out (D2).
    Clips never share source time (_check_video), so at most one clip matches."""
    for c in video_layout(doc):
        if c["src_in"] - EPS <= s < c["src_out"]:
            return c["t"] + (s - c["src_in"])
    return None


def voice_clip(doc: dict, chunk_id: str) -> dict:
    return {"offset": 0.0, "trim_in": 0.0, "trim_out": 0.0, "gain_db": 0.0, "muted": False, "detached_t": None,
            **doc["voice"]["clips"].get(chunk_id, {})}


@dataclass
class Placed:
    chunk_id: str
    t: float
    length: float
    trim_in: float
    gain_db: float
    muted: bool
    flags: list[str] = field(default_factory=list)


def layout(doc: dict, chunks: list[dict]) -> tuple[list[Placed], list[dict]]:
    """Visible voice clips with timeline positions and flags (D6), plus hidden ones with reasons.

    chunks: rows with id, anchor_src_s, anchor_len_s, audio_duration_s, status."""
    placed, hidden = [], []
    end = duration_t(doc)
    vl = video_layout(doc)
    for ch in sorted(chunks, key=lambda c: c["idx"]):
        cid = str(ch["id"])
        vc = voice_clip(doc, cid)
        if ch.get("anchor_src_s") is None:
            hidden.append({"chunk_id": cid, "reason": "unplaced"})
            continue
        if not ch.get("audio_duration_s"):
            hidden.append({"chunk_id": cid, "reason": "no_audio"})
            continue
        anchor = float(ch["anchor_src_s"])
        if vc["detached_t"] is not None:                                   # C6: free-floating
            t = float(vc["detached_t"])
        else:
            mapped = src_to_t(doc, anchor)
            if mapped is None:
                hidden.append({"chunk_id": cid, "reason": "video_cut"})
                continue
            t = mapped + vc["offset"]
        length = max(0.0, float(ch["audio_duration_s"]) - vc["trim_in"] - vc["trim_out"])
        p = Placed(cid, round(t, 6), round(length, 6), vc["trim_in"], vc["gain_db"], vc["muted"])
        if t < -EPS:
            p.flags.append("before_start")
        if t + length > end + EPS:
            p.flags.append("past_end")
        if vc["detached_t"] is None and ch.get("anchor_len_s") is not None:
            span_end = anchor + float(ch["anchor_len_s"])
            home = next((c for c in vl if c["src_in"] - EPS <= anchor < c["src_out"] - EPS), None)
            if home and span_end > home["src_out"] + 0.05:
                p.flags.append("on_cut")
        placed.append(p)
    audible = sorted((p for p in placed if not p.muted), key=lambda p: p.t)
    for i, a in enumerate(audible):
        for b in audible[i + 1:]:
            if b.t >= a.t + a.length - EPS:
                break
            for x in (a, b):
                if "overlap" not in x.flags:
                    x.flags.append("overlap")                              # D6: allowed, flagged
    return placed, hidden


# ------------------------------------------------------------------ ops

def _num(op: dict, key: str, lo: float | None = None, hi: float | None = None) -> float:
    v = op.get(key)
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        raise InputInvalid(f"{op.get('type')}: '{key}' must be a number.")
    v = float(v)
    if (lo is not None and v < lo - EPS) or (hi is not None and v > hi + EPS):
        raise InputInvalid(f"{op.get('type')}: '{key}' must be between {lo} and {hi}, got {v}.")
    return v


def _video_index(doc: dict, clip_id) -> int:
    for i, c in enumerate(doc["video"]):
        if c["id"] == clip_id:
            return i
    raise InputInvalid(f"No video clip {clip_id!r}.")


def _check_video(doc: dict) -> None:
    if not doc["video"]:
        raise InputInvalid("The video track can't be empty.")
    spans = sorted((c["src_in"], c["src_out"]) for c in doc["video"])
    for (a0, a1), (b0, _) in zip(spans, spans[1:]):
        if b0 < a1 - EPS:
            raise InputInvalid("Video clips can't reuse the same part of the source.")
    for c in doc["video"]:
        if c["src_out"] - c["src_in"] < MIN_CLIP_S - EPS:
            raise InputInvalid(f"Video clips must be at least {MIN_CLIP_S}s long.")


VOICE_FIELDS = {"offset": (-30.0, 30.0), "trim_in": (0.0, 600.0), "trim_out": (0.0, 600.0),
                "gain_db": (GAIN_MIN_DB, GAIN_MAX_DB)}
TRACK_FIELDS = {
    "original_audio": {"gain_db": "gain", "muted": "bool", "auto_duck": "bool"},
    "voice": {"gain_db": "gain"},
    "music": {"gain_db": "gain"},
    "captions": {"enabled": "bool"},
}
MUSIC_FIELDS = {"t": (0.0, 3600.0), "media_in": (0.0, 3600.0), "media_out": (0.0, 3600.0),
                "fade_in": (0.0, 30.0), "fade_out": (0.0, 30.0), "gain_db": (GAIN_MIN_DB, GAIN_MAX_DB)}


def apply(doc: dict, op: dict, *, source_s: float, chunk_ids: set[str] | None = None,
          media: dict[str, float] | None = None) -> tuple[dict, dict]:
    """Apply one op to a copy of doc. Returns (doc', inverse). source_s bounds video edits;
    chunk_ids / media (id → duration) validate references when given (server side)."""
    if not isinstance(op, dict) or not isinstance(op.get("type"), str):
        raise InputInvalid(f"Malformed op {op!r}"[:200])
    d = copy.deepcopy(doc)
    kind = op["type"]

    if kind == "video.trim":
        i = _video_index(d, op.get("clip_id"))
        old = dict(d["video"][i])
        d["video"][i]["src_in"] = _num(op, "src_in", 0, source_s)
        d["video"][i]["src_out"] = _num(op, "src_out", 0, source_s)
        if d["video"][i]["src_out"] <= d["video"][i]["src_in"]:
            raise InputInvalid("video.trim: src_out must be after src_in.")
        _check_video(d)
        inv = {"type": "video.trim", "clip_id": old["id"], "src_in": old["src_in"], "src_out": old["src_out"]}

    elif kind == "video.split":
        i = _video_index(d, op.get("clip_id"))
        c = d["video"][i]
        at = _num(op, "at_src", c["src_in"], c["src_out"])
        new = {"id": op.get("new_id") or new_id("vc"), "src_in": at, "src_out": c["src_out"]}
        c["src_out"] = at
        d["video"].insert(i + 1, new)
        _check_video(d)
        inv = {"type": "video.join", "clip_id": c["id"], "next_id": new["id"]}

    elif kind == "video.join":                     # inverse of split: two source-adjacent clips
        i = _video_index(d, op.get("clip_id"))
        j = _video_index(d, op.get("next_id"))
        if j != i + 1 or abs(d["video"][i]["src_out"] - d["video"][j]["src_in"]) > EPS:
            raise InputInvalid("video.join: clips must be next to each other in both orders.")
        at = d["video"][i]["src_out"]
        d["video"][i]["src_out"] = d["video"][j]["src_out"]
        removed = d["video"].pop(j)
        inv = {"type": "video.split", "clip_id": d["video"][i]["id"], "at_src": at, "new_id": removed["id"]}

    elif kind == "video.delete":                   # ripple; anchored voice disappears (D2)
        i = _video_index(d, op.get("clip_id"))
        removed = d["video"].pop(i)
        _check_video(d)
        inv = {"type": "video.insert", "index": i, "clip": removed}

    elif kind == "video.insert":
        clip = op.get("clip")
        if not isinstance(clip, dict) or not clip.get("id"):
            raise InputInvalid("video.insert: needs a clip with an id.")
        idx = int(_num(op, "index", 0, len(d["video"])))
        c = {"id": clip["id"], "src_in": _num(clip | {"type": kind}, "src_in", 0, source_s),
             "src_out": _num(clip | {"type": kind}, "src_out", 0, source_s)}
        if any(x["id"] == c["id"] for x in d["video"]):
            raise InputInvalid(f"video.insert: clip {c['id']!r} already exists.")
        d["video"].insert(idx, c)
        _check_video(d)
        inv = {"type": "video.delete", "clip_id": c["id"]}

    elif kind == "video.move":
        i = _video_index(d, op.get("clip_id"))
        to = int(_num(op, "index", 0, len(d["video"]) - 1))
        d["video"].insert(to, d["video"].pop(i))
        inv = {"type": "video.move", "clip_id": op["clip_id"], "index": i}

    elif kind == "voice.set":
        cid = op.get("chunk_id")
        if not isinstance(cid, str) or (chunk_ids is not None and cid not in chunk_ids):
            raise InputInvalid(f"voice.set: no chunk {cid!r}.")
        fields = op.get("fields")
        if not isinstance(fields, dict) or not fields:
            raise InputInvalid("voice.set: 'fields' must be a non-empty object.")
        old = voice_clip(d, cid)
        clip = d["voice"]["clips"].setdefault(cid, {})
        for k, v in fields.items():
            if k in VOICE_FIELDS:
                clip[k] = _num({"type": kind, k: v}, k, *VOICE_FIELDS[k])
            elif k == "muted":
                if not isinstance(v, bool):
                    raise InputInvalid("voice.set: 'muted' must be true/false.")
                clip[k] = v
            elif k == "detached_t":                 # C6-proposal: detach allowed
                clip[k] = None if v is None else _num({"type": kind, k: v}, k, 0, 3600)
            else:
                raise InputInvalid(f"voice.set: unknown field {k!r}.")
        inv = {"type": "voice.set", "chunk_id": cid, "fields": {k: old[k] for k in fields}}

    elif kind == "track.set":
        track = op.get("track")
        allowed = TRACK_FIELDS.get(track)
        fields = op.get("fields")
        if allowed is None:
            raise InputInvalid(f"track.set: unknown track {track!r}.")
        if not isinstance(fields, dict) or not fields:
            raise InputInvalid("track.set: 'fields' must be a non-empty object.")
        old = {}
        for k, v in fields.items():
            t = allowed.get(k)
            if t is None:
                raise InputInvalid(f"track.set: {track} has no field {k!r}.")
            old[k] = d[track][k]
            if t == "bool":
                if not isinstance(v, bool):
                    raise InputInvalid(f"track.set: '{k}' must be true/false.")
                d[track][k] = v
            else:
                d[track][k] = _num({"type": kind, k: v}, k, GAIN_MIN_DB, GAIN_MAX_DB)
        inv = {"type": "track.set", "track": track, "fields": old}

    elif kind == "music.add":
        clip = op.get("clip")
        if not isinstance(clip, dict) or not clip.get("media_id"):
            raise InputInvalid("music.add: needs a clip with a media_id.")
        if media is not None and clip["media_id"] not in media:
            raise InputInvalid(f"music.add: no uploaded audio {clip['media_id']!r}.")
        mlen = media.get(clip["media_id"]) if media else None
        defaults = {"t": 0.0, "media_in": 0.0, "media_out": mlen, "fade_in": 0.0, "fade_out": 0.0, "gain_db": 0.0}
        c = {"id": clip.get("id") or new_id("mc"), "media_id": clip["media_id"]}
        for k, (lo, hi) in MUSIC_FIELDS.items():
            hi = mlen if k in ("media_in", "media_out") and mlen else hi
            c[k] = _num({"type": kind, k: clip.get(k, defaults[k])}, k, lo, hi)
        if c["media_out"] <= c["media_in"]:
            raise InputInvalid("music.add: media_out must be after media_in.")
        if any(x["id"] == c["id"] for x in d["music"]["clips"]):
            raise InputInvalid(f"music.add: clip {c['id']!r} already exists.")
        d["music"]["clips"].append(c)
        inv = {"type": "music.delete", "clip_id": c["id"]}

    elif kind == "music.delete":
        i = next((i for i, c in enumerate(d["music"]["clips"]) if c["id"] == op.get("clip_id")), None)
        if i is None:
            raise InputInvalid(f"music.delete: no clip {op.get('clip_id')!r}.")
        removed = d["music"]["clips"].pop(i)
        inv = {"type": "music.add", "clip": removed}

    elif kind == "music.set":
        c = next((c for c in d["music"]["clips"] if c["id"] == op.get("clip_id")), None)
        fields = op.get("fields")
        if c is None:
            raise InputInvalid(f"music.set: no clip {op.get('clip_id')!r}.")
        if not isinstance(fields, dict) or not fields:
            raise InputInvalid("music.set: 'fields' must be a non-empty object.")
        old = {}
        for k, v in fields.items():
            if k not in MUSIC_FIELDS:
                raise InputInvalid(f"music.set: unknown field {k!r}.")
            old[k] = c[k]
            c[k] = _num({"type": kind, k: v}, k, *MUSIC_FIELDS[k])
        if c["media_out"] <= c["media_in"]:
            raise InputInvalid("music.set: media_out must be after media_in.")
        inv = {"type": "music.set", "clip_id": c["id"], "fields": old}

    else:
        raise InputInvalid(f"Unknown op type {kind!r}.")
    return d, inv


def apply_all(doc: dict, ops: list, **kw) -> tuple[dict, list[dict]]:
    if not isinstance(ops, list) or not ops:
        raise InputInvalid("ops must be a non-empty list.")
    inverses = []
    for n, op in enumerate(ops):
        try:
            doc, inv = apply(doc, op, **kw)
        except InputInvalid as e:
            raise InputInvalid(f"Op {n} ({op.get('type') if isinstance(op, dict) else '?'}): {e}") from e
        inverses.append(inv)
    return doc, inverses
