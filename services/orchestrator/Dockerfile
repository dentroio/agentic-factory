FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN mkdir -p /data /watchdog
COPY . .
CMD ["python", "orchestrator.py"]
