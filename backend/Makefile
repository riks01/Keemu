.PHONY: help build up down restart logs shell test clean

help: ## Show this help message
	@echo 'Usage: make [target]'
	@echo ''
	@echo 'Available targets:'
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  %-15s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

build: ## Build Docker images
	docker compose build

up: ## Start all services
	docker compose up -d
	@echo "Services started!"
	@echo "API: http://localhost:8000"
	@echo "Docs: http://localhost:8000/docs"
	@echo "Flower: http://localhost:5555"

up-logs: ## Start all services with logs
	docker compose up

down: ## Stop all services
	docker compose down

restart: ## Restart all services
	docker compose restart

logs: ## View logs from all services
	docker compose logs -f

logs-api: ## View API logs only
	docker compose logs -f api

logs-celery: ## View Celery worker logs only
	docker compose logs -f celery_worker

shell: ## Open shell in API container
	docker compose exec api /bin/bash

db-shell: ## Open PostgreSQL shell
	docker compose exec postgres psql -U keemu_user -d keemu_db

redis-cli: ## Open Redis CLI
	docker compose exec redis redis-cli

test: ## Run tests
	docker compose exec api pytest

test-cov: ## Run tests with coverage
	docker compose exec api pytest --cov=app --cov-report=html

test-db: ## Test database connection
	docker compose exec api python test_db_connection.py

test-models: ## Test User models
	docker compose exec api python test_user_models.py

test-content-models: ## Test Channel, UserSubscription, and ContentItem models (NEW)
	docker compose exec api python test_content_models.py

migrate: ## Run database migrations
	docker compose exec api alembic upgrade head

migration: ## Create a new migration (usage: make migration msg="your message")
	docker compose exec api alembic revision --autogenerate -m "$(msg)"

migration-history: ## Show migration history
	docker compose exec api alembic history

migration-current: ## Show current migration version
	docker compose exec api alembic current

migration-downgrade: ## Rollback last migration
	docker compose exec api alembic downgrade -1

clean: ## Clean up containers, volumes, and cache
	docker compose down -v
	rm -rf __pycache__ .pytest_cache .coverage htmlcov

format: ## Format code with black and isort
	docker compose exec api black app tests
	docker compose exec api isort app tests

lint: ## Run linters
	docker compose exec api flake8 app
	docker compose exec api mypy app

health: ## Check health of all services
	@echo "Checking API health..."
	@curl -s http://localhost:8000/health | python -m json.tool
	@echo "\nChecking PostgreSQL..."
	@docker compose exec postgres pg_isready -U keemu_user
	@echo "\nChecking Redis..."
	@docker compose exec redis redis-cli ping

install: ## Install dependencies locally (for IDE support)
	poetry install

setup: ## Initial setup (copy env file)
	cp env.template .env
	@echo "Please edit .env with your API keys"

dev: ## Start development environment
	poetry run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
