"""Local UMX-HQ separation worker; freeze independently of GUI."""
import argparse
import hashlib
import json
import os
import signal
from pathlib import Path
import subprocess
import tempfile
import wave


def main():
    def stop(_signum, _frame):
        raise SystemExit(130)
    signal.signal(signal.SIGTERM, stop)
    parser = argparse.ArgumentParser()
    for name in ('input', 'output', 'models', 'ffmpeg'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    models = Path(args.models)
    checkpoint = models / 'vocals-b62c91ce.pth'
    if not checkpoint.is_file():
        raise RuntimeError('安裝包缺少人聲分離模型，請重新安裝完整版本。')
    if hashlib.sha256(checkpoint.read_bytes()).hexdigest() != 'b62c91cedbc7a066f1778ead5b5cecb377aa3a46a31af1cce7c5c8769339d083':
        raise RuntimeError('人聲分離模型完整性驗證失敗，請重新安裝完整版本。')
    import numpy as np
    import torch
    import openunmix
    torch.set_num_threads(2)
    separator = openunmix.umxhq(targets=['vocals'], residual=True, pretrained=False, device='cpu')
    state = torch.load(checkpoint, map_location='cpu', weights_only=True)
    # The official 2019 checkpoint contains transform buffers now owned by
    # Separator. Remove only these known legacy buffers; require every learned
    # parameter to match, unlike upstream's blanket strict=False loader.
    for legacy_buffer in ('sample_rate', 'stft.window', 'transform.0.window'):
        state.pop(legacy_buffer, None)
    separator.target_models['vocals'].load_state_dict(state, strict=True)
    separator.eval()
    # Decode onto disk rather than keeping a long video in memory. Model input
    # is bounded to 30 seconds plus one-second context on each side.
    with tempfile.TemporaryDirectory(prefix='shangzimu-separation-') as temporary:
        decoded = Path(temporary) / 'decoded.wav'
        process = subprocess.Popen([args.ffmpeg, '-nostdin', '-v', 'error', '-y', '-i',
                        args.input, '-ar', '44100', '-ac', '2', '-c:a',
                        'pcm_s16le', str(decoded)])
        try:
            if process.wait() != 0:
                raise RuntimeError('音訊解碼失敗，請確認影音檔案可播放。')
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
        with wave.open(str(decoded), 'rb') as source, wave.open(args.output, 'wb') as output:
            rate = source.getframerate()
            total = source.getnframes()
            output.setparams((2, 2, rate, 0, 'NONE', 'not compressed'))
            chunk = rate * 30
            for start in range(0, total, chunk):
                end = min(total, start + chunk)
                left, right = max(0, start - rate), min(total, end + rate)
                source.setpos(left)
                samples = np.frombuffer(source.readframes(right - left),
                                        dtype='<i2').reshape(-1, 2).astype(np.float32) / 32768
                padded = np.pad(samples, ((0, max(0, 4096-len(samples))), (0, 0)))
                with torch.inference_mode():
                    estimates = separator(torch.from_numpy(padded.T.copy()).unsqueeze(0))
                    vocals = separator.to_dict(estimates)['vocals'][0].T.numpy()
                vocals = vocals[start - left:end - left]
                if not np.isfinite(vocals).all() or len(vocals) != end - start:
                    raise RuntimeError('人聲分離產出無效。')
                output.writeframes((np.clip(vocals, -1, 1) * 32767).astype('<i2').tobytes())
                print(json.dumps({'completed': end, 'total': total}), flush=True)


if __name__ == '__main__':
    main()
