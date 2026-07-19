#!/usr/bin/env bash
# collect_power.bash — Campiona powermetrics per il tuo studio TCO.
#
# Uso:
#   bin/collect_power.bash <modalità> [durata]
#
# Modalità:
#   idle       — Solo CPU (stima consumo a vuoto). Default.
#   light      — GPU + CPU, inference leggera (es. un singolo prompt).
#   sustained  — GPU + CPU, inference sostenuta (loop Kowalski completo).
#
# Durata (opzionale, in secondi):
#   idle:  30  (3 campioni a 10s)
#   light: 60  (12 campioni a 5s)
#   sustained: 300 (60 campioni a 5s)
#
# Esempio:
#   # Campionamento idle (30s, una tantum)
#   bin/collect_power.bash idle
#
#   # Campionamento inference leggera (60s)
#   bin/collect_power.bash light
#
#   # Campionamento inference sostenuta (5min) — lancia Kowalski in un altro terminale
#   bin/collect_power.bash sustained
#
# Il file viene scritto in: logs/power_metrics.csv
#
# Nota: richiede sudo la prima volta (una password). Poi si chiude da solo.

set -euo pipefail
cd "$(dirname "$0")/.."

MODE="${1:-idle}"
DURATION_ARG="${2:-}"

LOGDIR="logs"
mkdir -p "$LOGDIR"
OUTFILE="$LOGDIR/power_metrics.csv"

# Default durate per modalità
case "$MODE" in
  idle)
    INTERVAL=10
    SAMPLES=3
    ;;
  light)
    INTERVAL=5
    SAMPLES=12
    ;;
  sustained)
    INTERVAL=5
    SAMPLES=60
    ;;
  *)
    echo "Uso: $0 <idle|light|sustained> [durata_secondi]"
    echo "Modalità: idle (default), light, sustained"
    exit 1
    ;;
esac

# Sovrascrive durata se fornita
if [ -n "$DURATION_ARG" ]; then
    SAMPLES=$(( DURATION_ARG / INTERVAL ))
    if [ "$SAMPLES" -lt 1 ]; then
        SAMPLES=1
    fi
fi

TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

echo "============================================"
echo "  Power Metrics Collector"
echo "============================================"
echo "  Modalità  : $MODE"
echo "  Intervallo: ${INTERVAL}s"
echo "  Campioni  : $SAMPLES (~$((SAMPLES * INTERVAL))s)"
echo "  Output    : $OUTFILE"
echo "============================================"
echo ""
echo "ATTENZIONE: il comando richiede sudo la prima volta."
echo "Inserisci la tua password quando richiesto."
echo "Il campionamento si fermerà automaticamente dopo $SAMPLES campioni."
echo ""
read -r -p "Premi Invio per iniziare (Ctrl+C per annullare)..."

# Header CSV
echo "timestamp,mode,interval_s,samples,total_s,gpu_power_w,cpu_power_w,total_power_w,thermal_state,cpu_freq_mhz,gpu_freq_mhz" > "$OUTFILE"

echo "[${TIMESTAMP}] Avvio campionamento..."

# Lancia powermetrics con sudo
# -samplers gpu,cpu_power: raccoglie GPU e CPU power
# -i INTERVAL: intervallo tra campioni
# -n SAMPLES: numero di campioni (poi si ferma da solo)
sudo powermetrics --samplers gpu,cpu_power -i "$INTERVAL" -n "$SAMPLES" 2>/dev/null | \
while IFS= read -r line; do
    # Parsa le righe rilevanti dall'output di powermetrics
    if echo "$line" | grep -q "GPU Power"; then
        gpu_w=$(echo "$line" | sed -E 's/.*([0-9]+\.?[0-]*) W.*/\1/')
    elif echo "$line" | grep -q "CPU Power"; then
        cpu_w=$(echo "$line" | sed -E 's/.*([0-9]+\.?[0-]*) W.*/\1/')
    elif echo "$line" | grep -q "System Power"; then
        total_w=$(echo "$line" | sed -E 's/.*([0-9]+\.?[0-]*) W.*/\1/')
    elif echo "$line" | grep -q "Thermal"; then
        thermal=$(echo "$line" | sed -E 's/.*Thermal: *(.*)/\1/' | tr -d ' ')
    elif echo "$line" | grep -q "CPU die frequency"; then
        cpu_freq=$(echo "$line" | sed -E 's/.*([0-9]+).*/\1/')
    elif echo "$line" | grep -q "GPU die frequency"; then
        gpu_freq=$(echo "$line" | sed -E 's/.*([0-9]+).*/\1/')
    fi

    # Quando troviamo un blocco completo (ogni intervallo), scrivi una riga CSV
    if [ -n "${gpu_w:-}" ] && [ -n "${cpu_w:-}" ] && [ -n "${total_w:-}" ]; then
        TS=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
        echo "${TS},${MODE},${INTERVAL},${SAMPLES},$((SAMPLES * INTERVAL)),${gpu_w:-0},${cpu_w:-0},${total_w:-0},${thermal:-N/A},${cpu_freq:-0},${gpu_freq:-0}" >> "$OUTFILE"
        # Reset per il prossimo campione
        gpu_w="" cpu_w="" total_w="" thermal="" cpu_freq="" gpu_freq=""
    fi
done

echo ""
echo "[OK] Campionamento completato."
echo "  File: $(realpath "$OUTFILE")"
echo "  Righe CSV (escluso header): $(( $(wc -l < "$OUTFILE") - 1 ))"
echo ""
echo "Prossimi passi:"
echo "  1. Lancia il tuo loop di inference (Kowalski) in un altro terminale"
echo "  2. Rilancia questo script con la modalità corretta"
echo "  3. I dati saranno disponibili in $OUTFILE per il tuo studio TCO"
echo ""
