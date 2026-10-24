#!/usr/bin/env bash
# Compacts a Herdr agent running pi (default: the orchestrator) from a helper tab.
# launch: reads the resume state from stdin or --resume-file, opens the helper tab and submits the worker.
# worker: Esc, wait for a settled state, /compact, wait for the durable compaction event in the
#         Pi session file, send the resume, wait for its delivery and new assistant activity, close the tab.
set -Eeuo pipefail

readonly DEFAULT_LABEL="auto-compact"
readonly DEFAULT_TIMEOUT_MS="300000"
SCRIPT_PATH="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/$(basename -- "${BASH_SOURCE[0]}")"
LOG_FILE=""

now() { date -u +%Y-%m-%dT%H:%M:%SZ; }

log() {
    local message="$*"
    if [[ -n "$LOG_FILE" ]]; then
        printf '[%s] %s\n' "$(now)" "$message" >>"$LOG_FILE"
    fi
    printf 'auto-compact: %s\n' "$message" >&2
}

fail() {
    log "ERROR $*"
    if [[ -n "$LOG_FILE" ]]; then
        printf 'auto-compact: FAILED (log=%s)\n' "$LOG_FILE" >&2
    fi
    exit 1
}

require_environment() {
    [[ "${HERDR_ENV:-}" == 1 ]] || fail "HERDR_ENV=1 is required"
    command -v herdr >/dev/null 2>&1 || fail "herdr is not on PATH"
}

run_step() {
    local step="$1"
    shift
    log "START $step"
    if "$@" >>"$LOG_FILE" 2>&1; then
        log "OK $step"
        return 0
    else
        local status=$?
        log "FAIL $step exit=$status"
        return "$status"
    fi
}

capture_step() {
    local step="$1"
    shift
    local output status
    log "START $step"
    if output=$("$@" 2>&1); then
        printf '%s\n' "$output" >>"$LOG_FILE"
        log "OK $step"
        printf '%s' "$output"
        return 0
    else
        status=$?
        printf '%s\n' "$output" >>"$LOG_FILE"
        log "FAIL $step exit=$status"
        return "$status"
    fi
}

wait_for_settled() {
    local target="$1"
    local timeout_ms="$2"
    local deadline=$(( $(date +%s) + (timeout_ms + 999) / 1000 ))
    local snapshot status

    log "START wait for settled target=$target"
    while :; do
        if snapshot=$(herdr agent get "$target" 2>&1) && \
            status=$(jq -er '.result.agent.agent_status | strings' <<<"$snapshot"); then
            if [[ "$status" == idle || "$status" == done ]]; then
                printf '%s\n' "$snapshot" >>"$LOG_FILE"
                log "OK wait for settled status=$status"
                return 0
            fi
        fi
        if (( $(date +%s) >= deadline )); then
            log "FAIL wait for settled: no idle/done state before timeout"
            return 1
        fi
        sleep 1
    done
}

wait_for_session_text() {
    local session_file="$1"
    local offset="$2"
    local needle="$3"
    local label="$4"
    local timeout_ms="$5"
    local deadline=$(( $(date +%s) + (timeout_ms + 999) / 1000 ))
    local size

    log "START wait $label offset=$offset"
    while :; do
        size=$(stat -c %s "$session_file") || {
            log "FAIL wait $label: cannot stat session file"
            return 1
        }
        if (( size > offset )) && tail -c "+$((offset + 1))" "$session_file" | grep -Fq "$needle"; then
            log "OK wait $label"
            return 0
        fi
        if (( $(date +%s) >= deadline )); then
            log "FAIL wait $label: marker not observed before timeout"
            return 1
        fi
        sleep 1
    done
}

launch_cleanup() {
    local status=$?
    if [[ "${TAB_CREATED:-0}" == 1 ]]; then
        log "START close helper after launch failure"
        if herdr tab close "$TAB_ID" >>"$LOG_FILE" 2>&1; then
            log "OK close helper after launch failure"
        else
            log "FAIL close helper after launch failure"
        fi
    fi
    log "launcher exit status=$status"
}

worker_cleanup() {
    local status=$?
    if [[ -n "${TAB_ID:-}" ]]; then
        log "START close helper tab"
        if herdr tab close "$TAB_ID" >>"$LOG_FILE" 2>&1; then
            log "tab closed"
        else
            log "FAIL close helper tab"
        fi
    fi
    log "worker exit status=$status"
}

launch() {
    local target="orchestrator"
    local label="$DEFAULT_LABEL"
    local timeout_ms="$DEFAULT_TIMEOUT_MS"
    local resume_file=""

    while (($#)); do
        case "$1" in
            --target)
                [[ $# -ge 2 ]] || fail "--target needs a value"
                target="$2"
                shift 2
                ;;
            --label)
                [[ $# -ge 2 ]] || fail "--label needs a value"
                label="$2"
                shift 2
                ;;
            --timeout)
                [[ $# -ge 2 ]] || fail "--timeout needs a value"
                timeout_ms="$2"
                shift 2
                ;;
            --resume-file)
                [[ $# -ge 2 ]] || fail "--resume-file needs a value"
                resume_file="$2"
                shift 2
                ;;
            *)
                fail "unknown launch option: $1"
                ;;
        esac
    done

    require_environment
    [[ -n "${HERDR_WORKSPACE_ID:-}" ]] || fail "HERDR_WORKSPACE_ID is required"
    [[ "$timeout_ms" =~ ^[0-9]+$ ]] || fail "--timeout must be an integer in milliseconds"
    command -v jq >/dev/null 2>&1 || fail "jq is required to read Herdr JSON"

    local run_dir
    run_dir="$(mktemp -d "${TMPDIR:-/tmp}/autocompact.XXXXXX")"
    LOG_FILE="$run_dir/events.log"
    local state_file="$run_dir/resume.md"
    touch "$LOG_FILE"
    trap launch_cleanup EXIT
    log "launcher started target=$target label=$label timeout_ms=$timeout_ms"

    if [[ -n "$resume_file" ]]; then
        [[ -s "$resume_file" ]] || fail "resume file is missing or empty: $resume_file"
        cp -- "$resume_file" "$state_file"
    else
        [[ ! -t 0 ]] || fail "resume state must come from stdin or --resume-file"
        cat >"$state_file" || fail "could not read resume state from stdin"
        [[ -s "$state_file" ]] || fail "resume state is empty"
    fi
    log "resume state saved at $state_file"

    local tabs_json existing
    tabs_json="$(capture_step "tab list" herdr tab list --workspace "$HERDR_WORKSPACE_ID")" \
        || fail "tab list failed"
    existing="$(jq -er --arg label "$label" '
        if (.result.tabs | type) != "array" then error("missing result.tabs")
        else [.result.tabs[] | select(.label == $label) | .tab_id] | join("\n")
        end' <<<"$tabs_json")" \
        || fail "tab list returned invalid JSON"
    [[ -z "$existing" ]] || fail "helper tab '$label' already exists: ${existing//$'\n'/, }; investigate it before retrying"

    local created_json
    created_json="$(capture_step "tab create" herdr tab create \
        --workspace "$HERDR_WORKSPACE_ID" --cwd "$PWD" --label "$label" --no-focus)" \
        || fail "tab create failed"

    local tab_id root_pane
    if ! tab_id="$(jq -er '
        if (.result.tab | type) == "object" then .result.tab.tab_id
        else .result.tab
        end // empty' <<<"$created_json")" || [[ -z "$tab_id" ]]; then
        fail "tab create returned invalid JSON (missing result.tab id)"
    fi
    if ! root_pane="$(jq -er '
        if (.result.root_pane | type) == "object" then .result.root_pane.pane_id
        else .result.root_pane
        end // empty' <<<"$created_json")" || [[ -z "$root_pane" ]]; then
        fail "tab create returned invalid JSON (missing result.root_pane id)"
    fi
    TAB_ID="$tab_id"
    TAB_CREATED=1
    log "helper created tab=$TAB_ID root_pane=$root_pane"

    local worker_command
    worker_command="AUTOCOMPACT_TAB_ID=$(printf '%q' "$TAB_ID")"
    worker_command+=" AUTOCOMPACT_RESUME_FILE=$(printf '%q' "$state_file")"
    worker_command+=" AUTOCOMPACT_LOG_FILE=$(printf '%q' "$LOG_FILE")"
    worker_command+=" AUTOCOMPACT_TARGET=$(printf '%q' "$target")"
    worker_command+=" AUTOCOMPACT_TIMEOUT_MS=$(printf '%q' "$timeout_ms")"
    worker_command+=" $(printf '%q' "$SCRIPT_PATH") worker"

    run_step "worker submit" herdr pane run "$root_pane" "$worker_command" \
        || fail "worker submit failed"
    TAB_CREATED=0
    log "helper submitted; diagnostics log=$LOG_FILE"
    printf 'auto-compact: helper submitted (log=%s)\n' "$LOG_FILE" >&2
}

worker() {
    LOG_FILE="${AUTOCOMPACT_LOG_FILE:-}"
    require_environment
    [[ -n "${AUTOCOMPACT_TAB_ID:-}" ]] || fail "AUTOCOMPACT_TAB_ID is required"
    [[ -n "${AUTOCOMPACT_RESUME_FILE:-}" ]] || fail "AUTOCOMPACT_RESUME_FILE is required"
    [[ -n "$LOG_FILE" ]] || fail "AUTOCOMPACT_LOG_FILE is required"
    [[ -n "${AUTOCOMPACT_TARGET:-}" ]] || fail "AUTOCOMPACT_TARGET is required"
    [[ -n "${AUTOCOMPACT_TIMEOUT_MS:-}" ]] || fail "AUTOCOMPACT_TIMEOUT_MS is required"
    [[ "$AUTOCOMPACT_TIMEOUT_MS" =~ ^[0-9]+$ ]] || fail "AUTOCOMPACT_TIMEOUT_MS must be an integer"
    command -v jq >/dev/null 2>&1 || fail "jq is required to verify agent state"

    TAB_ID="$AUTOCOMPACT_TAB_ID"
    local state_file="$AUTOCOMPACT_RESUME_FILE"
    local target="$AUTOCOMPACT_TARGET"
    local timeout_ms="$AUTOCOMPACT_TIMEOUT_MS"
    touch "$LOG_FILE"
    trap worker_cleanup EXIT

    [[ -s "$state_file" ]] || { log "ERROR resume state is missing or empty: $state_file"; return 1; }
    log "worker started target=$target timeout_ms=$timeout_ms"
    run_step "interrupt active turn" herdr agent send-keys "$target" esc
    wait_for_settled "$target" "$timeout_ms"

    local before_json session_file compact_offset compact_output compact_status
    before_json="$(capture_step "snapshot before compact" herdr agent get "$target")" || return 1
    if ! session_file="$(jq -er '.result.agent.agent_session.value | strings' <<<"$before_json")" || \
        [[ ! -r "$session_file" ]]; then
        log "FAIL snapshot before compact: readable agent session file is required"
        return 1
    fi
    compact_offset=$(stat -c %s "$session_file") || return 1

    log "START compact command"
    if compact_output=$(herdr agent prompt "$target" "/compact" --wait --timeout "$timeout_ms" 2>&1); then
        compact_status=0
        log "OK compact command"
    else
        compact_status=$?
        log "WARN compact command exit=$compact_status; waiting for durable compaction event"
    fi
    printf '%s\n' "$compact_output" >>"$LOG_FILE"
    wait_for_session_text "$session_file" "$compact_offset" '"type":"compaction"' \
        "compact event" "$timeout_ms"

    local resume resume_offset resume_token resume_output resume_status
    resume_offset=$(stat -c %s "$session_file") || return 1
    resume_token="AUTOCOMPACT_RESUME_ID_$(basename "$(dirname "$state_file")")"
    resume="$resume_token
$(<"$state_file")"

    log "START resume command token=$resume_token"
    if resume_output=$(herdr agent prompt "$target" "$resume" 2>&1); then
        resume_status=0
        log "OK resume command"
    else
        resume_status=$?
        log "WARN resume command exit=$resume_status; verifying durable delivery"
    fi
    printf '%s\n' "$resume_output" >>"$LOG_FILE"
    wait_for_session_text "$session_file" "$resume_offset" "$resume_token" \
        "resume delivery" "$timeout_ms"
    wait_for_session_text "$session_file" "$resume_offset" '"role":"assistant"' \
        "resume activity" "$timeout_ms"
    log "resume active; retaining diagnostics at $LOG_FILE"
}

case "${1:-}" in
    launch)
        shift
        launch "$@"
        ;;
    worker)
        shift
        worker "$@"
        ;;
    *)
        printf 'Usage: %s launch [--target AGENT] [--label LABEL] [--timeout MS] [--resume-file PATH]\n' "$0" >&2
        printf '       %s worker\n' "$0" >&2
        exit 2
        ;;
esac
