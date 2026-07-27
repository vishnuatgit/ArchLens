# Contributing to ArchLens

Thank you for your interest in contributing to ArchLens! I welcome all contributions, including bug fixes, new features, documentation improvements, and bug reports.

## Getting Started

1. **Fork the Repository:** Fork the ArchLens repository to your own GitHub account.
2. **Clone the Repository:** Clone your fork to your local machine:
   ```bash
   git clone https://github.com/YOUR_USERNAME/ArchLens.git
   cd ArchLens
   ```
3. **Set Up Development Environment:**
   I recommend creating a virtual environment and installing dev dependencies:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   pip install -e ".[dev]"
   ```
4. **Install Pre-commit Hooks:**
   I use pre-commit to automatically check formatting and linting rules:
   ```bash
   pre-commit install
   ```

## Development Flow

- **Code Formatting:** I use `black` for formatting and `ruff` for linting. They run automatically on commit. You can also run them manually:
  ```bash
  black app tests
  ruff check app tests
  ```
- **Testing:** Ensure all tests pass before submitting a pull request:
  ```bash
  pytest --cov=app tests/
  ```

## Submitting Pull Requests

1. Create a new branch for your feature or bugfix:
   ```bash
   git checkout -b feature/my-amazing-feature
   ```
2. Commit your changes. Ensure the pre-commit checks pass successfully.
3. Push to your branch and open a Pull Request against the `main` branch.
4. Describe your changes clearly in the PR description.
