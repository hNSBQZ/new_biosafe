import { useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import {
  Activity,
  CheckCircle2,
  ChevronRight,
  Clock3,
  FileText,
  History,
  Mic,
  MessageSquareText,
  RefreshCw,
  Search,
  Send,
  Settings2,
  Square,
  TriangleAlert,
  X,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

type ViewKey = 'assistant' | 'history' | 'system'
type TurnInputMode = 'text' | 'voice'
type TurnStatus = 'recording' | 'sending' | 'completed' | 'failed' | 'cancelled'
type AnswerSource = '' | 'instruction' | 'direct' | 'rag' | 'error'
type JsonRecord = Record<string, unknown>

type ExperimentItem = {
  id: string
  title: string
  step_count: number
  knowledge_point_count: number
}

type HistoryItem = {
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
  references: CitationReference[]
  ragflow_request: JsonRecord
  latency: JsonRecord
  status: string
  error_code: string
  error_message: string
  correction_updated_at?: string | null
}

type HistoryPage = {
  items: HistoryItem[]
  total: number
  page: number
  page_size: number
}

type QueryEventEnvelope = {
  event: string
  request_id: string
  sequence: number
  stage: string
  data: JsonRecord
  timestamp: string
}

type CitationReference = {
  citation_index?: number
  chunk_id: string
  dataset_id: string
  dataset_name: string
  document_id: string
  document_name: string
  content: string
  page_numbers: number[]
  positions: number[]
  image_id?: string
  similarity?: number | null
  vector_similarity?: number | null
  term_similarity?: number | null
  source_url?: string
  raw_metadata?: JsonRecord
}

type FuncCallData = {
  command: string
  confidence: number
  params: JsonRecord
}

type TimelineEntry = {
  sequence: number
  event: string
  stage: string
  label: string
  detail: string
}

type TurnRecord = {
  id: string
  requestId?: string
  inputMode: TurnInputMode
  status: TurnStatus
  question: string
  transcript: string
  answerSource: AnswerSource
  answer: string
  funcCall?: FuncCallData
  references: CitationReference[]
  historyId?: number
  errorCode?: string
  errorMessage?: string
  timeline: TimelineEntry[]
  rawEvents: QueryEventEnvelope[]
  createdAt: number
}

type VoiceSegment = {
  sequence: number
  text: string
}

type VoicePhase = 'idle' | 'connecting' | 'recording' | 'processing' | 'error'

type HealthState = {
  status: string
  service: string
  version: string
}

const VIEW_META: Record<ViewKey, { label: string; icon: LucideIcon }> = {
  assistant: { label: '助手', icon: MessageSquareText },
  history: { label: '历史', icon: History },
  system: { label: '系统', icon: Settings2 },
}

const EXPERIMENT_GENERIC: ExperimentItem = {
  id: 'generic',
  title: '通用实验',
  step_count: 0,
  knowledge_point_count: 0,
}

export function App() {
  const [view, setView] = useState<ViewKey>('assistant')
  const [experiments, setExperiments] = useState<ExperimentItem[]>([])
  const [selectedExperimentId, setSelectedExperimentId] = useState('generic')
  const [experimentLoaded, setExperimentLoaded] = useState(false)
  const [health, setHealth] = useState<HealthState | null>(null)
  const [globalNotice, setGlobalNotice] = useState('正在加载实验与历史')
  const [question, setQuestion] = useState('')
  const [turns, setTurns] = useState<TurnRecord[]>([])
  const [activeTurnId, setActiveTurnId] = useState<string | null>(null)
  const [voicePhase, setVoicePhase] = useState<VoicePhase>('idle')
  const [voiceMessage, setVoiceMessage] = useState('录音待命')
  const [voiceTranscript, setVoiceTranscript] = useState('')
  const [voiceSessionId, setVoiceSessionId] = useState('')
  const [voiceSegments, setVoiceSegments] = useState<VoiceSegment[]>([])
  const [voiceError, setVoiceError] = useState('')
  const [historyPage, setHistoryPage] = useState(1)
  const [historyPageSize, setHistoryPageSize] = useState(8)
  const [historyStatusFilter, setHistoryStatusFilter] = useState('')
  const [historyPageData, setHistoryPageData] = useState<HistoryPage>({
    items: [],
    total: 0,
    page: 1,
    page_size: 8,
  })
  const [historyLoading, setHistoryLoading] = useState(false)
  const [selectedHistoryId, setSelectedHistoryId] = useState<number | null>(null)
  const [selectedHistory, setSelectedHistory] = useState<HistoryItem | null>(null)
  const [historyCorrection, setHistoryCorrection] = useState('')
  const [savingCorrection, setSavingCorrection] = useState(false)
  const [selectedReference, setSelectedReference] = useState<CitationReference | null>(null)
  const [selectedReferenceOrigin, setSelectedReferenceOrigin] = useState<'turn' | 'history'>(
    'turn',
  )
  const [textRequestPending, setTextRequestPending] = useState(false)
  const chatAbortRef = useRef<AbortController | null>(null)
  const voiceSocketRef = useRef<WebSocket | null>(null)
  const recorderRef = useRef<MediaRecorder | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const voiceChunksRef = useRef<Blob[]>([])
  const voiceCancelRequestedRef = useRef(false)
  const pendingVoiceTurnIdRef = useRef<string | null>(null)

  const activeTurn = useMemo(
    () => turns.find((turn) => turn.id === activeTurnId) ?? null,
    [activeTurnId, turns],
  )
  const selectedExperiment = useMemo(
    () =>
      experiments.find((item) => item.id === selectedExperimentId) ?? EXPERIMENT_GENERIC,
    [experiments, selectedExperimentId],
  )
  const sessionId = useMemo(() => currentSessionId(), [])
  const currentReference = selectedReference
  const currentTurnReferences = activeTurn?.references ?? []
  const currentTurnTimeline = activeTurn?.timeline ?? []
  const supportedVoice = typeof window !== 'undefined' && 'MediaRecorder' in window

  useEffect(() => {
    void loadHealth()
    void loadExperiments()
    void loadHistoryPage()
  }, [])

  useEffect(() => {
    if (!experimentLoaded && experiments.length > 0) {
      setSelectedExperimentId(experiments[0].id)
      setExperimentLoaded(true)
    }
  }, [experimentLoaded, experiments])

  useEffect(() => {
    void loadHistoryPage()
  }, [selectedExperimentId, historyPage, historyPageSize, historyStatusFilter])

  useEffect(() => {
    if (!selectedHistoryId && historyPageData.items.length > 0) {
      setSelectedHistoryId(historyPageData.items[0].id)
    }
  }, [historyPageData.items, selectedHistoryId])

  useEffect(() => {
    if (selectedHistoryId === null) {
      setSelectedHistory(null)
      setHistoryCorrection('')
      return
    }
    void loadHistoryDetail(selectedHistoryId)
  }, [selectedHistoryId])

  useEffect(() => {
    if (selectedHistory) {
      setHistoryCorrection(selectedHistory.corrected_answer || selectedHistory.system_answer)
    }
  }, [selectedHistory])

  useEffect(() => {
    return () => {
      chatAbortRef.current?.abort()
      voiceSocketRef.current?.close()
      recorderRef.current?.stop()
      streamRef.current?.getTracks().forEach((track) => track.stop())
    }
  }, [])

  async function loadHealth() {
    try {
      const response = await fetch('/health')
      if (!response.ok) {
        throw new Error(`health ${response.status}`)
      }
      const payload = (await response.json()) as HealthState
      setHealth(payload)
    } catch (error) {
      setHealth(null)
      setGlobalNotice(`后端状态读取失败：${describeError(error)}`)
    }
  }

  async function loadExperiments() {
    try {
      const response = await fetch('/api/experiments')
      if (!response.ok) {
        throw new Error(`experiments ${response.status}`)
      }
      const payload = (await response.json()) as { items?: ExperimentItem[] }
      setExperiments(Array.isArray(payload.items) ? payload.items : [])
      setGlobalNotice('实验列表已加载')
    } catch (error) {
      setExperiments([])
      setGlobalNotice(`实验列表加载失败：${describeError(error)}`)
    }
  }

  async function loadHistoryPage() {
    setHistoryLoading(true)
    try {
      const params = new URLSearchParams()
      params.set('page', String(historyPage))
      params.set('page_size', String(historyPageSize))
      if (selectedExperimentId) {
        params.set('experiment_id', selectedExperimentId)
      }
      if (historyStatusFilter) {
        params.set('status', historyStatusFilter)
      }
      const response = await fetch(`/api/history?${params.toString()}`)
      if (!response.ok) {
        throw new Error(`history ${response.status}`)
      }
      const payload = (await response.json()) as HistoryPage
      setHistoryPageData(payload)
      if (payload.items.length > 0) {
        const stillVisible = payload.items.some((item) => item.id === selectedHistoryId)
        if (!stillVisible) {
          setSelectedHistoryId(payload.items[0].id)
        }
      } else {
        setSelectedHistoryId(null)
      }
    } catch (error) {
      setHistoryPageData({ items: [], total: 0, page: historyPage, page_size: historyPageSize })
      setSelectedHistoryId(null)
      setGlobalNotice(`历史记录加载失败：${describeError(error)}`)
    } finally {
      setHistoryLoading(false)
    }
  }

  async function loadHistoryDetail(historyId: number) {
    try {
      const response = await fetch(`/api/history/${historyId}`)
      if (!response.ok) {
        throw new Error(`history detail ${response.status}`)
      }
      const payload = (await response.json()) as HistoryItem
      setSelectedHistory(payload)
    } catch (error) {
      setGlobalNotice(`历史详情加载失败：${describeError(error)}`)
    }
  }

  async function saveCorrection() {
    if (selectedHistoryId === null) {
      return
    }
    setSavingCorrection(true)
    try {
      const response = await fetch(`/api/history/${selectedHistoryId}/correction`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ corrected_answer: historyCorrection }),
      })
      if (!response.ok) {
        throw new Error(`correction ${response.status}`)
      }
      const payload = (await response.json()) as HistoryItem
      setSelectedHistory(payload)
      setHistoryPageData((current) => ({
        ...current,
        items: current.items.map((item) => (item.id === payload.id ? payload : item)),
      }))
      setGlobalNotice('纠错已保存')
    } catch (error) {
      setGlobalNotice(`纠错保存失败：${describeError(error)}`)
    } finally {
      setSavingCorrection(false)
    }
  }

  async function submitQuestion(nextQuestion: string) {
    const trimmed = nextQuestion.trim()
    if (!trimmed || textRequestPending || activeTurnId !== null) {
      return
    }
    const turnId = makeId('turn')
    const turn: TurnRecord = {
      id: turnId,
      inputMode: 'text',
      status: 'sending',
      question: trimmed,
      transcript: '',
      answerSource: '',
      answer: '',
      references: [],
      timeline: [],
      rawEvents: [],
      createdAt: Date.now(),
    }
    setQuestion('')
    setTurns((current) => [turn, ...current])
    setActiveTurnId(turnId)
    setTextRequestPending(true)
    const controller = new AbortController()
    chatAbortRef.current = controller
    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          question: trimmed,
          experiment_id: selectedExperimentId,
          session_id: sessionId,
          input_mode: 'text',
        }),
        signal: controller.signal,
      })
      if (!response.ok || !response.body) {
        throw new Error(`chat ${response.status}`)
      }
      await consumeSseResponse(response, turnId)
      setGlobalNotice('文本问答已完成')
    } catch (error) {
      if (controller.signal.aborted) {
        updateTurn(turnId, (item) => ({
          ...item,
          status: 'cancelled',
          answerSource: item.answerSource || 'error',
          errorCode: 'cancelled',
          errorMessage: '已取消',
        }))
        setGlobalNotice('当前提问已取消')
      } else {
        updateTurn(turnId, (item) => ({
          ...item,
          status: 'failed',
          answerSource: item.answerSource || 'error',
          errorCode: 'chat_request_failed',
          errorMessage: describeError(error),
        }))
        setGlobalNotice(`文本问答失败：${describeError(error)}`)
      }
    } finally {
      setTextRequestPending(false)
      setActiveTurnId((current) => (current === turnId ? null : current))
      if (chatAbortRef.current === controller) {
        chatAbortRef.current = null
      }
    }
  }

  async function cancelCurrentQuery() {
    chatAbortRef.current?.abort()
    if (voicePhase === 'recording' || voicePhase === 'processing') {
      await stopVoiceSession(true)
    }
  }

  async function startVoiceSession() {
    if (voicePhase !== 'idle') {
      return
    }
    if (!supportedVoice) {
      setVoicePhase('error')
      setVoiceError('当前浏览器不支持录音')
      setVoiceMessage('录音不可用')
      setGlobalNotice('录音控制不可用')
      return
    }
    if (!('mediaDevices' in navigator) || !navigator.mediaDevices?.getUserMedia) {
      setVoicePhase('error')
      setVoiceError('当前浏览器无法访问麦克风')
      setVoiceMessage('麦克风不可用')
      return
    }
    setVoicePhase('connecting')
    setVoiceError('')
    setVoiceMessage('正在连接录音')
    setVoiceTranscript('')
    setVoiceSegments([])
    const turnId = makeId('voice')
    pendingVoiceTurnIdRef.current = turnId
    setTurns((current) => [
      {
        id: turnId,
        inputMode: 'voice',
        status: 'recording',
        question: '',
        transcript: '',
        answerSource: '',
        answer: '',
        references: [],
        timeline: [],
        rawEvents: [],
        createdAt: Date.now(),
      },
      ...current,
    ])
    setActiveTurnId(turnId)
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      streamRef.current = stream
      voiceCancelRequestedRef.current = false
      const mimeType = resolveRecordingMimeType()
      const recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream)
      recorderRef.current = recorder
      voiceChunksRef.current = []
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          voiceChunksRef.current.push(event.data)
        }
      }
      recorder.onstop = async () => {
        if (voiceCancelRequestedRef.current) {
          setVoicePhase('idle')
          setVoiceMessage('已取消')
          await stopVoiceResources()
          return
        }
        const chunks = voiceChunksRef.current.slice()
        voiceChunksRef.current = []
        const socket = voiceSocketRef.current
        if (!socket || socket.readyState !== WebSocket.OPEN) {
          setVoicePhase('error')
          setVoiceError('语音连接未就绪')
          setVoiceMessage('录音未发送')
          return
        }
        const blob = new Blob(chunks, { type: mimeType || 'audio/webm' })
        const arrayBuffer = await blob.arrayBuffer()
        socket.send(
          JSON.stringify({
            type: 'audio_data',
            seq: 0,
            data: bytesToBase64(new Uint8Array(arrayBuffer)),
          }),
        )
        socket.send(JSON.stringify({ type: 'audio_end' }))
        setVoicePhase('processing')
        setVoiceMessage('正在生成回答')
        updateTurn(turnId, (item) => ({
          ...item,
          status: 'sending',
        }))
      }
      recorder.start()
      const socket = new WebSocket(buildAudioSocketUrl(selectedExperimentId))
      voiceSocketRef.current = socket
      socket.onopen = () => {
        socket.send(
          JSON.stringify({
            type: 'audio_start',
            sample_rate: 16000,
            format: mimeType || 'webm',
          }),
        )
        setVoicePhase('recording')
        setVoiceMessage('正在录音')
        setGlobalNotice('录音会话已建立')
      }
      socket.onmessage = (event) => {
        const message = safeParseJson(event.data)
        if (message) {
          void handleVoiceMessage(turnId, message)
        }
      }
      socket.onerror = () => {
        setVoicePhase('error')
        setVoiceError('录音连接失败')
        setVoiceMessage('连接失败')
        updateTurn(turnId, (item) => ({
          ...item,
          status: 'failed',
          answerSource: item.answerSource || 'error',
          errorCode: 'voice_socket_error',
          errorMessage: '录音连接失败',
        }))
      }
      socket.onclose = () => {
        setVoicePhase((current) =>
          current === 'processing' || current === 'recording' || current === 'connecting'
            ? 'idle'
            : current,
        )
        setVoiceMessage('录音结束')
      }
    } catch (error) {
      setVoicePhase('error')
      setVoiceError(describeError(error))
      setVoiceMessage('录音启动失败')
      updateTurn(turnId, (item) => ({
        ...item,
        status: 'failed',
        answerSource: item.answerSource || 'error',
        errorCode: 'voice_start_failed',
        errorMessage: describeError(error),
      }))
      pendingVoiceTurnIdRef.current = null
      setActiveTurnId((current) => (current === turnId ? null : current))
      stopVoiceResources()
    }
  }

  async function stopVoiceSession(isInterrupted = false) {
    const socket = voiceSocketRef.current
    const recorder = recorderRef.current
    if (socket && socket.readyState === WebSocket.OPEN && isInterrupted) {
      socket.send(JSON.stringify({ type: 'interrupt' }))
      setVoiceMessage('已取消录音')
    }
    if (isInterrupted) {
      voiceCancelRequestedRef.current = true
      if (recorder && recorder.state !== 'inactive') {
        recorder.stop()
      } else {
        await stopVoiceResources()
      }
      const turnId = pendingVoiceTurnIdRef.current
      if (turnId) {
        updateTurn(turnId, (item) => ({
          ...item,
          status: 'cancelled',
          answerSource: item.answerSource || 'error',
          errorCode: 'interrupted',
          errorMessage: '已取消',
        }))
      }
      setVoicePhase('idle')
      setVoiceMessage('已取消')
      pendingVoiceTurnIdRef.current = null
      setActiveTurnId(null)
    } else {
      if (recorder && recorder.state !== 'inactive') {
        recorder.stop()
      }
      if (socket && socket.readyState === WebSocket.CONNECTING) {
        socket.close()
      }
      await stopVoiceResources()
      pendingVoiceTurnIdRef.current = null
      setActiveTurnId(null)
    }
  }

  async function handleVoiceMessage(turnId: string, message: JsonRecord) {
    const type = stringValue(message.type)
    if (type === 'connected') {
      setVoiceSessionId(stringValue(message.session_id))
      setVoiceMessage('录音会话已连接')
      return
    }
    if (type === 'status') {
      setVoiceMessage(stringValue(message.text) || stringValue(message.phase))
      return
    }
    if (type === 'packet_ack') {
      return
    }
    if (type === 'transcription') {
      const success = Boolean(message.success)
      const text = stringValue(message.text)
      setVoiceTranscript(text)
      updateTurn(turnId, (item) => ({
        ...item,
        question: text || item.question,
        transcript: text,
        status: success ? item.status : 'failed',
        answerSource: success ? item.answerSource : 'error',
        errorCode: success ? item.errorCode : stringValue(message.code) || 'asr_failed',
        errorMessage: success ? item.errorMessage : '语音转写失败',
      }))
      if (!success) {
        setVoicePhase('error')
        setVoiceError(stringValue(message.code) || 'asr_failed')
      }
      return
    }
    if (type === 'query_event') {
      const envelope = normalizeQueryEvent(message)
      if (envelope) {
        updateTurnFromQueryEvent(turnId, envelope)
      }
      return
    }
    if (type === 'instruction') {
      const funcCall: FuncCallData = {
        command: stringValue(message.command),
        confidence: numberValue(message.confidence),
        params: toJsonRecord(message.params),
      }
      updateTurn(turnId, (item) => ({
        ...item,
        status: 'completed',
        answerSource: 'instruction',
        funcCall,
        answer: formatInstructionAnswer(funcCall),
        historyId: numberValue(message.history_id) || item.historyId,
      }))
      return
    }
    if (type === 'answer') {
      updateTurn(turnId, (item) => ({
        ...item,
        status: 'completed',
        answerSource: stringAnswerSource(stringValue(message.answer_source)),
        answer: stringValue(message.answer),
        references: normalizeReferences(message.references),
        historyId: numberValue(message.history_id) || item.historyId,
      }))
      return
    }
    if (type === 'audio_stream') {
      if (stringValue(message.event) === 'data') {
        const sequence = numberValue(message.sequence)
        const text = stringValue(message.text)
        setVoiceSegments((current) => [
          ...current,
          {
            sequence,
            text,
          },
        ])
      }
      if (stringValue(message.event) === 'finished') {
        setVoiceMessage('语音输出已完成')
      }
      return
    }
    if (type === 'error') {
      const code = stringValue(message.code) || 'voice_error'
      const detail = stringValue(message.message) || '语音链路失败'
      setVoicePhase('error')
      setVoiceError(detail)
      updateTurn(turnId, (item) => ({
        ...item,
        status: 'failed',
        answerSource: item.answerSource || 'error',
        errorCode: code,
        errorMessage: detail,
      }))
      return
    }
    if (type === 'session_complete') {
      const reason = stringValue(message.reason)
      if (reason === 'interrupted') {
        setVoiceMessage('会话已中断')
      } else if (reason === 'error') {
        setVoiceMessage('会话失败')
      } else {
        setVoiceMessage('会话已完成')
      }
      setVoicePhase('idle')
      pendingVoiceTurnIdRef.current = null
      setActiveTurnId(null)
      stopVoiceResources()
    }
  }

  async function consumeSseResponse(response: Response, turnId: string) {
    const reader = response.body?.getReader()
    if (!reader) {
      throw new Error('response stream unavailable')
    }
    const decoder = new TextDecoder()
    let buffer = ''
    let terminalSeen = false
    while (true) {
      const { value, done } = await reader.read()
      buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done })
      while (true) {
        const separatorIndex = buffer.indexOf('\n\n')
        if (separatorIndex < 0) {
          break
        }
        const block = buffer.slice(0, separatorIndex)
        buffer = buffer.slice(separatorIndex + 2)
        if (block.trim()) {
          const payload = parseSseBlock(block)
          if (payload) {
            terminalSeen = applyQueryEvent(turnId, payload) || terminalSeen
          }
        }
      }
      if (done) {
        break
      }
    }
    buffer += decoder.decode()
    if (buffer.trim()) {
      const payload = parseSseBlock(buffer)
      if (payload) {
        terminalSeen = applyQueryEvent(turnId, payload) || terminalSeen
      }
    }
    if (!terminalSeen) {
      updateTurn(turnId, (item) => ({
        ...item,
        status: 'failed',
        answerSource: item.answerSource || 'error',
        errorCode: 'sse_missing_terminal_event',
        errorMessage: '流式响应未返回终态',
      }))
    }
  }

  function applyQueryEvent(turnId: string, payload: QueryEventEnvelope): boolean {
    updateTurn(turnId, (item) => {
      const nextTimeline = [
        ...item.timeline,
        {
          sequence: payload.sequence,
          event: payload.event,
          stage: payload.stage,
          label: stageLabel(payload.stage),
          detail: summarizeStageEvent(payload),
        },
      ]
      if (payload.event === 'stage') {
        return {
          ...item,
          requestId: item.requestId ?? payload.request_id,
          timeline: nextTimeline,
          rawEvents: [...item.rawEvents, payload],
        }
      }
      if (payload.event === 'stage_result') {
        return {
          ...item,
          requestId: item.requestId ?? payload.request_id,
          timeline: nextTimeline,
          rawEvents: [...item.rawEvents, payload],
        }
      }
      if (payload.event === 'completed') {
        const answerSource = stringAnswerSource(stringValue(payload.data.answer_source))
        if (answerSource === 'instruction') {
          const funcCall = normalizeFuncCall(payload.data.func_call)
          return {
            ...item,
            requestId: payload.request_id,
            status: 'completed',
            answerSource,
            answer: formatInstructionAnswer(funcCall),
            funcCall,
            historyId: numberValue(payload.data.history_id) || item.historyId,
            timeline: nextTimeline,
            references: [],
            errorCode: undefined,
            errorMessage: undefined,
            rawEvents: [...item.rawEvents, payload],
          }
        }
        return {
          ...item,
          requestId: payload.request_id,
          status: 'completed',
          answerSource,
          answer: stringValue(payload.data.answer),
          references: normalizeReferences(payload.data.references),
          historyId: numberValue(payload.data.history_id) || item.historyId,
          timeline: nextTimeline,
          errorCode: undefined,
          errorMessage: undefined,
          rawEvents: [...item.rawEvents, payload],
        }
      }
      if (payload.event === 'failed') {
        return {
          ...item,
          requestId: payload.request_id,
          status: 'failed',
          answerSource: stringAnswerSource(stringValue(payload.data.answer_source)) || 'error',
          errorCode: stringValue(payload.data.code) || 'query_failed',
          errorMessage: stringValue(payload.data.message) || '查询失败',
          historyId: numberValue(payload.data.history_id) || item.historyId,
          timeline: nextTimeline,
          rawEvents: [...item.rawEvents, payload],
        }
      }
      if (payload.event === 'cancelled') {
        return {
          ...item,
          requestId: payload.request_id,
          status: 'cancelled',
          answerSource: stringAnswerSource(stringValue(payload.data.answer_source)) || 'error',
          errorCode: 'cancelled',
          errorMessage: '已取消',
          historyId: numberValue(payload.data.history_id) || item.historyId,
          timeline: nextTimeline,
          rawEvents: [...item.rawEvents, payload],
        }
      }
      return {
        ...item,
        requestId: item.requestId ?? payload.request_id,
        timeline: nextTimeline,
        rawEvents: [...item.rawEvents, payload],
      }
    })
    return payload.event === 'completed' || payload.event === 'failed' || payload.event === 'cancelled'
  }

  function updateTurn(turnId: string, updater: (turn: TurnRecord) => TurnRecord) {
    setTurns((current) => current.map((turn) => (turn.id === turnId ? updater(turn) : turn)))
  }

  function updateTurnFromQueryEvent(turnId: string, payload: QueryEventEnvelope) {
    updateTurn(turnId, (item) => {
      const nextTimeline = [
        ...item.timeline,
        {
          sequence: payload.sequence,
          event: payload.event,
          stage: payload.stage,
          label: stageLabel(payload.stage),
          detail: summarizeStageEvent(payload),
        },
      ]
      if (payload.event === 'completed') {
        const answerSource = stringAnswerSource(stringValue(payload.data.answer_source))
        if (answerSource === 'instruction') {
          const funcCall = normalizeFuncCall(payload.data.func_call)
          return {
            ...item,
            requestId: payload.request_id,
            status: 'completed',
            answerSource,
            answer: formatInstructionAnswer(funcCall),
            funcCall,
            historyId: numberValue(payload.data.history_id) || item.historyId,
            timeline: nextTimeline,
            rawEvents: [...item.rawEvents, payload],
          }
        }
        return {
          ...item,
          requestId: payload.request_id,
          status: 'completed',
          answerSource,
          answer: stringValue(payload.data.answer),
          references: normalizeReferences(payload.data.references),
          historyId: numberValue(payload.data.history_id) || item.historyId,
          timeline: nextTimeline,
          rawEvents: [...item.rawEvents, payload],
        }
      }
      if (payload.event === 'failed') {
        return {
          ...item,
          requestId: payload.request_id,
          status: 'failed',
          answerSource: stringAnswerSource(stringValue(payload.data.answer_source)) || 'error',
          errorCode: stringValue(payload.data.code) || 'query_failed',
          errorMessage: stringValue(payload.data.message) || '查询失败',
          historyId: numberValue(payload.data.history_id) || item.historyId,
          timeline: nextTimeline,
          rawEvents: [...item.rawEvents, payload],
        }
      }
      if (payload.event === 'cancelled') {
        return {
          ...item,
          requestId: payload.request_id,
          status: 'cancelled',
          answerSource: stringAnswerSource(stringValue(payload.data.answer_source)) || 'error',
          errorCode: 'cancelled',
          errorMessage: '已取消',
          historyId: numberValue(payload.data.history_id) || item.historyId,
          timeline: nextTimeline,
          rawEvents: [...item.rawEvents, payload],
        }
      }
      return {
        ...item,
        requestId: item.requestId ?? payload.request_id,
        timeline: nextTimeline,
        rawEvents: [...item.rawEvents, payload],
      }
    })
  }

  function openReference(reference: CitationReference, origin: 'turn' | 'history') {
    setSelectedReference(reference)
    setSelectedReferenceOrigin(origin)
  }

  async function startQuestion() {
    await submitQuestion(question)
  }

  async function stopVoiceResources() {
    recorderRef.current = null
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop())
      streamRef.current = null
    }
    if (voiceSocketRef.current) {
      voiceSocketRef.current.close()
      voiceSocketRef.current = null
    }
  }

  const assistantTimeline = currentTurnTimeline

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <Activity aria-hidden="true" />
          <span>生物安全助手</span>
        </div>
        <nav aria-label="主导航" className="nav">
          {(Object.keys(VIEW_META) as ViewKey[]).map((key) => {
            const Icon = VIEW_META[key].icon
            return (
              <button
                key={key}
                type="button"
                className={view === key ? 'nav-item active' : 'nav-item'}
                onClick={() => setView(key)}
                aria-pressed={view === key}
              >
                <Icon aria-hidden="true" />
                <span>{VIEW_META[key].label}</span>
              </button>
            )
          })}
        </nav>
        <div className="sidebar-status">
          <div className="status-row">
            <span>后端</span>
            <Pill tone={health?.status === 'ok' ? 'success' : 'danger'}>
              {health?.status === 'ok' ? 'ok' : '异常'}
            </Pill>
          </div>
          <div className="status-row">
            <span>语音</span>
            <Pill tone={supportedVoice ? 'neutral' : 'warning'}>
              {supportedVoice ? '支持' : '受限'}
            </Pill>
          </div>
          <div className="status-row">
            <span>会话</span>
            <Pill tone={activeTurn ? 'neutral' : 'success'}>
              {activeTurn ? activeTurn.status : '空闲'}
            </Pill>
          </div>
        </div>
      </aside>

      <main className="workspace">
        <header className="topbar">
          <div className="topbar-copy">
            <p className="eyebrow">实验训练工作台</p>
            <h1>文本、历史与语音</h1>
          </div>
          <div className="topbar-meta">
            <span className="meta-chip">
              <Clock3 aria-hidden="true" />
              {sessionId.slice(0, 8)}
            </span>
            <span className="meta-chip">
              <Search aria-hidden="true" />
              {selectedExperiment.title}
            </span>
            <span className="meta-chip notice" aria-live="polite">
              {globalNotice}
            </span>
          </div>
        </header>

        <div className="workspace-grid">
          <section className="primary-column">
            {view === 'assistant' && (
              <div className="stack">
                <section className="panel panel-form">
                  <div className="panel-header">
                    <div>
                      <p className="panel-kicker">助手</p>
                      <h2>提问</h2>
                    </div>
                    <div className="panel-actions">
                      <button
                        type="button"
                        className="icon-button"
                        onClick={() => void loadExperiments()}
                        title="刷新实验"
                      >
                        <RefreshCw aria-hidden="true" />
                      </button>
                    </div>
                  </div>
                  <div className="controls-grid">
                    <label className="field">
                      <span>实验</span>
                      <select
                        value={selectedExperimentId}
                        onChange={(event) => setSelectedExperimentId(event.target.value)}
                      >
                        <option value={EXPERIMENT_GENERIC.id}>{EXPERIMENT_GENERIC.title}</option>
                        {experiments.map((item) => (
                          <option key={item.id} value={item.id}>
                            {item.title} · {item.step_count} 步 · {item.knowledge_point_count} 点
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="field grow">
                      <span>问题</span>
                      <textarea
                        value={question}
                        onChange={(event) => setQuestion(event.target.value)}
                        placeholder="输入需要确认的实验问题"
                        rows={4}
                      />
                    </label>
                  </div>
                  <div className="toolbar">
                    <button
                      type="button"
                      className="primary-button"
                      onClick={() => void startQuestion()}
                      disabled={!question.trim() || textRequestPending || activeTurnId !== null}
                    >
                      <Send aria-hidden="true" />
                      发送
                    </button>
                    <button
                      type="button"
                      className="ghost-button"
                      onClick={() => setQuestion('')}
                      disabled={!question}
                    >
                      <X aria-hidden="true" />
                      清空
                    </button>
                    <button
                      type="button"
                      className="ghost-button"
                      onClick={() => void cancelCurrentQuery()}
                      disabled={activeTurnId === null && voicePhase === 'idle'}
                    >
                      <Square aria-hidden="true" />
                      取消
                    </button>
                  </div>
                </section>

                <section className="panel">
                  <div className="panel-header">
                    <div>
                      <p className="panel-kicker">会话</p>
                      <h2>消息流</h2>
                    </div>
                    <Pill tone={activeTurn ? 'neutral' : 'success'}>
                      {activeTurn ? activeTurn.status : '空闲'}
                    </Pill>
                  </div>
                  {turns.length === 0 ? (
                    <EmptyState
                      icon={MessageSquareText}
                      title="等待提问"
                      text="文本和语音结果会显示在这里。"
                    />
                  ) : (
                    <div className="turn-list">
                      {turns.map((turn) => (
                        <TurnCard
                          key={turn.id}
                          turn={turn}
                          onOpenReference={(reference) => openReference(reference, 'turn')}
                        />
                      ))}
                    </div>
                  )}
                </section>

                <section className="panel">
                  <div className="panel-header">
                    <div>
                      <p className="panel-kicker">录音</p>
                      <h2>语音控制</h2>
                    </div>
                    <Pill tone={voicePhase === 'error' ? 'danger' : 'neutral'}>{voicePhase}</Pill>
                  </div>
                  <div className="toolbar">
                    <button
                      type="button"
                      className="primary-button"
                      onClick={() => void startVoiceSession()}
                      disabled={voicePhase !== 'idle' || textRequestPending}
                    >
                      <Mic aria-hidden="true" />
                      开始录音
                    </button>
                    <button
                      type="button"
                      className="ghost-button"
                      onClick={() => void stopVoiceSession(true)}
                      disabled={voicePhase === 'idle'}
                    >
                      <Square aria-hidden="true" />
                      停止
                    </button>
                  </div>
                  <div className="voice-grid">
                    <div className="mini-panel">
                      <span className="mini-label">状态</span>
                      <strong>{voiceMessage}</strong>
                      <p>{voiceError || '浏览器录音通过 WebSocket 接入现有语音链路。'}</p>
                    </div>
                    <div className="mini-panel">
                      <span className="mini-label">转写</span>
                      <strong>{voiceTranscript || '等待转写'}</strong>
                      <p>{voiceSessionId ? `会话 ${voiceSessionId.slice(0, 10)}` : '未建立会话'}</p>
                    </div>
                  </div>
                  {voiceSegments.length > 0 && (
                    <div className="segment-strip" aria-label="TTS 分片">
                      {voiceSegments.map((segment) => (
                        <div
                          key={segment.sequence}
                          className="segment-chip"
                        >
                          <FileText aria-hidden="true" />
                          {segment.sequence + 1}
                          <span>{segment.text}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </section>
              </div>
            )}

            {view === 'history' && (
              <section className="panel">
                <div className="panel-header">
                  <div>
                    <p className="panel-kicker">历史</p>
                    <h2>记录与纠错</h2>
                  </div>
                  <div className="panel-actions">
                    <label className="inline-field">
                      <span>状态</span>
                      <select
                        value={historyStatusFilter}
                        onChange={(event) => {
                          setHistoryStatusFilter(event.target.value)
                          setHistoryPage(1)
                        }}
                      >
                        <option value="">全部</option>
                        <option value="completed">completed</option>
                        <option value="failed">failed</option>
                        <option value="cancelled">cancelled</option>
                      </select>
                    </label>
                    <label className="inline-field">
                      <span>每页</span>
                      <select
                        value={historyPageSize}
                        onChange={(event) => {
                          setHistoryPageSize(Number(event.target.value))
                          setHistoryPage(1)
                        }}
                      >
                        <option value={8}>8</option>
                        <option value={12}>12</option>
                        <option value={20}>20</option>
                      </select>
                    </label>
                  </div>
                </div>
                <div className="history-layout">
                  <div className="history-list">
                    {historyLoading ? (
                      <EmptyState icon={RefreshCw} title="加载中" text="正在读取历史记录。" />
                    ) : historyPageData.items.length === 0 ? (
                      <EmptyState icon={History} title="暂无记录" text="当前筛选条件下没有历史。" />
                    ) : (
                      historyPageData.items.map((item) => (
                        <HistoryRow
                          key={item.id}
                          item={item}
                          active={item.id === selectedHistoryId}
                          onSelect={() => setSelectedHistoryId(item.id)}
                          onOpenReference={(reference) => openReference(reference, 'history')}
                        />
                      ))
                    )}
                  </div>

                  <div className="history-detail">
                    {selectedHistory ? (
                      <div className="detail-stack">
                        <div className="detail-card">
                          <div className="detail-meta">
                            <Pill tone={historyTone(selectedHistory.status)}>
                              {selectedHistory.status}
                            </Pill>
                            <Pill tone="neutral">{selectedHistory.answer_source}</Pill>
                            <span className="detail-time">{selectedHistory.created_at}</span>
                          </div>
                          <h3>{selectedHistory.question}</h3>
                          <div className="detail-grid">
                            <div>
                              <span className="mini-label">系统回答</span>
                              <p>{selectedHistory.system_answer || '空'}</p>
                            </div>
                            <div>
                              <span className="mini-label">纠错回答</span>
                              <p>{selectedHistory.corrected_answer || '未填写'}</p>
                            </div>
                            <div>
                              <span className="mini-label">实验</span>
                              <p>{selectedHistory.experiment_id}</p>
                            </div>
                            <div>
                              <span className="mini-label">错误</span>
                              <p>{selectedHistory.error_code || '无'}</p>
                            </div>
                            <div>
                              <span className="mini-label">纠错时间</span>
                              <p>{selectedHistory.correction_updated_at || '未更新'}</p>
                            </div>
                          </div>
                        </div>

                        <div className="detail-card">
                          <div className="panel-header slim">
                            <div>
                              <p className="panel-kicker">纠错</p>
                              <h2>编辑</h2>
                            </div>
                            <button
                              type="button"
                              className="ghost-button"
                              onClick={() =>
                                setHistoryCorrection(selectedHistory.system_answer)
                              }
                            >
                              恢复系统答案
                            </button>
                          </div>
                          <label className="field">
                            <span>纠错内容</span>
                            <textarea
                              value={historyCorrection}
                              onChange={(event) => setHistoryCorrection(event.target.value)}
                              rows={5}
                            />
                          </label>
                          <div className="toolbar">
                            <button
                              type="button"
                              className="primary-button"
                              onClick={() => void saveCorrection()}
                              disabled={savingCorrection}
                            >
                              <CheckCircle2 aria-hidden="true" />
                              保存
                            </button>
                            <button
                              type="button"
                              className="ghost-button"
                              onClick={() => {
                                setHistoryCorrection(selectedHistory.corrected_answer)
                              }}
                            >
                              <RefreshCw aria-hidden="true" />
                              还原
                            </button>
                          </div>
                        </div>

                        <div className="detail-card">
                          <div className="panel-header slim">
                            <div>
                              <p className="panel-kicker">引用</p>
                              <h2>快照</h2>
                            </div>
                          </div>
                          {selectedHistory.references.length === 0 ? (
                            <EmptyState
                              icon={FileText}
                              title="无引用"
                              text="这条历史没有可展开的引用。"
                            />
                          ) : (
                            <div className="reference-list">
                              {selectedHistory.references.map((reference) => (
                                <ReferenceButton
                                  key={`${reference.chunk_id}-${reference.citation_index ?? 0}`}
                                  reference={reference}
                                  onClick={() => openReference(reference, 'history')}
                                />
                              ))}
                            </div>
                          )}
                        </div>
                      </div>
                    ) : (
                      <EmptyState
                        icon={FileText}
                        title="选择一条记录"
                        text="右侧会显示原始问题、系统回答、纠错和引用。"
                      />
                    )}
                  </div>
                </div>
                <div className="pagination">
                  <button
                    type="button"
                    className="ghost-button"
                    onClick={() => setHistoryPage((page) => Math.max(1, page - 1))}
                    disabled={historyPage <= 1}
                  >
                    <ChevronRight className="rotate-180" aria-hidden="true" />
                    上一页
                  </button>
                  <span>
                    第 {historyPage} 页 / 共 {Math.max(1, Math.ceil(historyPageData.total / historyPageSize))}{' '}
                    页
                  </span>
                  <button
                    type="button"
                    className="ghost-button"
                    onClick={() =>
                      setHistoryPage((page) =>
                        page < Math.ceil(historyPageData.total / historyPageSize) ? page + 1 : page,
                      )
                    }
                    disabled={historyPage * historyPageSize >= historyPageData.total}
                  >
                    下一页
                    <ChevronRight aria-hidden="true" />
                  </button>
                </div>
              </section>
            )}

            {view === 'system' && (
              <section className="panel">
                <div className="panel-header">
                  <div>
                    <p className="panel-kicker">系统</p>
                    <h2>运行状态</h2>
                  </div>
                  <Pill tone={health?.status === 'ok' ? 'success' : 'danger'}>
                    {health?.status ?? 'unknown'}
                  </Pill>
                </div>
                <div className="system-grid">
                  <div className="mini-panel">
                    <span className="mini-label">后端</span>
                    <strong>{health?.service ?? 'biosafe-api'}</strong>
                    <p>{health?.version ?? 'unknown'}</p>
                  </div>
                  <div className="mini-panel">
                    <span className="mini-label">实验</span>
                    <strong>{experiments.length}</strong>
                    <p>已加载实验场景</p>
                  </div>
                  <div className="mini-panel">
                    <span className="mini-label">历史</span>
                    <strong>{historyPageData.total}</strong>
                    <p>当前筛选结果</p>
                  </div>
                  <div className="mini-panel">
                    <span className="mini-label">语音</span>
                    <strong>{supportedVoice ? '可用' : '受限'}</strong>
                    <p>{voicePhase}</p>
                  </div>
                </div>
                <div className="note-row">
                  <TriangleAlert aria-hidden="true" />
                  <span>知识库管理入口保留到下一阶段。</span>
                </div>
              </section>
            )}
          </section>

          <aside className="inspector">
            <section className="panel inspector-panel">
              <div className="panel-header slim">
                <div>
                  <p className="panel-kicker">状态</p>
                  <h2>路径</h2>
                </div>
                <Pill tone={activeTurn ? toneForTurn(activeTurn) : 'neutral'}>
                  {activeTurn ? activeTurn.answerSource || activeTurn.status : '空闲'}
                </Pill>
              </div>
              {assistantTimeline.length === 0 ? (
                <EmptyState
                  icon={Activity}
                  title="暂无路径"
                  text="发起提问后会显示 received / instruction / direct / rag / completed。"
                />
              ) : (
                <div className="timeline">
                  {assistantTimeline.map((entry) => (
                    <div key={`${entry.sequence}-${entry.event}-${entry.stage}`} className="timeline-row">
                      <div className="timeline-mark" />
                      <div className="timeline-copy">
                        <div className="timeline-head">
                          <strong>{entry.label}</strong>
                          <span>{entry.event}</span>
                        </div>
                        <p>{entry.detail || '—'}</p>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </section>

            <section className="panel inspector-panel">
              <div className="panel-header slim">
                <div>
                  <p className="panel-kicker">引用</p>
                  <h2>当前回答</h2>
                </div>
              </div>
              {currentTurnReferences.length === 0 ? (
                <EmptyState
                  icon={FileText}
                  title="无引用"
                  text="命中 RAG 时会在这里列出 chunk 快照。"
                />
              ) : (
                <div className="reference-list">
                  {currentTurnReferences.map((reference) => (
                    <ReferenceButton
                      key={`${reference.chunk_id}-${reference.citation_index ?? 0}`}
                      reference={reference}
                      onClick={() => openReference(reference, 'turn')}
                    />
                  ))}
                </div>
              )}
            </section>
          </aside>
        </div>
      </main>

      {currentReference && (
        <aside className="drawer" aria-label="引用详情">
          <div className="drawer-header">
            <div>
              <p className="panel-kicker">引用详情</p>
              <h2>{currentReference.document_name || currentReference.chunk_id}</h2>
            </div>
            <button
              type="button"
              className="icon-button"
              onClick={() => setSelectedReference(null)}
              aria-label="关闭引用详情"
            >
              <X aria-hidden="true" />
            </button>
          </div>
          <div className="drawer-body">
            <div className="drawer-meta">
              <Pill tone={selectedReferenceOrigin === 'history' ? 'neutral' : 'success'}>
                {selectedReferenceOrigin === 'history' ? '历史' : '当前'}
              </Pill>
              <span className="drawer-line">{currentReference.dataset_name}</span>
              <span className="drawer-line">{currentReference.document_name}</span>
            </div>
            <div className="detail-grid compact">
              <div>
                <span className="mini-label">Chunk</span>
                <p>{currentReference.chunk_id}</p>
              </div>
              <div>
                <span className="mini-label">页码</span>
                <p>{joinNumbers(currentReference.page_numbers)}</p>
              </div>
              <div>
                <span className="mini-label">位置</span>
                <p>{joinNumbers(currentReference.positions)}</p>
              </div>
              <div>
                <span className="mini-label">相似度</span>
                <p>{formatSimilarity(currentReference)}</p>
              </div>
            </div>
            <div className="drawer-content">
              <span className="mini-label">片段</span>
              <p>{currentReference.content}</p>
            </div>
            {currentReference.source_url ? (
              <a className="source-link" href={currentReference.source_url} target="_blank" rel="noreferrer">
                原文入口
              </a>
            ) : null}
          </div>
        </aside>
      )}
    </div>
  )
}

function EmptyState({
  icon: Icon,
  title,
  text,
}: {
  icon: LucideIcon
  title: string
  text: string
}) {
  return (
    <div className="empty-state">
      <Icon aria-hidden="true" />
      <h3>{title}</h3>
      <p>{text}</p>
    </div>
  )
}

function TurnCard({
  turn,
  onOpenReference,
}: {
  turn: TurnRecord
  onOpenReference: (reference: CitationReference) => void
}) {
  return (
    <article className="turn-card">
      <div className="turn-head">
        <div className="turn-meta">
          <Pill tone={turn.inputMode === 'voice' ? 'success' : 'neutral'}>
            {turn.inputMode === 'voice' ? '语音' : '文本'}
          </Pill>
          <Pill tone={toneForTurn(turn)}>{turn.status}</Pill>
          <span className="turn-id">{turn.requestId || turn.id}</span>
        </div>
        <span className="turn-time">{new Date(turn.createdAt).toLocaleTimeString('zh-CN')}</span>
      </div>

      <div className="turn-question">
        <span className="mini-label">问题</span>
        <p>{turn.question || turn.transcript || '等待转写'}</p>
      </div>

      {turn.inputMode === 'voice' && turn.transcript && turn.transcript !== turn.question ? (
        <div className="turn-answer muted">
          <span className="mini-label">转写</span>
          <p>{turn.transcript}</p>
        </div>
      ) : null}

      {turn.answerSource === 'instruction' ? (
        <div className="turn-instruction">
          <span className="mini-label">指令</span>
          <strong>{turn.funcCall?.command || 'FuncCall'}</strong>
          <p>{formatInstructionAnswer(turn.funcCall)}</p>
          {turn.funcCall?.params ? <code>{JSON.stringify(turn.funcCall.params, null, 2)}</code> : null}
        </div>
      ) : (
        <div className="turn-answer">
          <span className="mini-label">回答</span>
          <p>{renderAnswerText(turn.answer)}</p>
        </div>
      )}

      {turn.references.length > 0 ? (
        <div className="turn-references">
          {turn.references.map((reference) => (
            <button
              key={`${reference.chunk_id}-${reference.citation_index ?? 0}`}
              type="button"
              className="citation-chip"
              onClick={() => onOpenReference(reference)}
            >
              <FileText aria-hidden="true" />
              {reference.citation_index ? `[${reference.citation_index}]` : '[?]'}
              <span>{reference.document_name}</span>
            </button>
          ))}
        </div>
      ) : null}

      {turn.errorMessage ? (
        <div className="turn-error">
          <span className="mini-label">错误</span>
          <p>
            {turn.errorCode ? `${turn.errorCode} · ` : ''}
            {turn.errorMessage}
          </p>
        </div>
      ) : null}
    </article>
  )
}

function HistoryRow({
  item,
  active,
  onSelect,
  onOpenReference,
}: {
  item: HistoryItem
  active: boolean
  onSelect: () => void
  onOpenReference: (reference: CitationReference) => void
}) {
  return (
    <article className={active ? 'history-row active' : 'history-row'}>
      <button type="button" className="history-row-main" onClick={onSelect}>
        <div className="history-row-head">
          <div className="history-row-title">
            <Pill tone={historyTone(item.status)}>{item.status}</Pill>
            <span>{item.question}</span>
          </div>
          <ChevronRight aria-hidden="true" />
        </div>
        <div className="history-row-copy">
          <p>{item.system_answer || '无系统回答'}</p>
          <span>
            {item.created_at} · {item.answer_source}
          </span>
        </div>
      </button>
      {item.references.length > 0 ? (
        <div className="history-ref-strip">
          {item.references.slice(0, 3).map((reference) => (
            <button
              key={`${reference.chunk_id}-${reference.citation_index ?? 0}`}
              type="button"
              className="mini-citation"
              onClick={() => onOpenReference(reference)}
            >
              {reference.citation_index ? `[${reference.citation_index}]` : '[?]'}
            </button>
          ))}
        </div>
      ) : null}
    </article>
  )
}

function ReferenceButton({
  reference,
  onClick,
}: {
  reference: CitationReference
  onClick: () => void
}) {
  return (
    <button type="button" className="reference-row" onClick={onClick}>
      <div className="reference-row-head">
        <strong>{reference.citation_index ? `[${reference.citation_index}]` : '[?]'}</strong>
        <span>{reference.document_name}</span>
      </div>
      <p>{reference.content}</p>
      <div className="reference-row-foot">
        <span>{reference.dataset_name}</span>
        <span>{joinNumbers(reference.page_numbers)}</span>
      </div>
    </button>
  )
}

function Pill({
  tone,
  children,
}: {
  tone: 'neutral' | 'success' | 'warning' | 'danger'
  children: ReactNode
}) {
  return <span className={`pill ${tone}`}>{children}</span>
}

function renderAnswerText(answer: string) {
  if (!answer) {
    return '等待回答'
  }
  const nodes: ReactNode[] = []
  const pattern = /\[(\d{1,3})\]/g
  let lastIndex = 0
  let match: RegExpExecArray | null
  while ((match = pattern.exec(answer)) !== null) {
    if (match.index > lastIndex) {
      nodes.push(answer.slice(lastIndex, match.index))
    }
    nodes.push(
      <span key={`${match.index}-${match[1]}`} className="citation-inline">
        [{match[1]}]
      </span>,
    )
    lastIndex = match.index + match[0].length
  }
  if (lastIndex < answer.length) {
    nodes.push(answer.slice(lastIndex))
  }
  return nodes
}

function formatInstructionAnswer(funcCall?: FuncCallData) {
  if (!funcCall) {
    return '已触发指令'
  }
  const paramsText = Object.keys(funcCall.params || {}).length
    ? `，参数 ${JSON.stringify(funcCall.params)}`
    : ''
  return `触发指令：${funcCall.command}${paramsText}`
}

function normalizeFuncCall(value: unknown): FuncCallData {
  const source = toJsonRecord(value)
  return {
    command: stringValue(source.command),
    confidence: numberValue(source.confidence),
    params: toJsonRecord(source.params),
  }
}

function normalizeQueryEvent(value: JsonRecord): QueryEventEnvelope | null {
  if (!value || typeof value !== 'object') {
    return null
  }
  return {
    event: stringValue(value.event),
    request_id: stringValue(value.request_id),
    sequence: numberValue(value.sequence),
    stage: stringValue(value.stage),
    data: toJsonRecord(value.data),
    timestamp: stringValue(value.timestamp),
  }
}

function parseSseBlock(block: string): QueryEventEnvelope | null {
  try {
    const dataLines = block
      .split(/\r?\n/)
      .filter((line) => line.startsWith('data:'))
      .map((line) => line.slice(5).trimStart())
    if (dataLines.length === 0) {
      return null
    }
    return normalizeQueryEvent(JSON.parse(dataLines.join('\n')))
  } catch {
    return null
  }
}

function summarizeStageEvent(payload: QueryEventEnvelope) {
  if (payload.event === 'stage_result') {
    const details: string[] = []
    if (payload.data.decision) {
      details.push(`decision=${stringValue(payload.data.decision)}`)
    }
    if (payload.data.chunk_count !== undefined) {
      details.push(`chunk_count=${numberValue(payload.data.chunk_count)}`)
    }
    if (payload.data.fallback_reason) {
      details.push(`fallback=${stringValue(payload.data.fallback_reason)}`)
    }
    return details.join(' · ') || '已更新'
  }
  if (payload.event === 'completed') {
    return stringAnswerSource(stringValue(payload.data.answer_source)) || 'completed'
  }
  if (payload.event === 'failed') {
    return `${stringValue(payload.data.code) || 'failed'} · ${stringValue(payload.data.message)}`
  }
  if (payload.event === 'cancelled') {
    return '已取消'
  }
  return payload.stage
}

function stageLabel(stage: string) {
  const mapping: Record<string, string> = {
    received: '已接收',
    instruction: '指令识别',
    direct_decision: '直答判断',
    retrieving: 'RAG 检索',
    synthesizing: '答案合成',
    completed: '完成',
    failed: '失败',
    cancelled: '已取消',
  }
  return mapping[stage] || stage
}

function historyTone(status: string) {
  if (status === 'completed') {
    return 'success'
  }
  if (status === 'failed' || status === 'cancelled') {
    return 'danger'
  }
  return 'neutral'
}

function toneForTurn(turn: TurnRecord) {
  if (turn.status === 'completed') {
    return 'success'
  }
  if (turn.status === 'failed' || turn.status === 'cancelled') {
    return 'danger'
  }
  return 'neutral'
}

function stringAnswerSource(value: string): AnswerSource {
  if (value === 'instruction' || value === 'direct' || value === 'rag' || value === 'error') {
    return value
  }
  return ''
}

function normalizeReferences(value: unknown): CitationReference[] {
  if (!Array.isArray(value)) {
    return []
  }
  return value.map((item) => normalizeReference(item)).filter((item) => item.chunk_id)
}

function normalizeReference(value: unknown): CitationReference {
  const source = toJsonRecord(value)
  return {
    citation_index: numberOrUndefined(source.citation_index),
    chunk_id: stringValue(source.chunk_id),
    dataset_id: stringValue(source.dataset_id),
    dataset_name: stringValue(source.dataset_name),
    document_id: stringValue(source.document_id),
    document_name: stringValue(source.document_name),
    content: stringValue(source.content),
    page_numbers: toNumberArray(source.page_numbers),
    positions: toNumberArray(source.positions),
    image_id: stringOrUndefined(source.image_id),
    similarity: numberOrUndefined(source.similarity),
    vector_similarity: numberOrUndefined(source.vector_similarity),
    term_similarity: numberOrUndefined(source.term_similarity),
    source_url: stringOrUndefined(source.source_url),
    raw_metadata: toJsonRecord(source.raw_metadata),
  }
}

function stringValue(value: unknown) {
  return typeof value === 'string' ? value : value === null || value === undefined ? '' : String(value)
}

function stringOrUndefined(value: unknown) {
  const result = stringValue(value)
  return result ? result : undefined
}

function numberValue(value: unknown) {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value
  }
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : 0
  }
  return 0
}

function numberOrUndefined(value: unknown) {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value
  }
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : undefined
  }
  return undefined
}

function toNumberArray(value: unknown) {
  if (!Array.isArray(value)) {
    return []
  }
  return value
    .map((item) => numberOrUndefined(item))
    .filter((item): item is number => typeof item === 'number')
}

function toJsonRecord(value: unknown) {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as JsonRecord) : {}
}

function joinNumbers(values: number[]) {
  return values.length > 0 ? values.join(', ') : '—'
}

function formatSimilarity(reference: CitationReference) {
  const values = [reference.similarity, reference.vector_similarity, reference.term_similarity]
    .filter((item): item is number => typeof item === 'number' && Number.isFinite(item))
    .map((item) => item.toFixed(3))
  return values.length > 0 ? values.join(' / ') : '—'
}

function describeError(error: unknown) {
  if (error instanceof Error) {
    return error.message
  }
  return String(error)
}

function safeParseJson(value: unknown) {
  if (typeof value !== 'string') {
    return null
  }
  try {
    return JSON.parse(value) as JsonRecord
  } catch {
    return null
  }
}

function currentSessionId() {
  const existing = window.sessionStorage.getItem('biosafe-session-id')
  if (existing) {
    return existing
  }
  const value = makeId('session')
  window.sessionStorage.setItem('biosafe-session-id', value)
  return value
}

function makeId(prefix: string) {
  const uuid =
    typeof crypto !== 'undefined' && 'randomUUID' in crypto
      ? crypto.randomUUID().replace(/-/g, '')
      : `${Date.now().toString(36)}${Math.random().toString(36).slice(2)}`
  return `${prefix}-${uuid.slice(0, 12)}`
}

function buildAudioSocketUrl(experimentId: string) {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}/api/v1/chat/audio?experiment_id=${encodeURIComponent(
    experimentId,
  )}`
}

function resolveRecordingMimeType() {
  if (typeof MediaRecorder === 'undefined' || typeof MediaRecorder.isTypeSupported !== 'function') {
    return ''
  }
  if (MediaRecorder.isTypeSupported('audio/webm;codecs=opus')) {
    return 'audio/webm;codecs=opus'
  }
  if (MediaRecorder.isTypeSupported('audio/webm')) {
    return 'audio/webm'
  }
  return ''
}

function bytesToBase64(bytes: Uint8Array) {
  let binary = ''
  const chunkSize = 0x8000
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    const chunk = bytes.subarray(offset, offset + chunkSize)
    binary += String.fromCharCode(...chunk)
  }
  return btoa(binary)
}
