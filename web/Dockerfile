FROM node:24-bookworm-slim AS node
FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends libstdc++6 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=node /usr/local/bin/node /usr/local/bin/node
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 \
    BOOTH_NEST_PYTHON=python3 BOOTH_NEST_WEB_HOME=/data/BoothShelf/web \
    BOOTH_NEST_ENGINE_HOME=/data/BoothShelf PORT=8010
WORKDIR /app
COPY server.mjs online.mjs package.json LICENSE THIRD_PARTY_NOTICES.md /app/
COPY lib/ /app/lib/
COPY public/ /app/public/
COPY engine/ /app/engine/
EXPOSE 8010
CMD ["node", "/app/online.mjs"]
