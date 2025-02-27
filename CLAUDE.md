# RSVP Site Development Guide

## Commands
- Run app locally: `python3 app.py`
- Run all tests: `python3 -m pytest -v`
- Run specific test: `python3 -m pytest -v event_config_test.py::test_function_name`
- Run tests with coverage: `python3 -m pytest --cov=. --cov-report=term`
- Activate virtual environment: `source venv/bin/activate`

## Code Style Guidelines
- Import order: standard library → third-party → local modules
- Naming: snake_case for functions/variables, PascalCase for classes
- Tests: name files `*_test.py` and test functions `test_*`
- Docstrings: use for all functions, particularly tests
- Error handling: use try/except with specific exceptions
- Patterns: flask route functions, singleton for config
- Templates: Jinja2 in /templates, static assets in /static

## Project Structure
- Flask app routes in app.py
- Configuration management in event_config.py
- Email handling in email_handler.py
- Event slug generation in event_slug.py
- Tests with fixtures in conftest.py
- Template styling via static/invitation.css