"""Export: one ffmpeg filter graph from a timeline snapshot (design §10.5). Pure builders here;
the worker downloads inputs and runs the command.

video  : trim/setpts per clip → concat → scale to the chosen height (never upscaled)
audio  : original audio cut like the video, gain + optional auto-duck under the voice;
         each voice clip atrim + adelay to its timeline position; music with afade;
         amix (overlaps mixed, D6) → loudnorm → exactly duration_t long
captions (C3-proposal): SRT/VTT sidecar, or burned in with the subtitles filter
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import timeline

VIDEO_FORMATS = {
    "mp4": (["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"],
            ["-c:a", "aac", "-b:a", "192k"], ["-movflags", "+faststart"], "video/mp4"),
    "mov": (["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"],   # C12: H.264
            ["-c:a", "aac", "-b:a", "192k"], [], "video/quicktime"),
    "webm": (["-c:v", "libvpx-vp9", "-crf", "32", "-b:v", "0", "-row-mt", "1", "-deadline", "realtime", "-cpu-used", "8"],
             ["-c:a", "libopus", "-b:a", "128k"], [], "video/webm"),
}
AUDIO_FORMATS = {
    "mp3": (["-c:a", "libmp3lame", "-b:a", "192k"], "audio/mpeg"),
    "wav": (["-c:a", "pcm_s16le"], "audio/wav"),
}
MIX_SR = 48_000


def content_type(fmt: str) -> str:
    return VIDEO_FORMATS[fmt][3] if fmt in VIDEO_FORMATS else AUDIO_FORMATS[fmt][1]


@dataclass
class VoiceIn:
    path: str
    t: float
    trim_in: float
    length: float
    gain_db: float


@dataclass
class MusicIn:
    path: str
    t: float
    media_in: float
    media_out: float
    fade_in: float
    fade_out: float
    gain_db: float


@dataclass
class Plan:
    source: str
    source_has_audio: bool
    source_height: int
    video_clips: list[tuple[float, float]]
    duration: float
    fmt: str
    height: int | None
    audio_mix: str                       # full | voice  (C13)
    orig_gain_db: float
    orig_muted: bool
    auto_duck: bool
    voice_track_db: float
    music_track_db: float
    voices: list[VoiceIn] = field(default_factory=list)
    music: list[MusicIn] = field(default_factory=list)
    burn_captions: str | None = None     # filename relative to the ffmpeg cwd


def plan_from_snapshot(snapshot: dict, *, fmt: str, height: int | None, audio_mix: str, source: str,
                       source_has_audio: bool, source_height: int, chunk_paths: dict[str, str],
                       media_paths: dict[str, str]) -> tuple[Plan, list[dict], list[dict]]:
    """→ (plan, warnings, captions). Voice clips are placed with the same rules the editor shows."""
    doc = snapshot["doc"]
    placed, hidden = timeline.layout(doc, snapshot["chunks"])
    dur = timeline.duration_t(doc)
    texts = {str(c["id"]): c["text"] for c in snapshot["chunks"]}
    warnings = [{"chunk_id": p.chunk_id, "flags": p.flags} for p in placed if p.flags]
    warnings += [{"chunk_id": h["chunk_id"], "flags": [h["reason"]]} for h in hidden]
    voices, captions = [], []
    for p in placed:
        if p.muted or p.length <= 0:
            continue
        start, trim_in, length = p.t, p.trim_in, p.length
        if start < 0:                                    # clip starts before 0: drop the head
            trim_in, length, start = trim_in - start, length + start, 0.0
        length = min(length, dur - start)               # past the end is cut (flagged above)
        if length <= 0.01:
            continue
        voices.append(VoiceIn(chunk_paths[p.chunk_id], start, trim_in, length, p.gain_db))
        captions.append({"start": start, "end": start + length, "text": texts[p.chunk_id]})
    music = []
    for m in doc["music"]["clips"]:
        if m["t"] >= dur:
            continue
        music.append(MusicIn(media_paths[m["media_id"]], m["t"], m["media_in"], min(m["media_out"], m["media_in"] + dur - m["t"]),
                             m["fade_in"], m["fade_out"], m["gain_db"]))
    oa = doc["original_audio"]
    plan = Plan(
        source=source, source_has_audio=source_has_audio, source_height=source_height,
        video_clips=[(c["src_in"], c["src_out"]) for c in doc["video"]], duration=dur, fmt=fmt, height=height,
        audio_mix=audio_mix, orig_gain_db=oa["gain_db"], orig_muted=oa["muted"], auto_duck=oa["auto_duck"],
        voice_track_db=doc["voice"]["gain_db"], music_track_db=doc["music"]["gain_db"], voices=voices, music=music,
    )
    return plan, warnings, captions


def _ts(s: float, sep: str) -> str:
    ms = round(s * 1000)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    sec, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{sec:02d}{sep}{ms:03d}"


def captions_file(captions: list[dict], kind: str) -> str:
    """kind: srt | vtt."""
    sep = "," if kind == "srt" else "."
    lines = ["WEBVTT", ""] if kind == "vtt" else []
    for i, c in enumerate(sorted(captions, key=lambda c: c["start"]), 1):
        if kind == "srt":
            lines.append(str(i))
        lines += [f"{_ts(c['start'], sep)} --> {_ts(c['end'], sep)}", c["text"], ""]
    return "\n".join(lines)


def build_args(plan: Plan, out: str) -> list[str]:
    """Full ffmpeg argv (without the binary). Inputs: 0 = source, then voices, then music."""
    audio_only = plan.fmt in AUDIO_FORMATS
    inputs = ["-i", plan.source]
    for v in plan.voices:
        inputs += ["-i", v.path]
    for m in plan.music:
        inputs += ["-i", m.path]
    f, buses = [], []
    n = len(plan.video_clips)

    if not audio_only:
        for i, (a, b) in enumerate(plan.video_clips):
            f.append(f"[0:v]trim=start={a:.6f}:end={b:.6f},setpts=PTS-STARTPTS[v{i}]")
        f.append("".join(f"[v{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[vcat]")
        h = min(plan.height or plan.source_height, plan.source_height)
        h -= h % 2
        sub = f",subtitles={plan.burn_captions}" if plan.burn_captions else ""
        f.append(f"[vcat]scale=-2:{h}:flags=lanczos,setsar=1{sub}[vout]")

    def fmt_audio(label_in: str, label_out: str, extra: str = "") -> str:
        return f"[{label_in}]aresample={MIX_SR},aformat=sample_fmts=fltp:channel_layouts=stereo{extra}[{label_out}]"

    voice_bus = None
    if plan.voices:
        for i, v in enumerate(plan.voices, 1):
            ms = round(v.t * 1000)
            f.append(fmt_audio(f"{i}:a", f"vr{i}",
                               f",atrim=start={v.trim_in:.6f}:duration={v.length:.6f},asetpts=PTS-STARTPTS,"
                               f"volume={v.gain_db + plan.voice_track_db:.2f}dB,adelay={ms}:all=1"))
        k = len(plan.voices)
        f.append("".join(f"[vr{i}]" for i in range(1, k + 1)) + f"amix=inputs={k}:normalize=0:duration=longest[voice]")
        voice_bus = "voice"

    want_orig = plan.audio_mix == "full" and plan.source_has_audio and not plan.orig_muted
    if want_orig:
        for i, (a, b) in enumerate(plan.video_clips):
            f.append(fmt_audio("0:a", f"o{i}", f",atrim=start={a:.6f}:end={b:.6f},asetpts=PTS-STARTPTS"))
        f.append("".join(f"[o{i}]" for i in range(n)) + f"concat=n={n}:v=0:a=1,volume={plan.orig_gain_db:.2f}dB[orig]")
        if plan.auto_duck and voice_bus:
            f.append("[voice]asplit=2[voicemix][duckkey]")
            voice_bus = "voicemix"
            f.append("[orig][duckkey]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=300[origd]")
            buses.append("origd")
        else:
            buses.append("orig")
    if voice_bus:
        buses.append(voice_bus)
    if plan.audio_mix == "full" and plan.music:
        base = 1 + len(plan.voices)
        for j, m in enumerate(plan.music):
            length = m.media_out - m.media_in
            fades = ""
            if m.fade_in > 0:
                fades += f",afade=t=in:st=0:d={min(m.fade_in, length):.3f}"
            if m.fade_out > 0:
                fades += f",afade=t=out:st={max(0.0, length - m.fade_out):.3f}:d={min(m.fade_out, length):.3f}"
            f.append(fmt_audio(f"{base + j}:a", f"m{j}",
                               f",atrim=start={m.media_in:.6f}:end={m.media_out:.6f},asetpts=PTS-STARTPTS{fades},"
                               f"volume={m.gain_db + plan.music_track_db:.2f}dB,adelay={round(m.t * 1000)}:all=1"))
        k = len(plan.music)
        f.append("".join(f"[m{j}]" for j in range(k)) + f"amix=inputs={k}:normalize=0:duration=longest[music]")
        buses.append("music")

    dur = f"{plan.duration:.6f}"
    if buses:
        mix = "".join(f"[{b}]" for b in buses) + (f"amix=inputs={len(buses)}:normalize=0:duration=longest," if len(buses) > 1 else "")
        f.append(f"{mix}loudnorm=I=-16:TP=-1.5:LRA=11,aresample={MIX_SR},apad,atrim=0:{dur}[aout]")
    else:
        f.append(f"anullsrc=r={MIX_SR}:cl=stereo,atrim=0:{dur}[aout]")

    args = ["-y", "-hide_banner", "-loglevel", "error", "-nostats", "-progress", "pipe:1", *inputs,
            "-filter_complex", ";".join(f)]
    if audio_only:
        codec, _ = AUDIO_FORMATS[plan.fmt]
        args += ["-map", "[aout]", *codec, "-ar", str(MIX_SR)]
    else:
        vcodec, acodec, extra, _ = VIDEO_FORMATS[plan.fmt]
        args += ["-map", "[vout]", "-map", "[aout]", *vcodec, *acodec, *extra]
    args += ["-t", dur, out]
    return args
