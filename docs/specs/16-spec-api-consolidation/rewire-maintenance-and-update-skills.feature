# Source: docs/specs/16-spec-api-consolidation/16-spec-api-consolidation.md
# Pattern: API + State
# Recommended test type: Integration

Feature: Rewire Maintenance Orchestrator and Update Skills

  Scenario: Maintenance endpoint runs poll then rescore then classify-batch in sequence
    Given the MCP server is running in HTTP mode with a valid bearer token
    And feed sources and inbox entries exist in the store
    When a POST request is sent to /api/maintenance with the bearer token
    Then poll executes first and its results are included in the response
    And rescore executes second and its results are included in the response
    And classify-batch executes third and its results are included in the response

  Scenario: Maintenance endpoint returns combined results from all sub-operations
    Given the MCP server is running in HTTP mode with a valid bearer token
    When a POST request is sent to /api/maintenance with the bearer token
    Then the response body contains separate sections for poll, rescore, and classify-batch results
    And each section contains the same structure as its standalone webhook response

  Scenario: Briefing skill uses list with stale_days instead of stale tool
    Given the MCP server is running with entries that are 30+ days stale
    When the briefing skill requests stale entries
    Then it calls the list tool with stale_days parameter
    And receives the same entries that the former stale tool would have returned

  Scenario: Briefing skill uses list with group_by instead of aggregate tool
    Given the MCP server is running with entries of various statuses
    When the briefing skill requests entry distribution by status
    Then it calls the list tool with group_by="status"
    And receives grouped counts in the standard group_by response format

  Scenario: Pour skill uses list with group_by tags instead of tag_tree tool
    Given the MCP server is running with entries that have hierarchical tags
    When the pour skill requests tag browsing
    Then it calls the list tool with group_by="tags"
    And receives tag counts that replicate the former tag_tree output

  Scenario: Digest skill uses list with output stats instead of metrics tool
    Given the MCP server is running with entries in the store
    When the digest skill requests system metrics
    Then it calls the list tool with output="stats"
    And receives entries_by_type, entries_by_status, total_entries, and storage_bytes

  Scenario: Radar skill does not reference the interests tool
    Given the radar skill definition is loaded
    When the skill executes its feed suggestion workflow
    Then it does not call any tool named "interests"
    And interest profile computation is handled internally by the poll pipeline

  Scenario: Setup skill generates correct webhook URLs for new endpoints
    Given the setup skill is configuring scheduled tasks
    When it generates webhook URLs for the maintenance pipeline
    Then the URLs include /hooks/poll, /hooks/rescore, and /hooks/classify-batch

  Scenario: All skill definitions reference only the active tools
    Given all skill SKILL.md files are loaded
    When the tools listed in each skill frontmatter are collected
    Then no skill references removed tool names
    And every referenced tool exists in the current MCP surface
