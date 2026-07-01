import re
import json
import os


def _resolve_paths(config_path="llmstack_config.json"):
    cfg = {}
    if os.path.exists(config_path):
        try:
            with open(config_path, encoding="utf-8") as f:
                cfg = json.load(f)
        except (OSError, json.JSONDecodeError):
            cfg = {}

    base_dir = os.path.dirname(os.path.abspath(config_path))
    log_dir = cfg.get("log_dir", "logs")
    log_dir = log_dir if os.path.isabs(log_dir) else os.path.normpath(os.path.join(base_dir, log_dir))

    dflash_log = cfg.get("dflash_log", os.path.join(log_dir, "dflash_server.log"))
    clean_log = os.path.join(log_dir, "server_pulito.log")

    if not os.path.isabs(dflash_log):
        dflash_log = os.path.normpath(os.path.join(base_dir, dflash_log))
    if not os.path.isabs(clean_log):
        clean_log = os.path.normpath(os.path.join(base_dir, clean_log))

    return dflash_log, clean_log


input_file, output_file = _resolve_paths()
os.makedirs(os.path.dirname(output_file), exist_ok=True)

# La stessa Regex di prima, ma senza i gruppi di cattura () poiché dobbiamo solo verificare se c'è il match
pattern = re.compile(r'^\d{1,3}(?:\.\d{1,3}){3} \S+ \S+ \[[^\]]+\] "[^"]+" \d{3} \S+')

with open(input_file, 'r') as infile, open(output_file, 'w') as outfile:
    for line in infile:
        # Se la riga NON corrisponde al pattern del log, scrivila nel nuovo file
        if not pattern.match(line):
            outfile.write(line)

print("Pulizia completata! Le righe di log sono state rimosse.")