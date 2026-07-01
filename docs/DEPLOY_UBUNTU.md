# Deploy on Ubuntu with Docker

## First start

1. Install Docker Engine and the Docker Compose plugin.
2. Copy the project to the server.
3. Create `.env` from `.env.example` and set secrets, SMTP, ports, and worker limits.
4. Put the existing SQLite database at `data/app.db` if you are migrating from local.
5. Start:

```bash
docker compose up -d --build
```

The app listens on `http://SERVER_IP:5000` by default.

## Operations

```bash
docker compose logs -f parser
docker compose restart parser
docker compose down
```

Persistent data is mounted from these host folders: `data`, `logs`, `exports`, `feeds`, `storage`.

## Browser runtime

The image installs Playwright `chromium` and `chromium-headless-shell`. Headless parser methods prefer `chromium-headless-shell`; the visible debug method uses normal Chromium/Chrome for Testing because it needs a real headed browser window.
