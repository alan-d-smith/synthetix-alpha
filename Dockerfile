# syntax=docker/dockerfile:1

FROM golang:bookworm AS alpaca-cli

ENV CGO_ENABLED=0
RUN go install github.com/alpacahq/cli/cmd/alpaca@latest

FROM python:3.13-slim AS runtime

WORKDIR /app

# Matplotlib and other wheels that link against system libraries.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libfreetype6 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=alpaca-cli /go/bin/alpaca /usr/local/bin/alpaca

COPY pyproject.toml README.md ./
COPY synthetix_alpha ./synthetix_alpha
COPY config ./config
COPY datasets ./datasets
COPY docs ./docs

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["sh", "-c", "uvicorn synthetix_alpha.api.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
