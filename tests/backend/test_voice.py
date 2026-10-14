import base64
import hashlib
import io
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from integrations import voice
from integrations.voice import Voice, clean_text, find_binary, find_models, wav_problem


def wav(seconds=1.0, rate=16000, channels=1, bits=16):
    frames = int(seconds * rate)
    data = bytes(frames * channels * bits // 8)
    header = b'RIFF' + (36 + len(data)).to_bytes(4, 'little') + b'WAVEfmt ' + (16).to_bytes(4, 'little')
    header += (1).to_bytes(2, 'little') + channels.to_bytes(2, 'little') + rate.to_bytes(4, 'little')
    header += (rate * channels * bits // 8).to_bytes(4, 'little') + (channels * bits // 8).to_bytes(2, 'little')
    header += bits.to_bytes(2, 'little') + b'data' + len(data).to_bytes(4, 'little')
    return header + data


class Response(io.BytesIO):
    def __init__(self, data, status=200):
        super().__init__(data)
        self.status = status


class VoiceTests(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.calls = []

    def service(self, run=None, opener=None, system='Darwin'):
        return Voice(root=self.folder, run=run or self.whisper, opener=opener, system=lambda: system, retry_pause=0)

    def whisper(self, command, **options):
        self.calls.append((command, options))
        self.audio = Path(command[command.index('-f') + 1]).read_bytes()
        return SimpleNamespace(returncode=0, stdout=' Запушь это в main.\n[BLANK_AUDIO]\n (музыка) \n')

    def test_only_the_recorder_format_is_accepted(self):
        self.assertIsNone(wav_problem(wav()))
        self.assertIn('16 kHz', wav_problem(wav(rate=48000)))
        self.assertIn('16 kHz', wav_problem(wav(channels=2)))
        self.assertIn('WAV', wav_problem(b'OggS' + bytes(60)))

    def test_noise_markers_are_not_speech(self):
        self.assertEqual(clean_text(' one\n[BLANK_AUDIO]\n(Music)\n two \n'), 'one two')

    def test_recognition_runs_whisper_on_a_private_copy_and_deletes_it(self):
        service = self.service()
        with patch.object(Voice, 'look', return_value=('/opt/homebrew/bin/whisper-cli', Path('/m/ggml-small.bin'))):
            text = service.transcribe(base64.b64encode(wav()).decode(), 'ru', 'previous\x1b[2J text')
        self.assertEqual(text, 'Запушь это в main.')
        command, options = self.calls[0]
        self.assertEqual(command[:2], ['/opt/homebrew/bin/whisper-cli', '-m'])
        self.assertEqual(command[command.index('-l') + 1], 'ru')
        self.assertEqual(command[-2:], ['--prompt', 'previous [2J text'])
        self.assertEqual(options['input'], '')
        self.assertEqual(self.audio, wav())
        self.assertFalse(Path(command[command.index('-f') + 1]).exists())

    def test_a_strange_language_falls_back_to_detection(self):
        with patch.object(Voice, 'look', return_value=('whisper-cli', Path('/m/ggml-small.bin'))):
            self.service().transcribe(base64.b64encode(wav()).decode(), '--help')
        self.assertEqual(self.calls[0][0][self.calls[0][0].index('-l') + 1], 'auto')

    def test_bad_recordings_are_refused_before_whisper_runs(self):
        service = self.service()
        with patch.object(Voice, 'look', return_value=('whisper-cli', Path('/m/ggml-small.bin'))):
            for audio, message in ((None, 'No recording'), ('***', 'base64'), (base64.b64encode(wav(30)).decode(), 'too long'),
                                   (base64.b64encode(wav(rate=44100)).decode(), '16 kHz')):
                with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                    service.transcribe(audio)
        self.assertEqual(self.calls, [])

    def test_recognition_without_whisper_says_it_is_not_installed(self):
        with patch.object(Voice, 'look', return_value=(None, None)), self.assertRaisesRegex(RuntimeError, 'not installed'):
            self.service().transcribe(base64.b64encode(wav()).decode())

    def test_a_broken_download_resumes_where_it_stopped_and_is_checked(self):
        model = b'0123456789' * 100
        requests = []

        def opener(request, timeout):
            requests.append(request.get_header('Range'))
            if len(requests) == 1:
                raise OSError('connection reset')
            if len(requests) == 2:
                return Response(model[:400])
            return Response(model[400:], status=206)
        fake = {'name': 'model.bin', 'size': len(model), 'sha256': hashlib.sha256(model).hexdigest()}
        with patch.dict(voice.MODEL, fake):
            service = self.service(opener=opener)
            service.download_model()
            self.assertEqual((self.folder / 'model.bin').read_bytes(), model)
        self.assertEqual(requests, [None, None, 'bytes=400-'])
        self.assertFalse((self.folder / 'model.bin.part').exists())

    def test_a_damaged_download_is_deleted_and_reported(self):
        fake = {'name': 'model.bin', 'size': 4, 'sha256': '0' * 64}
        with patch.dict(voice.MODEL, fake), self.assertRaisesRegex(RuntimeError, 'damaged'):
            self.service(opener=lambda request, timeout: Response(b'evil')).download_model()
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_installing_on_a_mac_uses_homebrew_then_downloads_the_model(self):
        found = iter([(None, None), ('/opt/homebrew/bin/whisper-cli', None), ('/opt/homebrew/bin/whisper-cli', None)])
        service = self.service(run=lambda command, **options: self.calls.append(command) or SimpleNamespace(returncode=0))
        with patch.object(Voice, 'look', side_effect=lambda again=False: next(found)), \
                patch.object(Voice, 'brew', return_value='/opt/homebrew/bin/brew'), \
                patch.object(Voice, 'download_model') as download:
            service.install_job()
        self.assertEqual(self.calls, [['/opt/homebrew/bin/brew', 'install', 'whisper-cpp']])
        download.assert_called_once()
        self.assertEqual(service.job['phase'], 'done')

    def test_without_homebrew_the_error_says_what_to_install(self):
        service = self.service(system='Linux')
        with patch.object(Voice, 'look', return_value=(None, None)):
            service.install_job()
            self.assertFalse(service.status()['voice']['can_install'])
        self.assertEqual(service.job['phase'], 'error')
        self.assertIn('whisper-cli', service.job['error'])
        self.assertEqual(self.calls, [])

    def test_an_unexpected_failure_is_named_by_its_type_only(self):
        service = self.service()
        with patch.object(Voice, 'look', return_value=('whisper-cli', None)), \
                patch.object(Voice, 'download_model', side_effect=PermissionError('/Users/secret/path')):
            service.install_job()
        self.assertEqual(service.job, {'phase': 'error', 'error': 'PermissionError while installing'})



def model_file(path, magic=b'lmgg'):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'wb') as stream:
        stream.write(magic)
        stream.truncate(31_000_000)  # Sparse: big enough to count as a model, no disk used.
    return path


class InstalledCopyTests(unittest.TestCase):
    """The owner's own whisper.cpp and models are used; a third copy is never installed beside them."""

    def setUp(self):
        self.home = Path(tempfile.mkdtemp())

    def test_the_best_model_already_on_the_computer_is_chosen(self):
        model_file(self.home / 'src/whisper.cpp/models/ggml-small.bin')
        best = model_file(self.home / 'whisper.cpp/models/ggml-large-v3-turbo-q5_0.bin')
        model_file(self.home / 'whisper.cpp/models/ggml-large-v3-turbo.en.bin')
        model_file(self.home / 'whisper.cpp/models/ggml-large-v3-turbo-encoder.bin')
        model_file(self.home / 'whisper.cpp/models/ggml-medium.bin', magic=b'PK\x03\x04')  # Not a model.
        apps = model_file(self.home / 'Library/Application Support/MacWhisper/models/ggml-base.bin')
        found = find_models(self.home, self.home / '.cache/agent-deck/whisper')
        self.assertEqual(found[0], best)
        self.assertEqual([p.name for p in found], ['ggml-large-v3-turbo-q5_0.bin', 'ggml-small.bin', 'ggml-base.bin',
                                                   'ggml-large-v3-turbo.en.bin'])
        self.assertIn(apps, found)

    def test_a_model_inside_an_app_folder_is_found_by_its_content(self):
        # Where Audio Hijack keeps them, as seen on a Mac.
        folder = self.home / 'Library/Application Support/Rogue Amoeba/Transcription Models'
        small, large = model_file(folder / 'fast.model'), model_file(folder / 'accurate.model')
        with open(large, 'r+b') as stream:
            stream.truncate(60_000_000)
        model_file(self.home / 'Library/Application Support/noScribe/models/model.bin', magic=b'\x00\x00\x00\x00')
        self.assertEqual(find_models(self.home, self.home / 'own'), [large, small])

    def test_audio_hijacks_large_model_is_preferred_to_its_base_one(self):
        folder = self.home / 'Library/Application Support/Rogue Amoeba/Transcription Models'
        base, large = model_file(folder / 'whisper-base.bin'), model_file(folder / 'whisper-large-v2.bin')
        self.assertEqual(find_models(self.home, self.home / 'own'), [large, base])

    def test_guarded_folders_are_never_read(self):
        model_file(self.home / 'Documents/whisper.cpp/models/ggml-large-v3.bin')
        built = self.home / 'Documents/whisper.cpp/build/bin/whisper-cli'
        built.parent.mkdir(parents=True)
        built.write_text('#!/bin/sh\n')
        built.chmod(0o755)
        self.assertEqual(find_models(self.home, self.home / 'own'), [])
        with patch.dict('os.environ', {'PATH': ''}), patch.object(voice, 'SEARCH', ()):
            self.assertIsNone(find_binary(self.home))

    def test_a_whisper_cpp_built_in_a_project_folder_is_found(self):
        built = self.home / 'projects/whisper.cpp/build/bin/whisper-cli'
        built.parent.mkdir(parents=True)
        built.write_text('#!/bin/sh\n')
        built.chmod(0o755)
        with patch.dict('os.environ', {'PATH': ''}), patch.object(voice, 'SEARCH', ()):
            self.assertEqual(find_binary(self.home), str(built))

    def test_status_names_the_copies_in_use_from_home(self):
        model_file(self.home / 'whisper.cpp/models/ggml-large-v3.bin')
        service = Voice(home=self.home)
        with patch.object(voice, 'find_binary', return_value='/opt/homebrew/bin/whisper-cli'):
            state = service.status()['voice']
        self.assertTrue(state['ready'])
        self.assertEqual(state['uses'], ['/opt/homebrew/bin/whisper-cli', '~/whisper.cpp/models/ggml-large-v3.bin'])

    def test_with_a_model_found_installing_downloads_nothing(self):
        model_file(self.home / 'whisper.cpp/models/ggml-large-v3.bin')
        calls = []
        service = Voice(home=self.home, system=lambda: 'Darwin', opener=lambda *a, **k: calls.append(a),
                        run=lambda command, **options: calls.append(command) or SimpleNamespace(returncode=0))
        with patch.object(voice, 'find_binary', return_value='/opt/homebrew/bin/whisper-cli'):
            service.install_job()
        self.assertEqual(calls, [])
        self.assertEqual(service.job['phase'], 'done')


if __name__ == '__main__':
    unittest.main()
