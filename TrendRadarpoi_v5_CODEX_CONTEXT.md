# TrendRadarpoi v5.0 Codex Context

## Purpose

This document provides long-term project context for AI coding agents
working on TrendRadarpoi.

It explains the project's goals, architectural decisions, and
constraints.

The purpose is to prevent unnecessary redesign and keep future
development consistent.

------------------------------------------------------------------------

# 1. Project Identity

TrendRadarpoi is a personal AI intelligence assistant.

It is NOT intended to become:

-   A SaaS platform.
-   A multi-user enterprise system.
-   A large distributed infrastructure project.

Primary user:

One personal user.

Primary goal:

Collect, understand, summarize, and discuss important information.

------------------------------------------------------------------------

# 2. Product Vision

The final system should work as:

    Information Sources

    ↓

    Content Collection

    ↓

    Event Understanding

    ↓

    AI Analysis

    ↓

    Personal Knowledge

    ↓

    Feishu Assistant

The system should answer questions such as:

-   What important AI events happened today?
-   Why is this news important?
-   What are the recent cybersecurity trends?
-   Research this company/project/topic.
-   Summarize recent discussions.

------------------------------------------------------------------------

# 3. Core Architectural Principles

## 3.1 Prefer Simplicity

This project values:

-   Low maintenance.
-   Low resource usage.
-   Simple deployment.

Avoid unnecessary enterprise architecture.

Do NOT introduce:

-   Kubernetes.
-   Microservices.
-   Complex message queues.
-   Heavy infrastructure.

Unless there is a real requirement.

------------------------------------------------------------------------

## 3.2 Incremental Refactoring

The existing TrendRadarpoi codebase should not be rewritten.

Preferred approach:

    Existing System

    +

    New Interfaces

    +

    Gradual Migration

Every improvement should preserve existing functionality.

------------------------------------------------------------------------

# 4. Deployment Philosophy

Current preferred deployment:

    GitHub Actions

            |

    Personal VPS

            |

    TrendRadarpoi Runtime

GitHub Actions:

Responsible for:

-   CI
-   Testing
-   Backup
-   Release

VPS:

Responsible for:

-   Feishu Bot
-   Assistant Service
-   Scheduler
-   Database
-   Agent-Reach integration

------------------------------------------------------------------------

# 5. Database Decision

Current choice:

SQLite.

Reason:

The project is personal use.

SQLite provides:

-   Low maintenance.
-   Simple backup.
-   Enough performance.

Do not introduce:

-   PostgreSQL.
-   Distributed databases.

Unless future requirements justify them.

------------------------------------------------------------------------

# 6. Intelligence Pipeline Design

The core data flow is:

    Source

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

    Notification

------------------------------------------------------------------------

# 7. Story Is a Core Concept

Story is not an optional enhancement.

The project should not remain a simple news aggregator.

Difference:

Bad:

    100 news articles

Desired:

    5 important events

    with:

    - Context
    - Sources
    - Importance
    - Explanation

Story represents meaningful events across multiple sources.

------------------------------------------------------------------------

# 8. Agent-Reach Integration Philosophy

Agent-Reach is NOT merged into the crawler system.

It is a research capability.

Correct architecture:

    Gemini

    ↓

    Research Gateway

    ↓

    Agent-Reach

Purpose:

When the user asks a question that requires external investigation, the
assistant can search and gather information.

Do not:

-   Copy Agent-Reach source code into core.
-   Make it a required dependency for basic operation.

------------------------------------------------------------------------

# 9. Gemini Role

Gemini evolves from:

Current:

    Translation Tool

Into:

    Reasoning Engine

Responsibilities:

-   Translation.
-   Summarization.
-   Story generation.
-   User conversation.
-   Research analysis.

------------------------------------------------------------------------

# 10. Feishu Integration Decision

Preferred method:

Feishu SDK WebSocket long connection.

Reason:

-   Personal usage.
-   No public webhook required.
-   Simpler VPS deployment.

Architecture:

    Feishu

    ↓

    WebSocket Client

    ↓

    Assistant Worker

    ↓

    Gemini / Tools

    ↓

    Reply

Important:

Implement:

-   Reconnection.
-   User whitelist.
-   Error handling.

------------------------------------------------------------------------

# 11. Security Rules

Never commit:

-   API keys.
-   Bot tokens.
-   Private credentials.

Use:

-   Environment variables.
-   GitHub Secrets.
-   VPS secret files.

------------------------------------------------------------------------

# 12. Coding Rules For AI Agents

Before changing code:

1.  Understand existing architecture.
2.  Explain proposed changes.
3.  Modify minimally.
4.  Run tests.
5.  Document changes.

Avoid:

-   Large rewrites.
-   Dependency explosion.
-   Architecture changes without justification.

------------------------------------------------------------------------

# 13. Future Expansion Direction

Possible future features:

-   Better semantic search.
-   Personal knowledge graph.
-   Vector database.
-   More research tools.
-   More notification channels.

However:

Do not implement future complexity early.

Build the smallest useful system first.

------------------------------------------------------------------------

# Final Reminder

TrendRadarpoi is a personal intelligence assistant.

The priority order is:

1.  Reliability.
2.  Personal usefulness.
3.  Low maintenance.
4.  Intelligent analysis.
5.  Extensibility.

Architecture should serve the user, not become the goal itself.
