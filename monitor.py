#!/usr/bin/env python3
"""Monitor CAI pages for all meaningful news; highlight relevant mountain courses."""
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
STATE = ROOT / 'state.json'
SOURCES = ROOT / 'sources.json'
HEADERS = {'User-Agent': 'CAI-course-monitor/2.0 (personal, low-frequency monitoring)'}
RELEVANT = re.compile(
    r'\b(alpinism\w*|arrampicat\w*|multipitch|multi.pitch|vie a pi[uù] tiri|'
    r'ferrat\w*|ghiaccia\w*|ghiaccio|cascat\w*|alta montagna|roccia|'
    r'\bA1\b|\bA2\b|\bAG1\b|\bAR1\b|\bAL1\b|\bM.F1\b)\b', re.I)
GENERIC_COURSE = re.compile(r'\b(corso|corsi|iscrizion\w*|preiscrizion\w*|bando|programma|calendario)\b', re.I)
IGNORE_LINK = re.compile(r'(privacy|cookie|contatti|contact|login|accesso|facebook|instagram|youtube|'
                         r'whatsapp|telegram|mailto:|tel:|wp-admin|feed|rss|javascript:|\bhome\b)', re.I)
CHROME_CLASSES = re.compile(r'(nav|menu|sidebar|footer|header|breadcrumb|cookie|widget|pagination|social|share|search)', re.I)
FILE_SUFFIX = re.compile(r'\.(pdf|docx?|xlsx?|odt|ods)$', re.I)


def canonical(url):
    p = urlsplit(url)
    args = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
            if not k.lower().startswith('utm_') and k.lower() not in ('fbclid', 'gclid')]
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip('/') or '/', urlencode(args), ''))


def norm(text, limit=260):
    return ' '.join(text.split())[:limit]


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]


def relevant(text):
    return bool(RELEVANT.search(text))


def meaningful_title(title):
    return len(title) >= 8 and len(title.split()) >= 2


def is_chrome(el):
    for parent in [el, *list(el.parents)[:5]]:
        if getattr(parent, 'name', None) in ('nav', 'header', 'footer', 'aside'):
            return True
        if getattr(parent, 'attrs', None):
            flags = ' '.join(parent.get('class', [])) + ' ' + str(parent.get('id', ''))
            if CHROME_CLASSES.search(flags):
                return True
    return False


def fetch(source):
    r = requests.get(source['url'], headers=HEADERS, timeout=25)
    r.raise_for_status()
    soup = BeautifulSoup(r.content, 'html.parser')
    for bad in soup(['script', 'style', 'nav', 'footer', 'header', 'form', 'noscript', 'aside', 'svg']):
        bad.decompose()
    for bad in soup.select('[hidden], [aria-hidden="true"]'):
        bad.decompose()
    container = soup.select_one('main, #content, .site-content, .entry-content') or soup.body or soup
    found = {}
    homepage = canonical(source['url'])
    # Every new meaningful content link is eligible, even when it has no keyword.
    for a in container.find_all('a', href=True):
        if is_chrome(a):
            continue
        href = urljoin(source['url'], a['href'])
        if urlsplit(href).scheme not in ('http', 'https'):
            continue
        url = canonical(href)
        if url == homepage or IGNORE_LINK.search(href):
            continue
        title = norm(a.get_text(' ', strip=True))
        parent = a.find_parent(['article', 'li', 'p', 'h2', 'h3', 'h4']) or a.parent
        context = norm(parent.get_text(' ', strip=True), 360) if parent else title
        if not meaningful_title(title):
            if FILE_SUFFIX.search(urlsplit(href).path):
                title = norm(context, 170) or 'Documento pubblicato'
            else:
                continue
        # Ignore purely structural internal links, but keep distinct announcement titles.
        if len(title) > 190:
            title = title[:190]
        marker = digest(title.casefold() + '\n' + context[:180])
        found[url] = {'title': title, 'context_hash': marker, 'relevant': relevant(title + ' ' + context)}
    # Announcements without links: track heading + adjacent announcement text.
    for h in container.find_all(['h2', 'h3', 'h4']):
        if is_chrome(h):
            continue
        title = norm(h.get_text(' ', strip=True), 180)
        if not meaningful_title(title):
            continue
        wrapper = h.find_parent('article') or h.parent
        context = norm(wrapper.get_text(' ', strip=True), 360) if wrapper else title
        key = homepage + '#titolo-' + digest(title.casefold())[:12]
        found.setdefault(key, {'title': title, 'context_hash': digest(title + '\n' + context[:180]),
                               'relevant': relevant(title + ' ' + context)})
    return found


def telegram(message):
    token = os.getenv('TELEGRAM_BOT_TOKEN', '')
    chat_id = os.getenv('TELEGRAM_CHAT_ID', '')
    if not token or not chat_id:
        print('Notifica non inviata: configurare TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID')
        print(message)
        return False
    response = requests.post(f'https://api.telegram.org/bot{token}/sendMessage',
                             data={'chat_id': chat_id, 'text': message, 'disable_web_page_preview': 'true'},
                             timeout=25)
    response.raise_for_status()
    return True


def main():
    sources = json.loads(SOURCES.read_text(encoding='utf-8'))
    state = json.loads(STATE.read_text(encoding='utf-8')) if STATE.exists() else {'sources': {}}
    updates = []
    errors = []
    for source in sources:
        print('Controllo:', source['name'])
        try:
            current = fetch(source)
            if not current:
                raise ValueError('Nessun contenuto monitorabile trovato: archivio precedente conservato')
            old = state.setdefault('sources', {}).get(source['url'])
            if old is not None:
                for url, data in current.items():
                    if url not in old:
                        updates.append((source['name'], 'NUOVO', data, url))
                    elif data['context_hash'] != old[url].get('context_hash'):
                        updates.append((source['name'], 'AGGIORNATO', data, url))
            # A newly configured source is baselined independently (no old-news flood).
            state['sources'][source['url']] = current
            print('  Elementi:', len(current), '| nuove segnalazioni:', len(updates))
        except Exception as exc:
            errors.append(f"{source['name']}: {type(exc).__name__}: {exc}")
            print('  ERRORE:', exc, file=sys.stderr)
        time.sleep(1)
    state['last_checked_utc'] = datetime.now(timezone.utc).isoformat()
    # Send before persisting the state: failed Telegram calls can retry on the next run.
    failed = False
    for name, change, data, link in updates[:25]:
        flag = '🔥 CORSO/ATTIVITA PERTINENTE' if data.get('relevant') else '📰 NOVITA GENERICA'
        try:
            if not telegram(f'🏔️ CAI - {change}\n{flag}\n{name}\n{data["title"]}\n{link}'):
                failed = True
        except requests.RequestException as exc:
            print('Errore Telegram:', exc, file=sys.stderr)
            failed = True
    if len(updates) > 25:
        try:
            if not telegram(f'CAI monitor: altre {len(updates)-25} novita; consulta i log GitHub Actions.'):
                failed = True
        except requests.RequestException:
            failed = True
    if failed and updates:
        print('Invio notifiche non completato: lo stato NON viene aggiornato, ritentero al prossimo controllo.', file=sys.stderr)
        return 1
    STATE.write_text(json.dumps(state, indent=2, ensure_ascii=False, sort_keys=True) + '\n', encoding='utf-8')
    if not updates:
        print('Nessuna nuova pubblicazione o aggiornamento rilevato (o prima acquisizione).')
    if errors:
        print('Pagine non raggiungibili; ritentero al prossimo controllo:', *errors, sep='\n - ', file=sys.stderr)
        if len(errors) == len(sources):
            return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
