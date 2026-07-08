# syntax=docker/dockerfile:1
#
# Multi-stage build for the OSW Next.js frontend.
#
# `NEXT_PUBLIC_API_URL` is a `NEXT_PUBLIC_*` variable: Next.js inlines it into
# the client JS bundle at BUILD time (see `frontend/src/lib/api-client.ts`'s
# `getApiBaseUrl()`), it is not re-read at container start. It must therefore
# be supplied as a build ARG (`docker-compose.prod.yml` wires this via
# `build.args`) -- a plain runtime `environment:` entry on the `frontend`
# service would have no effect on the already-built client bundle.

# Next.js 16 itself only requires Node >=20.9 (see `docs/01-app/02-guides/
# upgrading/version-16.mdx`), but pnpm 11.5.0 (pinned below to match
# `.github/workflows/ci.yml`) hard-requires Node >=22.13 at startup (it uses
# the `node:sqlite` builtin internally) -- verified by an actual `docker build`
# under `node:20-alpine` failing with `ERR_UNKNOWN_BUILTIN_MODULE: node:sqlite`
# before a single dependency could even be resolved. 22-alpine satisfies both
# constraints; kept as one ARG so deps/builder/runner all agree.
ARG NODE_VERSION=22-alpine

# ---- deps: install dependencies only, cached separately from source edits ----
FROM node:${NODE_VERSION} AS deps
WORKDIR /app

# Pin pnpm to the exact version pinned in CI (see
# `.github/workflows/ci.yml`'s `pnpm/action-setup@v3, version: "11.5.0"`) so
# the committed lockfile (`lockfileVersion: '9.0'`) is read by a compatible
# pnpm build, identically to CI/local dev.
RUN corepack enable && corepack prepare pnpm@11.5.0 --activate

# `.npmrc` / `pnpm-workspace.yaml` gate which dependencies (sharp,
# unrs-resolver) are allowed to run install/build scripts -- copy them
# alongside the lockfile so `pnpm install` behaves exactly as it does locally.
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml .npmrc ./
RUN pnpm install --frozen-lockfile

# ---- builder: compile the production build ----
FROM node:${NODE_VERSION} AS builder
WORKDIR /app
RUN corepack enable && corepack prepare pnpm@11.5.0 --activate

ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}

COPY --from=deps /app/node_modules ./node_modules
COPY . .

# `package.json`'s `build` script is pinned to `next build --webpack` (see
# `next.config.ts`'s "Bundler note" docstring: Next 16's default Turbopack
# production bundler was observed to break Molstar's chunk loading at
# runtime). Deliberately NOT overridden to plain `next build` here.
RUN pnpm run build

# ---- runner: minimal production image ----
FROM node:${NODE_VERSION} AS runner
WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

RUN addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 nextjs

# `output: "standalone"` (see `next.config.ts`) traces only the production
# `node_modules` subset actually needed at runtime into `.next/standalone`,
# alongside a minimal `server.js` that replaces `next start` -- Next.js itself
# warns at startup that "next start" does not honor "output: standalone".
# `public/` and `.next/static/` are deliberately left out of that trace
# (Next's own docs: intended to be served by a CDN instead) and must be
# copied alongside it by hand for this self-contained image to serve them.
COPY --from=builder --chown=nextjs:nodejs /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs
EXPOSE 3000

# Used by `docker-compose.prod.yml` / k8s readiness+liveness probes.
# Implemented with plain Node (no curl/wget dependency needed in this image).
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
  CMD node -e "require('http').get('http://127.0.0.1:3000/', (res) => process.exit(res.statusCode < 500 ? 0 : 1)).on('error', () => process.exit(1))"

CMD ["node", "server.js"]
