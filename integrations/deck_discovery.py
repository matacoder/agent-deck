"""Finding DeckAway computers: Tailscale peers and the neighbours of the local network."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import copy
import http.client
import ipaddress
import json
import re
import shutil
import subprocess
import threading
from pathlib import Path
from urllib.parse import urlsplit

from . import deck_transport as transport
from .lan import is_tailnet, neighbours
from .relay import private_write

IDENTITY = re.compile(r'[0-9a-f]{24}\Z')
MAX_ADDRESSES = 4


class Discovery:
    """The search half of `RemoteDecks`: it reads `profiles`, `lock`, `instance`, `local_url`, `local_address`."""
    def discover(self, port=8790):
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValueError('Enter a valid DeckAway port')
        with self.lock:
            if self.discovery['phase'] == 'running':return copy.deepcopy(self.discovery)
            self.discovery = {'phase':'running','results':[]}
        threading.Thread(target=self._discover, args=(port,), daemon=True).start()
        return self.status()['discovery']

    def tailscale_peers(self, port):
        binary = shutil.which('tailscale')
        app = Path('/Applications/Tailscale.app/Contents/MacOS/Tailscale')
        binary = binary or (str(app) if app.is_file() else None)
        if not binary:raise ValueError('Tailscale is not installed on the gateway')
        result = subprocess.run([binary,'status','--json'], input='', capture_output=True, text=True, timeout=5, check=True)
        status = json.loads(result.stdout)
        if status.get('BackendState') != 'Running':raise ValueError('Connect the gateway to Tailscale')
        peers, seen = [], set()
        for peer in (status.get('Peer') or {}).values():
            if peer.get('Online') is False:continue
            for raw in peer.get('TailscaleIPs', []):
                try:address = ipaddress.ip_address(raw)
                except ValueError:continue
                if address.version != 4 or address not in transport.TAILNET or str(address) in seen:continue
                seen.add(str(address));peers.append({'url':f'http://{address}:{port}', 'name':' '.join(str(peer.get('HostName') or address).split())[:100]})
        return peers[:128]

    def _discover(self, port):
        try:
            try:
                peers = self.tailscale_peers(port)
            except (OSError, subprocess.SubprocessError, ValueError, TypeError, AttributeError):
                peers = None  # A computer without Tailscale still has its local network.
            local = self.local_address()
            if peers is None and not local:
                raise ValueError('No network to search')
            targets = (peers or []) + [{'url': f'http://{address}:{port}', 'name': address} for address in (neighbours(local) if local else [])]
            found = []
            with ThreadPoolExecutor(max_workers=32) as pool:
                futures = {pool.submit(self._probe, p):p for p in targets}
                for future in as_completed(futures):
                    answer = future.result()
                    if answer:
                        found.append({**futures[future], **(answer if isinstance(answer, dict) else {})})
                        with self.lock:self.discovery['results'] = self.merged(found)
            with self.lock:
                results = self.merged(found)
                self.remember(found)
                self.discovery = {'phase':'done','results':results}
        except (OSError, subprocess.SubprocessError, ValueError, TypeError, AttributeError):
            with self.lock:self.discovery = {'phase':'error','results':[], 'error':'Could not discover DeckAway instances; check Tailscale or the local network on the gateway'}

    def merged(self, found):
        """One row per computer: the same one seen over Tailscale and in the local network names itself by
        the same id. This computer and the ones already connected are left out."""
        with self.lock:
            saved = {p.get('instance') for p in self.profiles.values() if p.get('instance')}
            known = {u for p in self.profiles.values() for u in self.addresses(p)}
        rows, own = {}, self.instance()
        for item in sorted(found, key=lambda i: not is_tailnet(urlsplit(i['url']).hostname)):
            instance = item.get('instance', '')
            if item['url'] in known or item['url'] == self.local_url or (instance and instance in saved | {own}):
                continue
            row = rows.setdefault(instance or item['url'], {'name': item['name'], 'url': item['url'], 'urls': [], 'instance': instance})
            if item['url'] != row['url'] and len(row['urls']) < MAX_ADDRESSES:
                row['urls'].append(item['url'])
        return sorted(rows.values(), key=lambda row: row['name'].casefold())

    def remember(self, found):
        """A connected computer found on one more address keeps it. The address is only a claim until it
        proves the pair key, so nothing is trusted here."""
        changed = False
        for profile in self.profiles.values():
            if not profile.get('instance') or not profile.get('pair'):
                continue
            new = [i['url'] for i in found if i.get('instance') == profile['instance'] and i['url'] not in self.addresses(profile)]
            if new:
                # A claim never pushes out an address already kept: the owner removes those.
                profile['urls'] = (profile.get('urls', []) + new)[:MAX_ADDRESSES]
                changed = True
        if changed:
            try:private_write(self.path, self.profiles)
            except (OSError, ValueError):pass  # Found again by the next search.

    @staticmethod
    def _probe(profile):
        try:
            status, headers, body = transport.http_request(profile['url'], 'GET', '/api/hello', timeout=2, limit=65536)
            if status == 200:
                answer = json.loads(body)
                if answer.get('app') != 'away-deck' or not isinstance(answer.get('id'), str) or not IDENTITY.fullmatch(answer['id']):
                    return False
                name = answer.get('name')
                return {'instance': answer['id'], **({'name': ' '.join(name.split())[:100]} if isinstance(name, str) and name.strip() and name.isprintable() else {})}
            # A panel before 1.44 does not introduce itself; its sign-in page still tells what it is.
            status, headers, body = transport.http_request(profile['url'], 'GET', '/login', timeout=2, limit=1024*1024)
            server = next((v for k,v in headers.items() if k.lower() == 'server'), '')
            return status == 200 and ('cc-panel/' in server or b'<title>DeckAway' in body
                                      or b'<title>Away Deck' in body or b'<title>Agent Deck' in body)  # Earlier names.
        except (OSError, http.client.HTTPException, ValueError, AttributeError):return False
