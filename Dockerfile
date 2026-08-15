FROM python:3.12-slim

WORKDIR /app

# Install dependencies (includes Flask for debug visualizer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project code
COPY . .

ENV PYTHONUNBUFFERED=1

# Default run-id; override via docker-compose.yml command or build args
ARG RUN_ID=docker-demo
ENV RUN_ID=${RUN_ID}

# NOTE: The LLM URL is hardcoded to host.docker.internal:8000.
# To use a different server, override via docker-compose.yml command:
#   docker compose run --rm agent python main.py --llm-url http://your-llm-server:8000/v1

CMD ["python", "main.py", "--run-id", "${RUN_ID}", "--llm-url", "http://host.docker.internal:8000/v1"]
