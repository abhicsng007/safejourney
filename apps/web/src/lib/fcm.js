// Firebase Cloud Messaging — web push registration.
//
// Fully env-gated: with no VITE_FIREBASE_* config the whole module is a no-op that returns
// an empty token, so the app runs identically without Firebase. When configured, enablePush()
// asks for notification permission, registers the messaging service worker, and returns an
// FCM token the backend stores on the trip to push alerts even when the tab is closed.

import { initializeApp, getApps } from "firebase/app";
import { getMessaging, getToken, onMessage, isSupported } from "firebase/messaging";

const cfg = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY,
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID,
  messagingSenderId: import.meta.env.VITE_FIREBASE_MESSAGING_SENDER_ID,
  appId: import.meta.env.VITE_FIREBASE_APP_ID,
};
const VAPID = import.meta.env.VITE_FIREBASE_VAPID_KEY;

export function fcmConfigured() {
  return Boolean(cfg.apiKey && cfg.projectId && cfg.messagingSenderId && cfg.appId && VAPID);
}

let _messaging = null;
async function getMessagingSafe() {
  if (_messaging) return _messaging;
  if (!(await isSupported().catch(() => false))) return null;
  const app = getApps().length ? getApps()[0] : initializeApp(cfg);
  _messaging = getMessaging(app);
  return _messaging;
}

// The messaging service worker can't read import.meta.env, so we hand it the (public)
// Firebase config on the registration URL and it reads it from location.search.
// Registered at a dedicated NARROW scope so it never collides with the app's PWA sw.js at "/".
async function registerMessagingSw() {
  const params = new URLSearchParams({
    apiKey: cfg.apiKey || "",
    authDomain: cfg.authDomain || "",
    projectId: cfg.projectId || "",
    messagingSenderId: cfg.messagingSenderId || "",
    appId: cfg.appId || "",
  });
  return navigator.serviceWorker.register(`/firebase-messaging-sw.js?${params.toString()}`, {
    scope: "/firebase-cloud-messaging-push-scope",
  });
}

/**
 * Request permission and return an FCM token, or "" if unavailable/declined.
 * @param {(payload:any)=>void} onForeground called when a push arrives while the tab is open.
 */
export async function enablePush(onForeground) {
  if (!fcmConfigured()) return "";
  if (!("serviceWorker" in navigator) || !("Notification" in window)) return "";
  try {
    const perm = await Notification.requestPermission();
    if (perm !== "granted") return "";
    const messaging = await getMessagingSafe();
    if (!messaging) return "";
    const swReg = await registerMessagingSw();
    const token = await getToken(messaging, {
      vapidKey: VAPID,
      serviceWorkerRegistration: swReg,
    });
    if (token && onForeground) onMessage(messaging, onForeground);
    return token || "";
  } catch (e) {
    console.warn("[fcm] enablePush failed", e);
    return "";
  }
}
