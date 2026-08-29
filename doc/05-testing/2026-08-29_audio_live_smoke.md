# Audio Live Smoke

## 目标

验证 ASR -> `QueryService.answer_text()` -> TTS 的真实链路，确认文本回答和音频分片都能返回。

## 命令

```bash
conda run -n biosafe python scripts/audio_live_smoke.py
```

## 结果

- `ok`: `true`
- `answer_source`: `rag`
- `tts_success`: `true`
- `audio_chunks`: `8`
- `session_reason`: `done`
- `history_id`: `1`

## 备注

TTS endpoint 返回的是原始音频字节，不是 RIFF WAV 容器；烟测按 `pcm` 送回 ASR 后完成整轮会话。
