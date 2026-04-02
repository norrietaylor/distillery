#!/usr/bin/env bash
# Scripted demo recording for asciinema
# Simulates a Claude Code session showing /distill → /pour flow
set -e

# ANSI color codes (only those used in the script)
RESET='\033[0m'
BOLD='\033[1m'
DIM='\033[2m'
GREEN='\033[32m'
YELLOW='\033[33m'
BLUE='\033[34m'
CYAN='\033[36m'
BRIGHT_WHITE='\033[97m'

# Simulate typing with random delays
type_text() {
    local text="$1"
    local min_delay="${2:-0.03}"
    local max_delay="${3:-0.08}"
    for (( i=0; i<${#text}; i++ )); do
        printf '%s' "${text:$i:1}"
        # Random delay using $RANDOM
        local delay
        delay=$(python3 -c "import random; print(f'{random.uniform($min_delay, $max_delay):.3f}')")
        sleep "$delay"
    done
}

# Simulate thinking spinner
spin() {
    local duration="$1"
    local label="$2"
    local frames=("·" "✢" "✳" "✶" "✻" "✽" "✻" "✶" "✳" "✢")
    local end_time
    end_time=$(python3 -c "import time; print(time.time() + $duration)")
    local i=0
    while python3 -c "import time; exit(0 if time.time() < $end_time else 1)" 2>/dev/null; do
        printf '\r  %s %s   ' "${frames[$((i % ${#frames[@]}))]}" "$label"
        sleep 0.1
        i=$((i + 1))
    done
    printf '\r%*s\r' 60 ''
}

clear

# ── Claude Code header ──────────────────────────────────────────────────────
echo ""
printf "  ${BOLD}▐▛███▜▌${RESET} Claude Code v2.1.90\n"
printf "  ${BOLD}▝▜█████▛▘${RESET} ${DIM}Opus 4.6 (1M context) · Claude Max${RESET}\n"
printf "  ${DIM} ▘▘▝▝${RESET} ~/code/distillery\n"
echo ""
printf "  ──────────────────────────────────────────────────────────────────────────\n"
echo ""

sleep 1.0

# ── User types /distill command ─────────────────────────────────────────────
printf "  ${BRIGHT_WHITE}❯${RESET} "
type_text '/distill "We decided to use DuckDB with HNSW indexes for vector search — it keeps everything in a single file, avoids network hops, and the VSS extension handles cosine similarity natively."'
sleep 0.3
echo ""
echo ""

spin 2.0 "Distilling…"

# ── Distill output ──────────────────────────────────────────────────────────
printf "  ${GREEN}✓${RESET} ${BOLD}Distilled and stored${RESET}\n"
echo ""
printf "  ${DIM}Entry${RESET}    ${CYAN}e7a3f1b2${RESET}\n"
printf "  ${DIM}Project${RESET}  distillery\n"
printf "  ${DIM}Author${RESET}   norrie\n"
printf "  ${DIM}Type${RESET}     ${YELLOW}decision${RESET}\n"
echo ""
printf "  ${BOLD}Summary${RESET}\n"
printf "  Use DuckDB with HNSW indexes for vector similarity search.\n"
printf "  Single-file storage avoids network hops; VSS extension handles\n"
printf "  cosine similarity natively.\n"
echo ""
printf "  ${DIM}Tags${RESET}  ${BLUE}#duckdb${RESET}  ${BLUE}#vector-search${RESET}  ${BLUE}#architecture${RESET}\n"
echo ""
printf "  ${DIM}Dedup${RESET}  no similar entries found\n"
echo ""
printf "  ──────────────────────────────────────────────────────────────────────────\n"
echo ""

sleep 1.5

# ── User types /pour command ────────────────────────────────────────────────
printf "  ${BRIGHT_WHITE}❯${RESET} "
type_text '/pour how does our vector search work?'
sleep 0.3
echo ""
echo ""

spin 2.5 "Synthesizing…"

# ── Pour output ─────────────────────────────────────────────────────────────
printf "  ${BOLD}# Vector Search in Distillery${RESET}\n"
echo ""
printf "  The team chose ${BOLD}DuckDB with HNSW indexes${RESET} for vector similarity\n"
printf "  search ${DIM}[Entry e7a3f1b2]${RESET}. This decision was driven by three factors:\n"
echo ""
printf "  ${BOLD}1.${RESET} ${BOLD}Single-file storage${RESET} — DuckDB keeps the entire knowledge base\n"
printf "     in one file, making backups and portability trivial.\n"
echo ""
printf "  ${BOLD}2.${RESET} ${BOLD}No network hops${RESET} — unlike hosted vector databases, queries\n"
printf "     run in-process with zero latency overhead.\n"
echo ""
printf "  ${BOLD}3.${RESET} ${BOLD}Native cosine similarity${RESET} — the VSS extension provides\n"
printf "     HNSW-indexed cosine distance out of the box.\n"
echo ""
printf "  ${DIM}┌─────────┬──────────────┬──────────┬─────────┬───────────┐${RESET}\n"
printf "  ${DIM}│${RESET} ${BOLD}Short ID${RESET} ${DIM}│${RESET} ${BOLD}Type${RESET}         ${DIM}│${RESET} ${BOLD}Author${RESET}   ${DIM}│${RESET} ${BOLD}Date${RESET}    ${DIM}│${RESET} ${BOLD}Sim${RESET}       ${DIM}│${RESET}\n"
printf "  ${DIM}├─────────┼──────────────┼──────────┼─────────┼───────────┤${RESET}\n"
printf "  ${DIM}│${RESET} ${CYAN}e7a3f1b2${RESET} ${DIM}│${RESET} ${YELLOW}decision${RESET}     ${DIM}│${RESET} norrie   ${DIM}│${RESET} Apr  1  ${DIM}│${RESET} ${GREEN}97%%${RESET}       ${DIM}│${RESET}\n"
printf "  ${DIM}└─────────┴──────────────┴──────────┴─────────┴───────────┘${RESET}\n"
echo ""
printf "  ${GREEN}Synthesis complete.${RESET} ${DIM}1 entry cited across 1 section.${RESET}\n"
echo ""
printf "  ──────────────────────────────────────────────────────────────────────────\n"
echo ""

sleep 2.0
