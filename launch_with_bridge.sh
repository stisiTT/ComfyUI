#!/bin/bash

# SPDX-License-Identifier: Apache-2.0
#
# SPDX-FileCopyrightText: © 2025 Tenstorrent AI ULC

################################################################################
# Unified ComfyUI with Tenstorrent Bridge Server Launcher
#
# This script orchestrates the complete startup sequence for running ComfyUI
# with Tenstorrent hardware acceleration through a Unix socket bridge server.
#
# Architecture:
#   ComfyUI (frontend) -> Unix socket -> Bridge Server -> SDXL Runner -> TT Hardware
#
# Startup Sequence:
#   1. Validate prerequisites (directories, virtual environments)
#   2. Configure tt-metal environment (TT_METAL_HOME, PYTHONPATH, etc.)
#   3. Launch bridge server in background with tt-metal venv
#   4. Wait for Unix socket to become ready (with health checks)
#   5. Launch ComfyUI in foreground with ComfyUI venv
#   6. Cleanup on exit (terminate bridge, remove socket)
#
# Usage:
#   ./launch_with_bridge.sh [OPTIONS]
#
# Options:
#   -h, --help              Show this help message and exit
#   --dev                   Enable dev mode (faster startup, single worker)
#   --port PORT             ComfyUI listen port (default: 8188)
#   --listen IP             ComfyUI listen address (default: 127.0.0.1)
#   --device ID             Device ID to use (default: 0, env: DEVICE_ID)
#   --socket PATH           Unix socket path (default: /tmp/tt-comfy.sock)
#   --timeout SECONDS       Socket readiness timeout (default: 120)
#   --bridge-log PATH       Bridge server log file (default: ./bridge_server.log)
#   --no-color              Disable colored output
#
# Environment Variables:
#   TT_COMFY_SOCKET        Socket path (default: /tmp/tt-comfy.sock)
#   DEVICE_ID              Device ID for Tenstorrent hardware (default: 0)
#   SDXL_DEV_MODE          Enable dev mode (set to "true")
#   TT_VISIBLE_DEVICES     Comma-separated device IDs for T3K multi-device
#   NO_COLOR               Disable colored output when set
#
# Examples:
#   # Basic launch with defaults
#   ./launch_with_bridge.sh
#
#   # Dev mode with custom port (faster startup for testing)
#   ./launch_with_bridge.sh --dev --port 8080
#
#   # Listen on all interfaces with custom device
#   ./launch_with_bridge.sh --listen 0.0.0.0 --device 1
#
#   # Custom socket path and timeout
#   ./launch_with_bridge.sh --socket /tmp/my-bridge.sock --timeout 180
#
#   # Production mode with specific configuration
#   ./launch_with_bridge.sh --port 8188 --listen 0.0.0.0 --bridge-log /var/log/bridge.log
#
# Requirements:
#   - tt-metal repository at /home/tt-admin/tt-metal with python_env
#   - ComfyUI installation at /home/tt-admin/ComfyUI-tt_standalone with venv
#   - Bridge server at /home/tt-admin/tt-metal/comfyui_bridge/server.py
#   - Tenstorrent custom nodes at custom_nodes/tenstorrent_nodes
#
################################################################################

set -euo pipefail  # Exit on error, undefined variables, pipe failures

#===============================================================================
# Configuration Variables
#===============================================================================

# Directory paths (fixed for this installation)
readonly TT_METAL_DIR="/home/tt-admin/tt-metal"
readonly COMFYUI_DIR="/home/tt-admin/ComfyUI-tt_standalone"
readonly BRIDGE_DIR="${TT_METAL_DIR}/comfyui_bridge"

# Virtual environment paths
readonly TT_METAL_VENV="${TT_METAL_DIR}/python_env"
readonly COMFYUI_VENV="${COMFYUI_DIR}/venv"

# Default configuration (can be overridden by arguments or environment)
SOCKET_PATH="${TT_COMFY_SOCKET:-/tmp/tt-comfy.sock}"
DEVICE_ID="${DEVICE_ID:-0}"
COMFYUI_PORT=8188
COMFYUI_LISTEN="127.0.0.1"
SOCKET_TIMEOUT=120
BRIDGE_LOG="${COMFYUI_DIR}/bridge_server.log"
DEV_MODE=false
USE_COLOR=true

# Process tracking
BRIDGE_PID=""

# Color detection
if [[ -n "${NO_COLOR:-}" ]] || [[ ! -t 1 ]]; then
    USE_COLOR=false
fi

#===============================================================================
# Color Output Functions
#===============================================================================

# Color codes (ANSI escape sequences)
readonly COLOR_RESET='\033[0m'
readonly COLOR_RED='\033[0;31m'
readonly COLOR_GREEN='\033[0;32m'
readonly COLOR_YELLOW='\033[0;33m'
readonly COLOR_BLUE='\033[0;34m'
readonly COLOR_CYAN='\033[0;36m'
readonly COLOR_BOLD='\033[1m'

# Print colored message to stdout
color_print() {
    local color="$1"
    shift
    if [[ "${USE_COLOR}" == "true" ]]; then
        echo -e "${color}$*${COLOR_RESET}"
    else
        echo "$*"
    fi
}

# Info message (cyan)
info() {
    color_print "${COLOR_CYAN}" "[INFO] $*"
}

# Success message (green)
success() {
    color_print "${COLOR_GREEN}" "[SUCCESS] $*"
}

# Warning message (yellow)
warn() {
    color_print "${COLOR_YELLOW}" "[WARN] $*"
}

# Error message (red, to stderr)
error() {
    color_print "${COLOR_RED}" "[ERROR] $*" >&2
}

# Status message (bold blue)
status() {
    color_print "${COLOR_BOLD}${COLOR_BLUE}" "===> $*"
}

#===============================================================================
# Cleanup Function
#===============================================================================

cleanup() {
    local exit_code=$?

    info "Cleanup initiated (exit code: ${exit_code})"

    # Terminate bridge server if running
    if [[ -n "${BRIDGE_PID}" ]] && kill -0 "${BRIDGE_PID}" 2>/dev/null; then
        info "Terminating bridge server (PID: ${BRIDGE_PID})..."

        # Try graceful shutdown first (SIGTERM)
        kill -TERM "${BRIDGE_PID}" 2>/dev/null || true

        # Wait up to 5 seconds for graceful shutdown
        local timeout=5
        while kill -0 "${BRIDGE_PID}" 2>/dev/null && [[ ${timeout} -gt 0 ]]; do
            sleep 1
            ((timeout--))
        done

        # Force kill if still running (SIGKILL)
        if kill -0 "${BRIDGE_PID}" 2>/dev/null; then
            warn "Bridge server did not terminate gracefully, forcing..."
            kill -KILL "${BRIDGE_PID}" 2>/dev/null || true
        fi

        success "Bridge server terminated"
    fi

    # Remove socket file
    if [[ -S "${SOCKET_PATH}" ]]; then
        info "Removing socket file: ${SOCKET_PATH}"
        rm -f "${SOCKET_PATH}"
    fi

    info "Cleanup complete"
    exit "${exit_code}"
}

# Register cleanup trap for EXIT, INT (Ctrl+C), and TERM signals
trap cleanup EXIT INT TERM

#===============================================================================
# Help Function
#===============================================================================

show_help() {
    cat << 'EOF'
Unified ComfyUI with Tenstorrent Bridge Server Launcher

USAGE:
    ./launch_with_bridge.sh [OPTIONS]

OPTIONS:
    -h, --help              Show this help message and exit
    --dev                   Enable dev mode (faster startup, single worker)
    --port PORT             ComfyUI listen port (default: 8188)
    --listen IP             ComfyUI listen address (default: 127.0.0.1)
    --device ID             Device ID to use (default: 0)
    --socket PATH           Unix socket path (default: /tmp/tt-comfy.sock)
    --timeout SECONDS       Socket readiness timeout (default: 120)
    --bridge-log PATH       Bridge server log file (default: ./bridge_server.log)
    --no-color              Disable colored output

ENVIRONMENT VARIABLES:
    TT_COMFY_SOCKET        Socket path (default: /tmp/tt-comfy.sock)
    DEVICE_ID              Device ID for Tenstorrent hardware (default: 0)
    SDXL_DEV_MODE          Enable dev mode (set to "true")
    TT_VISIBLE_DEVICES     Comma-separated device IDs for T3K multi-device
    NO_COLOR               Disable colored output when set

EXAMPLES:
    # Basic launch with defaults
    ./launch_with_bridge.sh

    # Dev mode with custom port (faster startup)
    ./launch_with_bridge.sh --dev --port 8080

    # Listen on all interfaces
    ./launch_with_bridge.sh --listen 0.0.0.0

    # Custom device and socket
    ./launch_with_bridge.sh --device 1 --socket /tmp/custom.sock

    # Production setup with logging
    ./launch_with_bridge.sh --port 8188 --listen 0.0.0.0 --bridge-log /var/log/bridge.log

ARCHITECTURE:
    ComfyUI (frontend) -> Unix socket -> Bridge Server -> SDXL Runner -> TT Hardware

STARTUP SEQUENCE:
    1. Validate prerequisites (directories, virtual environments)
    2. Configure tt-metal environment (TT_METAL_HOME, PYTHONPATH, etc.)
    3. Launch bridge server in background with tt-metal venv
    4. Wait for Unix socket to become ready (with health checks)
    5. Launch ComfyUI in foreground with ComfyUI venv
    6. Cleanup on exit (terminate bridge, remove socket)

REQUIREMENTS:
    - tt-metal at /home/tt-admin/tt-metal with python_env
    - ComfyUI at /home/tt-admin/ComfyUI-tt_standalone with venv
    - Bridge server at /home/tt-admin/tt-metal/comfyui_bridge/server.py
    - Custom nodes at custom_nodes/tenstorrent_nodes

For more information, see:
    - Bridge server docs: /home/tt-admin/tt-metal/comfyui_bridge/README.md
    - ComfyUI backend guide: /home/tt-admin/ComfyUI-tt_standalone/QUICK_START_BACKEND.md

EOF
}

#===============================================================================
# Argument Parsing
#===============================================================================

parse_arguments() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            -h|--help)
                show_help
                exit 0
                ;;
            --dev)
                DEV_MODE=true
                export SDXL_DEV_MODE=true
                shift
                ;;
            --port)
                COMFYUI_PORT="$2"
                shift 2
                ;;
            --listen)
                COMFYUI_LISTEN="$2"
                shift 2
                ;;
            --device)
                DEVICE_ID="$2"
                shift 2
                ;;
            --socket)
                SOCKET_PATH="$2"
                shift 2
                ;;
            --timeout)
                SOCKET_TIMEOUT="$2"
                shift 2
                ;;
            --bridge-log)
                BRIDGE_LOG="$2"
                shift 2
                ;;
            --no-color)
                USE_COLOR=false
                shift
                ;;
            *)
                error "Unknown option: $1"
                echo ""
                echo "Run with --help for usage information"
                exit 1
                ;;
        esac
    done
}

#===============================================================================
# Prerequisite Validation
#===============================================================================

validate_prerequisites() {
    status "Validating prerequisites"

    local errors=0

    # Check tt-metal directory
    if [[ ! -d "${TT_METAL_DIR}" ]]; then
        error "tt-metal directory not found: ${TT_METAL_DIR}"
        ((errors++))
    else
        info "Found tt-metal directory: ${TT_METAL_DIR}"
    fi

    # Check ComfyUI directory
    if [[ ! -d "${COMFYUI_DIR}" ]]; then
        error "ComfyUI directory not found: ${COMFYUI_DIR}"
        ((errors++))
    else
        info "Found ComfyUI directory: ${COMFYUI_DIR}"
    fi

    # Check bridge directory
    if [[ ! -d "${BRIDGE_DIR}" ]]; then
        error "Bridge directory not found: ${BRIDGE_DIR}"
        ((errors++))
    else
        info "Found bridge directory: ${BRIDGE_DIR}"
    fi

    # Check bridge server script
    if [[ ! -f "${BRIDGE_DIR}/server.py" ]]; then
        error "Bridge server not found: ${BRIDGE_DIR}/server.py"
        ((errors++))
    else
        info "Found bridge server: ${BRIDGE_DIR}/server.py"
    fi

    # Check tt-metal virtual environment
    if [[ ! -d "${TT_METAL_VENV}" ]]; then
        error "tt-metal virtual environment not found: ${TT_METAL_VENV}"
        error "Please create it: cd ${TT_METAL_DIR} && python3 -m venv python_env"
        ((errors++))
    else
        info "Found tt-metal virtual environment: ${TT_METAL_VENV}"
    fi

    # Check ComfyUI virtual environment
    if [[ ! -d "${COMFYUI_VENV}" ]]; then
        error "ComfyUI virtual environment not found: ${COMFYUI_VENV}"
        error "Please create it: cd ${COMFYUI_DIR} && python3 -m venv venv"
        ((errors++))
    else
        info "Found ComfyUI virtual environment: ${COMFYUI_VENV}"
    fi

    # Handle stale socket file
    if [[ -e "${SOCKET_PATH}" ]]; then
        if [[ -S "${SOCKET_PATH}" ]]; then
            warn "Stale socket file found: ${SOCKET_PATH}"

            # Try to connect to check if server is running
            if timeout 1 bash -c "echo > /dev/tcp/127.0.0.1/12345" 2>/dev/null; then
                error "Bridge server may already be running on socket: ${SOCKET_PATH}"
                error "Please stop the existing server or use a different socket path"
                ((errors++))
            else
                info "Removing stale socket file"
                rm -f "${SOCKET_PATH}"
            fi
        else
            error "Non-socket file exists at socket path: ${SOCKET_PATH}"
            error "Please remove it or use a different socket path"
            ((errors++))
        fi
    fi

    # Check for Tenstorrent custom nodes (warning only)
    if [[ ! -d "${COMFYUI_DIR}/custom_nodes/tenstorrent_nodes" ]]; then
        warn "Tenstorrent custom nodes not found at: ${COMFYUI_DIR}/custom_nodes/tenstorrent_nodes"
        warn "You may need to install them for full Tenstorrent integration"
    else
        info "Found Tenstorrent custom nodes"
    fi

    # Exit if errors found
    if [[ ${errors} -gt 0 ]]; then
        error "Validation failed with ${errors} error(s)"
        exit 1
    fi

    success "All prerequisites validated"
}

#===============================================================================
# tt-metal Environment Setup
#===============================================================================

setup_ttmetal_environment() {
    status "Setting up tt-metal environment"

    # Set TT_METAL_HOME
    export TT_METAL_HOME="${TT_METAL_DIR}"
    info "TT_METAL_HOME=${TT_METAL_HOME}"

    # Add models directory to PYTHONPATH
    export PYTHONPATH="${TT_METAL_DIR}/models:${PYTHONPATH:-}"
    info "PYTHONPATH=${PYTHONPATH}"

    # Set LD_LIBRARY_PATH for shared libraries
    export LD_LIBRARY_PATH="${TT_METAL_DIR}/build/lib:${LD_LIBRARY_PATH:-}"
    info "LD_LIBRARY_PATH=${LD_LIBRARY_PATH}"

    # Enable program cache for better performance
    export TT_METAL_ENABLE_PROGRAM_CACHE=1
    info "TT_METAL_ENABLE_PROGRAM_CACHE=1"

    # Set device ID
    export DEVICE_ID="${DEVICE_ID}"
    info "DEVICE_ID=${DEVICE_ID}"

    # Dev mode configuration
    if [[ "${DEV_MODE}" == "true" ]]; then
        export SDXL_DEV_MODE=true
        info "SDXL_DEV_MODE=true (fast startup enabled)"
    fi

    success "tt-metal environment configured"
}

#===============================================================================
# Bridge Server Startup
#===============================================================================

start_bridge_server() {
    status "Starting bridge server"

    # Activate tt-metal virtual environment
    info "Activating tt-metal virtual environment"
    # shellcheck disable=SC1091
    source "${TT_METAL_VENV}/bin/activate"

    # Build bridge server command
    local bridge_cmd=(
        python3 -m comfyui_bridge.server
        --socket-path "${SOCKET_PATH}"
        --device-id "${DEVICE_ID}"
    )

    # Add dev flag if enabled
    if [[ "${DEV_MODE}" == "true" ]]; then
        bridge_cmd+=(--dev)
    fi

    # Display configuration
    info "Bridge configuration:"
    info "  Socket path: ${SOCKET_PATH}"
    info "  Device ID:   ${DEVICE_ID}"
    info "  Dev mode:    ${DEV_MODE}"
    info "  Log file:    ${BRIDGE_LOG}"

    # Start bridge server in background with logging
    info "Launching bridge server in background..."

    # Change to tt-metal directory for proper module imports
    cd "${TT_METAL_DIR}"

    # Start server in background, redirect output to log file
    "${bridge_cmd[@]}" > "${BRIDGE_LOG}" 2>&1 &
    BRIDGE_PID=$!

    # Brief sleep to let process start
    sleep 1

    # Verify process started successfully
    if ! kill -0 "${BRIDGE_PID}" 2>/dev/null; then
        error "Bridge server failed to start"
        error "Check log file: ${BRIDGE_LOG}"
        if [[ -f "${BRIDGE_LOG}" ]]; then
            error "Last 20 lines of log:"
            tail -n 20 "${BRIDGE_LOG}" >&2
        fi
        exit 1
    fi

    success "Bridge server started (PID: ${BRIDGE_PID})"
    info "Bridge server log: ${BRIDGE_LOG}"
}

#===============================================================================
# Socket Readiness Wait Loop
#===============================================================================

wait_for_socket() {
    status "Waiting for socket to become ready"

    info "Socket path: ${SOCKET_PATH}"
    info "Timeout: ${SOCKET_TIMEOUT} seconds"

    local elapsed=0
    local check_interval=2
    local last_progress=0

    while [[ ${elapsed} -lt ${SOCKET_TIMEOUT} ]]; do
        # Check if bridge process is still running
        if ! kill -0 "${BRIDGE_PID}" 2>/dev/null; then
            error "Bridge server process terminated unexpectedly"
            error "Check log file: ${BRIDGE_LOG}"
            if [[ -f "${BRIDGE_LOG}" ]]; then
                error "Last 30 lines of log:"
                tail -n 30 "${BRIDGE_LOG}" >&2
            fi
            exit 1
        fi

        # Check if socket file exists
        if [[ -S "${SOCKET_PATH}" ]]; then
            success "Socket is ready: ${SOCKET_PATH}"
            return 0
        fi

        # Progress indicator (every 10 seconds)
        if [[ $((elapsed - last_progress)) -ge 10 ]]; then
            info "Still waiting... (${elapsed}s / ${SOCKET_TIMEOUT}s)"
            last_progress=${elapsed}
        fi

        # Wait before next check
        sleep ${check_interval}
        ((elapsed += check_interval))
    done

    # Timeout reached
    error "Socket did not become ready within ${SOCKET_TIMEOUT} seconds"
    error "Bridge server may have failed to initialize"
    error "Check log file: ${BRIDGE_LOG}"

    if [[ -f "${BRIDGE_LOG}" ]]; then
        error "Last 30 lines of log:"
        tail -n 30 "${BRIDGE_LOG}" >&2
    fi

    exit 1
}

#===============================================================================
# ComfyUI Launch
#===============================================================================

launch_comfyui() {
    status "Launching ComfyUI"

    # Deactivate tt-metal venv (if active)
    if [[ -n "${VIRTUAL_ENV:-}" ]]; then
        info "Deactivating tt-metal virtual environment"
        deactivate 2>/dev/null || true
    fi

    # Activate ComfyUI virtual environment
    info "Activating ComfyUI virtual environment"
    # shellcheck disable=SC1091
    source "${COMFYUI_VENV}/bin/activate"

    # Change to ComfyUI directory
    cd "${COMFYUI_DIR}"

    # Build ComfyUI command
    local comfyui_cmd=(
        python3 main.py
        --port "${COMFYUI_PORT}"
        --listen "${COMFYUI_LISTEN}"
        --tenstorrent
        --tt-socket "${SOCKET_PATH}"
    )

    # Display banner
    echo ""
    color_print "${COLOR_BOLD}${COLOR_GREEN}" "╔════════════════════════════════════════════════════════════════╗"
    color_print "${COLOR_BOLD}${COLOR_GREEN}" "║  ComfyUI with Tenstorrent Hardware Acceleration               ║"
    color_print "${COLOR_BOLD}${COLOR_GREEN}" "╚════════════════════════════════════════════════════════════════╝"
    echo ""
    info "ComfyUI Configuration:"
    info "  Listen address: ${COMFYUI_LISTEN}:${COMFYUI_PORT}"
    info "  Bridge socket:  ${SOCKET_PATH}"
    info "  Bridge PID:     ${BRIDGE_PID}"
    info "  Mode:           $([ "${DEV_MODE}" == "true" ] && echo "Development" || echo "Production")"
    echo ""

    if [[ "${COMFYUI_LISTEN}" == "127.0.0.1" ]]; then
        success "ComfyUI will be available at: http://127.0.0.1:${COMFYUI_PORT}"
    else
        success "ComfyUI will be available at: http://${COMFYUI_LISTEN}:${COMFYUI_PORT}"
        if [[ "${COMFYUI_LISTEN}" == "0.0.0.0" ]]; then
            info "Listening on all interfaces (accessible from network)"
        fi
    fi

    echo ""
    info "Press Ctrl+C to stop ComfyUI and bridge server"
    echo ""

    # Launch ComfyUI in foreground (blocking)
    # This will run until user presses Ctrl+C
    exec "${comfyui_cmd[@]}"
}

#===============================================================================
# Main Function
#===============================================================================

main() {
    # Print header
    echo ""
    color_print "${COLOR_BOLD}${COLOR_CYAN}" "════════════════════════════════════════════════════════════════"
    color_print "${COLOR_BOLD}${COLOR_CYAN}" "  Unified ComfyUI with Tenstorrent Bridge Server Launcher"
    color_print "${COLOR_BOLD}${COLOR_CYAN}" "════════════════════════════════════════════════════════════════"
    echo ""

    # Parse command-line arguments
    parse_arguments "$@"

    # Execute startup sequence
    validate_prerequisites
    setup_ttmetal_environment
    start_bridge_server
    wait_for_socket
    launch_comfyui

    # Note: This line is never reached because launch_comfyui uses exec
    # Cleanup is handled by the EXIT trap
}

# Execute main function with all arguments
main "$@"
