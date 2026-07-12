#!/usr/bin/env python3
"""Fetch newly saved Instagram posts and feed them into the ingest pipeline.

Uses the logged-in Instaloader session ONLY to list saved posts (shortcodes);
the actual download runs through the anonymous /ingest pipeline. State file
keeps processed shortcodes; --seed marks everything currently saved as seen
without processing (baseline)."""
import glob, os, sys, time
import requests
import instaloader

HOME = os.path.expanduser("~")
STATE = os.path.join(HOME, ".saved-seen.txt")
API = "http://localhost:8000/ingest"
FETCH_LIMIT = 60   # how many of the most recent saved posts to list
RUN_CAP = 15       # max posts processed per run (gentle on all sides)

def notify(text):
    try:
        env = dict(l.strip().split("=", 1) for l in open(HOME + "/.telegram-notify") if "=" in l)
        requests.post("https://api.telegram.org/bot%s/sendMessage" % env["TG_TOKEN"],
                      json={"chat_id": env["TG_CHAT"], "text": text}, timeout=15)
    except Exception as e:
        print("notify failed:", e)

def main():
    seed = "--seed" in sys.argv
    sessions = glob.glob(HOME + "/.config/instaloader/session-*")
    if not sessions:
        print("Keine Instaloader-Session gefunden. Bitte einloggen:"); sys.exit(1)
    username = os.path.basename(sessions[0]).replace("session-", "")
    L = instaloader.Instaloader(quiet=True)
    L.load_session_from_file(username)

    try:
        profile = instaloader.Profile.own_profile(L.context)
    except AttributeError:
        profile = instaloader.Profile.from_username(L.context, username)
    shortcodes = []
    for i, post in enumerate(profile.get_saved_posts()):
        if i >= FETCH_LIMIT: break
        shortcodes.append(post.shortcode)

    seen = set(open(STATE).read().split()) if os.path.exists(STATE) else set()
    new = [sc for sc in shortcodes if sc not in seen]

    if seed:
        with open(STATE, "a") as f:
            for sc in new: f.write(sc + "\n")
        print("Baseline: %d Beitraege als gesehen markiert" % len(new))
        notify("📌 Saved-Capture eingerichtet: %d vorhandene gespeicherte Beitraege als Baseline markiert. Ab jetzt werden neue automatisch erfasst." % len(new))
        return

    if not new:
        print("Keine neuen gespeicherten Beitraege."); return

    results, failed = [], []
    for sc in list(reversed(new))[:RUN_CAP]:   # oldest first
        url = "https://www.instagram.com/p/%s/" % sc
        try:
            r = requests.post(API, json={"url": url}, timeout=600).json()
        except Exception as e:
            r = {"success": False, "error_code": "transient", "user_message": str(e)}
        if r.get("success"):
            results.append("@%s (%s)" % (r.get("author"), r.get("kind")))
            with open(STATE, "a") as f: f.write(sc + "\n")
        else:
            failed.append("%s: %s" % (sc, r.get("user_message", "?")))
            if r.get("error_code") != "transient":   # permanent -> nicht ewig retryen
                with open(STATE, "a") as f: f.write(sc + "\n")
        time.sleep(3)

    msg = "📥 %d gespeicherte(r) Beitrag/Beitraege erfasst:\n" % len(results) + "\n".join(results)
    if failed: msg += "\n⚠️ Nicht erfasst:\n" + "\n".join(failed)
    if len(new) > RUN_CAP: msg += "\n(%d weitere folgen im naechsten Lauf)" % (len(new) - RUN_CAP)
    print(msg); notify(msg)

if __name__ == "__main__":
    main()
