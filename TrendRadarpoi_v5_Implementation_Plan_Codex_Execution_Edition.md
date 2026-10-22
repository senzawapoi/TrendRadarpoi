# TrendRadarpoi v5.0 Implementation Plan

## Codex Execution Edition

**Version:** v1.0\
**Purpose:** Engineering execution plan for upgrading TrendRadarpoi into
a personal AI intelligence assistant.

------------------------------------------------------------------------

# 0. Codex Execution Rules

## Development Principles

-   Do not rewrite the whole project.
-   Prefer incremental refactoring.
-   Preserve existing features.
-   Introduce adapters and interfaces before replacing implementations.
-   Every phase must keep the project runnable.

## Commit Convention

Examples:

``` text
feat(core): add ContentItem model

refactor(source): unify source adapters

feat(ai): introduce Gemini service
```

## Forbidden Actions

Codex must not:

-   Introduce unnecessary microservices.
-   Introduce Kubernetes.
-   Replace the database without a clear requirement.
-   Remove existing notification features.
-   Add enterprise-level complexity for a personal project.

------------------------------------------------------------------------

# Phase 0: Project Baseline Stabilization

## Goal

Create a stable foundation before feature expansion.

## Task 0.1: Codebase Review

Analyze:

-   trendradar/
-   config/
-   services/
-   storage/
-   notification/

Deliver:

-   Module dependency overview.
-   High coupling areas.
-   Refactoring recommendations.

Acceptance:

Create:

``` text
docs/code-review.md
```

------------------------------------------------------------------------

## Task 0.2: Configuration System Unification

Target:

Move all configuration into a unified system.

Create:

``` text
config/

settings.py

.env.example
```

Manage:

-   Gemini API Key
-   Feishu App ID
-   Feishu App Secret
-   Database path
-   External service configuration

Requirements:

-   No secrets committed to Git.
-   Local development and VPS deployment must share the same
    configuration style.

------------------------------------------------------------------------

# Phase 1: Unified Intelligence Data Layer

## Goal

Normalize all information sources into a common data model.

------------------------------------------------------------------------

# Task 1.1: Create ContentItem Model

Create:

``` text
trendradar/core/models/
```

File:

``` text
content.py
```

Model:

``` python
ContentItem
```

Fields:

``` text
id
title
content
url
source
domain
published_time
tags
metadata
```

Acceptance:

All crawlers can output ContentItem objects.

------------------------------------------------------------------------

# Task 1.2: Source Adapter System

Create:

``` text
trendradar/sources/
```

Structure:

``` text
sources/

base.py

news/

security/

social/

github/
```

Interface:

``` python
class SourceAdapter:

    fetch()

    normalize()

    health_check()
```

Purpose:

Allow future data sources without modifying core logic.

------------------------------------------------------------------------

# Task 1.3: Deduplication Pipeline

Create:

``` text
pipeline/deduplicate.py
```

Version 1 strategy:

-   URL hashing
-   Title similarity
-   Time window matching

Do not introduce vector databases at this stage.

Acceptance:

Duplicate information is reduced before analysis.

------------------------------------------------------------------------

# Phase 2: Story Intelligence Layer

## Goal

Upgrade from news collection to event intelligence.

Input:

``` text
ContentItem
```

Output:

``` text
Story
```

------------------------------------------------------------------------

# Task 2.1: Cluster Engine

Create:

``` text
pipeline/clustering.py
```

Purpose:

Identify related information items.

Initial clustering signals:

-   Time proximity
-   Title similarity
-   Entity keywords
-   Topic tags

------------------------------------------------------------------------

# Task 2.2: Story Model

Create:

``` text
core/models/story.py
```

Model:

``` python
Story
```

Fields:

``` text
id
title
summary
items[]
importance
tags
```

------------------------------------------------------------------------

# Task 2.3: Story Generation

Create:

``` text
ai/story_generator.py
```

Flow:

``` text
Cluster

↓

Gemini

↓

Story
```

Acceptance:

Daily reports should focus on important stories instead of raw articles.

------------------------------------------------------------------------

# Phase 3: Security Intelligence Domain

## Goal

Integrate cybersecurity-daily capabilities.

Do not copy the project directly.

Create:

``` text
domains/security/
```

Structure:

``` text
security/

collector.py

analyzer.py

report.py
```

Responsibilities:

-   CVE collection
-   Vulnerability intelligence
-   Security event analysis

Output:

All security information must become:

``` text
ContentItem
```

and enter the normal intelligence pipeline.

------------------------------------------------------------------------

# Phase 4: Gemini Intelligence Layer

## Goal

Transform Gemini from a translation utility into the reasoning engine.

Create:

``` text
ai/

client.py

translator.py

analyzer.py

assistant.py
```

Interfaces:

``` python
GeminiClient.chat()

GeminiClient.summary()

GeminiClient.analyze()
```

Responsibilities:

-   Translation
-   Summarization
-   Story analysis
-   User conversation
-   Research reasoning

------------------------------------------------------------------------

# Phase 5: Feishu Assistant Integration

## Goal

Provide a personal chat interface.

Architecture:

``` text
Feishu WebSocket

↓

Message Handler

↓

Assistant Service

↓

Gemini

↓

Reply
```

Create:

``` text
integrations/

feishu/

client.py

handler.py

session.py
```

Features:

Version 1:

-   Receive messages.
-   Reply to messages.
-   Push daily reports.
-   User whitelist control.

Deployment:

Use Feishu SDK WebSocket long connection.

Avoid unnecessary public webhook infrastructure.

------------------------------------------------------------------------

# Phase 6: Agent-Reach Integration

## Goal

Provide external research capability.

Agent-Reach is not a crawler replacement.

It is a research tool layer.

Architecture:

``` text
User

↓

Gemini

↓

Research Gateway

↓

Agent-Reach
```

Create:

``` text
integrations/

agent_reach/

adapter.py
```

Expose:

``` python
research()

search()

fetch()
```

Requirements:

-   Timeout handling.
-   Failure isolation.
-   Permission control.

------------------------------------------------------------------------

# Phase 7: Deployment

## Recommended Architecture

``` text
GitHub

    |

GitHub Actions

    |

Personal VPS

    |

-----------------

Feishu Bot

Assistant Worker

Scheduler

SQLite

Agent-Reach

-----------------
```

## VPS Responsibilities

Run:

-   Feishu Bot
-   Assistant Worker
-   Scheduler
-   Database

## GitHub Actions Responsibilities

Handle:

-   CI
-   Testing
-   Backup
-   Release workflow

------------------------------------------------------------------------

# Phase 8: Testing

## Unit Tests

Cover:

-   Source adapters
-   Data models
-   Gemini services
-   Feishu handlers

## Integration Tests

Verify:

``` text
User Message

↓

Feishu

↓

Assistant

↓

Gemini

↓

Response
```

------------------------------------------------------------------------

# Phase Completion Requirements

Every phase must provide:

``` text
Phase-X Complete

Changes:

-

Files:

-

Tests:

-

Known Issues:

-

Next Steps:
```

------------------------------------------------------------------------

# Codex Working Procedure

For every task:

1.  Read current implementation.
2.  Analyze impact.
3.  Propose modification plan.
4.  Modify code.
5.  Run tests.
6.  Report changes.
7.  Commit changes.

Never perform a full rewrite without approval.

------------------------------------------------------------------------

# Final Project Vision

TrendRadarpoi becomes:

``` text
Personal AI Intelligence Assistant

Sources

↓

ContentItem

↓

Cluster

↓

Story

↓

Ranking

↓

Gemini Analysis

↓

Feishu Assistant

↓

Personal Knowledge System
```

The project prioritizes:

-   Personal usability
-   Low maintenance
-   Low resource consumption
-   Incremental improvement
