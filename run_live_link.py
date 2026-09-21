import os
import sys
import time

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from core.bot_engine import BotEngine
from core.i18n import set_language

def main():
    set_language("it")
    print("=" * 60)
    print("🚀 DOKKAN BATTLE BOT - TEST LIVE LINK LEVEL FARMING")
    print("🥋 Stage: 1. Saiyan Training (Stanza dello Spirito e del Tempo)")
    print("⭐ Difficoltà: SUPER (40 STA)")
    print("🧹 Pre-Stage: Filtro Released + Level Up Possible, Remove All, Ricarica 6 carte")
    print("=" * 60)

    use_boost = "--boost" in sys.argv or "-b" in sys.argv
    if "--no-boost" in sys.argv:
        use_boost = False

    runs = None
    for a in sys.argv[1:]:
        if a.isdigit() and int(a) > 0:
            runs = int(a)

    engine = BotEngine()
    engine.register_log_callback(lambda msg: print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True))
    
    print("[1/3] Connessione al dispositivo Android...")
    engine.connect()

    boost_label = "ATTIVO" if use_boost else "DISATTIVO"
    runs_label = f"{runs} run" if runs is not None else "Finché c'è stamina (Illimitate)"
    print(f"[2/3] Avvio del task di Link Level farming ({runs_label}, Boost: {boost_label})...")
    ok = engine.start_link_level_farm(runs=runs, use_boost=use_boost)
    if not ok:
        print("❌ Impossibile avviare il task.")
        return

    print("[3/3] Task avviato! Monitoraggio in corso...")
    task = engine.current_task

    try:
        while task and task.is_running:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nInterruzione richiesta dall'utente...")
        engine.stop_task()

    print("=" * 60)
    print(f"🏁 TEST COMPLETATO! Run eseguite: {getattr(task, 'runs_completed', 0)}")
    print("=" * 60)

if __name__ == "__main__":
    main()
