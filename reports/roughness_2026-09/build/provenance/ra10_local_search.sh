#!/bin/zsh
# Reproducible local half of the Ra10 search (the Gmail / Calendar / Drive half is
# recorded in ra10_search_log.csv). Read-only. Run from anywhere.
REPO=/Users/stepheneacuello/Projects/windtunnel-control
PAT='Ra ?10\b|v1_Ra10|Ra_10'
echo "## 1. repo working tree (all files incl. logs/ data/ webapp/; excl .git and this dir)"
grep -rIn -E "$PAT" --exclude-dir=.git --exclude-dir=provenance "$REPO" | cut -c1-200
echo "## 2. repo file names"
find "$REPO" -path "$REPO/.git" -prune -o -iname '*ra10*' -print
echo "## 3. git history: pickaxe -S Ra10, -S 'Ra 10', -G v1_Ra10, --stat"
git -C "$REPO" log --all -S Ra10 --oneline
git -C "$REPO" log --all -S 'Ra 10' --oneline
git -C "$REPO" log --all -G 'v1_Ra10' --oneline
git -C "$REPO" log --all --stat | grep -i ra10
echo "## 4. every blade label that appears in logs/ data/ webapp/ src/ tests/ docs/"
grep -rhoI -E 'v[0-9]_Ra[0-9]+[A-Za-z_]*' "$REPO"/{data,webapp,logs,src,tests,docs} | sort | uniq -c | sort -rn
echo "## 5. ~/Downloads ~/Desktop ~/Documents: names (metadata only), then text contents of LOCAL files"
find ~/Downloads ~/Desktop ~/Documents \( -iname '*ra10*' -o -iname '*ra_10*' -o -iname '*ra 10*' -o -iname 'sweep_*' \) 2>/dev/null
# iCloud-evicted ("dataless") files are skipped so the search never triggers a download.
find ~/Downloads ~/Desktop ~/Documents -type f ! -flags +dataless -size -50M \
     \( -iname '*.csv' -o -iname '*.txt' -o -iname '*.md' -o -iname '*.json' -o -iname '*.py' -o -iname '*.tex' -o -iname '*.log' \) -print0 2>/dev/null \
  | xargs -0 grep -lE 'v1_Ra10|\bRa ?10\b' 2>/dev/null
echo "## 6. Spotlight content index, whole home"
mdfind -onlyin ~ '"Ra10"' 2>/dev/null | grep -v '/Library/'
echo "## 7. sweep files anywhere under ~/Projects other than the repo logs"
find ~/Projects -iname 'sweep_v*' -not -path "$REPO/logs/*" 2>/dev/null
