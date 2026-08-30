/* Spoken narration for the Guardian — so a rider who can't look at the screen still gets the
 * alert, out loud, hands-free (like Maps voice guidance).
 *
 * Two tiers, graceful like the rest of the app:
 *   1. Google Cloud Text-to-Speech (Chirp/Neural2) — a natural neural voice when online.
 *   2. Browser SpeechSynthesis — on-device, instant, free, works OFFLINE. The fallback.
 *
 * Priorities, one speaker:
 *   ALERT (2) — safety alerts + greetings. Always plays, preempts anything else.
 *   NAV   (1) — turn-by-turn. Instant browser voice so it never waits on a throttled
 *               Cloud TTS round-trip. Yields only to an in-flight ALERT.
 *
 * `_busy` is reserved the instant an utterance launches. A 2.5s TTS timeout + 12s
 * watchdog guarantee it cannot stick if the Cloud request hangs or `ended` never fires
 * (the previous "nothing plays during simulation" failure mode).
 */

import { api } from "../api";

let _voice = null;
let _useCloud = true;
let _audio = null;      // currently-playing Cloud TTS <audio>
let _busy = false;      // channel occupied (launching or playing)
let _pri = 0;           // 0 free, 1 nav, 2 alert
let _req = 0;           // monotonic token — only the latest launch may start audio
let _lastText = "";     // dedup: skip the same line repeated within a moment
let _lastAt = 0;
let _watchdog = null;
let _navQ = [];         // turn-by-turn lines waiting for the channel
let _rate = 1.05;       // SpeechSynthesis rate (raised during a compressed sim)

const PRI_NAV = 1;
const PRI_ALERT = 2;
const TTS_MS = 2500;
const BUSY_MAX_MS = 12000;
const NAV_Q_MAX = 8;

export function speechSupported() {
  return typeof window !== "undefined" && "speechSynthesis" in window;
}

function pickVoice() {
  if (!speechSupported()) return null;
  const voices = window.speechSynthesis.getVoices() || [];
  if (!voices.length) return null;
  const score = (v) => {
    let s = 0;
    if (/^en[-_]IN/i.test(v.lang)) s += 4;
    else if (/^en[-_]GB/i.test(v.lang)) s += 3;
    else if (/^en/i.test(v.lang)) s += 2;
    if (/google/i.test(v.name)) s += 2;
    if (/female|woman|samantha|aria|jenny|neerja/i.test(v.name)) s += 1;
    return s;
  };
  return voices.slice().sort((a, b) => score(b) - score(a))[0] || voices[0];
}

/** Call on a user gesture (e.g. Start Guardian) to unlock audio + load voices. */
export function primeSpeech() {
  if (!speechSupported()) return;
  _voice = pickVoice();
  window.speechSynthesis.onvoiceschanged = () => { _voice = pickVoice(); };
}

function armWatchdog() {
  if (_watchdog) clearTimeout(_watchdog);
  _watchdog = setTimeout(() => {
    _watchdog = null;
    if (_busy) {
      stopCurrent();
      drainNav();
    }
  }, BUSY_MAX_MS);
}

function enqueueNav(t) {
  if (!t) return;
  if (_navQ.length && _navQ[_navQ.length - 1] === t) return;
  _navQ.push(t);
  while (_navQ.length > NAV_Q_MAX) _navQ.shift();
}

function drainNav() {
  if (_busy) return;
  const t = _navQ.shift();
  if (!t) return;
  _lastText = t;
  _lastAt = Date.now();
  playNow(t, { pri: PRI_NAV, cloud: false });
}

function freeChannel() {
  _busy = false;
  _pri = 0;
  // Chrome often swallows speak() called synchronously from 'ended' — tick first.
  if (_navQ.length) setTimeout(drainNav, 60);
}

function stopCurrent() {
  if (_watchdog) {
    clearTimeout(_watchdog);
    _watchdog = null;
  }
  if (_audio) {
    try { _audio.onended = null; _audio.onerror = null; _audio.pause(); } catch {}
    _audio = null;
  }
  if (speechSupported()) {
    try { window.speechSynthesis.cancel(); } catch {}
  }
  _busy = false;
  _pri = 0;
}

function playBrowser(text) {
  if (!speechSupported()) { freeChannel(); return; }
  try {
    const u = new SpeechSynthesisUtterance(text);
    if (!_voice) _voice = pickVoice();
    if (_voice) u.voice = _voice;
    u.lang = (_voice && _voice.lang) || "en-IN";
    u.rate = _rate; u.pitch = 1.0; u.volume = 1.0;
    u.onend = () => { freeChannel(); };
    u.onerror = () => { freeChannel(); };
    try { window.speechSynthesis.resume(); } catch {}
    window.speechSynthesis.speak(u);
    armWatchdog();
  } catch {
    freeChannel();
  }
}

function ttsOrTimeout(text) {
  const ctrl = typeof AbortController !== "undefined" ? new AbortController() : null;
  const timer = setTimeout(() => { try { ctrl?.abort(); } catch {} }, TTS_MS);
  return Promise.resolve(api.tts(text, ctrl?.signal)).finally(() => clearTimeout(timer));
}

// Play one utterance NOW, preempting anything current.
async function playNow(text, { pri = PRI_ALERT, cloud = true } = {}) {
  stopCurrent();
  _busy = true;
  _pri = pri;
  const myReq = ++_req;
  armWatchdog();
  if (cloud && _useCloud && typeof navigator !== "undefined" && navigator.onLine) {
    try {
      const res = await ttsOrTimeout(text);
      if (myReq !== _req) return;               // a newer utterance superseded us
      if (res && res.audio) {
        const audio = new Audio(`data:${res.mime || "audio/mpeg"};base64,${res.audio}`);
        _audio = audio;
        audio.onended = () => { if (_audio === audio) { _audio = null; freeChannel(); } };
        audio.onerror = () => { if (_audio === audio) { _audio = null; playBrowser(text); } };
        try {
          await audio.play();
          return;                               // playing — _busy stays true until 'ended'
        } catch {
          if (myReq !== _req) return;
          // autoplay block or our own supersede — fall through to the browser voice
        }
      }
    } catch {}
    if (myReq !== _req) return;
  }
  playBrowser(text);
}

/** HIGH priority (alerts, greeting): always plays, preempting the current utterance. */
export async function speak(text) {
  const t = (text || "").trim();
  if (!t) return;
  const now = Date.now();
  if (t === _lastText && now - _lastAt < 3000) return; // ignore an immediate repeat
  _lastText = t; _lastAt = now;
  await playNow(t, { pri: PRI_ALERT, cloud: true });
}

/** Turn-by-turn / proximity. Instant browser voice so a throttled Cloud TTS call cannot
 * starve guidance.
 *   default  — queue if the channel is busy (live GPS: never drop a turn).
 *   replace  — drop the queue and cut any current NAV line so the cue matches
 *              where the traveller is NOW (compressed Simulate Drive). */
export function speakNav(text, opts = {}) {
  const t = (text || "").trim();
  if (!t) return false;
  const replace = !!opts.replace;
  if (replace) {
    _navQ = [];
    if (_busy && _pri >= PRI_ALERT) {
      enqueueNav(t);
      return true;
    }
    const now = Date.now();
    if (t === _lastText && now - _lastAt < 800) return true;
    _lastText = t; _lastAt = now;
    playNow(t, { pri: PRI_NAV, cloud: false });
    return true;
  }
  if (_busy) {
    enqueueNav(t);
    return true;
  }
  const now = Date.now();
  if (t === _lastText && now - _lastAt < 1200) return true;
  _lastText = t; _lastAt = now;
  playNow(t, { pri: PRI_NAV, cloud: false });
  return true;
}

export function clearNavQueue() {
  _navQ = [];
}

export function setSpeechRate(rate) {
  _rate = Math.max(0.8, Math.min(1.6, Number(rate) || 1.05));
}

export function cancelSpeech() {
  _req++; // invalidate any in-flight launch
  _navQ = [];
  stopCurrent();
}

/** Turn the Cloud tier off (browser voice still works). */
export function setCloudTTS(on) {
  _useCloud = !!on;
}
