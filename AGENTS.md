# AGENTS.md - StockTax Development Guide

This file provides guidance for AI agents working on this codebase.

## Project Overview

StockTax is a Python project for calculating stock-related taxes. The project is in early development stages.

## Build, Lint, and Test Commands

### Setup

```bash
pip install -e .     # or poetry install
python -m stocktax   # or python main.py
```

### Testing

```bash
pytest                          # Run all tests
pytest tests/test_file.py       # Run a single test file
pytest tests/test_file.py::test_function_name  # Run a single test function
pytest -k "test_pattern"        # Run tests matching a pattern
pytest -v                       # Run with verbose output
pytest --cov=stocktax           # Run with coverage
```

### Linting and Formatting

```bash
ruff check .     # Lint with ruff
ruff format .    # Format with ruff
mypy stocktax/   # Type check
ruff check . && ruff format . && mypy stocktax/  # All checks
```

## Code Style Guidelines

### Imports

Group imports: stdlib → third-party → local. Sort alphabetically within groups.
Use absolute imports, avoid wildcard imports (`from x import *`).

```python
import os
from datetime import datetime
from typing import Optional

import pandas as pd
from decimal import Decimal

from stocktax import calculations
from stocktax.models import Transaction
```

### Formatting

- 4 spaces for indentation (no tabs)
- Max line length: 100 characters
- Use trailing commas for multi-line collections
- Spaces around operators: `a + b`, not `a+b`
- No spaces inside parentheses: `func(a, b)`

### Types

- Use type hints for all function arguments and return values
- Use `Optional[X]` instead of `X | None` for Python < 3.10
- Use `Decimal` for financial calculations (never `float`)

```python
def calculate_gain(buy_price: Decimal, sell_price: Decimal, quantity: int) -> Decimal:
    ...
```

### Naming

- `snake_case` for functions, variables, methods
- `PascalCase` for classes and exceptions
- `UPPER_SNAKE_CASE` for constants
- Private: prefix with underscore (`_private_method`)

### Error Handling

- Use specific exception types
- Never catch bare `Exception` unless re-raising
- Use context managers for resources
- Provide meaningful error messages

```python
try:
    result = calculate_tax(income)
except ValueError as e:
    logger.error(f"Invalid income value: {income}")
    raise TaxCalculationError(f"Failed to calculate tax: {e}") from e
```

### Testing

- Test files: `tests/test_<module>.py`
- Test functions: `test_<function>_<scenario>`
- Use descriptive assertion messages
- Test edge cases and error conditions

```python
def test_calculate_short_term_gain_with_profit():
    result = calculate_gain(
        buy_price=Decimal("100.00"),
        sell_price=Decimal("150.00"),
        quantity=10
    )
    assert result == Decimal("500.00"), "Expected $500 profit"
```

### Logging

Use `logging` module, not print. Include context in messages.

```python
logger = logging.getLogger(__name__)
logger.info(f"Processing transaction {txn_id}")
logger.error(f"Failed to fetch rates: {e}", exc_info=True)
```

## File Organization

```
stocktax/
├── stocktax/           # Main package
│   ├── __init__.py
│   ├── models/         # Data models
│   ├── calculations/   # Business logic
│   └── utils/          # Utility functions
├── tests/              # Test suite
├── pyproject.toml      # Project configuration
└── README.md
```

## Additional Notes

- Run linters and tests before submitting changes
- Update this file as the project evolves
- Keep dependencies minimal; pin versions in pyproject.toml
