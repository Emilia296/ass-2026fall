FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home charge
COPY app ./app
COPY api-contract.json ./api-contract.json
COPY migrations ./migrations
USER charge
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "4", "--limit-concurrency", "500", "--timeout-keep-alive", "5"]
