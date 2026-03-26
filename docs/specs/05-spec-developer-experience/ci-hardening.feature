Feature: CI Hardening
  As a maintainer
  I want CI to test multiple Python versions with coverage enforcement
  So that regressions are caught early across all supported versions

  Scenario: CI tests Python 3.11, 3.12, and 3.13
    Given the CI workflow at .github/workflows/ci.yml
    Then it uses a matrix strategy with python-version ["3.11", "3.12", "3.13"]
    And each version runs lint, type check, and tests

  Scenario: CI caches pip dependencies
    Given the CI workflow at .github/workflows/ci.yml
    Then the setup-python step includes cache: 'pip'

  Scenario: CI enforces 80% coverage threshold
    Given the CI workflow at .github/workflows/ci.yml
    Then the pytest step includes --cov=src
    And the pytest step includes --cov-fail-under=80
    And the pytest step includes --cov-report=term-missing

  Scenario: CI uploads coverage artifact
    Given the CI workflow at .github/workflows/ci.yml
    Then a step uploads the coverage report as a GitHub Actions artifact

  Scenario: Coverage flags are not in pyproject.toml addopts
    Given the pytest configuration in pyproject.toml
    Then addopts does not contain --cov
    And addopts does not contain --cov-fail-under

  Scenario: Unit marker filters unit tests
    When I run `pytest tests/ -m unit`
    Then only tests marked with @pytest.mark.unit are collected
    And integration tests are excluded

  Scenario: Integration marker filters integration tests
    When I run `pytest tests/ -m integration`
    Then only tests marked with @pytest.mark.integration are collected
    And unit tests are excluded

  Scenario: All tests pass on Python 3.12
    Given Python 3.12 is installed
    When I run `pytest tests/ -v`
    Then all tests pass

  Scenario: All tests pass on Python 3.13
    Given Python 3.13 is installed
    When I run `pytest tests/ -v`
    Then all tests pass
