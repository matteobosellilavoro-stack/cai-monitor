#!/usr/bin/env python3
"""CAI page change monitor with per-source evidence and isolated diagnostic tests."""
import argparse
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
REPORT = ROOT / 'diagnostics.json'
HEADERS = {'User-Agent': 'CAI-course-monitor/3.0 (personal, low-frequency monitoring)'}
RELEVANT = re.compile(
    r'\b(alpinism\w*|arrampicat\w*|multipitch|multi.pitch|vie a pi[uù] tiri|'
    r'ferrat\w*|ghiaccia\w*|ghiaccio|cascat\w*|alta montagna|roccia|'
    r'A1|A2|AG1|AR1|AL1|M.F1)\b', re.I)
IGNORE_LINK = re.compile(r'(privacy|cookie|contatti|contact|login|accesso|facebook|instagram|youtube|'
                         r'whatsapp|telegram|mailto:|tel:|wp-admin|feed|rss|javascript:|\bhome\b)', re.I)
CHROME_CLASSES = re.compile(r'(nav|menu|sidebar|footer|header|breadcrumb|cookie|widget|pagination|social|share|search)', re.I)
FILE_SUFFIX = re.compile(r'\.(pdf|docx?|xlsx?|odt|ods)$', re.I)


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


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


def extract(source, html):
    """Return ordered entries. First element means first in document, not newest by date."""
    soup = BeautifulSoup(html, 'html.parser')
    for bad in soup(['script', 'style', 'nav', 'footer', 'header', 'form', 'noscript', 'aside', 'svg']):
        bad.decompose()
    for bad in soup.select('[hidden], [aria-hidden="true"]'):
        bad.decompose()
    container = soup.select_one('main, #content, .site-content, .entry-content') or soup.body or soup
    found = {}
    home = canonical(source['url'])
    for el in container.find_all(['a', 'h2', 'h3', 'h4']):
        if is_chrome(el):
            continue
        if el.name == 'a':
            if not el.has_attr('href'):
                continue
            href = urljoin(source['url'], el['href'])
            if urlsplit(href).scheme not in ('http', 'https'):
                continue
            url = canonical(href)
            if url == home or IGNORE_LINK.search(href):
                continue
            title = norm(el.get_text(' ', strip=True))
            parent = el.find_parent(['article', 'li', 'p', 'h2', 'h3', 'h4']) or el.parent
            context = norm(parent.get_text(' ', strip=True), 360) if parent else title
            if not meaningful_title(title):
                if FILE_SUFFIX.search(urlsplit(href).path):
                    title = norm(context, 170) or 'Documento pubblicato'
                else:
                    continue
            title = title[:190]
        else:
            title = norm(el.get_text(' ', strip=True), 180)
            if not meaningful_title(title):
                continue
            wrapper = el.find_parent('article') or el.parent
            context = norm(wrapper.get_text(' ', strip=True), 360) if wrapper else title
            url = home + '#titolo-' + digest(title.casefold())[:12]
        data = {'title': title, 'context_hash': digest(title.casefold() + '\n' + context[:180]),
                'relevant': relevant(title + ' ' + context)}
        found.setdefault(url, data)
    return found


def fetch(source):
    started = time.monotonic()
    r = requests.get(source['url'], headers=HEADERS, timeout=25)
    r.raise_for_status()
    found = extract(source, r.content)
    return found, {'http_status': r.status_code, 'final_url': r.url,
                   'elapsed_seconds': round(time.monotonic() - started, 2),
                   'bytes_downloaded': len(r.content), 'content_sha256': hashlib.sha256(r.content).hexdigest()}


def telegram(message):
    token = os.getenv('TELEGRAM_BOT_TOKEN', '')
    chat_id = os.getenv('TELEGRAM_CHAT_ID', '')
    if not token or not chat_id:
        raise RuntimeError('Secret TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID mancante')
    response = requests.post(f'https://api.telegram.org/bot{token}/sendMessage',
                             data={'chat_id': chat_id, 'text': message[:3900], 'disable_web_page_preview': 'true'},
                             timeout=25)
    response.raise_for_status()
    payload = response.json()
    if not payload.get('ok'):
        raise RuntimeError('Telegram ha rifiutato il messaggio')


def classify_updates(old, current):
    if old is None:
        return []
    result = []
    for url, data in current.items():
        if url not in old:
            result.append(('NUOVO', data, url))
        elif data['context_hash'] != old[url].get('context_hash'):
            result.append(('AGGIORNATO', data, url))
    return result


def save_json(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + '\n', encoding='utf-8')


def preview(entries):
    """Evidence: first *visible extracted* item in DOM order, not verified publication date."""
    if not entries:
        return None
    url = next(iter(entries))
    return {'title': entries[url]['title'], 'url': url}


def diagnostic_text(rows, at):
    ok = sum(row['status'] == 'OK' for row in rows)
    lines = [f'🏔️ CAI - DIAGNOSTICA {at[:16]} UTC',
             f'Siti letti: {ok}/{len(rows)}. Elenco: primo elemento estratto, NON data di pubblicazione verificata.']
    for row in rows:
        p = row.get('first_item') or {}
        symbol = '✅' if row['status'] == 'OK' else '❌'
        lines.append(f"\n{symbol} {row['name']}: {row.get('count', 0)} elementi | "
                     f"{row.get('changes', 0)} variazioni | HTTP {row.get('http_status', '-')}" )
        if p:
            lines.append(f"Primo: {p['title'][:100]}\n{p['url']}")
        if row.get('error'):
            lines.append('Errore: ' + row['error'][:120])
        if row.get('last_success_utc') and row['status'] != 'OK':
            lines.append('Ultima lettura riuscita: ' + row['last_success_utc'])
    return '\n'.join(lines)


def simulation():
    """Fixture: tests recognition and Telegram, never reads/writes state.json."""
    source = {'name': 'SIMULAZIONE', 'url': 'https://example.invalid/cai/'}
    base = '<main><article><a href="/programma">Programma iniziale della scuola</a></article></main>'
    changed = '''<main><article><a href="/programma">Programma iniziale della scuola</a></article>
    <article><a href="/a1">Corso alpinismo A1 iscrizioni aperte 2027</a></article>
    <article><a href="/primavera">Programma attivita primavera 2027</a></article></main>'''
    before, after = extract(source, base), extract(source, changed)
    updates = classify_updates(before, after)
    assert len(updates) == 2, f'Attesi 2 nuovi elementi, trovati {len(updates)}'
    assert sum(d['relevant'] for _, d, _ in updates) == 1
    assert not classify_updates(after, after), 'Duplicati non filtrati'
    telegram('🧪 TEST CAI MONITOR - simulazione superata\n'
             '🔥 Corso di alpinismo: rilevato\n'
             '📰 Novita generica: rilevata\n'
             '✅ Secondo passaggio: zero duplicati\n'
             'Questo test NON modifica lo storico reale e NON prova la lettura dei siti CAI.')
    print('TEST SUPERATO: 2 nuovi, 1 pertinente, 1 generico, 0 duplicati, Telegram OK')
    return 0


def main(mode):
    if mode == 'test':
        return simulation()
    sources = json.loads(SOURCES.read_text(encoding='utf-8'))
    state = json.loads(STATE.read_text(encoding='utf-8')) if STATE.exists() else {'sources': {}}
    state.setdefault('sources', {})
    state.setdefault('last_success', {})
    rows, updates = [], []
    at = utcnow()
    for source in sources:
        name, url = source['name'], source['url']
        print('Controllo:', name, '|', url, flush=True)
        row = {'name': name, 'source_url': url, 'checked_utc': at, 'status': 'ERROR',
               'last_success_utc': state['last_success'].get(url)}
        try:
            current, evidence = fetch(source)
            if not current:
                raise ValueError('Nessun elemento estraibile: archivio non aggiornato')
            old = state['sources'].get(url)
            changes = classify_updates(old, current)
            updates.extend((name, change, data, link) for change, data, link in changes)
            row.update({'status': 'OK', 'count': len(current), 'changes': len(changes),
                        'baseline_created': old is None, 'first_item': preview(current),
                        'last_success_utc': at, **evidence})
            # Stage in-memory; do not persist until Telegram notifications have been delivered.
            state['sources'][url] = current
            state['last_success'][url] = at
            print('  HTTP:', evidence['http_status'], '| elementi:', len(current),
                  '| variazioni:', len(changes), '| primo:', row['first_item']['title'], flush=True)
        except Exception as exc:
            row['error'] = f'{type(exc).__name__}: {exc}'
            print('  ERRORE:', row['error'], file=sys.stderr, flush=True)
        rows.append(row)
        time.sleep(0.5)
    report = {'generated_utc': at, 'sources': rows, 'changes_detected': len(updates),
              'explanation': 'first_item e il primo elemento estratto dalla pagina, non necessariamente il piu recente cronologicamente.'}
    save_json(REPORT, report)
    print('\n' + diagnostic_text(rows, at), flush=True)
    failed = False
    for name, change, data, link in updates:
        flag = '🔥 CORSO/ATTIVITA PERTINENTE' if data.get('relevant') else '📰 NOVITA GENERICA'
        try:
            telegram(f'🏔️ CAI - {change}\n{flag}\n{name}\n{data["title"]}\n{link}')
        except Exception as exc:
            print('NOTIFICA FALLITA:', type(exc).__name__, str(exc), file=sys.stderr)
            failed = True
            break
    # Send diagnostics on manual invocation, and on the scheduled evening check in Italy.
    should_send_report = mode == 'diagnostic' or (os.getenv('GITHUB_EVENT_NAME') == 'schedule' and os.getenv('GITHUB_SCHEDULE', '').startswith('17 18 '))
    if should_send_report:
        try:
            telegram(diagnostic_text(rows, at))
        except Exception as exc:
            print('REPORT TELEGRAM FALLITO:', type(exc).__name__, str(exc), file=sys.stderr)
            failed = True
    if failed:
        print('Stato NON salvato: riprovera al prossimo controllo. diagnostics.json resta consultabile.', file=sys.stderr)
        return 1
    state['last_checked_utc'] = at
    save_json(STATE, state)
    if all(row['status'] == 'ERROR' for row in rows):
        return 1
    if any(row['status'] == 'ERROR' for row in rows):
        print('ATTENZIONE: alcune fonti non sono state lette. Vedi diagnostics.json e log.', file=sys.stderr)
    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['normal', 'diagnostic', 'test'], default='normal')
    args = parser.parse_args()
    try:
        sys.exit(main(args.mode))
    except Exception as exc:
        print(f'ERRORE FATALE: {type(exc).__name__}: {exc}', file=sys.stderr)
        sys.exit(1)
