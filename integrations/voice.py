"""Speech to text with whisper.cpp on this computer: the page records, this turns one piece of it into text.

Nothing leaves the computer: the recording is written to a private temporary folder, read by whisper-cli and
deleted. The model is downloaded once, resumed after a broken connection and checked against its hash.
"""
import base64
import contextlib
import hashlib
import itertools
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.request

MODEL = {'name': 'ggml-large-v3-turbo-q8_0.bin', 'size': 874188075,
         'sha256': '317eb69c11673c9de1e1f0d459b253999804ec71ac4c23c17ecf5fbe24e259a1'}
MODEL_URL = 'https://huggingface.co/ggerganov/whisper.cpp/resolve/main/' + MODEL['name']
# launchd and systemd start the panel with a short PATH; Homebrew puts whisper-cli in one of these.
SEARCH = ('/opt/homebrew/bin', '/usr/local/bin')
# A piece must fit the panel's 1 MB JSON limit once in base64: about 22 s of 16 kHz mono speech.
MAX_AUDIO_BYTES = 720_000
LANGUAGE = re.compile(r'^(auto|[a-z]{2,3})$')
# whisper writes these for silence or noise; they are not speech.
NOISE = re.compile(r'^\s*[\[(][^\])]*[\])]\s*$')
CHUNK = 1 << 20
# A copy already on the computer is used instead of a new one: whisper.cpp built in a folder of its own,
# Homebrew's, or the models of an app such as MacWhisper. Folders macOS guards (Documents, Desktop...) are
# never looked into: a background panel reading them would make macOS ask the owner for permission.
GUARDED = {'Desktop', 'Documents', 'Downloads', 'Library', 'Movies', 'Music', 'Pictures', 'Public', 'Applications'}
MODEL_FOLDERS = ('.cache/agent-deck/whisper', 'whisper.cpp/models', '.cache/whisper.cpp', '.local/share/whisper.cpp',
                 'Library/Application Support/MacWhisper/models', 'Library/Application Support/superwhisper',
                 '/opt/homebrew/share/whisper-cpp', '/usr/local/share/whisper-cpp')
# Apps that keep whisper models of their own, under names of their own: searched by content, not by name.
APP_FOLDERS = ('Library/Application Support/Rogue Amoeba/Transcription Models', 'Library/Application Support/Audio Hijack',
               'Library/Application Support/noScribe', 'Library/Application Support/MacWhisper')
BUILT = ('whisper.cpp/build/bin/whisper-cli', 'whisper.cpp/whisper-cli')
# Better first; an English-only model (.en) only when nothing else is there.
SIZES = ('large-v3-turbo', 'large-v3', 'large-v2', 'large', 'medium', 'small', 'base', 'tiny')
LOOK_AGAIN = 60


def home_folders(home, tail):
    """tail under home and under each of its folders, one or two levels down, skipping the guarded ones."""
    found = [home / tail]
    with contextlib.suppress(OSError):
        for top in sorted(home.iterdir()):
            if top.name in GUARDED or top.name.startswith('.') or not top.is_dir():
                continue
            found.append(top / tail)
            with contextlib.suppress(OSError):
                found += [inner / tail for inner in sorted(top.iterdir()) if not inner.name.startswith('.') and inner.is_dir()]
    return found


def find_binary(home):
    path = os.pathsep.join([os.environ.get('PATH', ''), *SEARCH])
    for name in ('whisper-cli', 'whisper-cpp'):  # Homebrew called it whisper-cpp before 1.7.4.
        if found := shutil.which(name, path=path):
            return found
    for tail in BUILT:
        for candidate in home_folders(home, tail):
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)
    return None


def model_rank(path):
    name = path.name.lower()
    size = next((i for i, size in enumerate(SIZES) if size in name), len(SIZES))
    # An app's model may not say its size in the name; then the bigger file is the bigger model.
    with contextlib.suppress(OSError):
        return ('.en' in name, size, -path.stat().st_size, name)
    return ('.en' in name, size, 0, name)


def is_model(path):
    try:
        with open(path, 'rb') as stream:
            return path.stat().st_size > 30_000_000 and stream.read(4) == b'lmgg'  # ggml's magic, little-endian.
    except OSError:
        return False


def find_models(home, own):
    folders = [own, *(Path(f) if f.startswith('/') else home / f for f in MODEL_FOLDERS[1:])]
    folders += home_folders(home, 'whisper.cpp/models')[1:]
    found = {}
    for folder in folders:
        with contextlib.suppress(OSError):
            for path in folder.glob('ggml-*.bin'):
                if 'encoder' not in path.name and is_model(path):
                    found.setdefault(path.resolve(), path)
    for folder in APP_FOLDERS:
        with contextlib.suppress(OSError):
            for path in itertools.islice((home / folder).rglob('*'), 5000):
                if path.is_file() and not path.is_symlink() and is_model(path):
                    found.setdefault(path.resolve(), path)
    return sorted(found.values(), key=model_rank)


def wav_problem(audio):
    """The recorder writes one exact format; anything else is refused before whisper-cli reads it."""
    if len(audio) < 44 or audio[:4] != b'RIFF' or audio[8:16] != b'WAVEfmt ':
        return 'The recording is not a WAV file'
    fmt, channels, rate = (int.from_bytes(audio[a:b], 'little') for a, b in ((20, 22), (22, 24), (24, 28)))
    bits = int.from_bytes(audio[34:36], 'little')
    if (fmt, channels, rate, bits) != (1, 1, 16000, 16):
        return 'The recording must be 16 kHz mono 16-bit PCM'
    return None


def clean_text(output):
    lines = (line.strip() for line in output.splitlines())
    return ' '.join(line for line in lines if line and not NOISE.match(line))


class Voice:
    def __init__(self, root=None, home=None, opener=None, run=subprocess.run, system=platform.system, retry_pause=5):
        self.home = Path(home or Path.home())
        self.folder = Path(root or self.home / MODEL_FOLDERS[0])
        self.found = None
        self.opener = opener or urllib.request.urlopen
        self.run = run
        self.system = system
        self.retry_pause = retry_pause
        self.lock = threading.Lock()
        self.busy = threading.Lock()  # One recognition at a time: they share the GPU and the model's memory.
        self.job = {'phase': 'idle'}

    def look(self, again=False):
        """What is installed, looked up at most once a minute: the folders are walked, not only checked."""
        with self.lock:
            # Never a time 0: a computer up for less than a minute would otherwise never look.
            if again or self.found is None or time.monotonic() - self.found[0] > LOOK_AGAIN:
                models = find_models(self.home, self.folder)
                binary, model = find_binary(self.home), models[0] if models else None
                self.found = (time.monotonic(), binary, model)
            return self.found[1:]

    def binary(self):
        return self.look()[0]

    def model(self):
        return self.look()[1]

    def brew(self):
        return shutil.which('brew', path=os.pathsep.join([os.environ.get('PATH', ''), *SEARCH]))

    def status(self):
        binary, model = self.look()
        with self.lock:
            job = dict(self.job)
        can_install = bool(binary) or (self.system() == 'Darwin' and bool(self.brew()))
        return {'voice': {**job, 'ready': bool(binary and model), 'binary': bool(binary), 'model': bool(model),
                          'uses': [shown(path, self.home) for path in (binary, model) if path],
                          'can_install': can_install, 'size': MODEL['size']}}

    def install(self):
        with self.lock:
            if self.job['phase'] in ('binary', 'model'):
                return self.status()
            self.job = {'phase': 'binary'}
        threading.Thread(target=self.install_job, name='agent-deck-voice', daemon=True).start()
        return self.status()

    def install_job(self):
        try:
            if not self.look(again=True)[0]:
                self.install_binary()
            if not self.look(again=True)[1]:
                self.set_job(phase='model', done=0, total=MODEL['size'])
                self.download_model()
            self.set_job(phase='done')
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
            # Our own messages say what to do; anything else is named only by its type.
            message = str(error) if isinstance(error, RuntimeError) else f'{type(error).__name__} while installing'
            self.set_job(phase='error', error=message)

    def set_job(self, **job):
        with self.lock:
            self.job = job

    def install_binary(self):
        brew = self.brew()
        if self.system() != 'Darwin' or not brew:
            raise RuntimeError('Install whisper.cpp so that whisper-cli is on the PATH, then retry')
        env = {**os.environ, 'HOMEBREW_NO_AUTO_UPDATE': '1', 'HOMEBREW_NO_INSTALL_CLEANUP': '1'}
        done = self.run([brew, 'install', 'whisper-cpp'], input='', capture_output=True, text=True,
                        timeout=1800, env=env)
        if done.returncode != 0 or not self.look(again=True)[0]:
            raise RuntimeError('Homebrew could not install whisper-cpp; run "brew install whisper-cpp" in a terminal')

    def download_model(self):
        """A connection that breaks is resumed where it stopped, a few times, before giving up."""
        self.folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        part = self.folder / (MODEL['name'] + '.part')
        for attempt in range(6):
            try:
                self.fetch(part)
                break
            except OSError:
                if attempt == 5:
                    raise RuntimeError('The model download keeps failing; check the internet connection and retry')
                time.sleep(self.retry_pause)
        if sha256(part) != MODEL['sha256']:
            part.unlink()
            raise RuntimeError('The downloaded model is damaged; retry')
        os.replace(part, self.folder / MODEL['name'])
        self.look(again=True)

    def fetch(self, part):
        have = part.stat().st_size if part.is_file() else 0
        if have >= MODEL['size']:
            return
        headers = {'Range': f'bytes={have}-'} if have else {}
        with self.opener(urllib.request.Request(MODEL_URL, headers=headers), timeout=60) as response, \
                part.open('ab') as out:
            if have and getattr(response, 'status', 200) != 206:
                out.truncate(0)  # The server ignored the range and sends the whole file again.
                have = 0
            while block := response.read(CHUNK):
                out.write(block)
                have += len(block)
                self.set_job(phase='model', done=have, total=MODEL['size'])
        if have < MODEL['size']:
            raise OSError('download ended early')

    def transcribe(self, audio, language='auto', prompt=''):
        binary, model = self.look()
        if not binary or not model:
            raise RuntimeError('Speech recognition is not installed on this computer')
        audio = decode_audio(audio)
        language = language if isinstance(language, str) and LANGUAGE.match(language) else 'auto'
        prompt = re.sub(r'[\x00-\x1f\x7f]', ' ', prompt)[-300:].strip() if isinstance(prompt, str) else ''
        with tempfile.TemporaryDirectory(prefix='agent-deck-voice-') as folder:
            path = Path(folder) / 'speech.wav'
            path.write_bytes(audio)
            command = [binary, '-m', str(model), '-f', str(path), '-l', language, '-nt', '-np']
            with self.busy:
                done = self.run(command + (['--prompt', prompt] if prompt else []), input='', capture_output=True,
                                text=True, timeout=180)
        if done.returncode != 0:
            raise RuntimeError('whisper-cli could not read the recording')
        return clean_text(done.stdout)


def decode_audio(audio):
    if not isinstance(audio, str) or not audio:
        raise ValueError('No recording was sent')
    try:
        data = base64.b64decode(audio, validate=True)
    except ValueError:
        raise ValueError('The recording is not valid base64') from None
    if len(data) > MAX_AUDIO_BYTES:
        raise ValueError('The piece of recording is too long')
    problem = wav_problem(data)
    if problem:
        raise ValueError(problem)
    return data


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        while block := stream.read(CHUNK):
            digest.update(block)
    return digest.hexdigest()


def shown(path, home):
    """Paths in the page are written from ~, so the account name is not on the screen."""
    path = Path(path)
    with contextlib.suppress(ValueError):
        return '~/' + str(path.relative_to(home))
    return str(path)
