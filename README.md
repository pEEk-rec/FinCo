# Finance Copilot

A personal finance and budgeting copilot designed to help manage financial data safely with a governed tool executor. 
This system ensures accurate money management, tracks budget limits, and maintains a strict append-only audit log for all state changes.

## Installation

1. Clone the repository.
2. Ensure you have Python 3.11+ installed.
3. Create a virtual environment and install dependencies:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows use: .venv\Scripts\activate
   pip install -e .[dev]
   ```

## Running Tests

To run the test suite:
```bash
pytest
```

To run the linter and format checker:
```bash
ruff check
```
