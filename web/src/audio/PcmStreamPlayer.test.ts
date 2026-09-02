import { afterEach, describe, expect, it, vi } from 'vitest'
import { PcmStreamPlayer, decodeBase64Audio } from './PcmStreamPlayer'

type ScheduledSource = {
  startAt: number
  stopped: boolean
  samples: Float32Array
}

afterEach(() => {
  vi.useRealTimers()
})

describe('PcmStreamPlayer', () => {
  it('orders PCM chunks by sequence and schedules them continuously', async () => {
    const fake = createFakeAudioContext()
    const player = new PcmStreamPlayer(() => fake.context, { initialBufferSeconds: 0 })
    await player.prepare()

    await player.enqueue(chunk(1, [2000, -2000]))
    expect(fake.scheduled).toHaveLength(0)

    await player.enqueue(chunk(0, [1000, -1000]))

    expect(fake.scheduled).toHaveLength(2)
    expect(fake.scheduled[0].startAt).toBeCloseTo(1.03)
    expect(fake.scheduled[1].startAt).toBeCloseTo(1.032)
    expect(fake.scheduled[0].samples[0]).toBeCloseTo(1000 / 0x8000)
    expect(fake.scheduled[1].samples[0]).toBeCloseTo(2000 / 0x8000)
  })

  it('advances past a skipped failed segment', async () => {
    const fake = createFakeAudioContext()
    const player = new PcmStreamPlayer(() => fake.context, { initialBufferSeconds: 0 })
    await player.prepare()

    await player.enqueue(chunk(1, [2000, -2000]))
    await player.skip(0)

    expect(fake.scheduled).toHaveLength(1)
    expect(fake.scheduled[0].samples[0]).toBeCloseTo(2000 / 0x8000)
  })

  it('drains short buffered audio on finish and closes the context', async () => {
    vi.useFakeTimers()
    const fake = createFakeAudioContext()
    const player = new PcmStreamPlayer(() => fake.context, { initialBufferSeconds: 1 })
    await player.prepare()
    await player.enqueue(chunk(0, [1000, -1000]))
    expect(fake.scheduled).toHaveLength(0)

    const finished = player.finish()
    await vi.runAllTimersAsync()
    await finished

    expect(fake.scheduled).toHaveLength(1)
    expect(fake.close).toHaveBeenCalledOnce()
  })

  it('stops scheduled sources immediately when cancelled', async () => {
    const fake = createFakeAudioContext()
    const player = new PcmStreamPlayer(() => fake.context, { initialBufferSeconds: 0 })
    await player.prepare()
    await player.enqueue(chunk(0, [1000, -1000]))

    await player.stop()

    expect(fake.scheduled[0].stopped).toBe(true)
    expect(fake.close).toHaveBeenCalledOnce()
  })

  it('decodes base64 audio bytes', () => {
    expect(Array.from(decodeBase64Audio('UklGRg=='))).toEqual([82, 73, 70, 70])
  })
})

function chunk(sequence: number, samples: number[]) {
  const bytes = new Uint8Array(samples.length * 2)
  const view = new DataView(bytes.buffer)
  samples.forEach((sample, index) => view.setInt16(index * 2, sample, true))
  return {
    sequence,
    bytes,
    sampleRate: 1000,
    channels: 1,
    format: 'pcm_s16le',
  }
}

function createFakeAudioContext() {
  const scheduled: ScheduledSource[] = []
  const close = vi.fn(async () => undefined)
  const context = {
    currentTime: 1,
    state: 'running',
    destination: {},
    resume: vi.fn(async () => undefined),
    close,
    createBuffer: (_channels: number, length: number, sampleRate: number) => {
      let samples = new Float32Array()
      return {
        duration: length / sampleRate,
        copyToChannel: (value: Float32Array) => {
          samples = value.slice()
        },
        get samples() {
          return samples
        },
      }
    },
    createBufferSource: () => {
      const source = {
        buffer: null as { samples: Float32Array } | null,
        onended: null as (() => void) | null,
        connect: vi.fn(),
        start: (startAt: number) => {
          const scheduledSource: ScheduledSource = {
            startAt,
            stopped: false,
            samples: source.buffer?.samples ?? new Float32Array(),
          }
          scheduled.push(scheduledSource)
          source.stop = () => {
            scheduledSource.stopped = true
          }
        },
        stop: () => undefined,
      }
      return source
    },
  } as unknown as AudioContext
  return { context, scheduled, close }
}
