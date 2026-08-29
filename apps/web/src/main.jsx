import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App.jsx";
import "maplibre-gl/dist/maplibre-gl.css";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    // updateViaCache:"none" — never load sw.js from the HTTP cache, so a new deploy's worker
    // is always detected; update() forces that check on every visit.
    navigator.serviceWorker
      .register("/sw.js", { updateViaCache: "none" })
      .then((reg) => reg.update())
      .catch(() => {});

    // If a page is already controlled, a controllerchange means a newer worker just took over
    // (skipWaiting + clients.claim): reload once so the freshest bundle shows immediately.
    if (navigator.serviceWorker.controller) {
      let reloaded = false;
      navigator.serviceWorker.addEventListener("controllerchange", () => {
        if (reloaded) return;
        reloaded = true;
        window.location.reload();
      });
    }
  });
}
