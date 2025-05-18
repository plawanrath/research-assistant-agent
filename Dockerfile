# ---- Base image -------------------------------------------------------
FROM python:3.11-slim AS base

# ---- Metadata ---------------------------------------------------------
LABEL maintainer="Personal Research Assistant Agent"
LABEL org.opencontainers.image.source="https://github.com/plawanrath/research-assistant-agent.git"

# ---- System deps ------------------------------------------------------
RUN apt-get update -y && \
    apt-get install -y --no-install-recommends \
        build-essential \
        curl \
    && rm -rf /var/lib/apt/lists/*

# ---- Workdir ----------------------------------------------------------
WORKDIR /app

# ---- Python deps ------------------------------------------------------
# Copy requirements first for layer caching
COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# ---- Project code -----------------------------------------------------
COPY . .

# ---- Environment ------------------------------------------------------
ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PIP_NO_CACHE_DIR=1

# ---- Expose -----------------------------------------------------------
# Streamlit default port
EXPOSE 8501

# ---- Default command --------------------------------------------------
# Run the Streamlit UI; it calls the backend when needed
CMD ["streamlit", "run", "ui/app.py", "--server.port", "8501", "--server.enableCORS", "false"]
