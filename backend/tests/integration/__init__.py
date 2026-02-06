"""
Integration tests package.

Integration tests verify that multiple components work together correctly.
They require:
- Real database connection
- Real Redis connection
- Real external services (or mocked API calls)

To run integration tests:
    pytest tests/integration/ -v --run-integration

To skip integration tests (default):
    pytest tests/ -v
"""

