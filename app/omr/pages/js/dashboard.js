/**
 * Interval between automatic updates, in milliseconds.
 *
 * @type {number}
 */
const INTERVAL = 1000

/**
 * The admin key used for authentication.
 */
let key = ""

/**
 * Formats a byte count into a human-readable string.
 *
 * @param {number} bytes Number of bytes.
 * @returns {string} Formatted byte value with an appropriate unit.
 */
function formatBytes(bytes) {
    const units = ["B", "KB", "MB", "GB", "TB"]

    let value = bytes
    let unit = 0

    while (value >= 1024 && unit < units.length - 1) {
        value /= 1024
        unit++
    }

    return `${value.toFixed(2)} ${units[unit]}`
}

/**
 * Formats a duration in seconds as a day/hour/minute/second timestamp.
 *
 * @param {number} seconds Duration in seconds.
 * @returns {string} Formatted duration string (`DD:HH:MM:SS`).
 */
function formatTime(seconds) {
    let minutes = Math.floor(seconds / 60)
    seconds %= 60
    let hours = Math.floor(minutes / 60)
    minutes %= 60
    let days = Math.floor(hours / 60)
    hours %= 60

    let secStr = (seconds < 10 ? "0" : "") + seconds.toString()
    let minStr = (minutes < 10 ? "0" : "") + minutes.toString()
    let hourStr = (hours < 10 ? "0" : "") + hours.toString()
    let dayStr = (days < 10 ? "0" : "") + days.toString()

    return dayStr + ":" + hourStr + ":" + minStr + ":" + secStr
}

/**
 * Converts raw log text into HTML with syntax highlighting.
 *
 * @param {string} logs Raw log output.
 * @returns {string} HTML-formatted log output.
 */
function formatLogs(logs) {
    return logs
        .split("\n")
        .slice(-11, -1)
        .map(s => {
            s = s.replaceAll(" ", "&nbsp;")
            s = s.replaceAll(
                /https?:\/\/[^\s]+/g, 
                s => `<a href="${s}" target="_blank" class="link">${s}</a>`,
            )
            if (s.includes("[LOG]")) {
                return `<span class="misc">${s}</span>`
            } else if (s.includes("[INFO]")) {
                return `<span class="info">${s}</span>`
            } else if (s.includes("[WARN]")) {
                return `<span class="warn">${s}</span>`
            } else if (s.includes("[DEBUG]")) {
                return `<span class="debug">${s}</span>`
            } else if (s.includes("[ERROR]")) {
                return `<span class="error">${s}</span>`
            } else {
                return `<span class="misc">${s}</span>`
            }
        })
        .join("<br />") + "<br />"
}

/**
 * Sets the text content of a DOM element.
 *
 * @param {string} id ID of the target element.
 * @param {string} value Text content to assign.
 * @returns {void}
 */
function setText(id, value) {
    document.getElementById(id).textContent = value
}

/**
 * Sets the width of a progress bar element.
 *
 * @param {string} id ID of the target element.
 * @param {number} percent Percentage value. Values outside 0-100 are clamped.
 * @returns {void}
 */
function setBar(id, percent) {
    document.getElementById(id).style.width =
        `${Math.min(100, Math.max(0, percent))}%`
}

/**
 * Retrieves and updates system utilization information.
 *
 * Fetches CPU, memory, disk, and miscellaneous statistics from the server
 * and updates the corresponding dashboard elements.
 *
 * @async
 * @returns {Promise<void>}
 */
async function update() {
    const response = await fetch("/system/utilization?limit=1")

    if (!response.ok) {
        throw new Error(`${response.status}: ${response.statusText}`)
    }

    const data = await response.json()

    const cpu = data.cpuHistory[data.cpuHistory.length - 1]
    const memory = data.memoryHistory[data.memoryHistory.length - 1]
    const disk = data.disk

    //
    // CPU
    //

    setText("cpu-mhz", `${cpu.mhz.toFixed(0)} MHz`)
    setText("cpu-overall", `${cpu.overallPercent.toFixed(1)}%`)
    setText("cpu-threads", `${cpu.threads.length}`)

    setBar("cpu-bar", cpu.overallPercent)

    //
    // Memory
    //

    setText("memory-omr", formatBytes(memory.inUseOmr))
    setText("memory-free", formatBytes(memory.free))

    const memoryUsed =
        memory.inUseOmr +
        memory.inUseOther

    const totalMemory =
        memory.free +
        memory.inUseOther +
        memory.inUseOmr

    setText("memory-used", formatBytes(memoryUsed))

    setBar(
        "other-memory-bar",
        (memory.inUseOther / totalMemory) * 100,
    )

    setBar(
        "omr-memory-bar",
        (memory.inUseOmr / totalMemory) * 100,
    )

    //
    // Disk
    //

    setText("disk-used", formatBytes(disk.usage.used))

    const omrUsage = disk.omrUsage.total

    setBar(
        "omr-disk-bar",
        (omrUsage / disk.usage.total) * 100
    )

    setBar(
        "other-disk-bar",
        ((disk.usage.used - omrUsage) / disk.usage.total) * 100
    )

    setText(
        "disk-available",
        formatBytes(disk.usage.free)
    )

    setText(
        "disk-omr-total",
        formatBytes(omrUsage)
    )

    //
    // Misc
    //

    setText(
        "omr-memory-peak",
        formatBytes(data.memoryPeak)
    )

    setText(
        "uptime",
        formatTime(data.uptime)
    )
}

/**
 * Formats a Unix timestamp in milliseconds into a readable date string.
 *
 * @param {number} timestamp Timestamp in milliseconds.
 * @returns {string} Formatted date string.
 */
function formatTimestamp(timestamp) {

    if (!timestamp) {
        return "-"
    }

    return new Date(timestamp)
        .toLocaleString("en-US", {
            hour12: false,
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit",
        })
}

/**
 * Creates a progress bar HTML element.
 *
 * @param {object} job Job details.
 * @returns {string} HTML progress bar.
 */
function formatProgress(job) {
    const percent = Math.min(
        100,
        Math.max(0, job.progress * 100),
    )
    
    let c = ""
    if (!job.finishedTimestamp) {
        c = "in-progress"
    } else if (job.success) {
        c = "success"
    } else {
        c = "failure"
    }

    return `
        <div class="job-progress ${c}">
            <div
                class="job-progress-bar ${c}"
                style="width: ${percent}%"
            ></div>
        </div>
    `
}

/**
 * Formats a job status into a human-readable string.
 *
 * @param {object} job Job information.
 * @returns {string} Status HTML.
 */
function formatJobStatus(job) {
    if (!job.finishedTimestamp) {
        return `
            <span class="job-running">
                <a target="_blank" class="link" href="/job?id=${job.id}">
                    IN PROGRESS
                </a>
            </span>`
    }

    if (job.success) {
        return `
            <span class="job-success">
                <a target="_blank" class="link" href="/job/result?id=${job.id}">
                    SUCCESS
                </a>    
            </span>`
    }

    return `
        <span class="job-failed">
            <a target="_blank" class="link" href="/job/result?id=${job.id}">
                FAILURE
            </a>        
        </span>`
}

/**
 * Updates the job table.
 *
 * Retrieves recent background jobs and updates the job display table.
 *
 * @async
 * @returns {Promise<void>}
 */
async function updateJobs() {
    const response = await fetch(
        "/jobs?limit=10",
        { headers: [
            ["OMR-Admin-Key", key],
            ["Accept-Encoding", "deflate"]
        ] }
    )

    if (!response.ok) {
        throw new Error(`${response.status}: ${response.statusText}`)
    }

    const jobs = await response.json()
    const output = document.getElementById("jobs-output")

    output.innerHTML = jobs
        .reverse()
        .slice(0, 14)
        .map(job => `
            <tr>
                <td class="path-col">
                    ${job.method} ${job.path}
                </td>

                <td class="status-col">
                    ${formatJobStatus(job)}
                </td>

                <td class="progress-col">
                    ${formatProgress(job)}
                </td>

                <td>
                    ${formatTimestamp(job.startedTimestamp)}
                </td>

                <td>
                    ${formatTimestamp(job.finishedTimestamp)}
                </td>

                <td>
                    ${job.notes || ""}
                </td>
            </tr>
        `)
        .join("")
}

/**
 * Retrieves and updates the system log display.
 *
 * @async
 * @returns {Promise<void>}
 */
async function updateLogs() {
    const response = await fetch("/system/logs?limit=10")

    if (!response.ok) {
        throw new Error(`${response.status}: ${response.statusText}`)
    }

    const data = await response.text()
    const logsOutput = document.getElementById("logs-output")

    const formatted = formatLogs(data)
    if (formatted != logsOutput.innerHTML) {
        logsOutput.innerHTML = formatLogs(data)
        logsOutput.scrollTo(0, logsOutput.scrollHeight)
    }   
}

function startUpdateLoop() {
    update()
    updateLogs()
    updateJobs()
    setInterval(() => {
        update()
        updateLogs()
        updateJobs()
    }, INTERVAL)

}

/**
 * Returns `true` if and only if the given key is recognized by the OMR.
 * 
 * @param {string} key 
 * @returns {Promise<boolean>}
 */
async function validKey(key) {
    let resp = await fetch("/admin/authenticated", { 
        headers: [[ "OMR-Admin-Key", key ]]
    }) 
    return resp.ok
}

document.addEventListener("DOMContentLoaded", async () => {
    key = localStorage.getItem("omr-admin-key")
    while (true) {
        let isValid = await validKey(key)
        if (isValid) {
            break
        }
        key = prompt(
            "Enter the API key for the OMR.",
            "admin"
        )
    }
    localStorage.setItem("omr-admin-key", key)
    startUpdateLoop()
})
