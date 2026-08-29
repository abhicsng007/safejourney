/* Spoken narration for the Guardian — so a rider who can't look at the screen still gets the
 * alert, out loud, hands-free (like Maps voice guidance).
 *
 * Two tiers, graceful like the rest of the app:
 *   1. Google Cloud Text-to-Speech (Chirp/Neural2) — a natural neural voice when online.
 *   2. Browser SpeechSynthesis — on-device, instant, free, works OFFLINE. The fallback.
 *
 * One channel, one voice at a time. `_busy` is set the instant an utterance is launched (before
 * the Cloud fetch even returns) and cleared only by the audio's own 'ended' event, so low-
 * priority nav/proximity cues reliably YIELD instead of superseding an in-flight utterance
 * before it can play (the "nothing plays during simulation" bug). A request token guarantees
 * that when several high-priority calls race (double renders, back-to-back alerts) only the
 * latest one's audio actually starts — and it always starts, exactly once.
 */

import { api } from "../api";

let _voice = null;
let _useCloud = true;
let _audio = null;      // currently-playing Cloud TTS <audio>
let _busy = false;      // channel occupied (launching or playing)
let _req = 0;           // monotonic token — only the latest launch may start audio
let _lastText = "";     // dedup: skip the same line repeated within a moment
let _lastAt = 0;

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

function stopCurrent() {
  if (_audio) {
    try { _audio.onended = null; _audio.onerror = null; _audio.pause(); } catch {}
    _audio = null;
  }
  if (speechSupported()) {
    try { window.speechSynthesis.cancel(); } catch {}
  }
  _busy = false;
}

function playBrowser(text) {
  if (!speechSupported()) { _busy = false; return; }
  try {
    const u = new SpeechSynthesisUtterance(text);
    if (!_voice) _voice = pickVoice();
    if (_voice) u.voice = _voice;
    u.lang = (_voice && _voice.lang) || "en-IN";
    u.rate = 1.0; u.pitch = 1.0; u.volume = 1.0;
    u.onend = () => { _busy = false; };
    u.onerror = () => { _busy = false; };
    window.speechSynthesis.speak(u); // stopCurrent already cancelled anything prior
  } catch {
    _busy = false;
  }
}

// Play one utterance NOW, preempting anything current. Cloud first, browser fallback.
async function playNow(text) {
  stopCurrent();
  _busy = true;                 // reserve the channel synchronously (covers the fetch window)
  const myReq = ++_req;
  if (_useCloud && navigator.onLine) {
    try {
      const res = await api.tts(text);
      if (myReq !== _req) return;               // a newer utterance superseded us — abandon
      if (res && res.audio) {
        const audio = new Audio(`data:${res.mime || "audio/mpeg"};base64,${res.audio}`);
        _audio = audio;
        audio.onended = () => { if (_audio === audio) { _audio = null; _busy = false; } };
        audio.onerror = () => { if (_audio === audio) { _audio = null; _busy = false; } };
        try {
          await audio.play();
          return;                               // playing — _busy stays true until 'ended'
        } catch (e) {
          if (e && e.name === "AbortError") return; // our own supersede — handled
          // otherwise fall through to the browser voice
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
  await playNow(t);
}

/** LOW priority (turn-by-turn, proximity): speaks only when the channel is free, so a safety
 * alert or another instruction is never cut off. Returns true if it launched, false if it
 * yielded — the caller marks the cue "announced" only when it actually launched. */
export function speakNav(text) {
  if (_busy) return false;
  const t = (text || "").trim();
  if (!t) return false;
  const now = Date.now();
  if (t === _lastText && now - _lastAt < 3000) return false;
  _lastText = t; _lastAt = now;
  playNow(t); // fire-and-forget
  return true;
}

export function cancelSpeech() {
  _req++; // invalidate any in-flight launch
  stopCurrent();
}

/** Turn the Cloud tier off (browser voice still works). */
export function setCloudTTS(on) {
  _useCloud = !!on;
}
