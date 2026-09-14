"""Self-contained entry; public extra models download only when selected."""
from pathlib import Path
import os
import sys
import json
import tempfile
import subprocess
import wave

def configure():
    base = Path(getattr(sys, '_MEIPASS', Path(__file__).parent)) / 'resources'
    os.environ['WHISPER_FASTER_MODEL_DIR'] = str(base / 'models' / 'faster-small')
    os.environ['SHANGZIMU_RESOURCES'] = str(base)
    os.environ['PATH'] = str(base / 'bin') + os.pathsep + os.environ.get('PATH', '')
    configured_data = os.environ.get('WHISPER_PREVIEW_DATA_DIR')
    if configured_data:
        data = Path(configured_data)
    elif os.environ.get('LOCALAPPDATA'):
        data = Path(os.environ['LOCALAPPDATA']) / 'ShangZiMu'
    else:
        data = Path.home() / 'Library' / 'Application Support' / 'ShangZiMu'
    data.mkdir(parents=True, exist_ok=True)
    os.environ['WHISPER_APP_DATA_DIR'] = str(data)
    os.environ['WHISPER_PREVIEW_DATA_DIR'] = str(data)
    for key in ['WHISPER_PREVIEW', 'WHISPER_PREVIEW_LOCAL_ONLY', 'HF_HUB_DISABLE_TELEMETRY']:
        os.environ[key] = '1'
    # Decoder loads local files only. Public model downloads and explicitly
    # confirmed cloud TTS no longer inherit the limited-preview offline toggle.
    os.environ.pop('HF_HUB_OFFLINE', None)
    return base

def self_test(base, report):
    import socket
    def blocked(*args, **kwargs):
        raise RuntimeError('Network access forbidden during offline acceptance')
    socket.socket.connect = blocked
    socket.create_connection = blocked
    import tkinter as tk
    import onnxruntime
    onnxruntime.disable_telemetry_events()
    from faster_whisper import WhisperModel
    from opencc import OpenCC
    from download_model import model_ready
    assert model_ready(base / 'models' / 'faster-small', full=True), 'Model manifest invalid'
    tools = {}
    for name in ['ffmpeg', 'ffprobe']:
        path = base / 'bin' / (name + ('.exe' if sys.platform == 'win32' else ''))
        tools[name] = subprocess.check_output([str(path), '-version'], stderr=subprocess.STDOUT).decode().splitlines()[0]
    model = WhisperModel(str(base / 'models' / 'faster-small'), device='cpu', compute_type='int8', local_files_only=True)
    speech_text = None
    with tempfile.TemporaryDirectory() as directory:
        audio = Path(directory) / 'silence.wav'
        with wave.open(str(audio), 'wb') as stream:
            stream.setnchannels(1); stream.setsampwidth(2); stream.setframerate(16000)
            stream.writeframes(b'\0\0' * 16000)
        segments, info = model.transcribe(str(audio), language='zh', vad_filter=True, word_timestamps=True)
        assert list(segments) == [], 'Silence should not produce subtitles'
        if os.environ.get('SHANGZIMU_TEST_AUDIO'):
            speech = Path(directory) / 'speech.wav'
            subprocess.run([str(base / 'bin' / ('ffmpeg.exe' if sys.platform == 'win32' else 'ffmpeg')),
                '-y', '-i', os.environ['SHANGZIMU_TEST_AUDIO'], '-ar', '16000', '-ac', '1', str(speech)],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            segments, info = model.transcribe(str(speech), language='en', vad_filter=True, word_timestamps=True)
            result = list(segments)
            speech_text = ' '.join(s.text for s in result).strip()
            assert speech_text and any(s.words for s in result), 'Speech and word timing required'
            from subtitle_workspace import serialize_srt, save_new_file
            cues = [{'start':s.start, 'end':s.end, 'text':s.text} for s in result]
            target = Path(directory) / 'result.srt'
            save_new_file(target, serialize_srt(cues))
            assert '-->' in target.read_text(encoding='utf-8')
    assert OpenCC('s2twp').convert('字幕转换') == '字幕轉換'
    root = tk.Tk(); root.withdraw()
    import whisper_gui_mac as gui
    gui.messagebox.askyesno = lambda *a, **kw: False
    app = gui.WhisperApp(root)
    assert len(app.notebook.tabs()) == 4
    root.update_idletasks(); root.destroy()
    report.write_text(json.dumps({'status':'passed', 'python_socket_calls_blocked':True,
        'onnx_telemetry_disabled':True,
        'model_loaded':True, 'vad_silence_decoded':True, 'tk_gui_created':True,
        'speech_transcribed_and_srt_exported': bool(speech_text), 'synthetic_speech_text': speech_text,
        'tools':tools, 'executable':sys.executable, 'resources':str(base)}, ensure_ascii=False, indent=2), encoding='utf-8')

def network_probe(report):
    """CI-only TCP reachability control, before any socket monkeypatch/model import.

    No media or HTTP request is sent. A baseline plus OS-blocked repeat is
    required to establish network denial; this function alone proves neither.
    """
    import socket
    evidence = {'endpoint':'example.com:443', 'connected':False,
                'python_socket_patch_applied':False}
    try:
        with socket.create_connection(('example.com', 443), timeout=5):
            evidence['connected'] = True
    except OSError as error:
        evidence['error_type'] = type(error).__name__
    with Path(report).open('x', encoding='utf-8') as stream:
        json.dump(evidence, stream, indent=2)
    return evidence

def main():
    if len(sys.argv) == 3 and sys.argv[1] in ('--full-self-test', '--tts-self-test') and not os.environ.get('WHISPER_PREVIEW_DATA_DIR'):
        raise RuntimeError('Acceptance requires an isolated test data directory; user projects must not be read.')
    base = configure()
    if len(sys.argv) == 3 and sys.argv[1] in ('--full-self-test', '--tts-self-test'):
        from full_acceptance import run
        run(base, Path(sys.argv[2]), cloud=sys.argv[1] == '--tts-self-test')
        return
    if len(sys.argv) == 3 and sys.argv[1] == '--network-probe':
        network_probe(Path(sys.argv[2]))
        return
    if len(sys.argv) == 3 and sys.argv[1] == '--self-test':
        report = Path(sys.argv[2])
        try:
            self_test(base, report)
        except Exception:
            import traceback
            report.write_text(json.dumps({'status':'failed','error':traceback.format_exc()}, ensure_ascii=False, indent=2), encoding='utf-8')
            raise
        return
    import onnxruntime
    onnxruntime.disable_telemetry_events()
    import whisper_gui_mac as gui
    gui.main()

if __name__ == '__main__':
    import multiprocessing
    multiprocessing.freeze_support()
    main()
