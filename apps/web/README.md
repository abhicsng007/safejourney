# SafeJourney — web PWA

Mobile-first React + Vite PWA. Plan a journey, see safety-ranked routes on the map, start the
Guardian, and watch live alerts arrive as the road ahead is monitored.

## Run

```bash
npm install
cp .env.example .env      # set VITE_API_URL if the API isn't on localhost:8080
npm run dev
```

Open the printed URL. The map uses keyless OpenStreetMap tiles by default (set
`VITE_MAP_STYLE_URL` to a MapTiler/Google style for prettier maps).

## Demo flow

1. Pick a **demo journey** (or set A/B by tapping the map) and a travel mode.
2. **Find the safest route** — routes are drawn coloured by safety; the safest is recommended.
   Try the *Uttarakhand* or *Sikkim* presets to see the **GLOF cascade** hazard flagged.
3. **Start Guardian** — the app polls the monitoring engine every few seconds.
4. Hit a **Simulate a hazard** chip (e.g. *Live wire in water*) → within a tick a **reroute /
   take-shelter** alert pops as a toast and enters the feed, and the route/hazard pins update.
5. **Safe harbour** marks nearby refuges; **Advance** moves your position along the route so
   monitoring only watches the road still ahead.

## Build

```bash
npm run build      # outputs dist/ (deploy to Firebase Hosting)
```

> In the cloud build, monitoring runs server-side (Cloud Scheduler → Pub/Sub → worker) and
> alerts arrive via FCM push even with the app closed. The local client-driven polling loop
> exists so the same behaviour is visible without deploying.
