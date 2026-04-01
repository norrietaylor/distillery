# Source: docs/specs/03-spec-promotion-readiness/03-spec-promotion-readiness.md
# Pattern: State + CLI/Process
# Recommended test type: Integration

Feature: README Polish -- Badges and Demo Recording

  Scenario: README displays three shields.io badges in the header section
    Given the Distillery repository README.md has been updated
    When a user opens the README.md on GitHub
    Then a badge row is visible between the nav links and the separator
    And the row contains a PyPI version badge linking to the PyPI page
    And the row contains a License badge linking to the LICENSE file
    And the row contains a Python version badge showing "3.11+"

  Scenario: README includes an embedded demo recording
    Given the Distillery repository README.md has been updated
    And a demo recording asset exists at docs/assets/distillery-demo.gif or .svg
    When a user opens the README.md on GitHub
    Then a demo section appears after "What is Distillery?" and before "Skills"
    And the section contains an embedded image referencing docs/assets/distillery-demo.gif
    And a caption below the image explains what the recording shows

  Scenario: Demo recording asset is a valid viewable file under 2MB
    Given a demo recording has been created using asciinema rec and converted with agg
    When the file at docs/assets/distillery-demo.gif is opened in a browser
    Then the recording plays showing a /distill followed by /recall flow in a terminal session
    And the file size is 2MB or less

  Scenario: .env.example documents all required environment variables
    Given the Distillery repository root is checked
    When a user reads the .env.example file
    Then the file contains a placeholder entry for JINA_API_KEY with a descriptive comment
    And the file contains a placeholder entry for GITHUB_CLIENT_ID with a descriptive comment
    And the file contains a placeholder entry for GITHUB_CLIENT_SECRET with a descriptive comment
    And no entry contains a real credential or API key
