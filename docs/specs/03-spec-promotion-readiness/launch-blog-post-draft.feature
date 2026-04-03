# Source: docs/specs/03-spec-promotion-readiness/03-spec-promotion-readiness.md
# Pattern: CLI/Process + State
# Recommended test type: Integration

Feature: Launch Blog Post Draft

  Scenario: Blog post file exists at the expected path
    Given the docs/blog/ directory has been created
    When a user checks for the blog post
    Then the file docs/blog/building-a-second-brain-for-claude-code.md exists

  Scenario: Blog post meets the minimum word count
    Given the blog post file exists at docs/blog/building-a-second-brain-for-claude-code.md
    When the user runs "wc -w docs/blog/building-a-second-brain-for-claude-code.md"
    Then the word count is 1500 or greater
    And the word count is 2500 or fewer

  Scenario: Blog post contains dev.to-compatible YAML frontmatter
    Given the blog post file exists at docs/blog/building-a-second-brain-for-claude-code.md
    When a user reads the beginning of the file
    Then the file starts with a YAML frontmatter block delimited by triple dashes
    And the frontmatter contains a title field
    And the frontmatter contains a published field
    And the frontmatter contains a description field
    And the frontmatter contains a tags field
    And the frontmatter contains a canonical_url field

  Scenario: Blog post covers all required sections
    Given the blog post file exists at docs/blog/building-a-second-brain-for-claude-code.md
    When a user reads the full post
    Then the post contains a section about the problem of lost knowledge
    And the post contains a section about capturing knowledge inside the coding assistant
    And the post contains a section describing what Distillery does including skills and semantic search
    And the post contains a section about the four-layer architecture and MCP
    And the post contains a section about team access with GitHub OAuth
    And the post contains a demo flow walking through distill then recall then pour
    And the post contains a section about the roadmap
    And the post contains installation instructions

  Scenario: Blog post uses appropriate tone for developer audiences
    Given the blog post file exists at docs/blog/building-a-second-brain-for-claude-code.md
    When a user reads the post
    Then the writing style is personal and first-person
    And the tone is technical but accessible rather than academic
    And code examples are included inline where relevant
    And no real API keys or tokens appear in code examples

  Scenario: Drafts directory exists for the promotion pipeline
    Given the repository root is checked
    When a user lists the docs/drafts/ directory
    Then the directory exists and is accessible
