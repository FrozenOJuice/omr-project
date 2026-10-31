-- name: GetPdfRenderCosts :one
SELECT 
    *
FROM
    pdf_render_costs
ORDER BY
    sampled_at DESC
LIMIT 1;

-- name: CreatePdfRenderCosts :exec
INSERT INTO
    pdf_render_costs (pdf_render_baseline, pdf_render_increment)
VALUES
    (?, ?);

-- name: GetCpuLimit :one
SELECT 
    *
FROM
    cpu_limits
ORDER BY
    created_at DESC
LIMIT 1;

-- name: CreateCpuLimit :exec
INSERT INTO
    cpu_limits (max_threads)
VALUES
    (?);

-- name: DeleteCpuLimit :exec
DELETE FROM
    cpu_limits
WHERE
    ? = entry_id;

-- name: GetMemoryLimit :one
SELECT 
    *
FROM
    memory_limits
ORDER BY
    created_at DESC
LIMIT 1;

-- name: CreateMemoryLimit :exec
INSERT INTO
    memory_limits (max_memory)
VALUES
    (?);

-- name: DeleteMemoryLimit :exec
DELETE FROM
    memory_limits
WHERE
    ? = entry_id;

