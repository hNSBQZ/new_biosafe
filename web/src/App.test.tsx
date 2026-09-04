import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { App, TurnCard } from './App'

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
  auto_correction?: {
    id: number
    history_id: number
    status: string
    model: string
    can_answer: boolean | null
    answer: string
    cannot_answer_reason: string
    citations: { title: string; url: string; note: string }[]
    error: string
    enqueued_at: string
    started_at?: string | null
    finished_at?: string | null
  } | null
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
  auto_correction: {
    id: 3,
    history_id: 11,
    status: 'success',
    model: 'strong-model',
    can_answer: true,
    answer: '模型复核建议：应在生物安全三级实验室进行。',
    cannot_answer_reason: '',
    citations: [
      {
        title: '生物安全标准',
        url: 'https://example.test/standard',
        note: '活病毒培养设施要求',
      },
    ],
    error: '',
    enqueued_at: '2026-08-28T09:00:01Z',
    started_at: '2026-08-28T09:00:02Z',
    finished_at: '2026-08-28T09:00:05Z',
  },
}

const chatSse = [
  'data: {"event":"stage","request_id":"req-chat","sequence":1,"stage":"received","data":{"question":"新冠活病毒培养需要什么实验室？","experiment_id":"exp-1","input_mode":"text"},"timestamp":"2026-08-28T09:00:01Z"}',
  '',
  'data: {"event":"stage_result","request_id":"req-chat","sequence":2,"stage":"retrieving","data":{"chunk_count":1},"timestamp":"2026-08-28T09:00:02Z"}',
  '',
  'data: {"event":"completed","request_id":"req-chat","sequence":3,"stage":"completed","data":{"answer_source":"rag","answer":"新冠活病毒培养应在生物安全三级实验室进行。[1]","references":[{"chunk_id":"chunk-1","dataset_id":"dataset-1","dataset_name":"法规标准","document_id":"doc-1","document_name":"fixture.txt","content":"新型冠状病毒活病毒培养应在生物安全三级实验室进行。","page_numbers":[1],"positions":[18],"similarity":0.91,"citation_index":1}],"history_id":88},"timestamp":"2026-08-28T09:00:03Z"}',
  '',
].join('\n')

const knowledgeFile = {
  id: 'doc-1',
  name: '生物安全管理条例.pdf',
  category: 'laws',
  category_label: '法规标准',
  status: 'completed',
  status_label: '已完成',
  progress: 1,
  status_message: '',
  size: 2048,
  created_at: '2026-09-03T08:30:00Z',
  updated_at: '2026-09-03T08:35:00Z',
  preview_kind: 'pdf',
}

const retrievalMatch = {
  question: '办公区是指什么？',
  datasets: [
    {
      id: 'dataset-default',
      name: 'biosafe-dev-laws',
      chunk_method: 'laws',
    },
  ],
  page_size: 8,
  similarity_threshold: 0.2,
  vector_similarity_weight: 0.3,
  chunks: [
    {
      citation_index: 1,
      chunk_id: 'chunk-office',
      dataset_id: 'dataset-default',
      dataset_name: '法规标准',
      document_id: 'doc-office',
      document_name: '术语标准.pdf',
      content: '办公区是实验工作区域之外，与实验室区域有效隔离，保存相关资料、档案的区域。',
      page_numbers: [4],
      positions: [],
      image_id: null,
      similarity: 0.92,
      vector_similarity: 0.88,
      term_similarity: 0.95,
      source_url: null,
      raw_metadata: {},
    },
  ],
}

beforeEach(() => {
  window.history.replaceState({}, '', '/')
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

      if (path === '/api/admin/knowledge/files' && method === 'GET') {
        return jsonResponse({ items: [knowledgeFile], total: 1 })
      }

      if (path === '/api/admin/knowledge/retrieval-match' && method === 'POST') {
        return jsonResponse(retrievalMatch)
      }

      if (path === '/api/admin/knowledge/files/doc-1/content' && method === 'GET') {
        return new Response('%PDF fixture', {
          status: 200,
          headers: { 'Content-Type': 'application/pdf' },
        })
      }

      if (path === '/api/history/11/auto-correction' && method === 'POST') {
        return jsonResponse({
          ...historyItem.auto_correction,
          status: 'pending',
          answer: '',
          citations: [],
          model: '',
          can_answer: null,
          finished_at: null,
        })
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
  window.localStorage.clear()
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  window.sessionStorage.clear()
  window.localStorage.clear()
  window.history.replaceState({}, '', '/')
})

describe('App', () => {
  it('renders the assistant workspace and streams a citation-backed answer', async () => {
    render(<App />)

    expect(await screen.findByRole('heading', { name: '生物安全实验助手' })).toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: '实验场景' })).toBeInTheDocument()
    expect(screen.queryByRole('navigation', { name: '管理导航' })).not.toBeInTheDocument()

    fireEvent.change(screen.getByRole('textbox', { name: '问题' }), {
      target: { value: '新冠活病毒培养需要什么实验室？' },
    })
    fireEvent.keyDown(screen.getByRole('textbox', { name: '问题' }), { key: 'Enter' })

    const answer = await screen.findByText((_, node) => {
      return (
        node?.tagName.toLowerCase() === 'p' &&
        node.textContent?.includes('新冠活病毒培养应在生物安全三级实验室进行。') === true
      )
    })
    const turn = answer.closest('article')
    expect(turn).not.toBeNull()
    expect(turn!.querySelector('.user-message')?.textContent).toContain('新冠活病毒培养需要什么实验室？')
    expect(turn!.querySelector('.assistant-message')?.textContent).toContain('知识库回答')

    fireEvent.click(screen.getAllByRole('button', { name: '[1]fixture.txt' })[0])

    expect(await screen.findByRole('heading', { name: 'fixture.txt' })).toBeInTheDocument()
    expect(screen.getByText('法规标准')).toBeInTheDocument()
    expect(screen.getByText('chunk-1')).toBeInTheDocument()
  })

  it('keeps history compact until a row is expanded and saves a manual annotation', async () => {
    window.history.replaceState({}, '', '/admin/history')
    render(<App />)

    expect(await screen.findByRole('heading', { name: '记录与纠错' })).toBeInTheDocument()
    expect(screen.getByRole('navigation', { name: '管理导航' })).toBeInTheDocument()
    await screen.findByText('新冠活病毒培养需要什么实验室？')
    await waitFor(() => expect(screen.queryByText('加载中')).not.toBeInTheDocument())
    const historyRow = screen.getByText('新冠活病毒培养需要什么实验室？').closest('button')!
    expect(historyRow).toHaveAttribute('aria-expanded', 'false')
    expect(screen.getByText('2026/08/28')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '查看答案' })).not.toBeInTheDocument()

    fireEvent.click(historyRow)
    expect(await screen.findByRole('button', { name: '查看答案' })).toBeInTheDocument()
    expect(screen.getByText('新冠活病毒培养需要什么实验室？').closest('button')).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByRole('button', { name: /自动纠错/ })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '人工标注' }))

    expect(screen.getByRole('dialog', { name: '编辑人工标注' })).toBeInTheDocument()
    const textarea = screen.getByLabelText('人工标注内容')
    fireEvent.change(textarea, { target: { value: '人工纠错答案' } })
    fireEvent.click(screen.getByRole('button', { name: '保存人工标注' }))

    expect(await screen.findByRole('button', { name: '修改人工标注' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '查看答案' }))
    expect(screen.getByRole('dialog', { name: '查看答案' })).toBeInTheDocument()
    expect(screen.getByText('人工纠错答案')).toBeInTheDocument()
    expect(screen.getAllByText(/2026\/08\/28/).length).toBeGreaterThan(0)
  })

  it('shows the model correction and only adopts it into the manual editor', async () => {
    window.history.replaceState({}, '', '/admin/history')
    render(<App />)

    await screen.findByText('新冠活病毒培养需要什么实验室？')
    await waitFor(() => expect(screen.queryByText('加载中')).not.toBeInTheDocument())
    const historyRow = screen.getByText('新冠活病毒培养需要什么实验室？').closest('button')!
    fireEvent.click(historyRow)
    fireEvent.click(await screen.findByRole('button', { name: /自动纠错/ }))
    expect(await screen.findByText('模型复核建议：应在生物安全三级实验室进行。')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /生物安全标准/ })).toHaveAttribute(
      'href',
      'https://example.test/standard',
    )
    fireEvent.click(screen.getByRole('button', { name: '用于人工标注' }))

    expect(screen.getByRole('dialog', { name: '编辑人工标注' })).toBeInTheDocument()
    expect(screen.getByLabelText('人工标注内容')).toHaveValue(
      '模型复核建议：应在生物安全三级实验室进行。',
    )
    const patchCalls = vi.mocked(fetch).mock.calls.filter(([, init]) => init?.method === 'PATCH')
    expect(patchCalls).toHaveLength(0)
  })

  it('can requeue a model correction', async () => {
    window.history.replaceState({}, '', '/admin/history')
    render(<App />)

    await screen.findByText('新冠活病毒培养需要什么实验室？')
    await waitFor(() => expect(screen.queryByText('加载中')).not.toBeInTheDocument())
    const historyRow = screen.getByText('新冠活病毒培养需要什么实验室？').closest('button')!
    fireEvent.click(historyRow)
    fireEvent.click(await screen.findByRole('button', { name: /自动纠错/ }))
    fireEvent.click(screen.getByRole('button', { name: '重新纠错' }))

    expect(await screen.findByText('等待中')).toBeInTheDocument()
  })

  it('handles missing microphone support', async () => {
    render(<App />)

    fireEvent.click(screen.getByRole('button', { name: '语音' }))
    fireEvent.click(screen.getByRole('button', { name: '开始录音' }))

    expect(await screen.findByText('录音不可用')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '取消' }))
    await waitFor(() => {
      expect(screen.queryByRole('button', { name: '取消' })).not.toBeInTheDocument()
    })
  })

  it('keeps knowledge management on its own route', async () => {
    window.history.replaceState({}, '', '/admin/knowledge')
    render(<App />)

    expect(window.location.pathname).toBe('/admin/knowledge')
    expect(screen.getByRole('heading', { level: 1, name: '知识库管理' })).toBeInTheDocument()
    expect(screen.getByText(/BIOSAFE_ADMIN_PASSWORD/)).toBeInTheDocument()
    expect(screen.queryByRole('textbox', { name: '问题' })).not.toBeInTheDocument()
  })

  it('shows a category-driven file center without dataset or chunk details', async () => {
    window.history.replaceState({}, '', '/admin/knowledge')
    window.localStorage.setItem('biosafe-admin-token', 'admin-token')
    vi.stubGlobal('URL', {
      ...URL,
      createObjectURL: vi.fn(() => 'blob:knowledge-preview'),
      revokeObjectURL: vi.fn(),
    })

    render(<App />)

    expect(await screen.findByText('生物安全管理条例.pdf')).toBeInTheDocument()
    expect(screen.getAllByText('法规标准').length).toBeGreaterThan(0)
    expect(screen.getAllByText('已完成').length).toBeGreaterThan(0)
    expect(screen.queryByText(/dataset/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/chunk/i)).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '预览 生物安全管理条例.pdf' }))
    const previewFrame = await screen.findByTitle('生物安全管理条例.pdf')
    expect(previewFrame).toHaveAttribute('src', 'blob:knowledge-preview')
    expect(previewFrame).not.toHaveAttribute('sandbox')

    fireEvent.change(screen.getByRole('combobox', { name: '类别' }), {
      target: { value: 'laws' },
    })
    fireEvent.click(screen.getByRole('button', { name: '筛选' }))
    await waitFor(() => {
      expect(vi.mocked(fetch)).toHaveBeenCalledWith(
        expect.stringContaining('category=laws'),
        expect.anything(),
      )
    })

    fireEvent.click(screen.getByRole('button', { name: '上传文件' }))
    expect(screen.getByRole('dialog', { name: '上传文件' })).toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: '资料类别' })).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText(/选择文件/), {
      target: {
        files: [new File(['duplicate'], '生物安全管理条例.pdf', { type: 'application/pdf' })],
      },
    })
    expect(await screen.findByRole('alert')).toHaveTextContent('同名文件已存在')
    expect(screen.getByRole('alert')).toHaveTextContent('2026')
    expect(screen.getByRole('button', { name: '上传' })).toBeDisabled()
  })

  it('opens retrieval matching and shows chunks from the online default configuration', async () => {
    window.history.replaceState({}, '', '/admin/knowledge')
    window.localStorage.setItem('biosafe-admin-token', 'admin-token')
    render(<App />)

    fireEvent.click(await screen.findByRole('button', { name: '检索匹配' }))

    expect(window.location.pathname).toBe('/admin/knowledge/retrieval')
    const input = screen.getByRole('textbox', { name: '检索问题' })
    fireEvent.change(input, { target: { value: '办公区是指什么？' } })
    fireEvent.click(screen.getByRole('button', { name: '检索' }))

    expect(await screen.findByText('术语标准.pdf')).toBeInTheDocument()
    expect(screen.getByText(/实验工作区域之外/)).toBeInTheDocument()
    expect(screen.getByText('biosafe-dev-laws · 法规标准')).toBeInTheDocument()
    expect(screen.getByText('综合 0.920')).toBeInTheDocument()
    expect(screen.getByText('向量 0.880')).toBeInTheDocument()
    expect(screen.getByText('关键词 0.950')).toBeInTheDocument()
    expect(vi.mocked(fetch)).toHaveBeenCalledWith(
      '/api/admin/knowledge/retrieval-match',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ question: '办公区是指什么？' }),
      }),
    )
  })

  it('redirects legacy management routes to the admin entry', async () => {
    window.history.replaceState({}, '', '/history')
    render(<App />)

    await waitFor(() => expect(window.location.pathname).toBe('/admin/history'))
    expect(screen.getByRole('navigation', { name: '管理导航' })).toBeInTheDocument()
  })

  it('shows a playing waveform and ordered voice subtitle chunks', () => {
    const onOpenReference = vi.fn()
    render(
      <TurnCard
        turn={{
          id: 'voice-turn',
          inputMode: 'voice',
          status: 'completed',
          question: '语音问题',
          transcript: '语音问题',
          answerSource: 'rag',
          answer: '第一段回答 [1]。第二段回答 [1]。',
          voiceSegments: [
            { sequence: 1, text: '第二段回答 [1]。' },
            { sequence: 0, text: '第一段回答 [1]。' },
          ],
          voicePlayback: 'playing',
          references: [reference],
          timeline: [],
          rawEvents: [],
          createdAt: Date.now(),
        }}
        onOpenReference={onOpenReference}
      />,
    )

    expect(screen.getByLabelText('正在播放语音')).toBeInTheDocument()
    const subtitles = screen.getByLabelText('语音回答字幕')
    expect(subtitles.textContent).toContain('第一段回答 [1]fixture.txt。第二段回答 [1]fixture.txt。')
    fireEvent.click(screen.getAllByRole('button', { name: '引用 1，fixture.txt' })[0])
    expect(onOpenReference).toHaveBeenCalledWith(expect.objectContaining({ document_name: 'fixture.txt' }))
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
