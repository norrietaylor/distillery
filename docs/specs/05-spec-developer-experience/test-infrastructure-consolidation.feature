Feature: Test Infrastructure Consolidation
  As a contributor
  I want shared test fixtures in conftest.py
  So that I don't have to copy-paste helpers when writing new tests

  Scenario: conftest.py provides make_entry factory
    Given tests/conftest.py exists
    When I call make_entry() with no arguments
    Then a valid Entry is returned with default content, type, source, and author

  Scenario: conftest.py provides make_entry with overrides
    Given tests/conftest.py exists
    When I call make_entry(content="custom", entry_type=EntryType.BOOKMARK)
    Then the returned Entry has content "custom" and entry_type BOOKMARK

  Scenario: conftest.py provides parse_mcp_response helper
    Given tests/conftest.py exists
    When I call parse_mcp_response with a valid MCP TextContent list
    Then a parsed dict is returned from the JSON payload

  Scenario: conftest.py provides mock_embedding_provider fixture
    Given tests/conftest.py exists
    When I request the mock_embedding_provider fixture
    Then it returns a hash-based provider with 4 dimensions
    And different texts produce different vectors

  Scenario: conftest.py provides deterministic_embedding_provider fixture
    Given tests/conftest.py exists
    When I request the deterministic_embedding_provider fixture
    Then it supports register(text, vector) for precise control
    And unregistered texts fall back to hash-based vectors

  Scenario: conftest.py provides controlled_embedding_provider fixture
    Given tests/conftest.py exists
    When I request the controlled_embedding_provider fixture
    Then it uses 8 dimensions for precise threshold testing
    And registered vectors are L2-normalized

  Scenario: conftest.py provides async store fixture
    Given tests/conftest.py exists
    When I request the store fixture
    Then it returns an initialized DuckDBStore with in-memory database
    And the store is closed after the test completes

  Scenario: No duplicate _make_entry definitions remain
    When I search for "_make_entry" across all test files
    Then only tests/conftest.py contains the definition

  Scenario: All existing tests pass after consolidation
    When I run `pytest tests/ -v`
    Then all 368+ tests pass
    And no test has changed behavior

  Scenario: conftest.py is compatible with mypy
    When I run `mypy tests/conftest.py`
    Then the exit code is 0
