"""Print each message of a saved Gmail get_thread JSON with quoted history removed."""
import json, sys, re
d = json.load(open(sys.argv[1]))
maxc = int(sys.argv[2]) if len(sys.argv) > 2 else 4000
for m in d['messages']:
    body = m.get('plaintextBody', '') or ''
    lines = [l for l in body.splitlines() if not l.lstrip().startswith('>')]
    txt = '\n'.join(lines)
    txt = re.split(r'\n\s*On [A-Z][a-z]{2}, [A-Z][a-z]{2} \d{1,2}, \d{4}', txt)[0]
    txt = re.sub(r'\n{3,}', '\n\n', txt)
    print('=====', m['id'], m['date'], m['sender'], '->', m.get('toRecipients'), 'cc', m.get('ccRecipients'), '|', m.get('subject'))
    att = [a['filename'] for a in m.get('attachments', [])]
    if att: print('attachments:', att)
    print(txt[:maxc].strip())
