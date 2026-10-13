# Build the React app, serve it with nginx, and proxy /api to the services (see nginx.conf).
FROM node:22-alpine AS build
WORKDIR /web
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# Only the two PUBLIC Supabase values reach the bundle (vite.config.js reads them from env).
ARG SUPABASE_URL=""
ARG SUPABASE_PUBLISHABLE_KEY=""
ENV SUPABASE_URL=$SUPABASE_URL SUPABASE_PUBLISHABLE_KEY=$SUPABASE_PUBLISHABLE_KEY
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /web/dist /usr/share/nginx/html
EXPOSE 80
