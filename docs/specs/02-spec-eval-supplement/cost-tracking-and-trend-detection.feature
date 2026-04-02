# Source: docs/specs/02-spec-eval-supplement/02-spec-eval-supplement.md
# Pattern: CLI/Process + State
# Recommended test type: Integration

Feature: Cost Tracking and Trend Detection

  Scenario: Baseline JSON includes per-scenario token and cost data
    Given the eval suite has been run with cost tracking enabled
    When the user runs "distillery eval --save-baseline baseline.json"
    Then baseline.json is created
    And each scenario entry in the JSON contains input_tokens, output_tokens, total_tokens, and total_cost_usd fields

  Scenario: Baseline JSON includes top-level cost summary
    Given the eval suite has been run with cost tracking enabled
    When the user runs "distillery eval --save-baseline baseline.json"
    Then baseline.json contains a top-level cost_summary object
    And cost_summary includes total_cost_usd and total_tokens fields
    And cost_summary includes a per_skill breakdown

  Scenario: Per-skill cost breakdown contains correct fields
    Given a baseline JSON has been saved with multiple skills evaluated
    When the user inspects the cost_summary.per_skill section
    Then each skill entry contains cost_usd, tokens, and scenario_count fields
    And the sum of per-skill tokens equals total_tokens

  Scenario: Cost comparison reports total cost delta
    Given a previous baseline exists at baseline.json with known cost data
    When the user runs "distillery eval --baseline baseline.json --compare-cost"
    Then the output includes total cost delta as an absolute value
    And the output includes total cost delta as a percentage

  Scenario: Cost comparison reports per-skill cost deltas
    Given a previous baseline exists at baseline.json
    And the current run has different per-skill costs
    When the user runs "distillery eval --baseline baseline.json --compare-cost"
    Then the output includes a per-skill cost delta table
    And each skill shows its cost change from the baseline

  Scenario: Skills with more than 20 percent cost increase are flagged as warnings
    Given a previous baseline where skill "recall" had a cost of 0.10 USD
    And the current run shows skill "recall" cost at 0.15 USD (50 percent increase)
    When the user runs "distillery eval --baseline baseline.json --compare-cost"
    Then the output flags "recall" with a cost regression warning
    And the warning includes the percentage increase

  Scenario: Cost comparison with missing baseline cost data degrades gracefully
    Given a baseline JSON from an older version without cost_summary
    When the user runs "distillery eval --baseline baseline.json --compare-cost"
    Then the output indicates no cost baseline is available for comparison
    And the command does not crash or produce an error

  Scenario: Cost comparison output appends after pass-fail summary in text mode
    Given a baseline exists and cost comparison is enabled
    When the user runs "distillery eval --baseline baseline.json --compare-cost"
    Then the pass/fail summary appears first in stdout
    And the cost comparison section appears after the summary

  Scenario: Cost comparison output includes cost_comparison key in JSON mode
    Given a baseline exists and cost comparison is enabled
    When the user runs "distillery eval --baseline baseline.json --compare-cost --format json"
    Then the JSON output includes a cost_comparison key
    And cost_comparison contains total_delta and per_skill_deltas

  Scenario: Nightly CI persists cost data in uploaded artifact
    Given the nightly eval workflow uses --save-baseline
    When the nightly eval run completes
    Then the uploaded artifact contains a baseline JSON with cost_summary
    And cost data is available for historical trend comparison
