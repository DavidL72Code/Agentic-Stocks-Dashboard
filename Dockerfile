# Monsoon backend.
#
# Two stages so the final image carries no pip cache and no build toolchain.
# Everything in requirements.txt ships manylinux wheels for CPython 3.13
# (pandas, numpy and yfinance included), so no compiler is needed - if that
# ever changes, add build-essential to the build stage only.
#
# NOTE this image is NOT what render.yaml uses - that runs Render's native
# Python runtime, so nothing here affects the deploy or its startup time. This
# exists for local parity (docker-compose.yml brings up app + redis in one
# command) and so moving host later is a config change. See HOSTING.md.

FROM python:3.13-slim AS build

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copied alone so the dependency layer is cached independently of source edits.
COPY requirements.txt .
RUN pip install -r requirements.txt

# Optional extra, on by build arg rather than by editing the file. The Turso
# driver is no longer one: it is in requirements.txt, since Render needs it.
ARG WITH_REDIS=false
RUN if [ "$WITH_REDIS" = "true" ]; then pip install "redis>=6.0"; fi


FROM python:3.13-slim

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8077

# Runs unprivileged. /data is where a SQLite file goes when one is used at all;
# mount a volume over it, or set TURSO_DATABASE_URL and ignore it.
RUN useradd --create-home --uid 10001 monsoon \
 && mkdir -p /data \
 && chown monsoon:monsoon /data

WORKDIR /app
COPY --from=build /opt/venv /opt/venv
COPY --chown=monsoon:monsoon backend/ backend/
COPY --chown=monsoon:monsoon web/ web/

USER monsoon
EXPOSE 8077

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os,urllib.request;\
urllib.request.urlopen(f\"http://127.0.0.1:{os.environ.get('PORT','8077')}/api/health\",timeout=4)"

# `exec` so uvicorn replaces the shell and becomes PID 1 - otherwise sh swallows
# SIGTERM and every stop waits for the kill timeout. Shell form is needed at all
# because $PORT has to expand (hosts assign it); 0.0.0.0 because the default
# binds loopback, which no container router can reach.
CMD ["sh", "-c", "exec uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port ${PORT:-8077}"]
