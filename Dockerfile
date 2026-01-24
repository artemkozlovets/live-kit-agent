FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN useradd -m -u 10001 appuser

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY . /app

RUN chown -R appuser:appuser /app

USER appuser

EXPOSE 8081
EXPOSE 9090

CMD ["python", "-m", "livekit_agent.agent", "start"]
