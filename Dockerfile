FROM python:3.11-slim

WORKDIR /app

# Install basic system dependencies and ca-certificates for TLS
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Set unbuffered python output for Render real-time console logs
ENV PYTHONUNBUFFERED=1
ENV PORT=5555

EXPOSE 5555

# Run main application
CMD ["python", "-u", "mycloud_all_timescale.py"]
