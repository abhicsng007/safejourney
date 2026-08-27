/* SafeJourney FCM background service worker.
 *
 * Renders the OS notification when a push arrives while the tab/app is closed — the
 * "app-closed alert" behaviour — and deep-links the click back to the alerting trip.
 *
 * The (public) Firebase config is passed on this SW's registration URL by src/lib/fcm.js,
 * because a service worker can't read the app's build-time env. With no config the file is
 * inert, so the app still works without Firebase.
 */
importScripts("https://www.gstatic.com/firebasejs/10.13.2/firebase-app-compat.js");
importScripts("https://www.gstatic.com/firebasejs/10.13.2/firebase-messaging-compat.js");

const params = new URL(location).searchParams;
const cfg = {
  apiKey: params.get("apiKey"),
  authDomain: params.get("authDomain"),
  projectId: params.get("projectId"),
  messagingSenderId: params.get("messagingSenderId"),
  appId: params.get("appId"),
};

if (cfg.apiKey && cfg.projectId) {
  firebase.initializeApp(cfg);
  const messaging = firebase.messaging();

  messaging.onBackgroundMessage((payload) => {
    const n = payload.notification || {};
    const data = payload.data || {};
    const title = n.title || data.title || "SafeJourney";
    self.registration.showNotification(title, {
      body: n.body || data.body || "A hazard is on the road ahead.",
      icon: "/icon.svg",
      badge: "/icon.svg",
      tag: data.tripId || "safejourney",
      renotify: true,
      requireInteraction: true,
      data,
    });
  });
}

// Focus an existing tab or open the app at the alerting trip.
self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const tripId = event.notification.data && event.notification.data.tripId;
  const target = tripId ? `/?trip=${tripId}` : "/";
  event.waitUntil(
    clients.matchAll({ type: "window", includeUncontrolled: true }).then((wins) => {
      for (const w of wins) {
        if ("focus" in w) {
          w.navigate && w.navigate(target);
          return w.focus();
        }
      }
      return clients.openWindow(target);
    })
  );
});
