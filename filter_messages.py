#!/usr/bin/env python3
"""
Interactively filter a Discord JSON export.

Usage:
    python filter_messages.py messages.json
    python filter_messages.py messages.json --freq --min-dupes 5

Modes:
    default : walks through messages in order (oldest -> newest)
    --freq  : shows each unique message ONCE, most common first.
              Much faster for clearing out "hi", "lol", etc.

Your original file is never modified. Output goes to <name>_filtered.json
and your progress is saved to <name>.json.progress.json so you can resume.
"""
import argparse
import json
import os
import re
import sys
from collections import defaultdict

AUTOSAVE_EVERY = 25

# Scripts written without spaces between words (Chinese, Japanese kana/kanji, Thai,
# Lao, Burmese, Khmer). Each character counts as one "word" so a whole sentence is
# never mistaken for a single word.
_UNSPACED = (r"\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
             r"\u0e00-\u0eff\u1000-\u109f\u1780-\u17ff")
_WORD_RE = re.compile(rf"[{_UNSPACED}]|[^\s{_UNSPACED}]+")
_HAS_UNSPACED = re.compile(rf"[{_UNSPACED}]")


def count_words(text):
    return len(_WORD_RE.findall(text))


def load(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data, data
    if isinstance(data, dict) and isinstance(data.get("messages"), list):
        return data, data["messages"]
    sys.exit("Couldn't find a message list (expected a list, or an object with a 'messages' key).")


def save_output(data, msgs, deleted, out_path):
    kept = [m for i, m in enumerate(msgs) if i not in deleted]
    if isinstance(data, list):
        result = kept
    else:
        result = dict(data)
        result["messages"] = kept
        if "messageCount" in result:
            result["messageCount"] = len(kept)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return len(kept)


def save_progress(path, msgs, deleted, seen, kept_keys, protected=()):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "deleted_ids": [msgs[i].get("id") for i in deleted],
                "seen_ids": [msgs[i].get("id") for i in seen],
                "kept_keys": sorted(kept_keys),
                "protected_ids": [msgs[i].get("id") for i in protected],
            },
            f,
        )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("-o", "--output")
    ap.add_argument("--freq", action="store_true", help="review each unique message once, most common first")
    ap.add_argument("--min-dupes", type=int, default=1, help="(--freq) only show messages appearing at least N times")
    ap.add_argument("--case-sensitive", action="store_true", help="treat 'Hi' and 'hi' as different")
    ap.add_argument("--newest-first", action="store_true",
                    help="review from most recent to oldest instead of oldest first")
    ap.add_argument("--restore-cjk", action="store_true",
                    help="un-delete every previously deleted message containing Chinese/Japanese/Thai text")
    ap.add_argument("--keep-attachments", action="store_true",
                    help="protect every message with an attachment from deletion (and skip it in review)")
    ap.add_argument("--delete-bots", action="store_true", help="delete every message from a bot")
    ap.add_argument("--delete-role", action="append", default=[], metavar="ROLE",
                    help="delete every message from users with this role (name or id). Repeatable.")
    ap.add_argument("--delete-user", action="append", default=[], metavar="USER",
                    help="delete every message from this user (username, nickname or id). Repeatable.")
    args = ap.parse_args()

    out_path = args.output or os.path.splitext(args.input)[0] + "_filtered.json"
    prog_path = args.input + ".progress.json"

    print("Loading...")
    data, msgs = load(args.input)

    def key_of(m):
        c = (m.get("content") or "").strip()
        return c if args.case_sensitive else c.lower()

    keys = [key_of(m) for m in msgs]
    groups = defaultdict(list)  # content key -> [message indices]
    for i, k in enumerate(keys):
        groups[k].append(i)

    id_to_idx = {m.get("id"): i for i, m in enumerate(msgs)}
    deleted, seen, kept_keys, protected = set(), set(), set(), set()

    if os.path.exists(prog_path):
        with open(prog_path, encoding="utf-8") as f:
            p = json.load(f)
        deleted = {id_to_idx[x] for x in p.get("deleted_ids", []) if x in id_to_idx}
        seen = {id_to_idx[x] for x in p.get("seen_ids", []) if x in id_to_idx}
        kept_keys = set(p.get("kept_keys", []))
        protected = {id_to_idx[x] for x in p.get("protected_ids", []) if x in id_to_idx}
        print(f"Resumed: {len(deleted)} deleted so far, {len(kept_keys)} contents marked keep, "
              f"{len(protected)} messages protected.")

    if args.restore_cjk:
        back = [i for i in deleted if _HAS_UNSPACED.search(msgs[i].get("content") or "")]
        deleted.difference_update(back)
        save_progress(prog_path, msgs, deleted, seen, kept_keys, protected)
        print(f"Restored {len(back)} previously deleted message(s) containing Chinese/Japanese/Thai text.")

    def new_attachment_idxs():
        return [i for i, mm in enumerate(msgs)
                if mm.get("attachments") and i not in deleted and i not in protected]

    if args.keep_attachments:
        newly = new_attachment_idxs()
        protected.update(newly)
        print(f"Protected {len(newly)} messages with attachments (they won't be deleted or shown).")

    # ---- Bulk deletion rules (bots / roles / users) ----
    rules = []  # (label, predicate on author dict)
    if args.delete_bots:
        rules.append(("bots", lambda a: bool(a.get("isBot"))))
    for r in args.delete_role:
        rl = r.strip().lower()
        rules.append((
            f"role '{r}'",
            lambda a, rl=rl: any(
                rl in ((x.get("name") or "").lower(), str(x.get("id")))
                for x in (a.get("roles") or [])
            ),
        ))
    for u in args.delete_user:
        ul = u.strip().lower()
        rules.append((
            f"user '{u}'",
            lambda a, ul=ul: ul in (
                (a.get("name") or "").lower(),
                (a.get("nickname") or "").lower(),
                str(a.get("id")),
            ),
        ))

    if rules:
        hits = {label: [] for label, _ in rules}
        for i, m in enumerate(msgs):
            if i in deleted or i in protected:
                continue
            a = m.get("author") or {}
            for label, pred in rules:
                if pred(a):
                    hits[label].append(i)
        to_delete = set()
        print("Bulk deletion preview:")
        for label, idxs in hits.items():
            note = "  <-- no matches, check spelling" if not idxs else ""
            print(f"  {label}: {len(idxs)} message(s){note}")
            to_delete.update(idxs)
        if to_delete:
            ans = input(f"Delete these {len(to_delete)} messages now? [y/N] ").strip().lower()
            if ans == "y":
                deleted.update(to_delete)
                save_progress(prog_path, msgs, deleted, seen, kept_keys, protected)
                print(f"  Deleted {len(to_delete)} messages.\n")
            else:
                print("  Skipped bulk deletion.\n")

    def live(k):
        return [i for i in groups[k] if i not in deleted and i not in protected]

    # Build the review queue (only things that are still left to review)
    if args.freq:
        live_groups = []
        for k, v in groups.items():
            if k in kept_keys:
                continue
            lv = [i for i in v if i not in deleted and i not in protected]
            if lv and len(lv) >= args.min_dupes:
                live_groups.append(lv)
        if args.newest_first:
            for lv in live_groups:
                lv.reverse()  # newest message becomes the one shown
            live_groups.sort(key=lambda lv: (-len(lv), -lv[0]))
        else:
            live_groups.sort(key=lambda lv: (-len(lv), lv[0]))
        queue = [lv[0] for lv in live_groups if lv[0] not in seen]
    else:
        queue = [i for i in range(len(msgs))
                 if i not in deleted and i not in protected and i not in seen
                 and keys[i] not in kept_keys]
        if args.newest_first:
            queue.reverse()

    remaining_msgs = len(msgs) - len(deleted)
    remaining_unique = sum(1 for k in groups if any(i not in deleted for i in groups[k]))
    print(f"{remaining_msgs} messages remaining, {remaining_unique} unique contents, "
          f"{len(queue)} items to review.")
    print("Commands: [d]elete this  [a]ll-delete every message with this content  "
          "[x] delete everything by this author  [f]ilter by dupes/length  [n] delete short unique  [c]ontains word  [l]ist users  [p]rotect attachments  [s]kip  "
          "[k]eep all of this content  [u]ndo  [w]rite  [q]uit+save\n")

    stack = []  # undo history
    pos = 0
    since_save = 0

    def do_save(final=False):
        n = save_output(data, msgs, deleted, out_path)
        save_progress(prog_path, msgs, deleted, seen, kept_keys, protected)
        print(f"  Saved {n} messages to {out_path}" + (" (done)" if final else ""))

    try:
        while pos < len(queue):
            idx = queue[pos]
            k = keys[idx]
            if idx in deleted or idx in protected or idx in seen or k in kept_keys:
                pos += 1
                continue

            m = msgs[idx]
            members = live(k)
            authors = {msgs[i].get("author", {}).get("id") for i in members}
            a = m.get("author", {})
            name = a.get("nickname") or a.get("name") or "?"
            content = m.get("content") or ""
            shown = content if content else "(no text - attachment/embed/etc.)"
            if len(shown) > 600:
                shown = shown[:600] + "..."

            print("-" * 60)
            print(f"[{pos + 1}/{len(queue)}]  {(m.get('timestamp') or '')[:19]}  {name} ({a.get('name', '?')})")
            print(f"  {shown}")
            if len(members) > 1:
                print(f"  >> {len(members)} messages with this content, from {len(authors)} author(s)")
            else:
                print("  >> unique")

            while True:
                cmd = input("  [d/a/x/f/n/c/l/p/s/k/u/w/q] > ").strip().lower() or "s"
                if cmd in ("d", "a", "x", "f", "n", "c", "l", "p", "s", "k", "u", "w", "q"):
                    break
                print("  ?  d=delete this, a=delete all duplicates, x=delete all by this author, "
                      "f=filter by dupes/length, n=delete short unique, c=delete containing a word, l=list users, p=protect attachments, s=skip, k=keep all, u=undo, w=save, q=quit")

            if cmd == "q":
                break
            if cmd == "w":
                do_save()
                continue
            if cmd == "u":
                if not stack:
                    print("  Nothing to undo.")
                    continue
                last = stack.pop()
                deleted -= set(last["deleted"])
                protected -= set(last.get("protected", []))
                if last["seen"] is not None:
                    seen.discard(last["seen"])
                if last["kept"] is not None:
                    kept_keys.discard(last["kept"])
                pos = last["pos"]
                print("  Undone.")
                continue

            if cmd == "p":
                newly = new_attachment_idxs()
                already_gone = sum(1 for i in deleted if msgs[i].get("attachments"))
                protected.update(newly)
                stack.append({"pos": pos, "deleted": [], "seen": None, "kept": None, "protected": newly})
                print(f"  Protected {len(newly)} message(s) with attachments from further deletion.")
                if already_gone:
                    print(f"  ({already_gone} attachment message(s) were already deleted earlier; "
                          f"use u or delete the .progress.json file to bring them back.)")
                continue

            if cmd == "l":
                counts, info = {}, {}
                for i, mm in enumerate(msgs):
                    au = mm.get("author") or {}
                    uid = au.get("id")
                    info[uid] = au  # keeps the most recent name/nickname seen
                    if i not in deleted:
                        counts[uid] = counts.get(uid, 0) + 1
                rows = sorted(counts.items(), key=lambda kv: -kv[1])
                print(f"  {len(rows)} users with messages remaining:")
                print(f"  {'MSGS':>7}  {'USERNAME':<24} {'NICKNAME':<24} ID")
                for uid, n_ in rows:
                    au = info[uid]
                    tag = "  [BOT]" if au.get("isBot") else ""
                    print(f"  {n_:>7}  {str(au.get('name', '?')):<24} "
                          f"{str(au.get('nickname') or ''):<24} {uid}{tag}")
                print("  (use x to delete one author's messages, or --delete-user at startup)")
                continue

            if cmd == "c":
                term = input("  Delete messages containing (word or phrase): ").strip()
                if not term:
                    print("  Cancelled.")
                    continue
                whole = input("  Whole word only? (so 'ass' won't match 'class') [Y/n]: ").strip().lower() != "n"
                pat = re.escape(term)
                if whole:
                    pat = r"(?<!\w)" + pat + r"(?!\w)"
                rx = re.compile(pat, 0 if args.case_sensitive else re.IGNORECASE)
                matched, excluded = [], 0
                for i, mm in enumerate(msgs):
                    if i in deleted or i in protected:
                        continue
                    c = mm.get("content") or ""
                    if c and rx.search(c):
                        if keys[i] in kept_keys:
                            excluded += 1
                        else:
                            matched.append(i)
                if excluded:
                    print(f"  ({excluded} match(es) left alone because you marked that content 'keep')")
                if not matched:
                    print("  No messages match.")
                    continue
                from collections import Counter
                top = Counter(keys[i] for i in matched).most_common(8)
                print(f"  {len(matched)} message(s) contain {term!r}. Most common:")
                for t, n_ in top:
                    print(f"    {n_:>6} x {t[:70]!r}")
                if input(f"  Delete all {len(matched)}? [y/N] ").strip().lower() != "y":
                    print("  Cancelled.")
                    continue
                deleted.update(matched)
                stack.append({"pos": pos, "deleted": matched, "seen": None, "kept": None})
                print(f"  Deleted {len(matched)} message(s).")
                continue

            if cmd == "n":
                v = input("  Delete unique messages with at most how many words? [default 2]: ").strip()
                max_words = int(v) if v.isdigit() else 2
                matched = []
                for gk, gv in groups.items():
                    if not gk or gk in kept_keys:  # skip empty and 'keep' marked content
                        continue
                    lv = [i for i in gv if i not in deleted and i not in protected]
                    if len(lv) != 1:
                        continue
                    c = (msgs[lv[0]].get("content") or "").strip()
                    if count_words(c) <= max_words:
                        matched.append(lv[0])
                if not matched:
                    print("  No messages match.")
                    continue
                print(f"  {len(matched)} unique message(s) of {max_words} word(s) or fewer. Samples:")
                for i in matched[:8]:
                    print(f"    {(msgs[i].get('content') or '').strip()[:60]!r}")
                if input(f"  Delete all {len(matched)}? [y/N] ").strip().lower() != "y":
                    print("  Cancelled.")
                    continue
                deleted.update(matched)
                stack.append({"pos": pos, "deleted": matched, "seen": None, "kept": None})
                print(f"  Deleted {len(matched)} message(s).")
                continue

            if cmd == "f":
                def ask(label):
                    v = input(f"  {label} [blank = no limit]: ").strip()
                    return int(v) if v.isdigit() else None
                fx = ask("Has at least X identical messages (X)")
                fy = ask("Has at most Y words (Y)")
                fz = ask("Is fewer than Z characters (Z)")
                if fx is None and fy is None and fz is None:
                    print("  No conditions given, cancelled.")
                    continue
                matched = []
                for gk, gv in groups.items():
                    if not gk:  # skip attachment-only / empty messages
                        continue
                    lv = [i for i in gv if i not in deleted and i not in protected]
                    if fx is not None and len(lv) < fx:
                        continue
                    for i in lv:
                        c = (msgs[i].get("content") or "").strip()
                        if fy is not None and count_words(c) > fy:
                            continue
                        if fz is not None and len(c) >= fz:
                            continue
                        matched.append(i)
                if not matched:
                    print("  No messages match.")
                    continue
                from collections import Counter
                top = Counter(keys[i] for i in matched).most_common(5)
                print(f"  {len(matched)} message(s) match. Most common:")
                for t, n in top:
                    print(f"    {n:>6} x {t[:60]!r}")
                if input(f"  Delete all {len(matched)}? [y/N] ").strip().lower() != "y":
                    print("  Cancelled.")
                    continue
                deleted.update(matched)
                stack.append({"pos": pos, "deleted": matched, "seen": None, "kept": None})
                print(f"  Deleted {len(matched)} message(s).")
                continue

            entry = {"pos": pos, "deleted": [], "seen": None, "kept": None}
            if cmd == "x":
                aid = a.get("id")
                theirs = [i for i, mm in enumerate(msgs)
                          if i not in deleted and i not in protected
                          and (mm.get("author") or {}).get("id") == aid]
                ans = input(f"  Delete ALL {len(theirs)} messages by {name}? [y/N] ").strip().lower()
                if ans != "y":
                    print("  Cancelled.")
                    continue
                entry["deleted"] = theirs
                deleted.update(theirs)
                print(f"  Deleted {len(theirs)} message(s).")
            elif cmd == "a" or (cmd == "d" and args.freq):
                entry["deleted"] = members[:]
                deleted.update(members)
                print(f"  Deleted {len(members)} message(s).")
            elif cmd == "d":
                entry["deleted"] = [idx]
                deleted.add(idx)
                print("  Deleted 1 message.")
            elif cmd == "k":
                entry["kept"] = k
                kept_keys.add(k)
            else:  # skip
                entry["seen"] = idx
                seen.add(idx)

            stack.append(entry)
            pos += 1
            since_save += 1
            if since_save >= AUTOSAVE_EVERY:
                save_progress(prog_path, msgs, deleted, seen, kept_keys, protected)
                since_save = 0
    except (KeyboardInterrupt, EOFError):
        print("\nInterrupted.")

    do_save(final=pos >= len(queue))
    print(f"Removed {len(deleted)} messages total.")


if __name__ == "__main__":
    main()