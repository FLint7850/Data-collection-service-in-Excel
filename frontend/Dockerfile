FROM node:24-alpine@sha256:f70403e87646dc51b45295f4b8b70cdad0b63d2297c4c9899119b03f7af7a6b3 AS build

WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run test \
    && npm run typecheck \
    && npm run build

FROM node:24-alpine@sha256:f70403e87646dc51b45295f4b8b70cdad0b63d2297c4c9899119b03f7af7a6b3

WORKDIR /app
ENV NODE_ENV=production
ENV PORT=3000
ENV NUXT_BACKEND_URL=http://parser:5000

COPY --from=build --chown=node:node /app/.output ./.output

EXPOSE 3000
USER node
CMD ["node", ".output/server/index.mjs"]
