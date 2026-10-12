# One image for everything that runs on the server: the API, the one-off database setup, and the admin
# commands. A second stage adds the tests, so the image that serves requests carries no test code.
FROM python:3.12-slim AS app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY schema.sql .
COPY app ./app
RUN useradd --system --no-create-home fleet
USER fleet
EXPOSE 8770
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8770", "--proxy-headers"]

FROM app AS test
USER root
RUN pip install --no-cache-dir httpx==0.28.1
COPY tests ./tests
USER fleet
CMD ["python", "-m", "unittest", "discover", "-s", "tests", "-v"]
