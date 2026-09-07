import os, sys, time, subprocess
from sync_live_scores import sync

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
print("🚀 Démarrage du Watcher Live Scores (Rafraîchissement toutes les 30s)...")
while True:
    try:
        success, updated = sync()
        if success and updated > 0:
            print(f"⚡ {updated} mise(s) à jour détectée(s) ! Push vers GitHub Pages...")
            subprocess.run(["git", "add", "docs/data.json"], cwd=base_dir, check=False)
            commit_res = subprocess.run(["git", "commit", "-m", "live(scores): maj scores en direct [skip ci]"], cwd=base_dir, capture_output=True, text=True)
            if commit_res.returncode == 0:
                subprocess.run(["git", "pull", "--rebase", "-X", "theirs", "origin", "master"], cwd=base_dir, check=False)
                push_res = subprocess.run(["git", "push", "origin", "master"], cwd=base_dir, capture_output=True, text=True)
                if push_res.returncode == 0:
                    print("✅ GitHub Pages mis à jour avec succès en direct !")
                else:
                    print(f"⚠️ Erreur git push: {push_res.stderr}")
            else:
                print("Rien à commiter.")
    except Exception as e:
        print(f"⚠️ Erreur watcher: {e}")

    time.sleep(30)
