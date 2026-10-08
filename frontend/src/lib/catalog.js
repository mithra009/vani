// Languages and voices supported by Gnani Prisma v2.5 (STT) and Timbre v2.5 (TTS).
// Voice list from docs.gnani.ai/api/TTS/available-voices (42 voices, all timbre-v2.5).

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

const V = (name, gender, language) => ({ id: name, name, gender, language });
export const VOICES = [
  V("Ambuja", "Female", "Hindi"), V("Asmita", "Female", "Tamil"), V("Bhavna", "Female", "Hindi"),
  V("Brinda", "Female", "Tamil"), V("Chitra", "Female", "Hindi"), V("Deepak", "Male", "Hindi"),
  V("Devika", "Female", "English"), V("Dhruva", "Male", "Bengali"), V("Falak", "Female", "Gujarati"),
  V("Girish", "Male", "English"), V("Hemraj", "Male", "Hindi"), V("Ishaan", "Male", "Marathi"),
  V("Jalaj", "Male", "Hindi"), V("Jwala", "Female", "Hindi"), V("Kaveri", "Female", "English"),
  V("Kavin", "Male", "Kannada"), V("Kirra", "Female", "Bengali"), V("Lavanya", "Female", "Telugu"),
  V("Lehara", "Female", "Telugu"), V("Mehuli", "Female", "Punjabi"), V("Nalini", "Female", "Hindi"),
  V("Noopur", "Female", "Tamil"), V("Omkar", "Male", "Hindi"), V("Poorvi", "Female", "Hinglish"),
  V("Pranav", "Male", "English"), V("Reshma", "Female", "Malayalam"), V("Riyaan", "Male", "Malayalam"),
  V("Roopesh", "Male", "Hindi"), V("Saanvi", "Female", "Kannada"), V("Shlok", "Male", "English"),
  V("Suhana", "Female", "Telugu"), V("Trisha", "Female", "Tamil"), V("Trupti", "Female", "English"),
  V("Urmila", "Female", "Hindi"), V("Varuni", "Female", "Telugu"), V("Vedika", "Female", "Tamil"),
  V("Veera", "Male", "Gujarati"), V("Vikrant", "Male", "Hindi"), V("Yashvi", "Female", "Hindi"),
  V("Yukti", "Female", "Telugu"), V("Zahira", "Female", "Marathi"), V("Zayan", "Male", "Punjabi"),
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

export const voicesFor = (targetCode) => {
  const t = TARGET_LANGS.find((l) => l.code === targetCode);
  if (!t) return [];
  const own = VOICES.filter((v) => v.language === t.voiceLang);
  // Hinglish has one dedicated voice; Hindi voices also speak it well.
  return t.code === "hi-en" ? [...own, ...VOICES.filter((v) => v.language === "Hindi")] : own;
};
