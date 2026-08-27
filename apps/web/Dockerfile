# SafeJourney web — build the Vite PWA, serve it with nginx on Cloud Run.
# Build context is the REPO ROOT:
#   docker build -f apps/web/Dockerfile --build-arg VITE_API_URL=https://... -t safejourney-web .
FROM node:20-alpine AS build
WORKDIR /app
COPY apps/web/package*.json ./
RUN npm ci || npm install
COPY apps/web/ ./
# Vite inlines VITE_* vars from .env at build time, so the API URL is baked into the bundle.
ARG VITE_API_URL=""
RUN echo "VITE_API_URL=${VITE_API_URL}" > .env
RUN npm run build

FROM nginx:alpine
COPY apps/web/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
