# Use official lightweight Python image
FROM python:3.12-slim

# Set system environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies first (Docker layer caching)
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY core/       /app/core/
COPY api/        /app/api/
COPY scrapers/   /app/scrapers/
COPY dau_mcp/        /app/dau_mcp/
COPY frontend/   /app/frontend/
COPY scripts/    /app/scripts/
COPY .env.example /app/

# Expose port
EXPOSE 8080

# Health check. The timeout is generous on purpose: a brief spike must not mark
# the container unhealthy and trigger a restart, which drops every in-flight
# request and surfaces in the browser as "Failed to fetch".
HEALTHCHECK --interval=30s --timeout=15s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:8080/api/health || exit 1

# Start the FastAPI application
CMD ["python", "-m", "uvicorn", "api.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080"]
