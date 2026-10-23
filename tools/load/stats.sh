#!/usr/bin/env bash
# CPU and memory of a rehearsal stack's containers every 5 s, as CSV, until killed.
#   tools/load/stats.sh voltage-load > stats.csv &
NAME="${1:-voltage-load}"
echo "t,container,cpu_pct,mem_mib"
while true; do
  now=$(date +%s)
  docker stats --no-stream --format '{{.Name}},{{.CPUPerc}},{{.MemUsage}}' | grep "^$NAME-" | while IFS=, read -r n c m; do
    mem=$(echo "$m" | awk '{print $1}')
    case "$mem" in *GiB) v=$(echo "${mem%GiB} * 1024" | bc);; *MiB) v=${mem%MiB};; *KiB) v=$(echo "${mem%KiB} / 1024" | bc -l);; *) v=0;; esac
    echo "$now,$n,${c%\%},$v"
  done
  sleep 5
done
