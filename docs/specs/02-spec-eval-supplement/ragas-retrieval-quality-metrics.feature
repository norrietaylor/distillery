# Source: docs/specs/02-spec-eval-supplement/02-spec-eval-supplement.md
# Pattern: CLI/Process + State
# Recommended test type: Integration

Feature: RAGAS Retrieval Quality Metrics

  Scenario: RAGAS dependency group installs successfully
    Given the Distillery repository is checked out
    When the user runs "pip install -e '.[ragas]'"
    Then the command exits with code 0
    And the ragas package is importable in Python

  Scenario: Retrieval scorer computes precision recall and MRR from search results
    Given a golden dataset with 5 retrieval scenarios and binary relevance labels
    And a set of search results from the recall skill
    When the retrieval scorer processes the results against the golden labels
    Then the output includes precision_at_k, recall_at_k, and mrr values
    And all metric values are between 0.0 and 1.0

  Scenario: Retrieval metrics appear in eval CLI output
    Given the ragas extras are installed
    And the golden retrieval dataset exists at tests/eval/golden/retrieval.yaml
    When the user runs "distillery eval --skill recall"
    Then stdout displays retrieval metrics including MRR and precision
    And each retrieval scenario shows its individual metric scores

  Scenario: Retrieval scenario fails when MRR falls below threshold
    Given a retrieval scenario where search results return irrelevant entries first
    And the golden dataset expects MRR >= 0.7
    When the retrieval scorer evaluates the results
    Then the scenario is marked as FAIL
    And failure_reasons includes the specific metric that fell below threshold
    And the actual MRR value is displayed in the failure output

  Scenario: Retrieval scenario fails when precision at 5 falls below threshold
    Given a retrieval scenario where 4 of 5 top results are irrelevant
    And the golden dataset expects precision_at_5 >= 0.6
    When the retrieval scorer evaluates the results
    Then the scenario is marked as FAIL
    And failure_reasons includes "precision@5" with the actual value

  Scenario: Eval output includes retrieval metrics in ScenarioResult
    Given the eval runner has completed a recall scenario with retrieval scoring
    When the scenario result is serialized to JSON
    Then the JSON contains a retrieval_metrics object
    And retrieval_metrics includes precision, recall, mrr, and faithfulness fields

  Scenario: Retrieval scorer works without RAGAS installed by using fallback
    Given the ragas package is not installed
    And the retrieval scorer module is imported
    When the scorer attempts to compute faithfulness
    Then faithfulness is returned as null
    And precision, recall, and mrr are still computed using built-in logic

  Scenario: Nightly eval workflow includes retrieval quality scenarios
    Given the nightly eval workflow installs the ragas extras
    When the nightly eval suite runs
    Then retrieval quality scenarios from the golden dataset are included
    And retrieval metrics are reported in the nightly output
