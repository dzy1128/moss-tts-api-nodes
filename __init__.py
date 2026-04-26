import base64
import io
import json
import os
import urllib.error
import urllib.request
import wave


class MossTTSApiNode:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text": (
                    "STRING",
                    {
                        "multiline": True,
                        "default": "hello world",
                    },
                ),
                "api_url": (
                    "STRING",
                    {
                        "default": "http://192.168.207.229:8083/v1/audio/tts",
                    },
                ),
                "response_format": (["wav", "pcm"], {"default": "wav"}),
                "timeout": (
                    "INT",
                    {
                        "default": 300,
                        "min": 1,
                        "max": 3600,
                        "step": 1,
                    },
                ),
            },
            "optional": {
                "prompt_audio": ("AUDIO",),
                "user_text": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": True,
                    },
                ),
                "user_audio": ("AUDIO",),
            },
        }

    RETURN_TYPES = ("AUDIO",)
    RETURN_NAMES = ("audio",)
    FUNCTION = "generate"
    CATEGORY = "audio/MOSS-TTS"
    DESCRIPTION = "Call a running MOSS-TTS FastAPI service and return ComfyUI AUDIO."

    def generate(
        self,
        text,
        api_url,
        response_format,
        timeout,
        prompt_audio=None,
        user_text="",
        user_audio=None,
    ):
        text = text.strip()
        if not text:
            raise ValueError("text 不能为空")

        api_key = _get_api_key()
        payload = {
            "model": "moss-tts",
            "text": text,
            "response_format": response_format,
        }
        _put_optional(payload, "user_text", user_text)

        if prompt_audio is not None:
            payload["prompt_audio_base64"] = _audio_to_wav_base64(prompt_audio)

        if user_audio is not None:
            payload["user_audio_base64"] = _audio_to_wav_base64(user_audio)

        audio_bytes, headers = _post_json(api_url, api_key, payload, timeout)

        if response_format == "pcm":
            sample_rate = int(headers.get("X-Audio-Sample-Rate", "24000"))
            channels = int(headers.get("X-Audio-Channels", "1"))
            waveform = _pcm_s16le_to_waveform(audio_bytes, channels)
        else:
            waveform, sample_rate = _wav_to_waveform(audio_bytes)

        return ({"waveform": waveform, "sample_rate": sample_rate},)


def _get_api_key():
    api_key = os.getenv("MOSS_TTS_API_KEY", "").strip()
    if api_key:
        return api_key

    api_keys = os.getenv("MOSS_TTS_API_KEYS", "").strip()
    if api_keys:
        first_key = api_keys.split(",", 1)[0].strip().strip('"').strip("'")
        if first_key:
            return first_key

    raise RuntimeError(
        "未找到 API key，请设置环境变量 MOSS_TTS_API_KEY，或设置 MOSS_TTS_API_KEYS。"
    )


def _put_optional(payload, key, value):
    value = value.strip() if isinstance(value, str) else value
    if value:
        payload[key] = value


def _audio_to_wav_base64(audio):
    return base64.b64encode(_audio_to_wav_bytes(audio)).decode("ascii")


def _audio_to_wav_bytes(audio):
    try:
        import torch
    except ImportError as error:
        raise RuntimeError("未找到 torch，请在 ComfyUI 的 Python 环境中运行该节点。") from error

    if not isinstance(audio, dict) or "waveform" not in audio or "sample_rate" not in audio:
        raise ValueError("AUDIO 输入格式不正确，缺少 waveform 或 sample_rate")

    waveform = audio["waveform"]
    sample_rate = int(audio["sample_rate"])
    if waveform.dim() == 3:
        waveform = waveform[0]
    elif waveform.dim() == 1:
        waveform = waveform.unsqueeze(0)
    elif waveform.dim() != 2:
        raise ValueError(f"AUDIO waveform 维度不支持: {tuple(waveform.shape)}")

    waveform = waveform.detach().cpu().to(torch.float32).clamp(-1.0, 1.0)
    channels = int(waveform.shape[0])
    pcm = (waveform.transpose(0, 1).contiguous() * 32767.0).to(torch.int16)

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm.numpy().tobytes())

    return buffer.getvalue()


def _post_json(url, api_key, payload, timeout):
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/octet-stream, audio/wav",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read(), response.headers
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"MOSS-TTS API 请求失败: HTTP {error.code} {detail}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"MOSS-TTS API 连接失败: {error.reason}") from error


def _wav_to_waveform(audio_bytes):
    with wave.open(io.BytesIO(audio_bytes), "rb") as wav_file:
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        sample_rate = wav_file.getframerate()
        frames = wav_file.readframes(wav_file.getnframes())

    if sample_width != 2:
        raise ValueError(f"当前仅支持 16-bit WAV，实际 sample width: {sample_width}")

    return _pcm_s16le_to_waveform(frames, channels), sample_rate


def _pcm_s16le_to_waveform(audio_bytes, channels):
    try:
        import torch
    except ImportError as error:
        raise RuntimeError("未找到 torch，请在 ComfyUI 的 Python 环境中运行该节点。") from error

    if channels < 1:
        raise ValueError(f"channels 必须大于 0，实际值: {channels}")

    audio = torch.frombuffer(bytearray(audio_bytes), dtype=torch.int16).to(torch.float32)
    if audio.numel() % channels != 0:
        raise ValueError("PCM 数据长度无法按声道数整除")

    audio = audio.reshape(-1, channels).transpose(0, 1)
    waveform = audio.unsqueeze(0) / 32768.0
    return waveform.contiguous()


NODE_CLASS_MAPPINGS = {
    "MossTTSApi": MossTTSApiNode,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "MossTTSApi": "MOSS-TTS API",
}
