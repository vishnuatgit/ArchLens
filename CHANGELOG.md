# Changelog

All notable changes to the ArchLens project will be documented in this file.

## [1.0.0] - 2026-07-25

### Added
- **Command Line Interface (CLI):** Introduced the `archlens` global executable CLI tool using Typer and Rich console formatting.
- **Glassmorphic Hero Section:** Rebuilt the landing page layout to support a two-column glassmorphic hero design with modern animations.
- **Security & Privacy Policy:** Added a dedicated section detailing how the platform interacts safely with GitHub via read-only APIs without cloning code.
- **CI/CD Integration:** Created GitHub Actions workflow for automated testing and code quality checks.
- **Git Hooks:** Configured `pre-commit` configuration for automated formatting and checking.

### Fixed
- **Redirect Bug:** Fixed `301 Moved Permanently` exception raised by `httpx` during API requests to renamed GitHub repositories.
- **Light/Dark Mode Theme Toggle:** Fixed theme toggle and ensured support for light mode across all pages.
- **Layout Bugs:** Fixed footer overlapping issues on the results and history pages.
