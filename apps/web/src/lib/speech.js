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

async function speakCloud(text) {
  // Returns true if it played Cloud TTS audio, false to fall back to the browser voice.
  if (!_useCloud || !navigator.onLine) return false;
  try {
    const res = await api.tts(text);
    if (!res || !res.audio) return false;
    cancelSpeech();
    const audio = new Audio(`data:${res.mime || "audio/mpeg"};base64,${res.audio}`);
    _audio = audio;
    await audio.play();
    return true;
  } catch {
    return false;
  }
}

/** Speak text aloud: Cloud TTS when available, else the on-device browser voice. */
export async function speak(text) {
  const t = (text || "").trim();
  if (!t) return;
  const now = Date.now();
  if (t === _lastText && now - _lastAt < 3000) return; // ignore an immediate repeat
  _lastText = t;
  _lastAt = now;
  const played = await speakCloud(t);
  if (!played) speakBrowser(t);
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
