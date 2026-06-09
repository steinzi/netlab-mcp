-- Compatibility matrix. One row per (module, scenario, dut_platform, peer set, provider,
-- netlab_version). Verdicts are version-scoped: a netlab version bump yields new rows and
-- leaves stale ones behind for re-validation rather than trusting old passes.
CREATE TABLE IF NOT EXISTS compat (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  module         TEXT NOT NULL,
  scenario       TEXT NOT NULL DEFAULT '',
  dut_platform   TEXT NOT NULL,
  peer_platforms TEXT NOT NULL DEFAULT '[]',   -- JSON list (sorted)
  provider       TEXT NOT NULL DEFAULT 'clab',
  netlab_version TEXT NOT NULL,
  image          TEXT,
  stage_create   TEXT,                          -- pass|fail|warning|null
  stage_up       TEXT,
  stage_config   TEXT,
  stage_validate TEXT,
  verdict        TEXT NOT NULL,                 -- pass|fail|warning|partial|deploy_failed
  topology_ref   TEXT,                          -- path to cached topology.yml
  config_ref     TEXT,                          -- path to cached configs.json
  notes          TEXT,
  warnings       TEXT NOT NULL DEFAULT '[]',    -- JSON list
  source         TEXT NOT NULL,                 -- harvest|report_failure|import:netlab|lab
  ts             TEXT NOT NULL,                 -- ISO-8601
  UNIQUE(module, scenario, dut_platform, peer_platforms, provider, netlab_version)
);

CREATE INDEX IF NOT EXISTS idx_compat_lookup
  ON compat(module, dut_platform, netlab_version);
