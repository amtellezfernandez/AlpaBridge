# syntax=docker/dockerfile:1.7
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1
ENV XDG_CACHE_HOME=/tmp/.cache
ENV ALPASIM_DRIVER_HOST=0.0.0.0
ENV ALPASIM_DRIVER_PORT=6789
ENV ALPASIM_DRIVER_GRPC_WORKERS=8
ENV WOD2SIM_CHALLENGE_MODEL=route_following
ENV WOD2SIM_CHALLENGE_TELEMETRY_PATH=/tmp/wod2sim/challenge-driver.jsonl
ENV WOD2SIM_CHALLENGE_LATENCY_TARGET_MS=100.0

RUN pip install --no-cache-dir \
    "grpcio==1.62.3" \
    "grpcio-tools==1.62.3" \
    "protobuf>=4.0.0,<5.0.0" \
    "setuptools<82" \
    "dataclasses-json>=0.6.7" \
    numpy \
    PyYAML

COPY --from=alpasim_grpc . /tmp/alpasim_grpc
RUN pip install --no-cache-dir --no-deps /tmp/alpasim_grpc && rm -rf /tmp/alpasim_grpc

WORKDIR /tmp/wod2sim
COPY pyproject.toml README.md LICENSE CITATION.cff ./
COPY LICENSES ./LICENSES
COPY src ./src
RUN pip install --no-cache-dir . && rm -rf /tmp/wod2sim

RUN groupadd --system alpasim \
    && useradd --system --gid alpasim --home-dir /app --shell /usr/sbin/nologin alpasim \
    && mkdir -p /app \
    && chown -R alpasim:alpasim /app

WORKDIR /app
USER alpasim
EXPOSE 6789

CMD ["wod2sim-challenge-driver"]
