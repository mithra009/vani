// Languages and voices supported by Gnani Prisma v2.5 (STT) and Timbre v3.0 (TTS).
// Voice list from docs.gnani.ai/api/TTS/available-voices (13 timbre-v3.0 voices, each speaks every language).

export const SOURCE_LANGS = [
  { code: "auto", name: "Detect automatically" },
  { code: "hi-IN", name: "Hindi" },
  { code: "en-IN", name: "English (India)" },
  { code: "bn-IN", name: "Bengali" },
  { code: "gu-IN", name: "Gujarati" },
  { code: "kn-IN", name: "Kannada" },
  { code: "ml-IN", name: "Malayalam" },
  { code: "mr-IN", name: "Marathi" },
  { code: "pa-IN", name: "Punjabi" },
  { code: "ta-IN", name: "Tamil" },
  { code: "te-IN", name: "Telugu" },
];

export const TARGET_LANGS = [
  { code: "hi-IN", name: "Hindi", native: "हिन्दी", voiceLang: "Hindi" },
  { code: "ta-IN", name: "Tamil", native: "தமிழ்", voiceLang: "Tamil" },
  { code: "te-IN", name: "Telugu", native: "తెలుగు", voiceLang: "Telugu" },
  { code: "kn-IN", name: "Kannada", native: "ಕನ್ನಡ", voiceLang: "Kannada" },
  { code: "ml-IN", name: "Malayalam", native: "മലയാളം", voiceLang: "Malayalam" },
  { code: "mr-IN", name: "Marathi", native: "मराठी", voiceLang: "Marathi" },
  { code: "bn-IN", name: "Bengali", native: "বাংলা", voiceLang: "Bengali" },
  { code: "gu-IN", name: "Gujarati", native: "ગુજરાતી", voiceLang: "Gujarati" },
  { code: "pa-IN", name: "Punjabi", native: "ਪੰਜਾਬੀ", voiceLang: "Punjabi" },
  { code: "en-IN", name: "English", native: "English", voiceLang: "English" },
  { code: "hi-en", name: "Hinglish", native: "Hinglish", voiceLang: "Hinglish" },
];

const V = (name, gender, description) => ({ id: name, name, gender, description, language: "All" });
export const VOICES = [
  V("Lakshmi", "Female", "Expressive, warm voice for storytelling"),
  V("Vasudha", "Female", "Expressive, composed voice for narration"),
  V("Yashraj", "Male", "Warm narrative voice"),
  V("Avinash", "Male", "Professional, firm, deliberate pacing"),
  V("Chetana", "Female", "Gentle, empathetic"),
  V("Devansh", "Male", "Energetic, young, conversational"),
  V("Kalpana", "Female", "Empathetic, composed"),
  V("Prakash", "Male", "Steady, deliberate"),
  V("Riyaa", "Female", "Confident, lively"),
  V("Shivani", "Female", "Warm, patient"),
  V("Shubham", "Male", "Energetic, confident"),
  V("Tarika", "Female", "Warm, reassuring"),
  V("Harshad", "Male", "Professional, firm"),
];

export const EMOTIONS = {
  neutral:  { label: "Neutral" },
  happy:    { label: "Happy" },
  excited:  { label: "Excited" },
  angry:    { label: "Angry" },
  sad:      { label: "Sad" },
  fearful:  { label: "Nervous" },
  whisper:  { label: "Whisper" },
  tender:   { label: "Tender" },
};

export const langName = (code) =>
  code === "same" ? "Same language" : [...SOURCE_LANGS, ...TARGET_LANGS].find((l) => l.code === code)?.name || code;

// Every Timbre v3.0 voice speaks every target language.
export const voicesFor = (targetCode) => (TARGET_LANGS.some((l) => l.code === targetCode) ? VOICES : []);
