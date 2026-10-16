# Voice-AI Market Research: Gnani vs Competitors, and Where to Build

Researched 7 October 2026 from public sources (linked at the end). Where a claim comes from a vendor's own marketing, it says so. "Gnani lacks X" means **no public evidence of X**, not proof of absence. Check anything you rely on in the Inya dashboard or on the hackathon Discord.

---

## 1. Findings in one page

1. **The hackathon isn't judged on beating Gnani's product line.** The Great Indian AI Internship Challenge has **10 separate awards** (₹50,000 each). The useful targets for us are *Real Deal* (farmers, kirana stores, rural health), *Noise Canceller* (messy phone audio), *Mixed Vibes* (code-mixed speech), *Main Character* (regional languages) and *Jugaad Genius* (unexpected use of the models). Pick an idea that clearly fits one or two of these.
2. **⚠️ Rule risk in our current build.** The rules say *"Use Gnani AI models/APIs only."* Gnani provides a reasoning model, **Evon v3.3** (30B MoE, about 3.5B parameters active, Apache 2.0, on Hugging Face). Our agent uses **Gemini**, which probably breaks this rule. Gnani's API docs show **no hosted LLM endpoint**, so Evon must be self-hosted. Ask on the Discord whether a non-Gnani LLM is allowed. Assume it isn't until they say so.
3. **Gnani is strong at the bottom of the stack:** Indic speech-to-text trained on 14M+ hours of phone audio, Indic TTS with lakh/crore number reading, voice cloning, a 5B speech-to-speech research model, and on-premise deployment. It also has an enterprise suite (collections, agent assist, voice biometrics, analytics) and the no-code Inya builder with templates, simulation testing and sentiment analytics.
4. **Where competitors are visibly ahead:**
   - **Controllable emotion in TTS:** Sarvam Bulbul v3/v4, ElevenLabs Expressive Mode and Hume EVI all offer it. Timbre v2.5's public API exposes only `speed` (0.85 to 1.15) and no emotion control.
   - **Model-level turn detection:** Deepgram Flux, about 260 ms. Gnani's Smart Pause is still in beta.
   - **Configurable fillers and backchannels:** Vapi, plus a `filler_style` setting on at least one platform. I found no public evidence of this in Inya.
   - **Speech-to-speech in production:** Hume EVI. Gnani's VoiceOS is a research preview and not in the API.
   - **Consumer-side protection:** Truecaller and Google. Gnani only sells to businesses.
5. **The biggest open gap is consumer scam protection in Indian languages.**
   - Truecaller's AI Call Scanner only detects whether *the voice is synthetic*. It doesn't analyse what's being said, and in India it's still beta and premium-only.
   - Google's Gemini Nano scam detection analyses call content, but in India it runs **only on Pixel 9 and later**. Pixels had **under 1% market share** in 2024.
   - Nobody serves the other ~99% of Indian phones with content-level scam detection in regional languages.
6. **Recommendation: build Kavach**, the live scam-call guardian, on Gnani models only. It fits *Real Deal*, *Noise Canceller* and *Mixed Vibes*. It fills a gap neither Gnani nor the big consumer players cover, and it reuses most of the Samvedna pipeline. Section 6 has the details.

---

## 2. The hackathon: the frame that actually decides winning

| Item | Detail |
|---|---|
| Theme | "Build Sovereign AI for India": an Indian problem, an Indian language, real Indian audio |
| Window | 1 Oct to **10 Nov 2026, 11:59 PM IST** (no extensions) |
| Team | Solo or 2 people |
| Models provided | **Prisma v2.5** (STT), **Timbre v2.5** (TTS, beta), **Evon v3.3** (open-weight reasoning model) |
| Credits | 5,000 per registrant |
| Must use | Gnani models/APIs only; name each model and each member's role |
| Data | **Synthetic only**: no real phone, account, Aadhaar or PAN numbers and no real recorded calls. Self-recordings with consent are fine. |
| Submission | Demo or video + write-up + models used + a public LinkedIn/X post with #GreatIndianAIInternshipChallenge #GnaniAI |
| Prize | ₹50,000 × 10 awards; up to 100 six-month internships (up to ₹1 lakh/month); one award per team |

Award categories and how well they suit a strong engineering build:

| Award | Exact brief | Fit |
|---|---|---|
| Real Deal | "Most useful real-world problem solved, for farmers, kirana stores, rural health and similar users" | **High**: needs a real user problem |
| Noise Canceller | "Best performance on messy, noisy telephonic audio" | **High**: phone audio is Prisma's strength, and we can measure it |
| Mixed Vibes | "Best code-mixed voice build: Hinglish, Tanglish, Benglish" | **High** |
| Main Character | "Best build in a regional or low-resource Indian language" | Medium: needs a native speaker for a non-Hindi language |
| Jugaad Genius | "Most creative or unexpected use of the models" | Medium |
| Demo Day Drop | Best 60-second video | Do this regardless |
| Two-Person Army / Solo Ninja / Small Town / Crowd Favourite | Team type, location, public votes | Depends on circumstance |

The brief's own example, voice form-filling for banking, will attract many entries. Avoid it.

---

## 3. Gnani's position today

| Layer | What Gnani has (public evidence) | Notes |
|---|---|---|
| STT | Prisma v2.5 (Vachana STT): 10 languages, code-mixed, streaming under 200 ms, 8/16 kHz, server-side VAD, ITN, word boosting, find-and-replace | Strongest asset: 14M+ hours of phone audio |
| TTS | Timbre v2.5: 10+ languages, context-aware prosody, lakh/crore numbers; `speed` 0.85 to 1.15 | **No emotion or style parameter in the API docs.** Vachana TTS *marketing* claims "warmth, urgency, empathy" |
| Voice cloning | Zero-shot from under 10 s of audio, 12 languages; REST, streaming and realtime endpoints | Strong, but clone consent and anti-spoofing are needed |
| Reasoning | Evon v3.3 open weights | **Not hosted** in the public API docs |
| Speech-to-speech | Inya VoiceOS 5B, research preview (Feb 2026), 15+ languages, preserves tone and emotion | Not in the API |
| Agent platform | Inya: no-code builder, templates (EMI reminder, banking reminder, support, leads, appointments…), Smart Pause (beta), interruptions, noise filter, DTMF, simulation testing, analytics with sentiment trend, call reasons and intents | Comparable to Bolna, Samvaad and Retell for business agents |
| Enterprise suite | Automate365, Assist365 (agent assist), Armour365 (voice biometrics with anti-spoof), Aura365 (analytics), Collect365 (collections) | Focused on contact centres and BFSI |
| Deployment | On-premise / sovereign stack | Real differentiator for regulated buyers |

---

## 4. Competitors in depth

### 4.1 Indian voice-AI companies

**Sarvam AI** (closest national rival on the "sovereign AI" story)
- **Bulbul v3 TTS:** 11 languages, **30+ persona voices**, native mid-sentence code-switching (Hinglish, Tanglish, Benglish), **under 250 ms** first byte over WebSocket, **emotion control**, voice cloning, about ₹30 per 10,000 characters (beta).
- **Bulbul v4 (30 July 2026):** "richer emotion, more natural expression and a wider vocal range".
- **Samvaad agents:** phone, **WhatsApp**, web and app in 11 languages; no-code with templates (leads, KYC/forms, order capture, support, booking); handles alphanumerics and proper nouns; under 1 s responses; analytics.
- Also has large LLMs (a 105B model is reported) and works with LiveKit, Pipecat, Exotel and Ozonetel.
- *Ahead of Gnani on:* developer-visible emotion control and personas in TTS, and WhatsApp voice agents.

**Smallest.ai**
- **Lightning v3.1 TTS:** 44 kHz, about 175 ms latency at 20 concurrent streams (about 200 ms to first byte), 12 languages, **geo-routed servers including Hyderabad**.
- **Atoms** agent SDK and platform.
- *Ahead on:* published latency and fidelity numbers, and latency-first marketing.

**Bolna**
- An orchestration layer over **20+ ASR/LLM/TTS models**, with a claimed latency under 300 ms.
- 10+ languages and 50+ accents, bulk calling campaigns, retries, IVR, language detection (Jan 2026), human hand-off, India/US data residency, on-premise option, and n8n/Make/Zapier integrations.
- Claims growth from 1,500 to 200,000 daily calls and 1,050 customers. Raised $6.3M from General Catalyst.
- *Ahead on:* model choice and developer-friendly self-serve.

**Yellow.ai, Jio Haptik, Uniphore, Skit.ai**
- **Yellow.ai:** agentic platform claiming 135+ languages and dialects.
- **Uniphore:** "emotion AI" plus real-time conversation analytics for contact centres; acquired Autonom8 (Aug 2025); KPMG partnership (Jan 2026).
- **Haptik:** chat and voice for e-commerce, banking and travel.
- **Skit.ai:** phone agents for banking, collections and insurance, competing directly with Collect365.
- *Ahead on:* Uniphore's emotion analytics is a mature product line.

### 4.2 Global platforms

| Company | What they're best at | Specifics |
|---|---|---|
| **ElevenLabs Agents** | Expressive, emotionally adaptive voice | **Expressive Mode** (Feb 2026) on Eleven v3 Conversational keeps emotional context across the *whole conversation*; real-time turn-taking reads pauses and hesitations; automatic language detection; first-turn latency under 500 ms; RAG |
| **Hume AI (EVI)** | Emotion as a first-class signal | Speech-to-speech that **measures vocal expression** (tune, rhythm, timbre) and returns it with transcripts; generates emotional prosody (sighs, laughs); 100K+ custom voices; 500 to 800 ms responses |
| **Deepgram** | Turn detection | **Flux**: end-of-turn detection built into the model (about 260 ms), EagerEndOfTurn events for speculative replies, configurable turn-taking; Voice Agent API |
| **Cartesia** | Raw TTS speed | Sonic Turbo **40 ms** time to first audio; Sonic-3.5 |
| **Vapi** | Developer orchestration and QA | Built-in **endpointing, backchannelling and filler injection**; **Simulations** with AI testers that have personalities, plus chat and voice modes and CI quality gates that block a deploy |
| **Retell AI** | Production QA | **Conductor** (June 2026), a graph-based review interface; simulation tests; targets **1.5 s** end-to-end latency |
| **PolyAI** | Contact-centre voice depth | Forrester-validated 391% three-year ROI; high-volume, high-stakes calls |
| **Sierra** | Outcome-based pricing | Charges only when the agent completes a task; covers every channel |
| **Hamming, Coval, Cekura** | Voice-agent testing as a product | Synthetic callers at scale, regression detection, production monitoring; Cekura tests 30+ languages including Hindi |

### 4.3 Consumer scam protection (relevant to Kavach)

| Player | What it does | Limitation in India |
|---|---|---|
| **Truecaller AI Call Scanner** | Detects whether the *caller's voice is AI-generated*, from voice patterns | Doesn't analyse *what* is said; premium; **India is beta** |
| **Google Scam Detection** | Gemini Nano analyses call content on the device; beeps to alert | **Pixel 9 and later only** (Pixels under 1% share); off by default; unknown numbers only |
| **Google + Navi/Paytm/GPay pilot** | Limits screen-sharing scams during calls | Targets screen sharing, not voice manipulation |
| **Gnani Armour365** | Voice biometrics with anti-spoof, for *enterprises* checking *their callers* | Protects companies, not citizens |

Losses to digital fraud in India are reported at over ₹70 billion.

---

## 5. Gap matrix: where competitors excel and Gnani isn't visibly present

Ratings: ✅ strong public evidence · ◐ partial or claimed · ✗ no public evidence

| Capability | Leaders | Gnani | Buildable by us on Gnani models? |
|---|---|---|---|
| Emotion/style control in TTS via the API | ElevenLabs, Sarvam, Hume | ◐ (claimed for Vachana; **API shows only `speed`**) | Partly: text shaping + `speed` + emotion-specific voice clones |
| Hearing the caller's emotion from their voice | Hume, Uniphore | ◐ (Inya sentiment trend after the call, text-based) | Yes: live acoustic + lexical tagging |
| Configurable fillers and backchannels | Vapi | ✗ | **Already built** (Samvedna) |
| Model-level turn detection | Deepgram Flux, ElevenLabs | ◐ (Smart Pause beta) | Not a good hackathon target |
| Simulation QA for agents | Vapi, Retell, Hamming, Coval, Cekura | ◐ (Inya testing framework) | Possible, but not award-shaped |
| Speech-to-speech in production | Hume, OpenAI | ◐ (research preview) | No |
| WhatsApp voice agents | Sarvam Samvaad | ✗ (not seen) | Out of scope for the time left |
| **Content-based scam detection for citizens in Indian languages** | Google (Pixel-only) | ✗ | **Yes**: Prisma + Evon + Timbre |
| Raw TTS latency leadership | Cartesia, Smallest | ◐ | No |

---

## 6. Where to build

### Option A: Kavach, a live scam-call guardian (recommended)

**Problem:** "digital arrest", fake KYC, courier/customs, fake police/CBI and OTP scams target elderly and less tech-savvy Indians, in Hindi, Hinglish and regional languages, over noisy phone lines.

**What it does:**
- Listens to the *other* party on a call.
- Tracks manipulation tactics live:
  - **authority** ("main CBI se bol raha hoon")
  - **fear** ("aapke naam pe FIR")
  - **urgency** ("abhi ke abhi")
  - **secrecy** ("kisi ko mat batana")
  - **isolation** ("call mat kaatna")
  - **payment or credential requests** (OTP, UPI PIN, "safe account" transfer, screen sharing)
- When risk crosses a threshold, it **speaks a warning to the user in their own language** through Timbre: "Yeh call fraud lag rahi hai. Koi OTP ya paise mat dijiye. Call kaat dijiye."
- Optionally notifies a family member with a summary.

**Why it stands out:**
- It covers what neither Google nor Truecaller does in India: **content-level** detection in **Indian languages**, not limited to Pixels and not limited to AI-voice detection.
- It serves the citizen, a segment Gnani doesn't serve.
- **Awards:**
  - *Real Deal*: elderly and rural users.
  - *Noise Canceller*: we can measure detection on noisy phone audio, which plays to Prisma's strength.
  - *Mixed Vibes*: scam scripts are heavily code-mixed.
  - *Jugaad Genius*: a voice AI that defends you from voice AI.

**What carries over from Samvedna:**
- Prisma streaming STT, Timbre TTS and the LiveKit setup.
- The emotion tagger, reused as a tactic tracker with smoothed risk.
- The number guard, reused as an OTP/UPI/account-number leak detector.
- The console, reused as a live risk meter and tactic timeline.

**Honest limits:**
- A real product needs phone-level call access, through an Android dialler app, a carrier or a conference bridge. For the hackathon, a three-way LiveKit call demonstrates it, and we say so plainly.
- Synthetic data only: scripted scam calls voiced by the team.
- **Evon has to run somewhere.** That means a GPU, or a quantised build on a cloud instance, and needs checking early.

### Option B: Samvedna as a "voice comfort layer"

Fillers plus emotion-adaptive pacing (text shaping + Timbre `speed`) plus distress detection, pitched as what Gnani's TTS API doesn't expose yet. It's technically valid, but it competes with Gnani's own roadmap (Vachana's emotional TTS and VoiceOS), and no single award fits it cleanly.

### Option C: A farmer or kirana voice line (Real Deal, Main Character)

The Real Deal brief names farmers and kirana stores, but AI4Bharat and others already work on farm advisory lines. It would only be distinctive with a sharp hook, such as a kirana store owner keeping their *credit ledger* by voice in Kannada over a phone call.

---

## 7. Immediate actions

1. **Ask on the hackathon Discord:** "Is a non-Gnani LLM (e.g. Gemini) allowed for reasoning, or must it be Evon v3.3? Is there a hosted Evon endpoint?"
2. Decide between Kavach and the alternatives. Then the report, roadmap and code get retargeted.
3. Test Evon hosting early, whichever idea wins: a quantised 30B MoE with about 3.5B active parameters should fit a single 24 GB GPU (to be verified).

---

## Sources
- Hackathon: [Great Indian AI Internship Challenge 2026 (Gnani)](https://www.gnani.ai/resources/blogs/great-indian-ai-internship-challenge-2026)
- Gnani: [Inya VoiceOS 5B (Business Today)](https://www.businesstoday.in/technology/news/story/india-ai-impact-summit-2026-gnaniai-launches-5-billion-parameter-voice-ai-model-under-indiaai-mission-516400-2026-02-17) · [VoiceOS speech models (Business Standard)](https://www.business-standard.com/technology/tech-news/gnani-ai-expands-inya-voiceos-capabilities-with-two-new-speech-models-126021900332_1.html) · [Zero-shot voice cloning TTS (Business Today)](https://www.businesstoday.in/amp/technology/story/gnaniai-launches-zero-shot-voice-cloning-tts-model-for-12-indic-languages-516896-2026-02-19) · [Gnani API docs](https://docs.gnani.ai/api/introduction/introduction.md) · [Inya agent analytics](https://docs.inya.ai/E03_Agent_Analytics) · [Inya testing guide](https://www.gnani.ai/resources/blogs/testing-evaluating-voice-agents-with-inya-ai-a-practical-guide/) · [Collect365 case study](https://www.gnani.ai/resources/case-studies/top-5-housing-finance-collect365-collections) · [Product line (bitscale)](https://bitscale.ai/directory/gnaniai) · [Armour365 (Business Wire)](https://www.businesswire.com/news/home/20210921005797/en/Gnani.ai-Launches-armour365-Voice-Biometrics-Software-Based-on-Patented-Tech)
- Sarvam: [Bulbul v3 explained (InVideo)](https://invideo.io/blog/sarvam-bulbul-indian-tts/) · [Bulbul v4 (explainx)](https://explainx.ai/blog/sarvam-bulbul-v4-tts-emotion-voice-july-2026) · [Samvaad on WhatsApp (AIM)](https://analyticsindiamag.com/ai-news-updates/sarvams-samvaad-voice-chat-ai-agents-hit-whatsapp-in-11-indian-languages) · [Sarvam TTS for voice agents](https://www.sarvam.ai/text-to-speech/voice-agents)
- Smallest.ai: [Models docs](https://docs.smallest.ai/waves/documentation/getting-started/models.md) · [Fastest TTS APIs 2026](https://smallest.ai/blog/top-fastest-text-to-speech-apis-in-2026)
- Bolna: [Seed funding press release](https://www.bolna.ai/newsroom/bolna-bags-63-million-seed-funding-led-by-general-catalyst-to-build-indias-voice-ai-platform) · [everydev listing](https://www.everydev.ai/tools/bolna)
- Others in India: [Agentic AI companies in India (nextagile)](https://nextagile.ai/blog/agentic-ai/agentic-ai-companies-in-india/) · [Uniphore vs Yellow.ai](https://neuronfeed.com/compare/yellow-ai-vs-uniphore)
- Global: [ElevenLabs Agents guide 2026](https://aividpipeline.com/blog/elevenlabs-agents-guide-2026) · [Hume EVI](https://hume.ai/blog/introducing-hume-evi-api) · [Hume (Contrary Research)](https://research.contrary.com/company/hume-ai) · [Deepgram Flux docs](https://developers.deepgram.com/docs/flux/quickstart) · [Best voice AI June 2026](https://futureagi.com/blog/best-voice-ai-june-2026/) · [Vapi Simulations](https://vapi.ai/blog/vapi-simulations) · [Retell Conductor](https://customerthink.com/voice-ai-startup-retell-ai-launches-conductor-featuring-the-first-ever-graph-native-review-interface-for-production-voice-agents/) · [PolyAI vs Sierra](https://thoughtly.com/blog/polyai-vs-sierra-comparison) · [Voice agent latency and fillers (Macha)](https://www.getmacha.com/blog/voice-ai-agent-latency) · [Filler config example (Amigo)](https://docs.amigo.ai/developer-guide/platform-api/platform-api/voice-configuration) · [Voice QA tools (HackerNoon)](https://hackernoon.com/best-voice-agent-evaluation-and-testing-tools-in-2026) · [Cekura multilingual testing](https://www.cekura.ai/blogs/cekura-multilingual-voice-ai-testing)
- Scam protection: [Google scam protection in India (TechCrunch)](https://techcrunch.com/2025/11/20/google-steps-up-ai-scam-protection-in-india-but-gaps-remain) · [Google on-device scam detection (Storyboard18)](https://www.storyboard18.com/digital/google-rolls-out-on-device-scam-detection-in-india-as-digital-fraud-losses-top-%e2%82%b970-billion-84553.htm) · [Truecaller AI Call Scanner (MediaNama)](https://www.medianama.com/2024/05/223-truecaller-ai-voice-scanner-spam-call/) · [Truecaller AI caller ID (MobileIDWorld)](https://mobileidworld.com/truecaller-launches-ai-powered-caller-id-system-with-real-time-scam-detection/)
- India market: [Voice AI and India's AI divide (Business Standard)](https://www.business-standard.com/technology/artificial-intelligence/voice-ai-could-bridge-the-gap-between-india-s-ai-haves-and-have-nots-126061501393_1.html) · [Voice AI India vs global (caller.digital)](https://www.caller.digital/blog/voice-ai-india-vs-global-platforms) · [Gen-AI voice in agricultural advisory (IFPRI)](https://southasia.ifpri.info/2026/04/23/generative-ai-powered-voice-technology-in-agricultural-advisory-services-lessons-from-india/)
