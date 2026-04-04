# Source: docs/specs/06-spec-browser-extension/06-spec-browser-extension.md
# Pattern: Web/UI
# Recommended test type: E2E

Feature: Bookmark Flow with Readability.js Content Extraction

  Scenario: Popup pre-fills bookmark form with extracted page metadata
    Given the extension is connected to a Distillery MCP server
    And the user is viewing a web page with title "Example Article" and a meta description "An example article about testing"
    When the user opens the extension popup
    Then the Bookmark tab displays the page title "Example Article" in an editable field
    And the URL field shows the current page URL as read-only
    And the description field is pre-filled with "An example article about testing"

  Scenario: Popup pre-fills default tags and project from options
    Given the extension options have default tags set to "reading,research"
    And the extension options have default project set to "my-project"
    When the user opens the extension popup on any page
    Then the tag input field is pre-filled with "reading,research"
    And the project dropdown shows "my-project" selected

  Scenario: User saves a bookmark with extracted article content
    Given the extension is connected to a Distillery MCP server
    And the user is viewing an article page with substantial body text
    When the user opens the popup and clicks "Save"
    Then the extension sends a distillery_store call with entry_type "bookmark"
    And the content includes the Readability-extracted article text
    And the source is set to "browser-extension"
    And searching for the article title in Distillery returns the stored entry

  Scenario: Bookmark content is truncated when exceeding 5000 characters
    Given the user is viewing a very long article exceeding 5000 characters
    When the user saves the page as a bookmark
    Then the stored content is truncated to 5000 characters maximum
    And the stored entry is retrievable via Distillery search

  Scenario: User edits title and description before saving bookmark
    Given the extension popup is showing the Bookmark tab with pre-filled metadata
    When the user changes the title to "Custom Title"
    And changes the description to "My custom description"
    And clicks "Save"
    Then the stored entry has the title "Custom Title"
    And the stored entry description contains "My custom description"

  Scenario: Context menu bookmark saves without opening popup
    Given the extension is connected to a Distillery MCP server
    And the user is viewing a web page
    When the user right-clicks and selects "Save to Distillery"
    Then the page is saved as a bookmark entry without the popup appearing
    And a brief success notification appears on the toolbar icon
    And searching for the page title in Distillery returns the stored entry

  Scenario: Selected text is used as bookmark content instead of Readability extraction
    Given the user has selected the text "This is my selected passage" on a web page
    When the user saves the page as a bookmark
    Then the stored bookmark content contains "This is my selected passage"
    And the Readability-extracted full article text is not used

  Scenario: Success notification appears after saving a bookmark
    Given the extension is connected to a Distillery MCP server
    When the user saves a bookmark successfully
    Then a check mark badge appears on the toolbar icon
    And the badge disappears after approximately 2 seconds

  Scenario: Content script extracts Open Graph metadata
    Given the user is viewing a page with Open Graph tags including og:title "OG Title" and og:description "OG Description"
    And the page has no standard meta description
    When the user opens the extension popup
    Then the description field is pre-filled with "OG Description"
