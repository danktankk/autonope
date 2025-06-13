FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY autonope/ ./autonope
COPY scripts/ ./scripts
COPY config/ ./config

RUN useradd -u 1000 autonope && chown -R autonope:autonope /app
USER autonope

ENTRYPOINT ["tini", "--"]
CMD ["python", "-m", "autonope.main"]
