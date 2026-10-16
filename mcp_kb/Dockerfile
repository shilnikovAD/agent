# MCP-сервер базы знаний: без сети наружу, без секретов, база знаний смонтирована только для чтения.
FROM python:3.12.8-slim-bookworm
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 MCP_TRANSPORT=http MCP_HOST=0.0.0.0 MCP_PORT=8765 KB_DIR=/kb
WORKDIR /srv
RUN pip install mcp==1.30.0
COPY mcp_kb ./mcp_kb
RUN useradd --create-home kb
USER kb
EXPOSE 8765
HEALTHCHECK --interval=5s --timeout=3s --retries=10 CMD python -c "import socket; socket.create_connection(('127.0.0.1', 8765), 2)"
CMD ["python", "-m", "mcp_kb.server"]
