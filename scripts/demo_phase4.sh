#!/usr/bin/env bash
# Runs the Phase 4 demo (docs/demo_script_phase4.md) end to end on a fresh database, offline.
set -euo pipefail
cd "$(dirname "$0")/.."
export FINCO_LLM=off PYTHONIOENCODING=utf-8 COLUMNS=170
PY="${PYTHON:-.venv/Scripts/python.exe}"
C="$PY -m copilot.cli.main"
D="${1:-${TMPDIR:-/tmp}/demo_phase4.db}"
rm -f "$D"
q() { "$PY" -c "import sqlite3,sys;c=sqlite3.connect(sys.argv[1]);print(c.execute(sys.argv[2]).fetchone()[0])" "$D" "$1"; }
NOW=2024-05-01T10:00:00+05:30

$C init-db --db "$D" >/dev/null
$C seed --months 4 --seed 42 --db "$D" >/dev/null
$C consent approve consent_seed_u1_42 --db "$D"
$C run --db "$D" --year 2024 --month 2 >/dev/null
# the persona stays inside its budgets, so give the food budget a limit it went over
"$PY" -c "import sqlite3,sys;c=sqlite3.connect(sys.argv[1]);c.execute(\"update budgets set limit_paise=300000 where category_id='food'\");c.commit()" "$D"

$C challenges offers --generate --clock $NOW --db "$D"
OFFER=$(q "select id from offers order by rank limit 1")
$C challenges accept "$OFFER" --clock $NOW --db "$D"
EXP=$(q "select id from experiments limit 1")
$C experiments show "$EXP" --clock 2024-05-04T10:00:00+05:30 --db "$D"
$C experiments checkin "$EXP" going_well --clock 2024-05-04T10:00:00+05:30 --db "$D"
$C memory exception --category food --reason travel --from 2024-05-03 --to 2024-05-05 --db "$D"
$C experiments tick --clock 2024-05-04T12:00:00+05:30 --db "$D" >/dev/null
$C adjustments list --db "$D"
ADJ=$(q "select id from adjustment_proposals where kind='extend' limit 1")
$C adjustments accept "$ADJ" --clock 2024-05-04T13:00:00+05:30 --db "$D"
$C experiments tick --clock 2024-05-12T12:00:00+05:30 --db "$D" >/dev/null
$C experiments review "$EXP" --db "$D"
$C progress --db "$D"
$C experiments feedback "$EXP" --difficulty 2 --helpful --repeat --clock 2024-05-12T13:00:00+05:30 --db "$D"
$C learning show --db "$D"
$C ask "what worked for me so far" --clock 2024-05-13T10:00:00+05:30 --db "$D"
$C sim run --policy thompson --persona ThriftyCook --weeks 26 --seed 42
$C sim run --policy random --persona ThriftyCook --weeks 26 --seed 42
$C timeline --db "$D"
