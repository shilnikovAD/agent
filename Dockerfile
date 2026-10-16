# Агент рабочих чатов. Сеть наружу нужна только для OpenRouter и Telegram; ключи приходят из .env при запуске,
# в образ не попадают.
FROM python:3.12.8-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements-agent.txt .
RUN pip install -r requirements-agent.txt
COPY workchat ./workchat
COPY mcp_kb ./mcp_kb
COPY data ./data
COPY tasks ./tasks
COPY tests ./tests
COPY mcp_pins.json ./
RUN useradd --create-home agent && mkdir -p /app/runs && chown agent /app/runs
USER agent
CMD ["python", "-m", "workchat", "run"]
