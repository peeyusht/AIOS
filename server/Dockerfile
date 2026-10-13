# One image for everything that runs on the server: the API with the console, the worker, the one-off
# database setup and the admin commands. A last stage adds the tests, so the image that serves requests
# carries no test code.
#
# The build context is the repository root (see docker-compose.yml), because the server shares code with the
# agent: its matching rules (cve.py, eol.py), its thresholds and control areas (compliance.py), the check of
# an agent release's signature (device-agent/release.py), and the console's design (shadow-filer/ui). /.dockerignore lets in those files and nothing else from the agent.

# ---- the console: the same components and styles as the PC's own console, a second entry page
FROM node:22-slim AS console
WORKDIR /ui
COPY shadow-filer/ui/package.json shadow-filer/ui/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY shadow-filer/ui/ ./
RUN npm run build:fleet && mv /ui/dist-fleet/fleet.html /ui/dist-fleet/index.html

FROM python:3.12-slim AS app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/srv/shared
WORKDIR /srv
COPY server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server/schema.sql .
COPY shadow-filer/cve.py shadow-filer/eol.py shadow-filer/compliance.py device-agent/release.py ./shared/
COPY server/app ./app
COPY --from=console /ui/dist-fleet ./app/console
# /data/ref is the worker's volume: its copy of the public CVE and end-of-life lists
RUN useradd --system --no-create-home fleet && mkdir -p /data/ref && chown fleet /data/ref
USER fleet
EXPOSE 8770
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8770", "--proxy-headers"]

FROM app AS test
USER root
RUN pip install --no-cache-dir httpx==0.28.1
COPY server/tests ./tests
USER fleet
CMD ["python", "-m", "unittest", "discover", "-s", "tests", "-v"]
