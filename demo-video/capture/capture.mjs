// Records the Vani demo from the live site as a sequence of clips, 1920×1080, each ending on the click
// that leads into the next one.
//
//   node capture.mjs --list                       the scenes, in order, and what each one costs
//   node capture.mjs 01-landing 02-library        record just these
//   node capture.mjs --allow-credits --all        the whole film (04 and 05 make real Gnani/Gemini calls)
//
// Reads from the repo's .env: DEMO_EMAIL, DEMO_PASSWORD (required); DEMO_UPLOAD (a short .mp4 to upload
// in the Library scene); optional DEMO_BASE, DEMO_VIDEO (Library video to build the project on),
// DEMO_NAME (the new project's name).
//
// Signs in once (not recorded); every scene starts signed in. Scenes 04-08 all follow the project that
// 04 creates (its id is kept in clips/state.json), so the film tells one continuous story.
//
// Frames come from Chrome's own DevTools screencast (near-lossless JPEG per painted frame, with its
// timestamp); ffmpeg lays them on a constant 30 fps timeline as H.264 CRF 14: crisp text, smooth motion.
// Long waits (generation, re-voicing, rendering) are taken "off air": the screencast pauses and the clip
// simply continues once the result is there. clips/<scene>.json notes when content was ready ("ready")
// and the click the clip should end on ("cut"), for the edit.
// Browser recordings show no mouse pointer, so a soft spotlight dot glides between targets and pulses on clicks.

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
import dotenv from "dotenv";
import { chromium } from "playwright";

const HERE = path.dirname(fileURLToPath(import.meta.url));
dotenv.config({ path: path.join(HERE, "..", "..", ".env") });
const env = (k, d) => (process.env[k] ?? d ?? "").trim();
const BASE = env("DEMO_BASE", "https://vani2.duckdns.org");
const W = 1920, H = 1080, FPS = 30;
const CLIPS = path.join(HERE, "clips");
const AUTH = path.join(HERE, ".auth.json");
const STATE = path.join(CLIPS, "state.json");
const DUMMY_SCRIPT = "Welcome to Vani. Every voice, in every Indian language, with the feeling kept intact.";

// ----------------------------------------------------------------------------- spotlight cursor

const CURSOR = () => {
  const install = () => {
    if (document.getElementById("__demo_cursor")) return;
    const s = document.createElement("style");
    s.textContent = `
      #__demo_cursor { position: fixed; z-index: 2147483647; left: 0; top: 0; width: 30px; height: 30px; margin: -15px 0 0 -15px;
        pointer-events: none; transform: translate(-200px, -200px); }
      /* The press shrinks this inner dot only: scaling the outer element would scale its position too
         (CSS applies \`scale\` on top of the translate), jumping the dot toward the top-left on every click. */
      #__demo_cursor i { position: absolute; inset: 0; border-radius: 50%; transition: transform .15s ease-out;
        background: radial-gradient(circle, rgba(255,255,255,.95) 0 28%, rgba(255,255,255,.35) 42%, rgba(255,255,255,0) 72%);
        box-shadow: 0 0 0 1.5px rgba(255,255,255,.55), 0 4px 18px rgba(0,0,0,.45); }
      #__demo_cursor.down i { transform: scale(.78); }
      .__demo_ripple { position: fixed; z-index: 2147483646; width: 30px; height: 30px; margin: -15px 0 0 -15px; border-radius: 50%;
        pointer-events: none; border: 2px solid rgba(255,255,255,.85); animation: __demo_r .6s ease-out forwards; }
      @keyframes __demo_r { to { transform: scale(2.6); opacity: 0; } }`;
    document.head.appendChild(s);
    const c = document.createElement("div");
    c.id = "__demo_cursor";
    c.appendChild(document.createElement("i"));
    document.body.appendChild(c);
    const at = { x: -200, y: -200 };
    const place = (x, y) => { at.x = x; at.y = y; c.style.transform = `translate(${x}px, ${y}px)`; };
    window.__demoPlace = place;
    window.__demoGlide = (tx, ty, ms) => new Promise((done) => {
      const x0 = at.x, y0 = at.y, t0 = performance.now();
      const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
      const step = (now) => {
        const k = Math.min(1, (now - t0) / ms);
        place(x0 + (tx - x0) * ease(k), y0 + (ty - y0) * ease(k));
        if (k < 1) requestAnimationFrame(step); else done();
      };
      requestAnimationFrame(step);
    });
    addEventListener("mousedown", (e) => {
      c.classList.add("down");
      const r = document.createElement("div");
      r.className = "__demo_ripple"; r.style.left = `${e.clientX}px`; r.style.top = `${e.clientY}px`;
      document.body.appendChild(r); setTimeout(() => r.remove(), 650);
    }, true);
    addEventListener("mouseup", () => c.classList.remove("down"), true);
  };
  if (document.readyState === "loading") addEventListener("DOMContentLoaded", install); else install();
};

// ----------------------------------------------------------------------------- the director

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);

function director(page, rec) {
  let x = W / 2, y = H / 2;
  const d = {
    page,
    marks: {},
    /** Every click: when (seconds into the finished clip) and where (frame pixels), for the edit's zoom and spotlight. */
    clicks: [],
    /** Log a click, with the box of the control under it (the nearest clickable ancestor) for the edit's callout. */
    async logClick() {
      const t = +rec.now().toFixed(3);
      const box = await page.evaluate(([px, py]) => {
        const hit = document.elementFromPoint(px, py);
        const el = hit?.closest("button, a, label, select, input, textarea, [role], [tabindex], [draggable], [class*='clip'], [id^='__demo_menu'] > *") ?? hit;
        if (!el) return null;
        const r = el.getBoundingClientRect();
        return [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)];
      }, [x, y]);
      d.clicks.push({ t, x: Math.round(x), y: Math.round(y), ...(box && { box }) });
    },
    /** Note a moment (seconds into the finished clip): "ready" once content shows, "cut" on the last click. */
    mark(name) { d.marks[name] = rec.now(); },
    pause: (ms = 700) => sleep(ms),
    /** Wait for something slow without filming it: the clip resumes the moment `fn` resolves. */
    offAir: (fn) => rec.offAir(fn),
    async glide(tx, ty, ms) {
      const dur = ms ?? Math.min(900, 300 + Math.hypot(tx - x, ty - y) * 0.45);
      await page.evaluate(([fx, fy]) => window.__demoPlace?.(fx, fy), [x, y]);     // re-place after a navigation
      await page.evaluate(([tx, ty, dur]) => window.__demoGlide?.(tx, ty, dur), [tx, ty, dur]);
      await page.mouse.move(tx, ty);
      x = tx; y = ty;
    },
    async to(target, { ms, dx = 0.5, dy = 0.5 } = {}) {
      const loc = typeof target === "string" ? page.locator(target).first() : target;
      await loc.waitFor({ state: "visible", timeout: 30000 });
      await loc.scrollIntoViewIfNeeded();
      const b = await loc.boundingBox();
      await d.glide(b.x + b.width * dx, b.y + b.height * dy, ms);
      return loc;
    },
    async click(target, opts = {}) {
      await d.to(target, opts);
      await sleep(160);
      await d.logClick();
      await page.mouse.down(); await sleep(90); await page.mouse.up();
      await sleep(opts.after ?? 600);
    },
    /** The final click of a scene: marks "cut" on it and holds a beat so the edit has a frame to cut on. */
    async cutOn(target, { visualOnly = false } = {}) {
      await d.to(target);
      await sleep(160);
      d.mark("cut");
      await d.logClick();
      if (visualOnly) await d.press(); else { await page.mouse.down(); await sleep(90); await page.mouse.up(); }
      await sleep(900);
    },
    /** The dot's press and ripple where it is, without a real click: nothing is submitted. */
    async press() {
      await page.evaluate(([px, py]) => {
        const c = document.getElementById("__demo_cursor");
        c?.classList.add("down");
        const r = document.createElement("div");
        r.className = "__demo_ripple"; r.style.left = `${px}px`; r.style.top = `${py}px`;
        document.body.appendChild(r); setTimeout(() => r.remove(), 650);
        setTimeout(() => c?.classList.remove("down"), 110);
      }, [x, y]);
    },
    /** Keep only the first video card on screen (the Library holds two copies of the demo video). */
    async oneVideoCard() {
      await page.addStyleTag({ content: ".ne-videos .ne-video:not(:first-child) { display: none !important; }" });
    },
    async type(target, text, { delay = 45 } = {}) {
      await d.click(target, { after: 200 });
      await page.keyboard.type(text, { delay });
    },
    /** Drag by (dx, dy) from the middle of `target`, with the dot following. */
    async drag(target, dx, dy = 0) {
      const loc = await d.to(target);
      const b = await loc.boundingBox();
      const sx = b.x + b.width / 2, sy = b.y + b.height / 2;
      await d.logClick();
      await page.mouse.down();
      const steps = 30;
      for (let i = 1; i <= steps; i++) {
        const k = ease(i / steps);
        await page.mouse.move(sx + dx * k, sy + dy * k);
        await page.evaluate(([px, py]) => window.__demoPlace?.(px, py), [sx + dx * k, sy + dy * k]);
        await sleep(22);
      }
      await page.mouse.up();
      x = sx + dx; y = sy + dy;
      await sleep(700);
    },
    /** Choose a value in a native <select>. Its OS menu never shows on video, so the open list (its real
     *  options, styled like the app) is drawn under it; the dot glides to the option and clicks it. */
    async pick(selector, value) {
      await d.click(selector, { after: 150 });
      await page.keyboard.press("Escape");
      await page.evaluate(([sel, value]) => {
        const el = document.querySelector(sel);
        const r = el.getBoundingClientRect();
        const menu = document.createElement("div");
        menu.id = "__demo_menu";
        Object.assign(menu.style, {
          position: "fixed", left: `${r.left}px`, top: `${r.bottom + 6}px`, minWidth: `${r.width}px`, zIndex: 2147483645,
          background: "#1c1c1e", border: "1px solid rgba(255,255,255,.12)", borderRadius: "12px", padding: "6px",
          boxShadow: "0 18px 50px rgba(0,0,0,.55)", font: getComputedStyle(el).font, color: "#f2efe8",
          maxHeight: "340px", overflow: "hidden", opacity: "0", transform: "translateY(-6px)",
          transition: "opacity .16s ease-out, transform .16s ease-out",
        });
        let target = null;
        for (const o of el.options) {
          const row = document.createElement("div");
          row.textContent = o.text;
          row.dataset.value = o.value;
          Object.assign(row.style, { padding: "8px 12px", borderRadius: "8px", whiteSpace: "nowrap",
            background: o.selected ? "rgba(255,255,255,.08)" : "transparent" });
          menu.appendChild(row);
          if (o.value === value) target = row;
        }
        document.body.appendChild(menu);
        if (target) menu.scrollTop = Math.max(0, target.offsetTop - 140);
        requestAnimationFrame(() => { menu.style.opacity = "1"; menu.style.transform = "none"; });
      }, [selector, value]);
      await sleep(260);
      const box = await page.evaluate((value) => {
        const t = document.querySelector(`#__demo_menu [data-value="${CSS.escape(value)}"]`).getBoundingClientRect();
        return { x: t.left + Math.min(60, t.width / 2), y: t.top + t.height / 2 };
      }, value);
      await d.glide(box.x, box.y, 520);
      await page.evaluate((value) => {
        const row = document.querySelector(`#__demo_menu [data-value="${CSS.escape(value)}"]`);
        if (row) row.style.background = "rgba(158,195,245,.22)";
      }, value);
      await sleep(220);
      await d.logClick();
      await page.mouse.down(); await sleep(90); await page.mouse.up();
      await page.selectOption(selector, value);
      await page.evaluate(() => { const m = document.getElementById("__demo_menu"); if (m) { m.style.opacity = "0"; setTimeout(() => m.remove(), 180); } });
      await sleep(700);
    },
    /** Scroll the page by `px` (negative = up) over `ms`, eased, one step per screen refresh. */
    async scroll(px, ms = 1400) {
      await page.evaluate(([px, ms]) => new Promise((done) => {
        const y0 = scrollY, t0 = performance.now();
        const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
        const step = (now) => {
          const k = Math.min(1, (now - t0) / ms);
          scrollTo(0, y0 + px * ease(k));
          if (k < 1) requestAnimationFrame(step); else done();
        };
        requestAnimationFrame(step);
      }), [px, ms]);
    },
  };
  return d;
}

// ----------------------------------------------------------------------------- shared state

const state = () => (fs.existsSync(STATE) ? JSON.parse(fs.readFileSync(STATE, "utf8")) : {});
const saveState = (patch) => fs.writeFileSync(STATE, JSON.stringify({ ...state(), ...patch }, null, 2));
const tab = (d, name) => d.page.getByRole("tab", { name, exact: true });
const nav = (d, name) => d.page.locator("header.nav").getByRole("link", { name, exact: true });

/** Call the app's API from the page, with the signed-in session (off camera). */
async function api(page, method, url, body, headers = {}) {
  return page.evaluate(async ([base, method, url, body, headers]) => {
    const tok = JSON.parse(localStorage.getItem("vani-auth") || "{}").access_token;
    const r = await fetch(`${base}${url}`, {
      method, headers: { Authorization: `Bearer ${tok}`, ...(body ? { "Content-Type": "application/json" } : {}), ...headers },
      body: body ? JSON.stringify(body) : undefined,
    });
    const text = await r.text();
    if (!r.ok) throw new Error(`${method} ${url} → ${r.status} ${text.slice(0, 200)}`);
    return text ? JSON.parse(text) : null;
  }, [BASE, method, url, body ?? null, headers]);
}
const deleteProject = (page, id) => api(page, "DELETE", `/api/editor/projects/${id}`);

/** The edited project the chunks, timeline and export scenes show (DEMO_PROJECT_ID, or DEMO_PROJECT by name); opens its editor. */
async function demoProject(page) {
  await page.goto(`${BASE}/`, { waitUntil: "networkidle" });
  const id = env("DEMO_PROJECT_ID"), name = env("DEMO_PROJECT", "Vani demo");
  const all = await api(page, "GET", "/api/editor/projects");
  const p = id ? all.find((x) => x.id === id) : all.find((x) => x.name === name);
  if (!p) throw new Error(id ? `no project with id ${id}` : `no project named "${name}" (set DEMO_PROJECT_ID)`);
  await page.goto(`${BASE}/editor/${p.id}`, { waitUntil: "domcontentloaded" });   // filming resumes on the editor
  return p.id;
}
function newProjectUrl() {
  const id = state().newProjectId;
  if (!id) throw new Error("no new project yet: record 04-new-project first");
  return `${BASE}/editor/${id}`;
}

// ----------------------------------------------------------------------------- the scenes, in film order

/** Wait (off camera) until every Library video has finished processing, so its preview can play. */
async function videosReady(d) {
  await d.offAir(async () => {
    await d.page.goto(`${BASE}/`, { waitUntil: "networkidle" });
    for (let i = 0; i < 120; i++) {
      const vids = await api(d.page, "GET", "/api/assets");
      if (vids.length && vids.every((v) => v.proxy_status === "READY")) return;
      await sleep(5000);
    }
    throw new Error("the Library video is still processing after 10 minutes");
  });
}

async function pickVideo(d) {
  const p = d.page;
  await p.locator(".ne-video").first().waitFor({ timeout: 30000 });
  await d.oneVideoCard();
  const v = env("DEMO_VIDEO") ? p.locator(".ne-video", { hasText: env("DEMO_VIDEO") }).first() : p.locator(".ne-video").first();
  await d.click(v, { after: 800 });
}
const kind = (d, t) => d.page.getByRole("radio", { name: new RegExp(`^${t}`) });

const SCENES = {
  "01-landing": {
    about: "Landing page to the very end, back up to the top, then Library (cut on the click)",
    async run(d) {
      await d.page.goto(`${BASE}/`, { waitUntil: "networkidle" });
      d.mark("ready");
      await d.pause(1000);
      await d.glide(W * 0.55, H * 0.45, 700);
      // Two screens down (the story and how it works), then back to the top.
      const total = await d.page.evaluate(() => document.documentElement.scrollHeight - innerHeight);
      let y = 0;
      for (let n = 0; n < 2 && y < total - 5; n++) {
        const by = Math.min(850, total - y);
        await d.scroll(by, 1200); y += by;
        await d.pause(550);
      }
      await d.pause(600);
      await d.scroll(-y, Math.min(2600, 900 + y * 0.35));
      await d.pause(500);
      await d.cutOn(nav(d, "Library"));
    },
  },
  "02-library": {
    about: "Library: empty to start, upload a video (DEMO_UPLOAD), preview it, then New project (cut on the click)",
    async run(d) {
      const p = d.page;
      const file = env("DEMO_UPLOAD");
      if (!file || !fs.existsSync(file)) throw new Error("set DEMO_UPLOAD in .env to a short .mp4 on this PC");
      await p.goto(`${BASE}/library`, { waitUntil: "networkidle" });
      if (await p.locator(".lib-card").count()) {
        throw new Error("the Library isn't empty: remove its videos in the app first (this scene never deletes anything)");
      }
      d.mark("ready");
      await d.pause(1800);                                          // the empty Library, on camera
      const [chooser] = await Promise.all([
        p.waitForEvent("filechooser"),
        d.click(p.getByRole("button", { name: /Upload (videos|a video)/ }).first(), { after: 300 }),
      ]);
      await chooser.setFiles(file);
      await d.glide(W * 0.5, H * 0.3, 700);
      await p.getByText(/Uploading|Finalizing|Preparing/).first().waitFor({ timeout: 15000 }).catch(() => {});
      await d.pause(2500);                                          // the progress bar, on camera
      // Upload, then the server prepares the preview: wait for the card's play button off camera.
      await d.offAir(() => p.locator(".lib-play").first().waitFor({ timeout: 900000 }));
      await d.pause(1500);
      await d.click(p.locator(".lib-play").first(), { after: 400 });
      await p.locator("video").first().waitFor({ timeout: 20000 }).catch(() => {});
      await d.pause(5000);                                          // the preview playing
      await p.keyboard.press("Escape");
      await d.pause(800);
      await d.cutOn(nav(d, "New project"));
    },
  },
  "03-narration": {
    about: "The narration recorder: pick My narration, create, show the recorder (no recording). Free: the project is deleted after",
    async run(d) {
      const p = d.page;
      await videosReady(d);
      await p.goto(`${BASE}/new`, { waitUntil: "networkidle" });
      await pickVideo(d);
      d.mark("ready");
      await d.click(kind(d, "My narration"), { after: 700 });
      await p.fill("#ne-name", env("DEMO_NAME", "Vani demo"));
      await d.click(p.getByRole("button", { name: /Create and record/ }), { after: 500 });
      await p.waitForURL(/\/editor\//, { timeout: 30000 });
      const id = p.url().split("/editor/")[1].split(/[?#]/)[0];
      try {
        await p.getByRole("button", { name: /Start recording/ }).waitFor({ timeout: 30000 });
        // The real <video>, not the "Loading video…" placeholder that shares its class, then its first frame.
        await d.offAir(async () => {
          const v = p.locator("video.narr-video").first();
          await v.waitFor({ timeout: 60000 });
          await v.evaluate((el) => el.readyState >= 2 || new Promise((ok) => el.addEventListener("loadeddata", ok, { once: true })));
        });
        d.mark("recorder");                                         // the blend into 04 starts here
        await d.pause(800);
        await d.to(p.locator(".narr-steps")); await d.pause(1300);
        await d.to(p.locator(".narr-clock")); await d.pause(1000);
        await d.to(p.getByRole("button", { name: /Start recording/ })); await d.pause(1600);   // shown, not pressed
      } finally {
        await deleteProject(p, id);
      }
    },
  },
  "04-new-project": {
    about: "New project: the three options (a script pasted), back to the video's own audio, languages and voice with dropdowns, a name, Create (cut on the click). (Create is shown, not sent: free)",
    async run(d) {
      const p = d.page;
      await videosReady(d);
      await p.goto(`${BASE}/new`, { waitUntil: "networkidle" });
      await p.locator(".ne-video").first().waitFor({ timeout: 30000 });
      await d.oneVideoCard();
      d.mark("ready");
      await d.pause(800);
      await pickVideo(d);
      await d.click(kind(d, "A script"), { after: 500 });
      await d.click("#ne-script", { after: 300 });
      await p.evaluate(() => navigator.clipboard?.writeText?.("").catch(() => {}));
      await p.keyboard.insertText(DUMMY_SCRIPT);                    // pasted, as a user would
      await d.pause(1300);
      await d.click(kind(d, "My narration"), { after: 1400 });
      await d.click(kind(d, "Video's own audio"), { after: 900 });
      await d.pick("#ne-src", "en-IN");
      await d.pick("#ne-tgt", "kn-IN");
      await d.pick("#ne-voice", "Lakshmi");
      await d.click("#ne-name", { after: 150 });
      await p.keyboard.press("Control+A");
      await p.keyboard.type(env("DEMO_NAME", "Vani demo"), { delay: 55 });
      await d.pause(700);
      // Shown, not sent: a real click would start another paid dub, and 05 already films the generation.
      await d.cutOn(p.getByRole("button", { name: /Create and generate/ }), { visualOnly: true });
    },
  },
  "05-generating": {
    about: "The new project generating: the steps ticking through (no extra cost: 04 started it)",
    async run(d) {
      const p = d.page;
      await p.goto(newProjectUrl(), { waitUntil: "domcontentloaded" });
      await p.locator(".stage-list, .editor-chunks").first().waitFor({ timeout: 60000 });
      d.mark("ready");
      await d.glide(W * 0.62, H * 0.55, 900);
      await d.pause(9000);
    },
  },
  "06-chunks": {
    about: "Chunks of the edited project: play a line, edit one (text, emotion, speed), save, hear it, then Timeline (cut). The line is put back afterwards. CREDITS: up to 2 Gnani calls",
    credits: true,
    async run(d) {
      const p = d.page;
      const id = await d.offAir(() => demoProject(p));               // looked up off camera
      const before = (await api(p, "GET", `/api/editor/projects/${id}`)).chunks.sort((a, b) => a.idx - b.idx)[1];
      const allVoiced = () => p.waitForFunction(() => {
        const rows = document.querySelectorAll(".editor-chunks .ck").length;
        return rows > 0 && document.querySelectorAll(".editor-chunks .ap-btn").length === rows;
      }, null, { timeout: 1_200_000 });
      try {
        await allVoiced();
        d.mark("ready");
        await d.pause(1200);
        await d.click(p.locator(".editor-chunks .ap-btn").first(), { after: 5000 });
        const row = p.locator(".editor-chunks .ck").nth(1);
        await d.click(row.getByRole("button", { name: "Edit", exact: true }), { after: 700 });
        await d.click(p.locator(".ck-editing textarea"), { after: 200 });
        await p.keyboard.press("End");
        await p.keyboard.type("!", { delay: 80 });
        await d.pause(500);
        await d.pick(".ck-editing select", "excited");
        await d.click(p.locator('.ck-editing input[type="number"]'), { after: 150 });
        await p.keyboard.press("Control+A");
        await p.keyboard.type("1.1", { delay: 90 });
        await d.pause(600);
        await d.click(p.getByRole("button", { name: /Save and re-voice/ }), { after: 2200 });   // the loader, on camera
        await d.offAir(allVoiced);
        await d.pause(800);
        await d.click(p.locator(".editor-chunks .ck").nth(1).locator(".ap-btn"), { after: 4500 });
        await d.cutOn(tab(d, "Timeline"));
      } finally {
        // Put the line back exactly as it was (its original take is cached, so this is usually free).
        await d.offAir(async () => {
          const now = (await api(p, "GET", `/api/editor/projects/${id}`)).chunks.find((c) => c.id === before.id);
          const changes = {};
          for (const k of ["text", "emotion_tag", "speed"]) if (String(now[k]) !== String(before[k])) changes[k] = k === "speed" ? Number(before[k]) : before[k];
          if (Object.keys(changes).length) {
            await api(p, "PATCH", `/api/editor/projects/${id}/chunks/${before.id}`, changes, { "If-Match": String(now.revision) });
          }
        });
      }
    },
  },
  "07-timeline": {
    about: "Timeline of the edited project: unmute and mute the original voice, a clip's side panel, drag a clip, captions on, play, then Export (cut). Restored afterwards",
    async run(d) {
      const p = d.page;
      const id = await d.offAir(() => demoProject(p));               // looked up off camera
      const orig = (await api(p, "GET", `/api/editor/projects/${id}/timeline`)).doc;
      try {
        await d.click(tab(d, "Timeline"), { after: 300 });
        await p.locator(".pp-clip-voice").first().waitFor({ timeout: 30000 });
        d.mark("ready");
        await d.pause(1000);
        const a1 = p.locator('.pp-th-btn[title$="the original audio"]');
        await d.click(a1, { after: 1100 });                         // unmute the video's own voice…
        await d.click(a1, { after: 900 });                          // …and mute it again
        await d.click(p.locator(".pp-clip-voice").nth(1), { after: 1800 });
        await d.to(".pp-textarea"); await d.pause(1100);
        await d.drag(p.locator(".pp-clip-voice").nth(2), 70);
        const cc = p.locator('.pp-th-btn[title^="Turn captions"]');
        if ((await cc.getAttribute("aria-pressed")) !== "true") await d.click(cc, { after: 900 });
        await d.click(p.locator(".pp-play"), { after: 6500 });      // captions over the playing video
        await d.click(p.locator(".pp-play"), { after: 600 });
        await d.cutOn(tab(d, "Export"));
      } finally {
        // Back to the timeline as it was: the three things this scene touches.
        await d.offAir(async () => {
          await sleep(2500);                                        // let the editor's autosave land first
          const cur = await api(p, "GET", `/api/editor/projects/${id}/timeline`);
          const ops = [];
          if (cur.doc.original_audio.muted !== orig.original_audio.muted)
            ops.push({ type: "track.set", track: "original_audio", fields: { muted: orig.original_audio.muted } });
          if (cur.doc.captions.enabled !== orig.captions.enabled)
            ops.push({ type: "track.set", track: "captions", fields: { enabled: orig.captions.enabled } });
          const keys = ["offset", "trim_in", "trim_out", "gain_db", "muted", "detached_t"];
          const dflt = { offset: 0, trim_in: 0, trim_out: 0, gain_db: 0, muted: false, detached_t: null };
          for (const cid of Object.keys(cur.doc.voice.clips)) {
            const was = { ...dflt, ...(orig.voice.clips[cid] || {}) }, is = { ...dflt, ...cur.doc.voice.clips[cid] };
            const fields = Object.fromEntries(keys.filter((k) => JSON.stringify(was[k]) !== JSON.stringify(is[k])).map((k) => [k, was[k]]));
            if (Object.keys(fields).length) ops.push({ type: "voice.set", chunk_id: cid, fields });
          }
          if (ops.length) await api(p, "POST", `/api/editor/projects/${id}/timeline/ops`, { base_version: cur.version, ops });
        });
      }
    },
  },
  "08-export": {
    about: "Export of the edited project: MP4, 720p, burned-in captions, Export (cut on the click)",
    async run(d) {
      const p = d.page;
      const id = await d.offAir(() => demoProject(p));               // looked up off camera
      await d.click(tab(d, "Export"), { after: 300 });
      await p.getByRole("radio", { name: "MP4", exact: true }).waitFor({ timeout: 30000 });
      d.mark("ready");
      await d.pause(900);
      for (const label of ["MP4", "720p", "Burned in"]) await d.click(p.getByRole("radio", { name: label, exact: true }), { after: 600 });
      // Shown, not sent: the project's finished export is what 09 opens, so the list holds just that one.
      await d.cutOn(p.locator(".xp-card-foot").getByRole("button", { name: "Export", exact: true }), { visualOnly: true });
    },
  },
  "09-done": {
    about: "The finished export: ▶ Preview, the download options, then Projects → Done shows the project",
    async run(d) {
      const p = d.page;
      const id = await d.offAir(() => demoProject(p));               // looked up off camera
      await d.click(tab(d, "Export"), { after: 300 });
      const newest = p.locator(".xp-item").first();
      await d.offAir(() => newest.getByRole("button", { name: /Preview/ }).waitFor({ timeout: 1_200_000 }));   // rendering, off camera
      d.mark("ready");
      await d.pause(900);
      await d.click(newest.getByRole("button", { name: /Preview/ }), { after: 6000 });
      for (const name of ["Captions", "Download"]) {
        const b = newest.getByRole("button", { name, exact: true });
        if (await b.count()) { await d.to(b); await d.pause(900); }
      }
      await d.click(nav(d, "Projects"), { after: 1400 });
      await d.click(p.getByRole("button", { name: /^Done/ }), { after: 1100 });
      await d.to(p.locator(".pj-row").first()); await d.pause(1800);
    },
  },
};

// ----------------------------------------------------------------------------- recorder

/** Painted frames (variable rate, real timestamps) → constant-rate H.264, each frame held until the next. */
function encode(shots, listFile, out) {
  if (!shots.length) throw new Error("no frames were captured");
  const lines = ["ffconcat version 1.0"];
  shots.forEach((s, i) => {
    const next = shots[i + 1]?.ts ?? s.ts + 0.5;
    lines.push(`file '${path.basename(s.file)}'`, `duration ${Math.max(0.001, next - s.ts).toFixed(4)}`);
  });
  lines.push(`file '${path.basename(shots.at(-1).file)}'`);
  fs.writeFileSync(listFile, lines.join("\n"));
  const r = spawnSync("ffmpeg", ["-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", listFile,
    "-vf", `fps=${FPS},scale=${W}:${H}:flags=lanczos,format=yuv420p`, "-c:v", "libx264", "-preset", "slow",
    "-crf", "14", "-movflags", "+faststart", out], { encoding: "utf8" });
  if (r.status !== 0) throw new Error(`ffmpeg failed: ${r.stderr.slice(-300)}`);
}

async function recordScene(browser, name) {
  const frames = path.join(CLIPS, `.${name}`);
  fs.rmSync(frames, { recursive: true, force: true });
  fs.mkdirSync(frames);
  const ctx = await browser.newContext({ viewport: { width: W, height: H }, deviceScaleFactor: 1, storageState: AUTH });
  await ctx.grantPermissions(["microphone"], { origin: BASE });
  await ctx.addInitScript(CURSOR);
  const page = await ctx.newPage();
  const cdp = await ctx.newCDPSession(page);
  const shots = [];
  let skew = 0;                       // seconds spent off air, taken out of every later timestamp
  let first = null;
  cdp.on("Page.screencastFrame", ({ data, metadata, sessionId }) => {
    const file = path.join(frames, `${String(shots.length).padStart(6, "0")}.jpg`);
    fs.writeFileSync(file, Buffer.from(data, "base64"));
    const ts = metadata.timestamp - skew;
    if (first === null) first = ts;
    shots.push({ file, ts });
    cdp.send("Page.screencastFrameAck", { sessionId }).catch(() => {});
  });
  const start = () => cdp.send("Page.startScreencast", { format: "jpeg", quality: 95, maxWidth: W, maxHeight: H, everyNthFrame: 1 });
  const wall0 = Date.now();
  const rec = {
    now: () => (Date.now() - wall0) / 1000 - skew,
    async offAir(fn) {
      await cdp.send("Page.stopScreencast").catch(() => {});
      const t = Date.now();
      try { return await fn(); } finally {
        skew += (Date.now() - t) / 1000;
        await start();
      }
    },
  };
  await start();
  const d = director(page, rec);
  try {
    await SCENES[name].run(d);
    await d.pause(400);
  } finally {
    await cdp.send("Page.stopScreencast").catch(() => {});
    await ctx.close();
  }
  const out = path.join(CLIPS, `${name}.mp4`);
  encode(shots, path.join(frames, "list.txt"), out);
  fs.writeFileSync(path.join(CLIPS, `${name}.json`), JSON.stringify({ scene: name, ...d.marks, frames: shots.length, clicks: d.clicks }, null, 2));
  fs.rmSync(frames, { recursive: true, force: true });
  return out;
}

async function signIn(browser) {
  const email = env("DEMO_EMAIL"), password = env("DEMO_PASSWORD");
  if (!email || !password) throw new Error("Set DEMO_EMAIL and DEMO_PASSWORD in the repo's .env.");
  const ctx = await browser.newContext({ viewport: { width: W, height: H } });
  const page = await ctx.newPage();
  await page.goto(`${BASE}/signin`, { waitUntil: "networkidle" });
  await page.fill("#identifier", email);
  await page.fill("#password", password);
  await page.locator("form button[type=submit], form button:has-text('Sign in')").last().click();
  await page.waitForURL((u) => !u.pathname.startsWith("/signin"), { timeout: 30000 });
  await page.waitForLoadState("networkidle");
  await sleep(1000);
  await ctx.storageState({ path: AUTH });
  await ctx.close();
}

// ----------------------------------------------------------------------------- main

const args = process.argv.slice(2);
if (args.includes("--list")) {
  for (const [k, s] of Object.entries(SCENES)) console.log(`${k.padEnd(15)} ${s.credits ? "[credits] " : ""}${s.about}`);
  process.exit(0);
}
// Account housekeeping between takes, through the app's own API (the same as deleting in the app):
//   --keep-only <projectId>   remove every project except this one
//   --remove-projects         remove every project
//   --remove-videos           remove every Library video
const housekeeping = ["--keep-only", "--remove-projects", "--remove-videos"].find((f) => args.includes(f));
if (housekeeping) {
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  try {
    await signIn(browser);
    const ctx = await browser.newContext({ storageState: AUTH });
    const page = await ctx.newPage();
    await page.goto(`${BASE}/`, { waitUntil: "networkidle" });
    if (housekeeping === "--remove-videos") {
      const vids = await api(page, "GET", "/api/assets");
      for (const v of vids) await api(page, "DELETE", `/api/assets/${v.id}`);
      console.log(`removed ${vids.length} video(s): ${vids.map((v) => v.original_filename).join(", ")}`);
    } else {
      const keep = housekeeping === "--keep-only" ? args[args.indexOf("--keep-only") + 1] : null;
      const all = await api(page, "GET", "/api/editor/projects");
      if (keep && !all.some((p) => p.id === keep)) throw new Error(`no project ${keep}; nothing removed`);
      const gone = all.filter((p) => p.id !== keep);
      for (const p of gone) await deleteProject(page, p.id);
      console.log(`removed ${gone.length} project(s): ${gone.map((p) => `${p.name} [${p.status}]`).join(", ")}${keep ? ` | kept ${keep}` : ""}`);
    }
    await ctx.close();
  } finally {
    await browser.close();
    fs.rmSync(AUTH, { force: true });
  }
  process.exit(0);
}
if (args.includes("--cleanup")) {
  // Remove any "Narration take" projects an interrupted 03-narration run left behind.
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  try {
    await signIn(browser);
    const ctx = await browser.newContext({ storageState: AUTH });
    const page = await ctx.newPage();
    await page.goto(`${BASE}/`, { waitUntil: "networkidle" });
    const ids = await page.evaluate(async (base) => {
      const tok = JSON.parse(localStorage.getItem("vani-auth") || "{}").access_token;
      const r = await fetch(`${base}/api/editor/projects`, { headers: { Authorization: `Bearer ${tok}` } });
      return (await r.json()).filter((p) => p.name === "Narration take").map((p) => p.id);
    }, BASE);
    for (const id of ids) await deleteProject(page, id);
    console.log(`removed ${ids.length} leftover narration project(s)`);
    await ctx.close();
  } finally {
    await browser.close();
    fs.rmSync(AUTH, { force: true });
  }
  process.exit(0);
}
const allowCredits = args.includes("--allow-credits");
const asked = args.includes("--all") ? Object.keys(SCENES) : args.filter((a) => !a.startsWith("--"));
if (!asked.length) { console.error("Name the scenes to record, or --all. See --list."); process.exit(2); }
for (const n of asked) {
  if (!SCENES[n]) { console.error(`Unknown scene "${n}". See --list.`); process.exit(2); }
  if (SCENES[n].credits && !allowCredits) { console.error(`"${n}" makes real Gnani/Gemini calls; add --allow-credits.`); process.exit(2); }
}

fs.mkdirSync(CLIPS, { recursive: true });
const browser = await chromium.launch({
  channel: "chrome", headless: true,
  args: ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"],   // narration: a simulated mic
});
let failed = 0;
try {
  await signIn(browser);
  for (const name of asked) {
    process.stdout.write(`${name.padEnd(15)} `);
    try {
      const out = await recordScene(browser, name);
      console.log(`ok → ${path.relative(HERE, out)}`);
    } catch (e) {
      failed++;
      console.log(`FAILED: ${e.message.split("\n")[0]}`);
    }
  }
} finally {
  await browser.close();
  fs.rmSync(AUTH, { force: true });                                  // the session token never stays on disk
}
process.exit(failed ? 1 : 0);
