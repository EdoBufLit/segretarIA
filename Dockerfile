# 1) Python 3.11 slim base
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV APP_HOME=/app

# Set work directory
WORKDIR $APP_HOME

# Install system dependencies
# libpq-dev is needed for psycopg2 (if using binary, it's included, but good practice if moving to non-binary)
# curl for healthchecks
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 2) Install deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project
COPY . .

# Make entrypoint executable (redundant with chmod above but safe for docker build context)
RUN chmod +x entrypoint.sh

# 4) Expose port 8000
EXPOSE 8000

# 3) Run alembic upgrade head on startup (handled in entrypoint.sh)
CMD ["./entrypoint.sh"]
