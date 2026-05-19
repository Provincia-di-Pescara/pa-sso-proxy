# pa-sso-proxy — Plan 1: Foundation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Running Docker Compose stack con postgres, nginx, placeholder satosa, e una functional config-api (login, dashboard, tutti i DB tables migrati).

**Architecture:** FastAPI + SQLAlchemy 2.0 async + Alembic per config-api. SessionMiddleware (Starlette built-in) per WebUI auth. Bootstrap 5 CDN, nessun build step. Nginx route `/admin` → config-api, `/` → satosa placeholder.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0 + asyncpg, Alembic, Jinja2, pytest + pytest-asyncio + httpx, Docker Compose v2, postgres:16, nginx:alpine.

Vedi file completo in repo.
