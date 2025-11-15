# Dependency Manager

A modern, high-performance CLI tool for checking the health and maintenance status of Python packages.

## Features

- 🚀 **Fast & Async**: Uses `httpx` with async/await for parallel API calls
- 📊 **Rich Output**: Beautiful terminal output with tables and panels
- 🩺 **Health Checks**: Analyzes PyPI and GitHub data to assess package health
- 🎯 **Simple CLI**: Built with Typer for an intuitive command-line experience

## Installation

```bash
pip install -r requirements.txt
```

## Usage

Check the health of any Python package:

```bash
python -m dep_manager.main health <package-name>
```

### Example

```bash
python -m dep_manager.main health requests
```

This will display:
- Latest version and release date
- Package license and description
- GitHub repository stats (stars, issues, last commit)
- Overall health recommendation

## Project Structure

```
dep-manager/
├── dep_manager/
│   ├── __init__.py      # Package initialization
│   ├── main.py          # CLI commands and Typer app
│   ├── health.py        # Health check logic
│   ├── services.py      # API clients (PyPI, GitHub)
│   └── models.py        # Pydantic data models
├── requirements.txt     # Project dependencies
└── README.md           # This file
```

## Development

The project follows modern Python best practices:

- **Async/Await**: All API calls are asynchronous for maximum performance
- **Type Safety**: Uses Pydantic models for data validation
- **Modular Design**: Clear separation of concerns across modules
- **Error Handling**: Graceful handling of API failures and edge cases

## Requirements

- Python 3.8+
- typer
- rich
- httpx
- pydantic
- packaging

## License

MIT
