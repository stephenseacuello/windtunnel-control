"""Decode a Gmail RAW get_message JSON dump (saved by the tool harness) and
extract every non-text MIME part to this directory. Usage:
  python3 decode_mime.py <tool-result.txt> <prefix>
"""
import json, sys, base64, email, os, hashlib
from email import policy
src, prefix = sys.argv[1], sys.argv[2]
d = json.load(open(src))
raw = d['raw']
try:
    b = base64.urlsafe_b64decode(raw + '=' * (-len(raw) % 4))
except Exception:
    b = raw.encode()
msg = email.message_from_bytes(b, policy=policy.default)
print('Message-ID', d.get('id'), 'Subject:', msg['subject'], 'Date:', msg['date'], 'From:', msg['from'])
here = os.path.dirname(os.path.abspath(__file__))
for i, part in enumerate(msg.walk()):
    ct = part.get_content_type()
    fn = part.get_filename()
    if part.is_multipart():
        continue
    payload = part.get_payload(decode=True)
    if ct.startswith('text/'):
        continue
    name = f"{prefix}__{fn or ('part%d' % i)}"
    path = os.path.join(here, name)
    open(path, 'wb').write(payload)
    print('saved', path, ct, len(payload), 'bytes sha256', hashlib.sha256(payload).hexdigest()[:16])
