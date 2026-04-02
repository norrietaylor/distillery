Feature: Deployment + Scheduling + Setup Skill Update
  As a Distillery operator
  I want automated scheduling via GitHub Actions and updated onboarding guidance
  So that webhook-based operations run on schedule and new users are guided correctly

  # --- Fly.io Deploy Config ---

  Scenario: Fly deploy config includes webhooks section
    Given the file "deploy/fly/distillery-fly.yaml"
    Then the YAML contains a "webhooks" section under "server"
    And "server.webhooks.enabled" is true
    And "server.webhooks.secret_env" is "DISTILLERY_WEBHOOK_SECRET"

  # --- GitHub Actions Scheduler Workflow ---

  Scenario: Scheduler workflow defines three cron triggers
    Given the file ".github/workflows/scheduler.yml"
    Then it defines a cron schedule "23 * * * *" for hourly poll
    And it defines a cron schedule "17 6 * * *" for daily rescore
    And it defines a cron schedule "41 7 * * 1" for weekly maintenance

  Scenario: Scheduler workflow supports manual dispatch
    Given the file ".github/workflows/scheduler.yml"
    Then it includes a "workflow_dispatch" trigger
    And the dispatch has an "operation" input with choices:
      | choice      |
      | poll        |
      | rescore     |
      | maintenance |
      | all         |

  Scenario: Each cron job calls the correct webhook endpoint
    Given the file ".github/workflows/scheduler.yml"
    Then the poll job runs:
      """
      curl -sf -X POST -H "Authorization: Bearer $SECRET" $URL/api/poll
      """
    And the rescore job runs:
      """
      curl -sf -X POST -H "Authorization: Bearer $SECRET" $URL/api/rescore
      """
    And the maintenance job runs:
      """
      curl -sf -X POST -H "Authorization: Bearer $SECRET" $URL/api/maintenance
      """

  Scenario: Workflow uses GitHub secrets and variables for credentials
    Given the file ".github/workflows/scheduler.yml"
    Then the secret is referenced as "${{ secrets.DISTILLERY_WEBHOOK_SECRET }}"
    And the URL is referenced as "${{ vars.DISTILLERY_URL }}"

  Scenario: Each job has a 5-minute timeout
    Given the file ".github/workflows/scheduler.yml"
    Then every job specifies "timeout-minutes: 5"

  Scenario: Workflow reports JSON response in job summary
    Given the file ".github/workflows/scheduler.yml"
    Then each job writes the curl response body to "$GITHUB_STEP_SUMMARY"

  # --- Setup Skill Update ---

  Scenario: Setup skill contains no RemoteTrigger references
    Given the file ".claude-plugin/skills/setup/SKILL.md"
    Then the file does not contain the string "RemoteTrigger"
    And the file does not contain the string "connector_uuid"

  Scenario: Setup skill skips cron setup for hosted/team transport
    Given the file ".claude-plugin/skills/setup/SKILL.md"
    Then for hosted or team transport the skill displays a note that scheduling is handled by GitHub Actions
    And the skill does not create CronCreate jobs for hosted or team transport

  Scenario: Setup skill creates CronCreate jobs for local transport only
    Given the file ".claude-plugin/skills/setup/SKILL.md"
    Then the file contains "CronCreate" for local transport users
    And CronCreate is only invoked when transport is detected as local

  # --- Linting and Formatting ---

  Scenario: All source and test files pass ruff check
    When I run "ruff check src/ tests/"
    Then the exit code is 0
    And there are no lint errors

  Scenario: All source and test files pass ruff format check
    When I run "ruff format --check src/ tests/"
    Then the exit code is 0
    And there are no formatting differences
