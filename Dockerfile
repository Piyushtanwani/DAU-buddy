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
COPY config/     /app/config/
COPY connectors/ /app/connectors/
COPY data/       /app/data/
COPY parsers/    /app/parsers/
COPY scrapers/   /app/scrapers/
COPY dau_mcp/    /app/dau_mcp/
COPY frontend/   /app/frontend/
COPY scripts/    /app/scripts/
COPY .env.example /app/

# Expose port
EXPOSE 8080

# Liveness check — deliberately does NOT touch the database.
#
# This probe answers one question: is the process still serving? A restart is
# the only remedy it can trigger, and restarting fixes a wedged process but not
# an unreachable database — it just drops every in-flight request, which is what
# surfaces in the browser as "Failed to fetch". So the probe hits the static
# root, not /api/health.
#
# /api/health does check the database and is the right probe for readiness (load
# balancer / orchestrator traffic gating), where the remedy is "stop sending
# traffic here" rather than "restart this".
#
# The timeout is generous on purpose: a brief latency spike must not be read as
# a dead process.
HEALTHCHECK --interval=30s --timeout=15s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:8080/ || exit 1

# Start the FastAPI application
CMD ["python", "-m", "uvicorn", "api.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080"]
