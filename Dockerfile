# Use official Python image
FROM python:3.12-slim

# Install git
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy project files
COPY . /app

# Install dependencies
RUN pip install --no-cache-dir .

# Set entrypoint for CLI tool
ENTRYPOINT ["scanarr"]
