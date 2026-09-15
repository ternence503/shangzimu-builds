"""Synthetic, installed-artifact acceptance; never reads user projects/media."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
from unittest.mock import patch


def run(base, report, cloud=False):
    import tkinter as tk
    import whisper_gui_mac as gui
    root = tk.Tk()
    root.withdraw()
    app = gui.WhisperApp(root)
    evidence = {'status': 'failed', 'cloud_test': cloud, 'resources': str(base)}
    dialogs = []
    # A headless acceptance must inspect, not wait on, every native message
    # box scheduled by a worker or validation callback. Real GUI use retains
    # the dialogs because this patch exists only inside the test process.
    dialog_patcher = patch.multiple(
        gui.messagebox,
        showerror=lambda *args, **kwargs: dialogs.append(('error', args)),
        showwarning=lambda *args, **kwargs: dialogs.append(('warning', args)),
        showinfo=lambda *args, **kwargs: dialogs.append(('info', args)),
        askyesno=lambda *args, **kwargs: False,
    )
    dialog_patcher.start()
    try:
        assert len(app.notebook.tabs()) == 4
        assert all(app.notebook.tab(tab, 'state') == 'normal' for tab in app.notebook.tabs())
        assert set(app.model_combo['values']) == set(gui.MODEL_OPTIONS)
        evidence['all_tabs_enabled'] = True
        assert gui.edge_tts is not None
        if cloud:
            text = '這是上字幕自製的驗收旁白，不含機密或個人資料。' * 45
            with tempfile.TemporaryDirectory(prefix='shangzimu-cloud-qa-') as directory:
                chunks = app._chunk_tts_text(text, max_chars=300)
                paths = asyncio.run(app._run_tts_chunks(chunks, 'zh-TW-HsiaoChenNeural', '+0%', '+0Hz', directory))
                output = str(Path(directory) / 'merged.mp3')
                app._concat_mp3_chunks(paths, output)
                subprocess.run([app._find_ffmpeg(), '-v', 'error', '-i', output, '-f', 'null', '-'], check=True)
                evidence['long_tts'] = {'characters': len(text), 'chunks': len(chunks), 'bytes': Path(output).stat().st_size}
        else:
            import socket
            def forbidden(*_args, **_kwargs):
                raise AssertionError('Offline acceptance tried to connect to network')
            with patch.object(socket.socket, 'connect', forbidden), patch.object(socket, 'create_connection', forbidden):
                audio = os.environ['SHANGZIMU_TEST_SPEECH']
                results = {}
                for name in gui.MODEL_OPTIONS:
                    result = app._transcribe(audio, name, dict(gui.DEFAULT_OPTIONS, language='en', word_timestamps=True), threading.Event())
                    assert result.get('text', '').strip(), name
                    assert any(segment.get('words') for segment in result['segments']), name
                    results[name] = result['text']
                    assert len(app.faster_model_cache) == 1
                evidence['models'] = results
                with tempfile.TemporaryDirectory(prefix='shangzimu-full-qa-') as directory:
                    app.lyrics_output_dir = directory
                    app.lyrics_language_var.set('英文 (en)')
                    app.lyrics_stop_event.clear()
                    app.lyrics_worker_thread = threading.Thread(target=app._lyrics_worker, args=(audio, 'small', True))
                    thread = app.lyrics_worker_thread
                    errors = []
                    with patch.object(gui.messagebox, 'showerror', lambda *args: errors.append(args)):
                        thread.start()
                        deadline = time.monotonic() + 600
                        def check_worker():
                            if not thread.is_alive() or time.monotonic() >= deadline:
                                root.quit()
                            else:
                                root.after(20, check_worker)
                        root.after(20, check_worker)
                        root.mainloop()
                        if thread.is_alive():
                            app.lyrics_stop_event.set()
                            thread.join(timeout=10)
                            raise AssertionError('Lyrics worker timed out')
                        root.update()
                    assert not errors, errors
                    outputs = {suffix: list(Path(directory).rglob('*' + suffix)) for suffix in ('.txt', '.lrc', '.srt')}
                    assert all(len(paths) == 1 and paths[0].stat().st_size > 0 for paths in outputs.values()), outputs
                    evidence['lyrics_outputs'] = {key: paths[0].stat().st_size for key, paths in outputs.items()}
                    app._set_layout_source(result['segments'], 'synthetic.json')
                    app.apply_subtitle_layout()
                    assert app.layout_result
                    project = Path(directory) / 'synthetic-project.json'
                    subtitle = Path(directory) / 'synthetic-subtitle.srt'
                    notices = []
                    with (patch.object(gui.filedialog, 'asksaveasfilename', return_value=str(project)),
                          patch.object(gui.messagebox, 'showwarning', lambda *args: notices.append(args)),
                          patch.object(gui.messagebox, 'showinfo', lambda *args: notices.append(args))):
                        assert app.save_layout_project()
                    from subtitle_workspace import read_document, validate_cues
                    restored, metadata = read_document(project, with_metadata=True)
                    # Documents intentionally trim outer whitespace. Compare
                    # against the same public validation contract, preserving
                    # all timing/word fields and meaningful internal newlines.
                    assert restored == validate_cues(app.layout_result), (restored, app.layout_result)
                    assert metadata['original_segments'] == validate_cues(app.layout_source)
                    assert metadata['settings'] == app._layout_settings()
                    with (patch.object(gui.filedialog, 'asksaveasfilename', return_value=str(subtitle)),
                          patch.object(gui.messagebox, 'showwarning', lambda *args: notices.append(args)),
                          patch.object(gui.messagebox, 'showinfo', lambda *args: notices.append(args))):
                        app.export_layout_srt()
                    assert subtitle.stat().st_size > 0
                    evidence['subtitle_project_roundtrip_and_srt'] = True
                    evidence['nonblocking_review_notices'] = len(notices)
                # Refusal must occur before any output or asynchronous work.
                app._get_tts_effective_text = lambda: '內部資料，不得外傳'
                with patch.object(gui.messagebox, 'askyesno', return_value=False), patch.object(app, '_get_tts_output_path', side_effect=AssertionError('output touched')):
                    app.start_tts_generation()
                assert app.tts_worker_thread is None
                evidence['cloud_refusal_without_output'] = True
        evidence['status'] = 'passed'
    finally:
        evidence['headless_dialogs'] = len(dialogs)
        dialog_patcher.stop()
        root.destroy()
        Path(report).write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
