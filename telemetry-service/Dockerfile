FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY telemetry/ telemetry/

EXPOSE 8080 8081

CMD ["uvicorn", "telemetry.service:app", "--host", "0.0.0.0", "--port", "8080"]
