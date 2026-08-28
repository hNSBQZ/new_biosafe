import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { App } from './App'

type HistoryReference = {
  citation_index: number
  chunk_id: string
  dataset_id: string
  dataset_name: string
  document_id: string
  document_name: string
  content: string
  page_numbers: number[]
  positions: number[]
  similarity: number
}

type HistoryPayload = {
  id: number
  request_id: string
  session_id: string
  created_at: string
  experiment_id: string
  input_mode: string
  question: string
  answer_source: string
  system_answer: string
  corrected_answer: string
  references: HistoryReference[]
  ragflow_request: Record<string, unknown>
  latency: Record<string, unknown>
  status: string
  error_code: string
  error_message: string
  correction_updated_at?: string | null
}

const experimentResponse = {
  items: [
    {
      id: 'exp-1',
      title: '样本处理',
      step_count: 2,
      knowledge_point_count: 3,
    },
  ],
}

const reference: HistoryReference = {
  citation_index: 1,
  chunk_id: 'chunk-1',
  dataset_id: 'dataset-1',
  dataset_name: '法规标准',
  document_id: 'doc-1',
  document_name: 'fixture.txt',
  content: '新型冠状病毒活病毒培养应在生物安全三级实验室进行。',
  page_numbers: [1],
  positions: [18],
  similarity: 0.91,
}

const historyItem: HistoryPayload = {
  id: 11,
  request_id: 'req-11',
  session_id: 'session-11',
  created_at: '2026-08-28T09:00:00Z',
  experiment_id: 'exp-1',
  input_mode: 'text',
  question: '新冠活病毒培养需要什么实验室？',
  answer_source: 'rag',
  system_answer: '新冠活病毒培养应在生物安全三级实验室进行。[1]',
  corrected_answer: '',
  references: [reference],
  ragflow_request: {
    question: '新冠活病毒培养需要什么实验室？',
    dataset_ids: ['dataset-1'],
  },
  latency: {
    total_ms: 12.3,
  },
  status: 'completed',
  error_code: '',
  error_message: '',
}

const chatSse = [
  'data: {"event":"stage","request_id":"req-chat","sequence":1,"stage":"received","data":{"question":"新冠活病毒培养需要什么实验室？","experiment_id":"exp-1","input_mode":"text"},"timestamp":"2026-08-28T09:00:01Z"}',
  '',
  'data: {"event":"stage_result","request_id":"req-chat","sequence":2,"stage":"retrieving","data":{"chunk_count":1},"timestamp":"2026-08-28T09:00:02Z"}',
  '',
  'data: {"event":"completed","request_id":"req-chat","sequence":3,"stage":"completed","data":{"answer_source":"rag","answer":"新冠活病毒培养应在生物安全三级实验室进行。[1]","references":[{"chunk_id":"chunk-1","dataset_id":"dataset-1","dataset_name":"法规标准","document_id":"doc-1","document_name":"fixture.txt","content":"新型冠状病毒活病毒培养应在生物安全三级实验室进行。","page_numbers":[1],"positions":[18],"similarity":0.91,"citation_index":1}],"history_id":88},"timestamp":"2026-08-28T09:00:03Z"}',
  '',
].join('\n')

beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const path = url.split('?')[0]
      const method = init?.method ?? 'GET'

      if (path === '/health') {
        return jsonResponse({
          status: 'ok',
          service: 'biosafe-api',
          version: '0.1.0',
        })
      }

      if (path === '/api/experiments') {
        return jsonResponse(experimentResponse)
      }

      if (path === '/api/history' && method === 'GET') {
        return jsonResponse({
          items: [historyItem],
          total: 1,
          page: 1,
          page_size: 8,
        })
      }

      if (path === '/api/history/11' && method === 'GET') {
        return jsonResponse(historyItem)
      }

      if (path === '/api/history/11/correction' && method === 'PATCH') {
        const body = init?.body ? JSON.parse(String(init.body)) : { corrected_answer: '' }
        return jsonResponse(
          {
            ...historyItem,
            corrected_answer: String(body.corrected_answer ?? ''),
            correction_updated_at: '2026-08-28T10:00:00Z',
          },
          200,
        )
      }

      if (path === '/api/chat' && method === 'POST') {
        return new Response(chatSse, {
          status: 200,
          headers: { 'Content-Type': 'text/event-stream' },
        })
      }

      throw new Error(`unhandled fetch ${method} ${path}`)
    }),
  )
  window.sessionStorage.clear()
})

afterEach(() => {
  vi.restoreAllMocks()
  window.sessionStorage.clear()
})

describe('App', () => {
  it('renders the assistant workspace and streams a citation-backed answer', async () => {
    render(<App />)

    expect(await screen.findByRole('heading', { name: '文本、历史与语音' })).toBeInTheDocument()
    expect(screen.getByRole('navigation', { name: '主导航' })).toBeInTheDocument()

    fireEvent.change(screen.getByRole('textbox', { name: '问题' }), {
      target: { value: '新冠活病毒培养需要什么实验室？' },
    })
    fireEvent.click(screen.getByRole('button', { name: '发送' }))

    expect(
      await screen.findByText((_, node) => {
        return (
          node?.tagName.toLowerCase() === 'p' &&
          node.textContent?.includes('新冠活病毒培养应在生物安全三级实验室进行。') === true
        )
      }),
    ).toBeInTheDocument()

    fireEvent.click(screen.getAllByRole('button', { name: '[1]fixture.txt' })[0])

    expect(await screen.findByRole('heading', { name: 'fixture.txt' })).toBeInTheDocument()
    expect(screen.getByText('法规标准')).toBeInTheDocument()
    expect(screen.getByText('chunk-1')).toBeInTheDocument()
  })

  it('shows history detail and saves a correction', async () => {
    render(<App />)

    fireEvent.click(screen.getAllByRole('button', { name: '历史' })[0])

    expect(await screen.findByRole('heading', { name: '记录与纠错' })).toBeInTheDocument()
    expect(await screen.findByRole('heading', { name: '新冠活病毒培养需要什么实验室？' })).toBeInTheDocument()

    fireEvent.click(
      screen.getAllByText('新冠活病毒培养需要什么实验室？')[0].closest('button')!,
    )

    expect(await screen.findByText('系统回答')).toBeInTheDocument()
    const textarea = screen.getByLabelText('纠错内容')
    fireEvent.change(textarea, { target: { value: '人工纠错答案' } })
    fireEvent.click(screen.getByRole('button', { name: '保存' }))

    expect(await screen.findByText('人工纠错答案')).toBeInTheDocument()
    expect(screen.getByText('2026-08-28T10:00:00Z')).toBeInTheDocument()
  })

  it('handles missing microphone support', async () => {
    render(<App />)

    fireEvent.click(screen.getAllByRole('button', { name: '开始录音' })[0])

    expect(await screen.findByText('录音不可用')).toBeInTheDocument()
  })
})

function jsonResponse(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      'Content-Type': 'application/json',
    },
  })
}
