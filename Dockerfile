FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir .

RUN useradd -m scanner
USER scanner
WORKDIR /home/scanner

ENTRYPOINT ["aliens_eye"]
