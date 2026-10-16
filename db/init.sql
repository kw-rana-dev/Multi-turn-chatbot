-- Runs once, on first start of an empty Postgres volume.
-- Tables are owned by the backend: app/models.py is the source of truth and
-- app/migrations.py creates/patches them on startup. Keep this file to
-- extensions only so the two can't drift apart.
CREATE EXTENSION IF NOT EXISTS vector;
