# Source: docs/specs/06-spec-browser-extension/06-spec-browser-extension.md
# Pattern: Web/UI + State
# Recommended test type: Integration + E2E

Feature: Feed Detection, Watch Flow, and Offline Queue

  Scenario: RSS feed detected on page shows badge icon
    Given the extension is active
    And the user navigates to a page containing a link element with rel="alternate" and type="application/rss+xml"
    When the page finishes loading
    Then the extension toolbar icon displays a feed badge indicator
    And the badge shows the number of detected feeds

  Scenario: Atom feed detected on page shows badge icon
    Given the extension is active
    And the user navigates to a page containing a link element with rel="alternate" and type="application/atom+xml"
    When the page finishes loading
    Then the extension toolbar icon displays a feed badge indicator

  Scenario: GitHub repository page detected as watchable source
    Given the extension is active
    And the user navigates to "https://github.com/owner/repo"
    When the page finishes loading
    Then the Watch tab shows the repository as a watchable GitHub source

  Scenario: User subscribes to a detected RSS feed via Watch tab
    Given the extension is connected to a Distillery MCP server
    And the current page has a detected RSS feed with URL "https://example.com/feed.xml" and title "Example Feed"
    When the user opens the popup Watch tab
    And clicks "Watch" next to the detected feed
    Then the extension calls distillery_watch with action "add", the feed URL, source_type "rss", and label "Example Feed"
    And the feed appears in the watched sources list
    And running "/watch list" in Claude Code shows "Example Feed" as a watched source

  Scenario: User manually enters a feed URL to watch
    Given the extension is connected to a Distillery MCP server
    And the popup Watch tab is open
    When the user enters "https://example.com/feed.xml" in the feed URL input
    And selects "RSS" as the source type
    And clicks the add button
    Then the feed is added to the watched sources list

  Scenario: User unwatches a feed source
    Given the extension is connected to a Distillery MCP server
    And the Watch tab shows "Example Feed" in the watched sources list
    When the user clicks "Unwatch" next to "Example Feed"
    Then the feed is removed from the watched sources list
    And running "/watch list" in Claude Code no longer shows "Example Feed"

  Scenario: Watch tab displays currently watched sources from server
    Given the extension is connected to a Distillery MCP server
    And the server has 3 watched feed sources
    When the user opens the popup Watch tab
    Then the Watch tab displays the list of 3 currently watched sources
    And each source shows its label, URL, and an "Unwatch" button

  Scenario: Bookmark operation queued when offline
    Given the extension is not connected to any Distillery server
    And the user is viewing a web page
    When the user saves a bookmark
    Then the bookmark operation is added to the offline queue in extension storage
    And the popup displays a pending count badge showing "1 pending"

  Scenario: Multiple operations queue and display count
    Given the extension is offline
    And 2 operations are already in the offline queue
    When the user saves another bookmark
    Then the offline queue contains 3 operations
    And the popup displays "3 pending" on the queue badge

  Scenario: Queued operations sync when connectivity is restored
    Given the extension has 3 operations in the offline queue
    And the Distillery MCP server becomes reachable
    When the browser fires the online event
    Then the queued operations are replayed in FIFO order
    And successfully replayed operations are removed from the queue
    And the pending count badge updates to reflect remaining items

  Scenario: Failed replay keeps operation in queue with incremented retry count
    Given the extension has 2 operations in the offline queue
    And the Distillery MCP server is reachable but returns a server error for the first operation
    When the queue replay begins
    Then the first operation remains in the queue with an incremented retry count
    And the second operation is replayed successfully and removed from the queue

  Scenario: Offline queue caps at 100 items
    Given the extension is offline
    And the offline queue contains 100 operations
    When the user saves another bookmark
    Then the oldest operation is dropped from the queue
    And the new operation is added to the queue
    And a warning notification is shown to the user

  Scenario: Only network errors are queued, not auth or validation errors
    Given the extension is connected to a remote Distillery server
    When a bookmark save fails with a 401 authentication error
    Then the operation is not added to the offline queue
    And the user is prompted to re-authenticate
