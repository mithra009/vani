// Placeholder library until the Library backend exists. Covers are CSS gradients standing in
// for video thumbnails. Replace with GET /api/library when it's built.
export const LIBRARY = [
  { id: "lib-1", name: "Product launch keynote.mp4", duration_s: 412, size: 186_400_000, uploaded_at: Date.now() - 2 * 3600e3, lang: "en-IN",
    cover: "linear-gradient(135deg, #1e3a8a 0%, #0f172a 100%)" },
  { id: "lib-2", name: "Cooking with Amma, episode 4.mov", duration_s: 538, size: 241_900_000, uploaded_at: Date.now() - 26 * 3600e3, lang: "ta-IN",
    cover: "linear-gradient(135deg, #7c2d12 0%, #1c1917 100%)" },
  { id: "lib-3", name: "Physics class 11, motion.mp4", duration_s: 297, size: 98_300_000, uploaded_at: Date.now() - 3 * 86400e3, lang: "hi-IN",
    cover: "linear-gradient(135deg, #14532d 0%, #052e16 100%)" },
  { id: "lib-4", name: "Startup pitch, Hinglish.mp4", duration_s: 184, size: 64_200_000, uploaded_at: Date.now() - 5 * 86400e3, lang: "hi-IN",
    cover: "linear-gradient(135deg, #581c87 0%, #1e1b4b 100%)" },
  { id: "lib-5", name: "Farm advisory, monsoon tips.webm", duration_s: 351, size: 120_700_000, uploaded_at: Date.now() - 9 * 86400e3, lang: "kn-IN",
    cover: "linear-gradient(135deg, #854d0e 0%, #292524 100%)" },
  { id: "lib-6", name: "Travel vlog, Varanasi ghats.mp4", duration_s: 466, size: 210_500_000, uploaded_at: Date.now() - 14 * 86400e3, lang: "hi-IN",
    cover: "linear-gradient(135deg, #155e75 0%, #0c0a09 100%)" },
];
