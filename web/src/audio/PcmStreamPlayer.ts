export type PcmAudioChunk = {
  sequence: number
  bytes: Uint8Array
  sampleRate: number
  channels: number
  format: string
}

type AudioContextFactory = () => AudioContext

type PlayerOptions = {
  initialBufferSeconds?: number
}

const DEFAULT_INITIAL_BUFFER_SECONDS = 0.35
const PLAYBACK_LEAD_SECONDS = 0.03

export class PcmStreamPlayer {
  private readonly contextFactory: AudioContextFactory
  private readonly initialBufferSeconds: number
  private context: AudioContext | null = null
  private pending = new Map<number, PcmAudioChunk | null>()
  private ready: PcmAudioChunk[] = []
  private sources = new Set<AudioBufferSourceNode>()
  private nextSequence = 0
  private nextPlayAt = 0
  private started = false
  private finished = false
  private closed = false
  private operations: Promise<void> = Promise.resolve()
  private finishPromise: Promise<void> | null = null
  private drainTimer: number | null = null
  private drainResolve: (() => void) | null = null

  constructor(contextFactory: AudioContextFactory = () => new AudioContext(), options: PlayerOptions = {}) {
    this.contextFactory = contextFactory
    this.initialBufferSeconds =
      options.initialBufferSeconds ?? DEFAULT_INITIAL_BUFFER_SECONDS
  }

  async prepare() {
    await this.ensureContext()
  }

  enqueue(chunk: PcmAudioChunk) {
    return this.run(async () => {
      if (this.closed || chunk.sequence < this.nextSequence) {
        return
      }
      validateChunk(chunk)
      await this.ensureContext()
      this.pending.set(chunk.sequence, chunk)
      this.consumeContiguous()
      this.scheduleIfReady()
    })
  }

  skip(sequence: number) {
    return this.run(async () => {
      if (this.closed || sequence < this.nextSequence) {
        return
      }
      this.pending.set(sequence, null)
      this.consumeContiguous()
      this.scheduleIfReady()
    })
  }

  finish() {
    if (this.finishPromise) {
      return this.finishPromise
    }
    this.finishPromise = this.run(async () => {
      if (this.closed) {
        return
      }
      this.finished = true
      this.consumeContiguous()
      if (this.pending.size > 0) {
        throw new Error(`音频分片序号不连续，等待序号 ${this.nextSequence}`)
      }
      this.scheduleIfReady()
      await this.waitForDrain()
      await this.closeContext()
    })
    return this.finishPromise
  }

  async stop() {
    if (this.closed) {
      return
    }
    this.closed = true
    this.pending.clear()
    this.ready = []
    if (this.drainTimer !== null) {
      window.clearTimeout(this.drainTimer)
      this.drainTimer = null
    }
    this.drainResolve?.()
    this.drainResolve = null
    for (const source of this.sources) {
      try {
        source.stop()
      } catch {
        // A source may already have ended between cancellation and cleanup.
      }
    }
    this.sources.clear()
    await this.closeContext()
  }

  private run(operation: () => Promise<void>) {
    const result = this.operations.then(operation)
    this.operations = result.catch(() => undefined)
    return result
  }

  private async ensureContext() {
    if (this.closed) {
      throw new Error('播放器已关闭')
    }
    if (!this.context) {
      this.context = this.contextFactory()
      this.nextPlayAt = this.context.currentTime
    }
    if (this.context.state === 'suspended') {
      await this.context.resume()
    }
    return this.context
  }

  private consumeContiguous() {
    while (this.pending.has(this.nextSequence)) {
      const chunk = this.pending.get(this.nextSequence)
      this.pending.delete(this.nextSequence)
      this.nextSequence += 1
      if (chunk) {
        this.ready.push(chunk)
      }
    }
  }

  private scheduleIfReady() {
    if (!this.context || this.closed || this.ready.length === 0) {
      return
    }
    const bufferedSeconds = this.ready.reduce(
      (total, chunk) => total + chunk.bytes.byteLength / 2 / chunk.sampleRate,
      0,
    )
    if (!this.started && !this.finished && bufferedSeconds < this.initialBufferSeconds) {
      return
    }
    this.started = true
    for (const chunk of this.ready.splice(0)) {
      this.scheduleChunk(chunk)
    }
  }

  private scheduleChunk(chunk: PcmAudioChunk) {
    const context = this.context
    if (!context) {
      return
    }
    const samples = pcm16LittleEndianToFloat32(chunk.bytes)
    if (samples.length === 0) {
      return
    }
    const buffer = context.createBuffer(1, samples.length, chunk.sampleRate)
    buffer.copyToChannel(samples, 0)
    const source = context.createBufferSource()
    source.buffer = buffer
    source.connect(context.destination)
    source.onended = () => this.sources.delete(source)
    this.sources.add(source)
    const startAt = Math.max(this.nextPlayAt, context.currentTime + PLAYBACK_LEAD_SECONDS)
    source.start(startAt)
    this.nextPlayAt = startAt + buffer.duration
  }

  private waitForDrain() {
    const context = this.context
    if (!context || this.nextPlayAt <= context.currentTime) {
      return Promise.resolve()
    }
    return new Promise<void>((resolve) => {
      this.drainResolve = resolve
      const waitMs = Math.max(0, Math.ceil((this.nextPlayAt - context.currentTime) * 1000) + 50)
      this.drainTimer = window.setTimeout(() => {
        this.drainTimer = null
        this.drainResolve = null
        resolve()
      }, waitMs)
    })
  }

  private async closeContext() {
    const context = this.context
    this.context = null
    if (context && context.state !== 'closed') {
      await context.close()
    }
  }
}

export function decodeBase64Audio(value: string) {
  const binary = atob(value)
  const bytes = new Uint8Array(binary.length)
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index)
  }
  return bytes
}

function validateChunk(chunk: PcmAudioChunk) {
  if (chunk.format !== 'pcm_s16le') {
    throw new Error(`不支持的音频格式：${chunk.format || 'unknown'}`)
  }
  if (chunk.channels !== 1) {
    throw new Error(`不支持的声道数：${chunk.channels}`)
  }
  if (!Number.isInteger(chunk.sampleRate) || chunk.sampleRate <= 0) {
    throw new Error('音频采样率无效')
  }
  if (chunk.bytes.byteLength % 2 !== 0) {
    throw new Error('PCM16 音频字节数无效')
  }
}

function pcm16LittleEndianToFloat32(bytes: Uint8Array) {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength)
  const samples = new Float32Array(bytes.byteLength / 2)
  for (let index = 0; index < samples.length; index += 1) {
    samples[index] = view.getInt16(index * 2, true) / 0x8000
  }
  return samples
}
