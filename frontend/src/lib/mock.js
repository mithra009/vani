// In-browser stand-in for the backend (PLAN.md §6), used until FastAPI is running.
// Everything here is simulated: transcripts are sample lines and the "dubbed" video is the
// uploaded file itself. The UI says so wherever demo data is shown.

const SCRIPT = [
  { text: "Namaste doston, aaj main aapko ek bahut interesting cheez dikhane wala hoon.", emotion: "happy", intensity: 2 },
  { text: "Pichle hafte maine socha, kyun na apni videos ko har bhasha mein bana doon?", emotion: "neutral", intensity: 1 },
  { text: "Aur sach bataun, result dekh ke main khud shocked ho gaya!", emotion: "excited", intensity: 3, nonverbal: ["laugh"] },
  { text: "Lekin ek problem thi. Awaaz aur video ka timing match hi nahi ho raha tha.", emotion: "sad", intensity: 2 },
  { text: "Teen din tak main bas yahi theek karta raha.", emotion: "angry", intensity: 2, nonverbal: ["sigh"] },
  { text: "Phir ek idea aaya, har line ko uske apne time pe rakho.", emotion: "neutral", intensity: 1 },
  { text: "Ek secret bataun? Yeh poora video maine sirf ek baar record kiya tha.", emotion: "whisper", intensity: 2 },
  { text: "Toh chaliye, dekhte hain yeh kaam kaise karta hai.", emotion: "happy", intensity: 1 },
  { text: "Pehle aap video upload kijiye, phir apni bhasha chuniye.", emotion: "neutral", intensity: 1 },
  { text: "Bas itna hi. Video pasand aaye toh share zaroor kijiye!", emotion: "excited", intensity: 2 },
];

const TRANSLATIONS = {
  "hi-IN": [
    "नमस्ते दोस्तों, आज मैं आपको एक बहुत दिलचस्प चीज़ दिखाने वाला हूँ।",
    "पिछले हफ्ते मैंने सोचा, क्यों न अपने वीडियो हर भाषा में बना दूँ?",
    "<laugh> और सच बताऊँ, नतीजा देखकर मैं खुद हैरान रह गया!",
    "लेकिन एक दिक्कत थी… आवाज़ और वीडियो का समय मेल ही नहीं खा रहा था।",
    "<sigh> तीन दिन तक मैं बस यही ठीक करता रहा।",
    "फिर एक विचार आया, हर पंक्ति को उसके अपने समय पर रखो।",
    "<whispers> एक राज़ बताऊँ? यह पूरा वीडियो मैंने सिर्फ एक बार रिकॉर्ड किया था।",
    "तो चलिए, देखते हैं यह काम कैसे करता है।",
    "पहले आप वीडियो अपलोड कीजिए, फिर अपनी भाषा चुनिए।",
    "बस इतना ही। वीडियो पसंद आए तो शेयर ज़रूर कीजिए!",
  ],
  "ta-IN": [
    "வணக்கம் நண்பர்களே, இன்று உங்களுக்கு ஒரு சுவாரஸ்யமான விஷயத்தைக் காட்டப் போகிறேன்.",
    "கடந்த வாரம் நினைத்தேன், என் வீடியோக்களை எல்லா மொழிகளிலும் ஏன் உருவாக்கக் கூடாது?",
    "<laugh> உண்மையைச் சொன்னால், முடிவைப் பார்த்து நானே ஆச்சரியப்பட்டேன்!",
    "ஆனால் ஒரு பிரச்சனை இருந்தது… குரலும் வீடியோவும் நேரத்தில் பொருந்தவில்லை.",
    "<sigh> மூன்று நாட்கள் இதையே சரிசெய்து கொண்டிருந்தேன்.",
    "பிறகு ஒரு யோசனை வந்தது, ஒவ்வொரு வரியையும் அதன் சொந்த நேரத்தில் வைக்கவும்.",
    "<whispers> ஒரு ரகசியம் சொல்லட்டுமா? இந்த முழு வீடியோவையும் ஒரே முறைதான் பதிவு செய்தேன்.",
    "சரி, இது எப்படி வேலை செய்கிறது என்று பார்ப்போம்.",
    "முதலில் வீடியோவைப் பதிவேற்றுங்கள், பிறகு உங்கள் மொழியைத் தேர்ந்தெடுங்கள்.",
    "அவ்வளவுதான். வீடியோ பிடித்திருந்தால் பகிருங்கள்!",
  ],
};

const jobs = new Map();
const listeners = new Map();
let seq = 1;

const now = () => Date.now();
const emit = (id) => (listeners.get(id) || []).forEach((cb) => cb(structuredClone(strip(jobs.get(id)))));
const strip = (j) => { const { _timers, ...rest } = j; return rest; };

function videoDuration(url) {
  return new Promise((resolve) => {
    const v = document.createElement("video");
    v.preload = "metadata";
    v.onloadedmetadata = () => resolve(v.duration || 60);
    v.onerror = () => resolve(60);
    v.src = url;
  });
}

function makeSegments(duration, from = 0.6) {
  const out = [];
  let t = from;
  let i = 0;
  while (t < duration - 1.5) {
    const line = SCRIPT[i % SCRIPT.length];
    const len = Math.min(2.4 + (line.text.length / 70) * 3.2, duration - t - 0.3);
    if (len < 1.2) break;
    out.push({
      idx: out.length,
      start_s: +t.toFixed(2),
      end_s: +(t + len).toFixed(2),
      src_text: line.text,
      tgt_text: "",
      emotion: line.emotion,
      intensity: line.intensity,
      nonverbal: line.nonverbal || [],
      emotion_overridden: false,
      keep_original: false,
      speed: null,
      stretch: null,
      flags: [],
      _line: i % SCRIPT.length,
    });
    t += len + 0.35 + (i % 3) * 0.25;
    i++;
  }
  return out;
}

function runStages(job, stages, onDone) {
  const step = (k) => {
    if (k >= stages.length) return onDone();
    const [stage, ms] = stages[k];
    job.stage = stage;
    job.stage_index = k;
    job.stage_progress = 0;
    emit(job.id);
    const ticks = 10;
    let n = 0;
    const timer = setInterval(() => {
      n++;
      job.stage_progress = n / ticks;
      emit(job.id);
      if (n >= ticks) { clearInterval(timer); step(k + 1); }
    }, ms / ticks);
    job._timers.push(timer);
  };
  step(0);
}

function transcribe(job, from, to) {
  runStages(job, [["ingest", 700], ["transcribe", 2200], ["emotion", 1200]], () => {
    job.segments = makeSegments(to, from);
    if (job.src_lang === "auto") job.src_lang = "hi-IN";
    if (job.tgt_lang === "same") job.tgt_lang = job.src_lang;
    job.status = "review";
    job.stage = null;
    emit(job.id);
  });
}

export const mock = {
  async health() { return { mode: "demo" }; },

  async listJobs() {
    return [...jobs.values()].map(strip).sort((a, b) => b.created_at - a.created_at);
  },

  async createJob(file, srcLang, tgtLang, _onUpload, mode = "dub") {
    const id = `demo-${seq++}`;
    const video_url = URL.createObjectURL(file);
    const duration_s = await videoDuration(video_url);
    const job = {
      id, name: file.name, size: file.size, created_at: now(), mode,
      status: mode === "narrate" ? "awaiting_narration" : "transcribing",
      stage: mode === "narrate" ? null : "ingest", stage_index: 0, stage_progress: 0,
      src_lang: srcLang, tgt_lang: tgtLang, duration_s, video_url, output_url: null, narration: null,
      segments: [], voice: null, bg_mode: "duck", stats: null, error: null, demo: true, _timers: [],
    };
    jobs.set(id, job);
    if (mode === "dub") transcribe(job, 0.6, duration_s);
    return strip(job);
  },

  async uploadNarration(id, take) {
    const j = jobs.get(id);
    const end = Math.min(j.duration_s, take.offset_s + take.duration_s);
    j.narration = { url: take.url, offset_s: take.offset_s, duration_s: end - take.offset_s };
    j.status = "transcribing";
    emit(id);
    transcribe(j, take.offset_s + 0.3, end);
    return strip(j);
  },

  async getJob(id) {
    const j = jobs.get(id);
    if (!j) throw new Error("This project doesn't exist any more. Demo projects are cleared when the page reloads.");
    return structuredClone(strip(j));
  },

  async updateSegments(id, segments) {
    const j = jobs.get(id);
    j.segments = segments.map((s) => ({ ...s }));
    return structuredClone(strip(j));
  },

  async startDub(id, { voice, bg_mode }) {
    if (voice?.sample instanceof Blob) voice = { ...voice, sample: undefined };
    const j = jobs.get(id);
    j.voice = voice;
    j.bg_mode = bg_mode;
    j.status = "dubbing";
    emit(id);
    const own = voice?.mode === "own";
    const same = j.tgt_lang === j.src_lang;
    const stages = own
      ? [["clean", 1200], ["assemble", 900], ["mux", 800]]
      : [...(same ? [] : [["translate", 1800]]), ["synthesize", 3000], ["fit", 1200], ["assemble", 900], ["mux", 800]];
    runStages(j, stages, () => {
      const tr = TRANSLATIONS[j.tgt_lang];
      j.segments = j.segments.map((s, k) => {
        const flagged = !own && k === 3;
        return {
          ...s,
          tgt_text: s.keep_original || own || same ? s.src_text : tr ? tr[s._line] : `[${j.tgt_lang} translation of line ${k + 1}]`,
          speed: own ? 1 : +(0.95 + ((k * 7) % 20) / 100).toFixed(2),
          stretch: own ? 1 : flagged ? 1.22 : +(1 + ((k * 3) % 9) / 100).toFixed(2),
          flags: flagged ? ["stretched_over_limit"] : [],
        };
      });
      const stretches = j.segments.map((s) => s.stretch).sort((a, b) => a - b);
      j.stats = {
        segments: j.segments.length,
        flagged: j.segments.filter((s) => s.flags.length).length,
        stretch_p95: stretches[Math.floor(stretches.length * 0.95)] || 1,
        duration_error_samples: 0,
      };
      j.output_url = j.video_url;
      j.status = "done";
      j.stage = null;
      emit(id);
    });
    return strip(j);
  },

  async regenerate(id, idx) {
    const j = jobs.get(id);
    const s = j.segments[idx];
    await new Promise((r) => setTimeout(r, 1400));
    s.stretch = 1.06;
    s.flags = [];
    j.stats.flagged = j.segments.filter((x) => x.flags.length).length;
    emit(id);
    return structuredClone(strip(j));
  },

  subscribe(id, cb) {
    const arr = listeners.get(id) || [];
    arr.push(cb);
    listeners.set(id, arr);
    return () => listeners.set(id, (listeners.get(id) || []).filter((f) => f !== cb));
  },

  downloads(job) {
    return {
      video: job.output_url,
      srtSource: srtUrl(job.segments, "src_text"),
      srtTarget: srtUrl(job.segments, "tgt_text"),
    };
  },
};

function srtUrl(segments, key) {
  const t = (s) => {
    const ms = Math.round(s * 1000);
    const h = String(Math.floor(ms / 3600000)).padStart(2, "0");
    const m = String(Math.floor((ms % 3600000) / 60000)).padStart(2, "0");
    const sec = String(Math.floor((ms % 60000) / 1000)).padStart(2, "0");
    return `${h}:${m}:${sec},${String(ms % 1000).padStart(3, "0")}`;
  };
  const body = segments
    .map((s, i) => `${i + 1}\n${t(s.start_s)} --> ${t(s.end_s)}\n${(s[key] || "").replace(/<[^>]+>\s*/g, "")}\n`)
    .join("\n");
  return URL.createObjectURL(new Blob([body], { type: "text/plain" }));
}
