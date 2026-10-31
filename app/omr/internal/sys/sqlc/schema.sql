CREATE TABLE IF NOT EXISTS pdf_render_costs (
    entry_id INTEGER PRIMARY KEY,
    sampled_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now') * 1000),
    pdf_render_baseline INT NOT NULL,
    pdf_render_increment INT NOT NULL
);

CREATE TABLE IF NOT EXISTS cpu_limits (
    entry_id INTEGER PRIMARY KEY,
    created_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now') * 1000),
    max_threads INT NOT NULL
);

CREATE TABLE IF NOT EXISTS memory_limits (
    entry_id INTEGER PRIMARY KEY,
    created_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now') * 1000),
    max_memory INT NOT NULL
);
