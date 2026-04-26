# MOSS-TTS FastAPI 接口文档

本文档说明如何启动后端 API，以及如何从其他服务调用 TTS 接口。

## 1. 启动服务

先生成 API Key：

```bash
.venv/bin/python generate_api_key.py
```

生成的 key 会自动追加到根目录 `.env`：

```env
MOSS_TTS_API_KEYS="moss_xxx,moss_yyy"
```

启动 API 服务：

```bash
./start_api.sh
```

默认配置：

| 项 | 默认值 |
|---|---|
| Host | `0.0.0.0` |
| Port | `8083` |
| GPU | `cuda:1` |
| Log | `api.log` |
| PID | `api.pid` |

查看日志：

```bash
tail -f api.log
```

停止服务：

```bash
kill "$(cat api.pid)"
```

## 2. 鉴权

所有 API 请求都必须带 Bearer Token：

```http
Authorization: Bearer <api_key>
```

只有 `.env` 中 `MOSS_TTS_API_KEYS` 列出的 key 可以访问接口。

未带 key 或 key 不正确时返回：

```json
{"detail": "invalid api key"}
```

## 3. 单请求 TTS

### `POST /v1/audio/tts`

最推荐的业务调用接口。请求一次，返回完整音频。

请求地址：

```text
http://服务器IP:8083/v1/audio/tts
```

请求头：

| Header | 必填 | 说明 |
|---|---|---|
| `Authorization` | 是 | `Bearer <api_key>` |
| `Content-Type` | 是 | `application/json` |

请求体：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `model` | string | 是 | `moss-tts` | 当前只支持 `moss-tts` |
| `text` | string | 是 | 无 | 要合成的文本 |
| `prompt_audio` | string/null | 否 | `null` | 参考音频路径，用于音色克隆 |
| `user_text` | string/null | 否 | `Hello!` | 对话上下文里的用户文本 |
| `user_audio` | string/null | 否 | `null` | 用户语音上下文 |
| `response_format` | string | 否 | `wav` | `wav` 或 `pcm` |
| `session_id` | string/null | 否 | 自动生成 | 请求内部 session id |

### 返回 WAV

默认返回：

```text
Content-Type: audio/wav
```

curl 示例：

```bash
curl -X POST http://127.0.0.1:8083/v1/audio/tts \
  -H "Authorization: Bearer your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "moss-tts",
    "text": "hello world"
  }' \
  --output output.wav
```

Python 示例：

```python
import requests

api_key = "your-api-key"
url = "http://127.0.0.1:8083/v1/audio/tts"
headers = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json",
}
payload = {
    "model": "moss-tts",
    "text": "hello world",
}

response = requests.post(url, headers=headers, json=payload, timeout=300)
response.raise_for_status()

with open("output.wav", "wb") as f:
    f.write(response.content)
```

### 使用参考音频

`prompt_audio` 填服务器上的音频文件路径：

```json
{
  "model": "moss-tts",
  "text": "hello world",
  "prompt_audio": "/data/users/dzy/moss-tts/my_voice.wav"
}
```

注意：`prompt_audio` 是服务端路径，不是调用方本地路径。

### 返回 PCM

请求：

```json
{
  "model": "moss-tts",
  "text": "hello world",
  "response_format": "pcm"
}
```

返回：

```text
Content-Type: application/octet-stream
X-Audio-Codec: pcm_s16le
X-Audio-Sample-Rate: 24000
X-Audio-Channels: 1
```

保存 PCM：

```bash
curl -X POST http://127.0.0.1:8083/v1/audio/tts \
  -H "Authorization: Bearer your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "moss-tts",
    "text": "hello world",
    "response_format": "pcm"
  }' \
  --output output.pcm
```

转成 WAV：

```bash
ffmpeg -f s16le -ar 24000 -ac 1 -i output.pcm output.wav
```

## 4. 健康检查

### `GET /health`

请求：

```bash
curl http://127.0.0.1:8083/health \
  -H "Authorization: Bearer your-api-key"
```

响应示例：

```json
{
  "status": "ok",
  "target_sr": 24000,
  "model_path": "/data/users/dzy/moss-tts/models/MOSS-TTS-Realtime",
  "tokenizer_path": "/data/users/dzy/moss-tts/models/MOSS-TTS-Realtime",
  "codec_model_path": "/data/users/dzy/moss-tts/models/MOSS-Audio-Tokenizer",
  "device": "cuda:1",
  "attn_impl": "sdpa"
}
```

## 5. 底层 Session 接口

这组接口适合需要分段推送文本、单独拉取 PCM 音频流的场景。普通业务优先使用 `/v1/audio/tts`。

### `POST /tts/session/start`

开始一个 TTS session。

请求：

```bash
curl -X POST http://127.0.0.1:8083/tts/session/start \
  -H "Authorization: Bearer your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "demo-1",
    "user_text": "hello",
    "assistant_text": "hello world",
    "prompt_audio": null,
    "user_audio": null,
    "new_turn": true
  }'
```

响应：

```json
{
  "ok": true,
  "session_id": "demo-1",
  "message": "turn started"
}
```

### `POST /tts/session/push`

向已有 session 追加文本。

```bash
curl -X POST http://127.0.0.1:8083/tts/session/push \
  -H "Authorization: Bearer your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "demo-1",
    "text": " more text",
    "is_final": false
  }'
```

如果是最后一段文本：

```json
{
  "session_id": "demo-1",
  "text": "",
  "is_final": true
}
```

### `GET /tts/session/{session_id}/audio`

获取 PCM 音频流。

```bash
curl http://127.0.0.1:8083/tts/session/demo-1/audio \
  -H "Authorization: Bearer your-api-key" \
  --output output.pcm
```

响应头：

```text
X-Audio-Codec: pcm_s16le
X-Audio-Sample-Rate: 24000
X-Audio-Channels: 1
```

### `POST /tts/session/close`

关闭 session。

```bash
curl -X POST http://127.0.0.1:8083/tts/session/close \
  -H "Authorization: Bearer your-api-key" \
  -H "Content-Type: application/json" \
  -d '{"session_id": "demo-1"}'
```

## 6. 错误码

| 状态码 | 场景 |
|---|---|
| `400` | 请求参数错误，例如 `text` 为空、`model` 不支持 |
| `401` | 未提供 API key，或 API key 不在 `.env` 白名单 |
| `404` | session 不存在 |
| `500` | 推理或音频处理异常 |
| `503` | 服务端没有配置任何 API key |

## 7. 外部访问注意事项

- 远程调用时把 `127.0.0.1` 替换成服务器 IP 或域名
- 启动服务时默认监听 `0.0.0.0:8083`
- 服务器安全组或防火墙需要放行 `8083`
- `prompt_audio` 必须是服务端机器上的文件路径