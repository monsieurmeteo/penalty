import os, sys, time, subprocess
from sync_live_scores import sync

print("🚀 Démarrage du Watcher Live Scores (Rafraîchissement toutes les 30s)...")
while True:
    try:
        success, updated = sync()
        if success and updated > 0:
            print(f"⚡ {updated} mise(s) à jour détectée(s) ! Push vers GitHub Pages...")
            subprocess.run(["git", "add", "docs/data.json"], check=False)
            commit_res = subprocess.run(["git", "commit", "-m", "live(scores): maj scores en direct [skip ci]"], capture_output=True, text=True)
            if commit_res.returncode == 0:
                push_res = subprocess.run(["git", "push", "origin", "master"], capture_output=True, text=True)
                if push_res.returncode == 0:
                    print("✅ GitHub Pages mis à jour avec succès en direct !")
                else:
                    print(f"⚠️ Erreur git push: {push_res.stderr}")
            else:
                print("Rien à commiter.")
    except Exception as e:
        print(f"⚠️ Erreur watcher: {e}")

    time.sleep(30)
