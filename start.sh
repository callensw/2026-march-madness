#!/bin/bash
set -e

# March Madness Agent Swarm - tmux session launcher
# Creates a "madness" session with 3 panes

SESSION="madness"
PROJECT_DIR="$HOME/march-madness-swarm"

# Check that required tools are available
if ! command -v tmux &>/dev/null; then
    echo "Error: tmux is not installed or not in PATH." >&2
    exit 1
fi

if ! command -v python &>/dev/null && ! command -v python3 &>/dev/null; then
    echo "Error: python is not installed or not in PATH." >&2
    exit 1
fi

# Trap SIGINT/SIGTERM to kill the tmux session cleanly
cleanup() {
    echo "Caught signal, killing tmux session '$SESSION'..."
    tmux kill-session -t "$SESSION" 2>/dev/null || true
    exit 0
}
trap cleanup SIGINT SIGTERM

# Kill existing session if it exists
tmux kill-session -t "$SESSION" 2>/dev/null || true

# Create new session with first pane (swarm engine)
tmux new-session -d -s "$SESSION" -c "$PROJECT_DIR"
tmux send-keys -t "$SESSION" "source venv/bin/activate" C-m
tmux send-keys -t "$SESSION" "echo '🏀 Pane 1: Swarm Engine — run: python swarm_engine.py'" C-m

# Split horizontally for log tailing
tmux split-window -h -t "$SESSION" -c "$PROJECT_DIR"
tmux send-keys -t "$SESSION" "source venv/bin/activate" C-m
tmux send-keys -t "$SESSION" "echo '📋 Pane 2: Logs — waiting for log files...'" C-m
tmux send-keys -t "$SESSION" "# tail -f logs/*.log" C-m

# Split pane 2 vertically for general terminal
tmux split-window -v -t "$SESSION" -c "$PROJECT_DIR"
tmux send-keys -t "$SESSION" "source venv/bin/activate" C-m
tmux send-keys -t "$SESSION" "echo '🔧 Pane 3: General terminal'" C-m

# Select first pane
tmux select-pane -t "$SESSION:0.0"

# Attach to session
tmux attach-session -t "$SESSION"
