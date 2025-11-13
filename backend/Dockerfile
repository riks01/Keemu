# Using Python 3.11 for best package compatibility
FROM python:3.11

WORKDIR /app

# Copy requirements
COPY pyproject.toml poetry.lock* ./

# Install poetry and dependencies using pip instead
RUN pip install poetry && \
    poetry config virtualenvs.create false && \
    poetry install --no-root
# Note: Installs both main and dev dependencies for development
# For production, add --only main flag

# Copy app
COPY . .

RUN mkdir -p models logs

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
