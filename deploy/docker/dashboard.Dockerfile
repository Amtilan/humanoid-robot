# Web dashboard — build the Vite bundle, then serve it via nginx.

FROM node:22-alpine AS build
WORKDIR /work

RUN corepack enable

COPY web/dashboard/package.json web/dashboard/pnpm-lock.yaml web/dashboard/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

COPY web/dashboard ./
RUN pnpm exec tsc -b --noEmit
RUN pnpm exec vite build


FROM nginx:1.27-alpine AS runtime
COPY --from=build /work/dist /usr/share/nginx/html
COPY deploy/docker/dashboard.nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
