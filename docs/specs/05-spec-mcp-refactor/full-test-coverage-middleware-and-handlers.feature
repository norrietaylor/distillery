# Source: docs/specs/05-spec-mcp-refactor/05-spec-mcp-refactor.md
# Pattern: API
# Recommended test type: Unit

Feature: Full Test Coverage - Middleware and All Handlers

  # RateLimitMiddleware scenarios

  Scenario: Rate limiter allows requests within per-minute limit
    Given the RateLimitMiddleware is configured with 60 requests per minute
    And a client IP has made 10 requests in the current minute
    When the client sends another request
    Then the request passes through to the application
    And the response includes rate limit headers showing remaining quota

  Scenario: Rate limiter rejects requests exceeding per-minute limit
    Given the RateLimitMiddleware is configured with 60 requests per minute
    And a client IP has made 60 requests in the current minute
    When the client sends another request
    Then the response status is 429
    And the response includes a Retry-After header with a positive value

  Scenario: Rate limiter rejects requests exceeding per-hour limit
    Given the RateLimitMiddleware is configured with 1000 requests per hour
    And a client IP has made 1000 requests in the current hour
    When the client sends another request
    Then the response status is 429

  Scenario: Rate limiter sliding window expires old request counts
    Given a client IP made 60 requests one minute ago
    And no requests have been made in the current minute window
    When the client sends a new request
    Then the request passes through to the application
    And the per-minute counter reflects only the new request

  Scenario: Rate limiter tracks requests per IP independently
    Given client IP 10.0.0.1 has made 60 requests in the current minute
    And client IP 10.0.0.2 has made 5 requests in the current minute
    When client IP 10.0.0.2 sends another request
    Then the request from 10.0.0.2 passes through to the application

  # BodySizeLimitMiddleware scenarios

  Scenario: Body size middleware allows requests within size limit
    Given the BodySizeLimitMiddleware is configured with a 1MB limit
    When a client sends a request with a 500KB body
    Then the request passes through to the application

  Scenario: Body size middleware rejects oversized requests
    Given the BodySizeLimitMiddleware is configured with a 1MB limit
    When a client sends a request with a 2MB body
    Then the response status is 413
    And the response body indicates the request is too large

  Scenario: Body size middleware handles exact boundary size
    Given the BodySizeLimitMiddleware is configured with a 1MB limit
    When a client sends a request with exactly a 1MB body
    Then the request passes through to the application

  # OrgMembershipMiddleware scenarios

  Scenario: Org membership middleware allows valid org member
    Given the OrgMembershipMiddleware is configured for org "myorg"
    And the GitHub API confirms the token holder is a member of "myorg"
    When the client sends a request with a valid Authorization header
    Then the request passes through to the application

  Scenario: Org membership middleware rejects non-member
    Given the OrgMembershipMiddleware is configured for org "myorg"
    And the GitHub API confirms the token holder is NOT a member of "myorg"
    When the client sends a request with a valid Authorization header
    Then the response status is 403
    And the response body indicates the user is not an org member

  Scenario: Org membership middleware rejects missing auth header
    Given the OrgMembershipMiddleware is configured for org "myorg"
    When the client sends a request without an Authorization header
    Then the response status is 403
    And the response body indicates authentication is required

  Scenario: Org membership middleware handles GitHub API errors gracefully
    Given the OrgMembershipMiddleware is configured for org "myorg"
    And the GitHub API returns a 500 error
    When the client sends a request with a valid Authorization header
    Then the response status is 403
    And no internal error details are exposed in the response

  Scenario: Org membership middleware caches successful membership checks
    Given the OrgMembershipMiddleware is configured for org "myorg"
    And the GitHub API confirms the token holder is a member
    When the client sends two requests with the same Authorization header
    Then both requests pass through to the application
    And the GitHub API is called only once for that token

  # Handler test coverage scenarios

  Scenario: Aggregate handler returns grouped results for valid input
    Given the MCP server is running with a store containing 10 tagged entries
    When a client invokes the "distillery_aggregate" tool with group_by "entry_type"
    Then the response contains entry counts grouped by type

  Scenario: Aggregate handler rejects invalid group_by field
    Given the MCP server is running
    When a client invokes the "distillery_aggregate" tool with group_by "nonexistent_field"
    Then the response contains an error indicating the field is not valid for grouping

  Scenario: Tag tree handler returns hierarchical tag structure
    Given the MCP server is running with entries tagged "python/asyncio" and "python/typing"
    When a client invokes the "distillery_tag_tree" tool
    Then the response contains a tree with "python" as parent and "asyncio" and "typing" as children

  Scenario: Type schemas handler returns schema for each entry type
    Given the MCP server is running
    When a client invokes the "distillery_type_schemas" tool
    Then the response contains metadata schema definitions for each known entry type

  Scenario: Metrics handler returns system statistics
    Given the MCP server is running with a store containing entries
    When a client invokes the "distillery_metrics" tool
    Then the response contains total entry count and entries by status

  Scenario: Quality handler returns data quality assessment
    Given the MCP server is running with entries of varying completeness
    When a client invokes the "distillery_quality" tool
    Then the response contains quality scores reflecting entry completeness

  Scenario: Stale handler identifies entries older than threshold
    Given the MCP server is running with an entry last modified 45 days ago
    And the configured stale_days threshold is 30
    When a client invokes the "distillery_stale" tool
    Then the response lists the 45-day-old entry as stale

  Scenario: Interests handler returns user interest profile
    Given the MCP server is running with entries across multiple topics
    When a client invokes the "distillery_interests" tool
    Then the response contains topic areas derived from stored entries

  Scenario: Watch handler registers a new feed source
    Given the MCP server is running
    When a client invokes the "distillery_watch" tool with type "rss" and URL "https://example.com/feed.xml"
    Then the feed source is registered in the store
    And the response confirms the subscription

  Scenario: Poll handler fetches new items from registered feeds
    Given the MCP server is running with a registered RSS feed source
    And the feed has new items since the last poll
    When a client invokes the "distillery_poll" tool
    Then new entries are created from the feed items
    And the response reports the number of new entries

  Scenario: Suggest sources handler recommends feeds based on interests
    Given the MCP server is running with entries about "distributed systems"
    When a client invokes the "distillery_suggest_sources" tool
    Then the response contains suggested feed URLs relevant to distributed systems

  Scenario: Check conflicts handler detects contradictory entries
    Given the MCP server is running with two entries containing conflicting information
    When a client invokes the "distillery_check_conflicts" tool
    Then the response identifies the conflicting entry pair
    And the response describes the nature of the conflict

  Scenario: Test suite achieves 95% coverage on mcp package
    Given all new test files are in place for middleware and handlers
    When pytest is run with coverage measurement on the mcp package
    Then the coverage report shows at least 95% line coverage for src/distillery/mcp/
