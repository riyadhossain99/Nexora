FROM python:3.12-slim

# Install system dependencies and Node.js 20 LTS
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    gnupg \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" > /etc/apt/sources.list.d/nodesource.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python requirements
COPY backend/requirements.txt /app/backend/
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

# Install Node dependencies for WhatsApp bridge
COPY backend/whatsapp/package*.json /app/backend/whatsapp/
RUN cd /app/backend/whatsapp && npm install --omit=dev

# Copy all project source code
COPY . /app/

# Collect static assets for production
ENV DJANGO_SETTINGS_MODULE=nexora.settings
ENV PYTHONUNBUFFERED=1
RUN python backend/manage.py collectstatic --noinput

# Ensure execution permission on startup script
RUN chmod +x /app/render_start.sh

EXPOSE 8000
CMD ["/app/render_start.sh"]
