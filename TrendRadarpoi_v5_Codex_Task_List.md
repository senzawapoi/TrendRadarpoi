# TrendRadarpoi v5.0 Codex Task List

## Engineering Issue Breakdown

**Version:** v1.0

Purpose:

This document converts the TrendRadarpoi v5.0 Implementation Plan into
executable engineering tasks for Codex.

Each task should be completed independently where possible.

------------------------------------------------------------------------

# Phase 0 - Project Baseline Stabilization

## TASK-001: Repository Architecture Review

### Goal

Understand current project structure before modifications.

### Actions

Analyze:

-   trendradar/
-   config/
-   services/
-   storage/
-   notification/
-   ai modules

### Deliverables

Create:

    docs/code-review.md

Containing:

-   Current architecture diagram
-   Dependency overview
-   High coupling modules
-   Refactoring recommendations

### Acceptance Criteria

-   No code changes required.
-   Current runtime behavior remains unchanged.

------------------------------------------------------------------------

## TASK-002: Configuration System Audit

### Goal

Unify configuration management.

### Actions

Identify:

-   Hardcoded configuration
-   Environment variables
-   YAML configuration
-   Secrets

### Deliverables

Create:

    config/settings.py
    .env.example

### Acceptance Criteria

-   No secrets exist in repository.
-   Local and VPS configuration use the same pattern.

------------------------------------------------------------------------

# Phase 1 - Unified Intelligence Data Layer

------------------------------------------------------------------------

# TASK-101: Create ContentItem Model

### Goal

Create a common information object.

### Files

Create:

    trendradar/core/models/content.py

### Implementation

Create:

``` python
ContentItem
```

Fields:

    id
    title
    content
    url
    source
    domain
    published_time
    tags
    metadata

### Acceptance Criteria

-   Model can represent existing crawler outputs.
-   Unit tests added.

------------------------------------------------------------------------

# TASK-102: Create Source Adapter Interface

### Goal

Separate data collection from business logic.

### Files

Create:

    trendradar/sources/base.py

### Interface

``` python
class SourceAdapter:

    fetch()

    normalize()

    health_check()
```

### Acceptance Criteria

-   Existing sources can migrate gradually.
-   Core pipeline does not depend on specific crawler implementation.

------------------------------------------------------------------------

# TASK-103: Migrate Existing Sources

### Goal

Convert existing collectors into adapters.

### Migration Order

1.  Existing news sources
2.  RSS sources
3.  GitHub sources
4.  Other sources

### Acceptance Criteria

-   Existing daily reports still work.
-   All new data enters through ContentItem.

------------------------------------------------------------------------

# TASK-104: Implement Deduplication Pipeline

### Goal

Reduce repeated information.

### Files

Create:

    pipeline/deduplicate.py

### Version 1 Methods

-   URL hash
-   Canonical URL
-   Title similarity
-   Time window

### Do Not Implement

-   Vector database
-   Complex ML clustering

### Acceptance Criteria

Duplicate content is reduced before AI processing.

------------------------------------------------------------------------

# Phase 2 - Story Intelligence

------------------------------------------------------------------------

# TASK-201: Implement Cluster Engine

### Goal

Group related information items.

### Files

Create:

    pipeline/clustering.py

### Input

ContentItem list

### Output

Cluster objects

### Signals

-   Time proximity
-   Keyword similarity
-   Entity matching

------------------------------------------------------------------------

# TASK-202: Create Story Model

### Goal

Represent meaningful events.

### Files

Create:

    core/models/story.py

### Model

    Story

    id
    title
    summary
    items
    importance
    tags

------------------------------------------------------------------------

# TASK-203: Implement Story Generator

### Goal

Convert clusters into human-readable intelligence.

### Files

Create:

    ai/story_generator.py

### Flow

    Cluster

    ↓

    Gemini

    ↓

    Story

### Acceptance Criteria

Daily reports use Story instead of raw articles.

------------------------------------------------------------------------

# TASK-204: Implement Importance Ranking

### Goal

Rank information importance.

### Ranking Factors

-   Source count
-   Source reliability
-   Growth speed
-   User interests

### Acceptance Criteria

Top stories are prioritized.

------------------------------------------------------------------------

# Phase 3 - Security Intelligence Domain

------------------------------------------------------------------------

# TASK-301: Create Security Domain Module

### Goal

Integrate cybersecurity-daily capabilities.

### Files

Create:

    domains/security/

Structure:

    collector.py
    analyzer.py
    report.py

------------------------------------------------------------------------

# TASK-302: Security Source Integration

### Features

Support:

-   CVE information
-   Vulnerability news
-   Security events

### Acceptance Criteria

Security data enters normal ContentItem pipeline.

------------------------------------------------------------------------

# Phase 4 - Gemini Intelligence Layer

------------------------------------------------------------------------

# TASK-401: Create Gemini Client Abstraction

### Files

Create:

    ai/client.py

### Interface

``` python
chat()

summary()

analyze()
```

------------------------------------------------------------------------

# TASK-402: Build Assistant Service

### Files

Create:

    ai/assistant.py

### Responsibilities

-   Conversation handling
-   Context loading
-   Tool selection

------------------------------------------------------------------------

# Phase 5 - Feishu Assistant

------------------------------------------------------------------------

# TASK-501: Create Feishu Integration Module

### Files

Create:

    integrations/feishu/

Structure:

    client.py
    handler.py
    session.py

------------------------------------------------------------------------

# TASK-502: Implement WebSocket Bot

### Goal

Use Feishu SDK long connection mode.

### Features

-   Receive messages
-   Send replies
-   Push daily reports

------------------------------------------------------------------------

# TASK-503: Add User Access Control

### Requirements

Only approved users can interact.

Implement:

    allowed_users

------------------------------------------------------------------------

# Phase 6 - Agent-Reach Integration

------------------------------------------------------------------------

# TASK-601: Create Research Gateway

### Files

Create:

    integrations/agent_reach/

### Purpose

Provide controlled external research ability.

------------------------------------------------------------------------

# TASK-602: Implement Research Adapter

### Interface

``` python
research()

search()

fetch()
```

### Requirements

-   Timeout handling
-   Error isolation
-   Logging

------------------------------------------------------------------------

# Phase 7 - Deployment

------------------------------------------------------------------------

# TASK-701: Create VPS Runtime Services

### Services

Create:

    trendradar-bot
    trendradar-worker

Using:

    systemd

------------------------------------------------------------------------

# TASK-702: Deployment Documentation

Create:

    docs/deployment.md

Include:

-   VPS setup
-   Environment variables
-   Service restart
-   Backup strategy

------------------------------------------------------------------------

# Phase 8 - Testing

------------------------------------------------------------------------

# TASK-801: Unit Test Coverage

Test:

-   Models
-   Adapters
-   Pipeline
-   Gemini services

------------------------------------------------------------------------

# TASK-802: Integration Testing

Verify:

    Feishu Message

    ↓

    Assistant

    ↓

    Gemini

    ↓

    Response

------------------------------------------------------------------------

# Codex Execution Template

For every completed task output:

    TASK-ID Complete

    Changes:

    -

    Files Modified:

    -

    Tests:

    -

    Known Issues:

    -

    Next Recommended Task:

    -

------------------------------------------------------------------------

# Development Rules

Always:

-   Prefer small commits.
-   Keep backward compatibility.
-   Avoid unnecessary dependencies.
-   Document architectural decisions.

Never:

-   Rewrite the entire project without approval.
-   Add infrastructure complexity without need.
-   Commit secrets.
