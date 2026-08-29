/* Spoken narration for the Guardian — so a rider who can't look at the screen still gets the
 * alert, out loud, hands-free (like Maps voice guidance).
 *
 * Two tiers, graceful like the rest of the app:
 *   1. Browser SpeechSynthesis — on-device, instant, free, works OFFLINE. Always available.
 *   2. Google Cloud Text-to-Speech (Chirp/WaveNet) — a natural neural voice when online.
 *      (Layered in via speakCloud(); falls back to the browser voice on any failure.)
 */

import { api } from "../api";

let _voice = null;
let _useCloud = true; // try Cloud TTS first when available; browser is the fallback
let _audio = null; // currently-playing Cloud TTS audio element
let _lastText = ""; // dedup: skip the same line repeated within a moment (double renders)
let _lastAt = 0;
let _gen = 0; // generation counter — a newer utterance supersedes older in-flight ones
let _pending = false; // a high-priority utterance is being launched (fetch in flight) — treat
                      // as "speaking" so rapid nav/proximity calls yield instead of superseding
                      // it before its audio can start (the "nothing plays during sim" cascade)

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
    if (/google/i.test(v.name)) s += 2; // Chrome's Google voices are the most natural
    if (/female|woman|samantha|aria|jenny|neerja/i.test(v.name)) s += 1;
    return s;
  };
  return voices.slice().sort((a, b) => score(b) - score(a))[0] || voices[0];
}

/** Call on a user gesture (e.g. Start Guardian) to unlock audio + load voices. */
export function primeSpeech() {
  if (!speechSupported()) return;
  _voice = pickVoice();
  // Voices load asynchronously in most browsers — re-pick when they arrive.
  window.speechSynthesis.onvoiceschanged = () => { _voice = pickVoice(); };
}

function speakBrowser(text) {
  if (!speechSupported() || !text) return;
  try {
    const u = new SpeechSynthesisUtterance(text);
    if (!_voice) _voice = pickVoice();
    if (_voice) u.voice = _voice;
    u.lang = (_voice && _voice.lang) || "en-IN";
    u.rate = 1.0;
    u.pitch = 1.0;
    u.volume = 1.0;
    window.speechSynthesis.cancel(); // an alert supersedes whatever was speaking
    window.speechSynthesis.speak(u);
  } catch {}
}

async function speakCloud(text, gen) {
  // Returns true when the Cloud tier handled the utterance (played, or was superseded by a
  // newer one), false only on a genuine failure so the browser voice can take over. Crucially
  // it must NOT report failure when its own audio is interrupted — otherwise the same line
  // gets spoken twice, once by Cloud and once by the browser (the "two accents" bug).
  if (!_useCloud || !navigator.onLine) return false;
  try {
    const res = await api.tts(text);
    if (gen !== _gen) return true;          // a newer utterance started — don't double up
    if (!res || !res.audio) return false;
    const audio = new Audio(`data:${res.mime || "audio/mpeg"};base64,${res.audio}`);
    _audio = audio;
    try {
      await audio.play();
    } catch (e) {
      // AbortError = our own cancel/supersede paused it → handled, no fallback.
      // Any other error (e.g. autoplay blocked) → let the browser voice try.
      if (!e || e.name !== "AbortError") return false;
    }
    return true;
  } catch {
    return false;
  }
}

/** Speak text aloud: Cloud TTS when available, else the on-device browser voice. Never both. */
export async function speak(text) {
  const t = (text || "").trim();
  if (!t) return;
  const now = Date.now();
  if (t === _lastText && now - _lastAt < 3000) return; // ignore an immediate repeat
  _lastText = t;
  _lastAt = now;
  const myGen = ++_gen;   // claim the newest generation
  _pending = true;        // hold off lower-priority narration while we launch this
  cancelSpeech();         // stop whatever is currently speaking (one voice at a time)
  try {
    const played = await speakCloud(t, myGen);
    if (myGen === _gen && !played) speakBrowser(t); // fall back only if still current
  } finally {
    if (myGen === _gen) _pending = false; // launched — audio/browser now carries the state
  }
}

function isSpeaking() {
  if (_pending) return true; // a fetch is in flight — don't step on it
  const browser = speechSupported() && window.speechSynthesis.speaking;
  const cloud = _audio && !_audio.paused && !_audio.ended;
  return !!(browser || cloud);
}

/** Lower-priority narration (turn-by-turn, proximity): speaks only when nothing else is, so a
 * safety alert or another instruction is never cut off. Returns true if it actually launched
 * (so the caller can mark the step announced), false if it yielded. Synchronous on purpose. */
export function speakNav(text) {
  if (isSpeaking()) return false;
  speak(text); // fire-and-forget; we've claimed the slot
  return true;
}

export function cancelSpeech() {
  if (speechSupported()) {
    try { window.speechSynthesis.cancel(); } catch {}
  }
  if (_audio) {
    try { _audio.pause(); _audio.currentTime = 0; } catch {}
    _audio = null;
  }
}

/** Turn the Cloud tier off (e.g. if the backend has no TTS configured) — browser stays. */
export function setCloudTTS(on) {
  _useCloud = !!on;
}
