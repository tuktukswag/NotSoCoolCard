FROM python:3.11-slim

WORKDIR /app

# Optional but helpful
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install dependencies first for better layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Expose the app port
EXPOSE 5000

# Start the Python app
CMD ["python", "app.py"]