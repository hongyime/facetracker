# Face Search Engine Tests

This directory contains all tests for the face search engine project.

## Test Structure

```
tests/
├── unit/               # Unit tests for individual components
│   ├── test_detector.py    # Face detection tests
│   ├── test_scanner.py     # File discovery tests
│   ├── test_quality.py     # Quality scoring tests
│   ├── test_faiss.py       # FAISS index tests
│   └── test_clustering.py  # Identity clustering tests
├── integration/        # Integration tests for full pipeline
│   └── test_pipeline.py    # End-to-end pipeline tests
└── __init__.py
```

## Running Tests

### Run all tests
```bash
pytest
```

### Run unit tests only
```bash
pytest tests/unit/
```

### Run integration tests only
```bash
pytest tests/integration/
```

### Run specific test file
```bash
pytest tests/unit/test_detector.py
```

### Run with coverage report
```bash
pytest --cov=src --cov-report=html
```

### Run verbose output
```bash
pytest -v
```

## Test Requirements

Install test dependencies:
```bash
pip install pytest pytest-asyncio pytest-cov httpx
```

## Test Categories

- **Unit Tests**: Test individual components in isolation with mocked dependencies
- **Integration Tests**: Test end-to-end pipeline functionality

## Adding New Tests

1. Create test file in appropriate directory (`unit/` or `integration/`)
2. Name file `test_<component>.py`
3. Use `Test<Component>` class naming convention
4. Use `test_<method_name>` function naming convention
5. Add docstrings explaining what each test verifies
