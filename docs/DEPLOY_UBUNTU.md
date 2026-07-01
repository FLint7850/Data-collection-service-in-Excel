# Deploy on Ubuntu with Docker

## First start

1. Install Docker Engine and the Docker Compose plugin.
2. Copy the project to the server.
3. Create `.env` from `.env.example` and set secrets, SMTP, ports, and default thread counts.
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

The image installs Playwright `chromium` and `chromium-headless-shell`. Playwright headless rendering prefers `chromium-headless-shell`. Botasaurus methods use normal Chromium because Botasaurus expects a full browser executable even in headless mode; the visible debug method also uses normal Chromium/Chrome for Testing.

## Local Windows Docker notes

The compose file limits the parser container to 3 GB RAM and 2 CPUs. Docker Desktop still runs inside WSL2, and `vmmemWSL` can keep already allocated memory after containers stop. For local testing, stop the stack when you are done:

```powershell
docker-compose down
wsl --shutdown
```

To put a hard cap on all WSL2 memory, create or edit `%UserProfile%\.wslconfig`:

```ini
[wsl2]
memory=6GB
processors=4
swap=2GB
```

Then run `wsl --shutdown` and start Docker Desktop again.
