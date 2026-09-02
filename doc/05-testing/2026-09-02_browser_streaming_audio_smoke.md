# 浏览器流式语音播放 Smoke

## 范围

验证浏览器录音到 ASR、在线问答、TTS PCM 分片、AudioContext 连续播放和播放中取消。测试不创建或删除 RAGFlow 资源，不记录凭据。

## 环境

- 前端：Vite `http://127.0.0.1:5173`，`/api` 开启 WebSocket 转发。
- 后端：本地 FastAPI 8000 端口，由 `scripts/run_api.py` 加载 `.env`。
- 浏览器：Playwright Chromium，授权虚拟麦克风。
- 输入：配置的 TTS 服务生成 2.08 秒测试问题，封装为 24000Hz 单声道 WAV，文件位于 Git 忽略的 `logs/`。

## 自动化结果

### 确定性测试

- 后端全量：47 passed。
- 前端：9 passed，其中 `PcmStreamPlayer` 5 项覆盖乱序分片、skipped 序号、finished 排空、取消停止和 Base64 解码。
- 前端 lint、生产 build、Python ruff：通过。

### 外部服务链路

`conda run -n biosafe python scripts/audio_live_smoke.py` 返回：

- `ok=true`
- ASR 转写成功
- `answer_source=rag`
- `tts_success=true`
- `audio_chunks=7`
- `session_reason=done`

### 浏览器播放

Playwright 通过虚拟麦克风提交问题后：

- 收到 `audio_stream.data`，序号为 0、1。
- 每个分片为 `format=pcm_s16le`、`sample_rate=24000`、`channels=1`。
- `AudioBufferSourceNode.start()` 被调用 2 次，调度时间为 11.7009s、18.2209s，后一段紧接前一段的结束时间。
- 页面状态为“正在播放语音”，浏览器 page error 为 0。

### 播放取消

第二轮浏览器流程在首个分片开始播放后点击“取消”：

- source start 次数：1。
- source stop 次数：1。
- AudioContext 被关闭。
- 页面最终状态保留“已取消”，取消按钮消失。
- 浏览器 page error 为 0。

## 结论

浏览器已真实消费后端 PCM 分片并按序连续播放；正常完成会等待已排队音频，主动取消会立即停止。Phase 6 仍需完成其他页面和部署项，不能据此标记整体 DONE。

实现提交：`5acefb3 feat(voice): stream pcm audio in browser`。
