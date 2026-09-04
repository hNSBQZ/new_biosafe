import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { KeyboardEvent, ReactNode } from 'react'
import {
  Activity,
  Bot,
  BookOpen,
  CheckCircle2,
  ChevronRight,
  Clock3,
  FileText,
  History,
  Keyboard,
  Mic,
  MessageSquareText,
  RefreshCw,
  ScanSearch,
  Send,
  Settings2,
  Square,
  UserRound,
  Volume2,
  X,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { KnowledgeAdminPanel } from './KnowledgeAdminPanel'
import { KnowledgeRetrievalPanel } from './KnowledgeRetrievalPanel'
import { PcmStreamPlayer, decodeBase64Audio } from './audio/PcmStreamPlayer'

type ViewKey = 'assistant' | 'history' | 'system' | 'knowledge' | 'retrieval'
type TurnInputMode = 'text' | 'voice'
type TurnStatus = 'recording' | 'sending' | 'completed' | 'failed' | 'cancelled'
type AnswerSource = '' | 'instruction' | 'direct' | 'rag' | 'error'
type VoicePlayback = 'none' | 'buffering' | 'playing' | 'completed' | 'failed'
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
  auto_correction?: AutoCorrection | null
}

type AutoCorrectionCitation = {
  title: string
  url: string
  note: string
}

type AutoCorrection = {
  id: number
  history_id: number
  status: string
  model: string
  can_answer: boolean | null
  answer: string
  cannot_answer_reason: string
  citations: AutoCorrectionCitation[]
  error: string
  enqueued_at: string
  started_at?: string | null
  finished_at?: string | null
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
  voiceSegments: VoiceSegment[]
  voicePlayback: VoicePlayback
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

const VIEW_META: Record<ViewKey, { label: string; title: string; href: string; icon: LucideIcon }> = {
  assistant: { label: '助手演示', title: '生物安全实验助手', href: '/', icon: MessageSquareText },
  history: { label: '历史与纠错', title: '历史与人工纠错', href: '/admin/history', icon: History },
  system: { label: '系统状态', title: '系统运行状态', href: '/admin/system', icon: Settings2 },
  knowledge: { label: '知识库管理', title: '知识库管理', href: '/admin/knowledge', icon: BookOpen },
  retrieval: { label: '检索匹配', title: '检索匹配', href: '/admin/knowledge/retrieval', icon: ScanSearch },
}

const EXPERIMENT_GENERIC: ExperimentItem = {
  id: 'generic',
  title: '通用实验',
  step_count: 0,
  knowledge_point_count: 0,
}

export function App() {
  const [view, setView] = useState<ViewKey>(() => viewFromPath(window.location.pathname))
  const [composerMode, setComposerMode] = useState<TurnInputMode>('text')
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
  const selectedHistoryIdRef = useRef<number | null>(null)
  const [selectedHistory, setSelectedHistory] = useState<HistoryItem | null>(null)
  const [historyCorrection, setHistoryCorrection] = useState('')
  const [savingCorrection, setSavingCorrection] = useState(false)
  const [queueingCorrection, setQueueingCorrection] = useState(false)
  const [selectedReference, setSelectedReference] = useState<CitationReference | null>(null)
  const [selectedReferenceOrigin, setSelectedReferenceOrigin] = useState<'turn' | 'history'>(
    'turn',
  )
  const [textRequestPending, setTextRequestPending] = useState(false)
  const chatAbortRef = useRef<AbortController | null>(null)
  const voiceSocketRef = useRef<WebSocket | null>(null)
  const voicePlayerRef = useRef<PcmStreamPlayer | null>(null)
  const voicePlaybackFailedRef = useRef(false)
  const voiceConnectTimeoutRef = useRef<number | null>(null)
  const conversationRef = useRef<HTMLDivElement | null>(null)
  const recorderRef = useRef<MediaRecorder | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const voiceChunksRef = useRef<Blob[]>([])
  const voiceCancelRequestedRef = useRef(false)
  const voiceSessionCompleteReceivedRef = useRef(false)
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
  const supportedVoice = typeof window !== 'undefined' && 'MediaRecorder' in window

  useEffect(() => {
    void loadHealth()
    void loadExperiments()
  }, [])

  useEffect(() => {
    const handlePopState = () => setView(viewFromPath(window.location.pathname))
    window.addEventListener('popstate', handlePopState)
    return () => window.removeEventListener('popstate', handlePopState)
  }, [])

  useEffect(() => {
    const canonicalPath = VIEW_META[view].href
    if (window.location.pathname !== canonicalPath && isLegacyManagementPath(window.location.pathname)) {
      window.history.replaceState({}, '', canonicalPath)
    }
  }, [view])

  useEffect(() => {
    selectedHistoryIdRef.current = selectedHistoryId
  }, [selectedHistoryId])

  useEffect(() => {
    if (!experimentLoaded && experiments.length > 0) {
      setSelectedExperimentId(experiments[0].id)
      setExperimentLoaded(true)
    }
  }, [experimentLoaded, experiments])

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
    const historyId = selectedHistoryId
    const status = selectedHistory?.auto_correction?.status
    if (historyId === null || (status !== 'pending' && status !== 'running')) {
      return
    }
    const controller = new AbortController()
    const timeout = window.setTimeout(() => {
      void fetchHistoryDetail(historyId, controller.signal)
        .then((payload) => {
          setSelectedHistory((current) => (current?.id === historyId ? payload : current))
          setHistoryPageData((current) => ({
            ...current,
            items: current.items.map((item) => (item.id === payload.id ? payload : item)),
          }))
        })
        .catch(() => undefined)
    }, 1500)
    return () => {
      window.clearTimeout(timeout)
      controller.abort()
    }
  }, [selectedHistoryId, selectedHistory?.auto_correction?.status])

  useEffect(() => {
    return () => {
      chatAbortRef.current?.abort()
      clearVoiceConnectTimeout()
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

  const loadHistoryPage = useCallback(async () => {
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
        const stillVisible = payload.items.some((item) => item.id === selectedHistoryIdRef.current)
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
  }, [historyPage, historyPageSize, historyStatusFilter, selectedExperimentId])

  useEffect(() => {
    if (view !== 'assistant') {
      void loadHistoryPage()
    }
  }, [loadHistoryPage, view])

  useEffect(() => {
    const conversation = conversationRef.current
    if (view === 'assistant' && conversation) {
      if (typeof conversation.scrollTo === 'function') {
        conversation.scrollTo({ top: conversation.scrollHeight, behavior: 'smooth' })
      } else {
        conversation.scrollTop = conversation.scrollHeight
      }
    }
  }, [turns, view])

  async function loadHistoryDetail(historyId: number) {
    try {
      const payload = await fetchHistoryDetail(historyId)
      setSelectedHistory(payload)
    } catch (error) {
      setGlobalNotice(`历史详情加载失败：${describeError(error)}`)
    }
  }

  async function enqueueAutoCorrection() {
    if (selectedHistoryId === null) {
      return
    }
    setQueueingCorrection(true)
    try {
      const response = await fetch(`/api/history/${selectedHistoryId}/auto-correction`, {
        method: 'POST',
      })
      if (!response.ok) {
        throw new Error(`auto correction ${response.status}`)
      }
      const correction = (await response.json()) as AutoCorrection
      setSelectedHistory((current) => current ? { ...current, auto_correction: correction } : current)
      setHistoryPageData((current) => ({
        ...current,
        items: current.items.map((item) => (
          item.id === selectedHistoryId ? { ...item, auto_correction: correction } : item
        )),
      }))
      setGlobalNotice('模型修正已入队')
    } catch (error) {
      setGlobalNotice(`模型修正提交失败：${describeError(error)}`)
    } finally {
      setQueueingCorrection(false)
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
      voiceSegments: [],
      voicePlayback: 'none',
      references: [],
      timeline: [],
      rawEvents: [],
      createdAt: Date.now(),
    }
    setQuestion('')
    setTurns((current) => [...current, turn])
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
    voicePlaybackFailedRef.current = false
    const turnId = makeId('voice')
    pendingVoiceTurnIdRef.current = turnId
    setTurns((current) => [
      ...current,
      {
        id: turnId,
        inputMode: 'voice',
        status: 'recording',
        question: '',
        transcript: '',
        answerSource: '',
        answer: '',
        voiceSegments: [],
        voicePlayback: 'none',
        references: [],
        timeline: [],
        rawEvents: [],
        createdAt: Date.now(),
      },
    ])
    setActiveTurnId(turnId)
    try {
      const previousPlayer = voicePlayerRef.current
      voicePlayerRef.current = null
      if (previousPlayer) {
        void previousPlayer.stop()
      }
      const player = new PcmStreamPlayer()
      voicePlayerRef.current = player
      await player.prepare()
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      streamRef.current = stream
      voiceCancelRequestedRef.current = false
      voiceSessionCompleteReceivedRef.current = false
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
        let audioBytes: Uint8Array
        try {
          audioBytes = await blobToWavBytes(blob, 16_000)
        } catch (error) {
          const detail = `录音格式转换失败：${describeError(error)}`
          setVoicePhase('error')
          setVoiceError(detail)
          setVoiceMessage('录音处理失败')
          updateTurn(turnId, (item) => ({
            ...item,
            status: 'failed',
            answerSource: item.answerSource || 'error',
            errorCode: 'voice_audio_conversion_failed',
            errorMessage: detail,
          }))
          pendingVoiceTurnIdRef.current = null
          setActiveTurnId((current) => (current === turnId ? null : current))
          await stopVoiceResources()
          return
        }
        socket.send(
          JSON.stringify({
            type: 'audio_data',
            seq: 0,
            data: bytesToBase64(audioBytes),
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
      let socketOpened = false
      voiceSocketRef.current = socket
      voiceConnectTimeoutRef.current = window.setTimeout(() => {
        if (socket.readyState !== WebSocket.CONNECTING) {
          return
        }
        socket.close()
        setVoicePhase('error')
        setVoiceError('连接语音服务超时，请检查网络或服务地址')
        setVoiceMessage('连接超时')
        updateTurn(turnId, (item) => ({
          ...item,
          status: 'failed',
          answerSource: item.answerSource || 'error',
          errorCode: 'voice_socket_timeout',
          errorMessage: '连接语音服务超时',
        }))
        pendingVoiceTurnIdRef.current = null
        setActiveTurnId((current) => (current === turnId ? null : current))
        void stopVoiceResources()
      }, 8_000)
      socket.onopen = () => {
        socketOpened = true
        clearVoiceConnectTimeout()
        socket.send(
          JSON.stringify({
            type: 'audio_start',
            sample_rate: 16000,
            format: 'wav',
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
        clearVoiceConnectTimeout()
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
        pendingVoiceTurnIdRef.current = null
        setActiveTurnId((current) => (current === turnId ? null : current))
        void stopVoiceResources()
      }
      socket.onclose = () => {
        clearVoiceConnectTimeout()
        if (
          socketOpened &&
          !voiceCancelRequestedRef.current &&
          !voiceSessionCompleteReceivedRef.current
        ) {
          setVoicePhase('error')
          setVoiceError('语音连接意外中断')
          setVoiceMessage('语音连接已中断')
          void stopVoiceResources()
        }
      }
    } catch (error) {
      clearVoiceConnectTimeout()
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
          voicePlayback: item.voiceSegments.length > 0 ? 'failed' : item.voicePlayback,
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

  function finishVoiceRecording() {
    const recorder = recorderRef.current
    if (voicePhase !== 'recording' || !recorder || recorder.state === 'inactive') {
      return
    }
    setVoiceMessage('正在提交录音')
    recorder.stop()
  }

  async function handleVoiceMessage(turnId: string, message: JsonRecord) {
    const type = stringValue(message.type)
    if (type === 'connected') {
      setVoiceSessionId(stringValue(message.session_id))
      setVoiceMessage('录音会话已连接')
      return
    }
    if (type === 'status') {
      const phase = stringValue(message.phase)
      setVoiceMessage(voiceStatusLabel(phase, stringValue(message.text)))
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
        voicePlayback: 'buffering',
        references: normalizeReferences(message.references),
        historyId: numberValue(message.history_id) || item.historyId,
      }))
      return
    }
    if (type === 'audio_stream') {
      const streamEvent = stringValue(message.event)
      if (streamEvent === 'data') {
        const sequence = numberValue(message.sequence)
        const text = stringValue(message.text)
        updateTurn(turnId, (item) => ({
          ...item,
          voiceSegments: upsertVoiceSegment(item.voiceSegments, { sequence, text }),
          voicePlayback: 'playing',
        }))
        const player = voicePlayerRef.current
        if (player) {
          try {
            await player.enqueue({
              sequence,
              bytes: decodeBase64Audio(stringValue(message.data)),
              format: stringValue(message.format),
              sampleRate: numberValue(message.sample_rate),
              channels: numberValue(message.channels),
            })
            setVoiceMessage('正在播放语音')
          } catch (error) {
            const detail = `语音播放失败：${describeError(error)}`
            voicePlaybackFailedRef.current = true
            setVoiceError(detail)
            setVoiceMessage('语音播放失败，已保留文字')
            updateTurn(turnId, (item) => ({ ...item, voicePlayback: 'failed' }))
            voicePlayerRef.current = null
            await player.stop()
          }
        }
      }
      if (streamEvent === 'skipped') {
        const sequence = numberValue(message.sequence)
        updateTurn(turnId, (item) => ({
          ...item,
          voiceSegments: upsertVoiceSegment(item.voiceSegments, {
            sequence,
            text: stringValue(message.text),
          }),
        }))
        await voicePlayerRef.current?.skip(sequence)
      }
      if (streamEvent === 'finished') {
        const player = voicePlayerRef.current
        if (player) {
          try {
            setVoiceMessage('正在播放语音')
            await player.finish()
            if (voicePlayerRef.current === player) {
              voicePlayerRef.current = null
              setVoiceMessage(
                message.tts_success === true
                  ? '语音输出已完成'
                  : '语音合成失败，已保留文字',
              )
              updateTurn(turnId, (item) => ({
                ...item,
                voicePlayback: message.tts_success === true ? 'completed' : 'failed',
              }))
              setVoicePhase('idle')
            }
          } catch (error) {
            if (voicePlayerRef.current === player) {
              voicePlayerRef.current = null
              voicePlaybackFailedRef.current = true
              setVoiceError(`语音播放失败：${describeError(error)}`)
              setVoiceMessage('语音播放失败，已保留文字')
              updateTurn(turnId, (item) => ({ ...item, voicePlayback: 'failed' }))
              setVoicePhase('idle')
            }
            await player.stop()
          }
        }
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
      voiceSessionCompleteReceivedRef.current = true
      const reason = stringValue(message.reason)
      if (reason === 'interrupted') {
        setVoiceMessage('会话已中断')
      } else if (reason === 'error') {
        setVoiceMessage('会话失败')
      } else if (!voicePlayerRef.current && !voicePlaybackFailedRef.current) {
        setVoiceMessage('会话已完成')
      }
      if (reason !== 'done' || !voicePlayerRef.current) {
        setVoicePhase('idle')
      }
      pendingVoiceTurnIdRef.current = null
      setActiveTurnId(null)
      await stopVoiceResources(reason !== 'done')
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
          voicePlayback: 'buffering',
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

  function handleQuestionKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== 'Enter' || event.shiftKey || event.nativeEvent.isComposing) {
      return
    }
    event.preventDefault()
    void startQuestion()
  }

  function navigate(nextView: ViewKey) {
    const href = VIEW_META[nextView].href
    if (window.location.pathname !== href) {
      window.history.pushState({}, '', href)
    }
    setView(nextView)
  }

  async function stopVoiceResources(stopPlayback = true) {
    clearVoiceConnectTimeout()
    const recorder = recorderRef.current
    recorderRef.current = null
    if (recorder && recorder.state !== 'inactive') {
      recorder.ondataavailable = null
      recorder.onstop = null
      recorder.stop()
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop())
      streamRef.current = null
    }
    if (voiceSocketRef.current) {
      voiceSocketRef.current.close()
      voiceSocketRef.current = null
    }
    if (stopPlayback && voicePlayerRef.current) {
      const player = voicePlayerRef.current
      voicePlayerRef.current = null
      await player.stop()
    }
  }

  function clearVoiceConnectTimeout() {
    if (voiceConnectTimeoutRef.current !== null) {
      window.clearTimeout(voiceConnectTimeoutRef.current)
      voiceConnectTimeoutRef.current = null
    }
  }

  return (
    <div className={view === 'assistant' ? 'app-shell assistant-shell' : 'app-shell management-shell'}>
      {view !== 'assistant' && <aside className="sidebar">
        <a className="brand" href="/">
          <Activity aria-hidden="true" />
          <span>生物安全管理</span>
        </a>
        <nav aria-label="管理导航" className="nav">
          {(Object.keys(VIEW_META) as ViewKey[]).filter((key) => key !== 'assistant' && key !== 'retrieval').map((key) => {
            const Icon = VIEW_META[key].icon
            return (
              <a
                key={key}
                href={VIEW_META[key].href}
                className={view === key ? 'nav-item active' : 'nav-item'}
                onClick={(event) => {
                  event.preventDefault()
                  navigate(key)
                }}
                aria-current={view === key ? 'page' : undefined}
              >
                <Icon aria-hidden="true" />
                <span>{VIEW_META[key].label}</span>
              </a>
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
      </aside>}

      <main className="workspace">
        {view === 'assistant' ? (
          <header className="chat-topbar">
            <div className="chat-brand">
              <span className="chat-brand-mark"><Activity aria-hidden="true" /></span>
              <div>
                <h1>生物安全实验助手</h1>
                <p><span className={health?.status === 'ok' ? 'online-dot' : 'online-dot offline'} />{health?.status === 'ok' ? '在线' : '服务异常'}</p>
              </div>
            </div>
            <div className="chat-context">
              <label className="experiment-select">
                <span>实验场景</span>
                <select
                  value={selectedExperimentId}
                  onChange={(event) => setSelectedExperimentId(event.target.value)}
                  aria-label="实验场景"
                >
                  <option value={EXPERIMENT_GENERIC.id}>{EXPERIMENT_GENERIC.title}</option>
                  {experiments.filter((item) => item.id !== EXPERIMENT_GENERIC.id).map((item) => (
                    <option key={item.id} value={item.id}>{item.title}</option>
                  ))}
                </select>
              </label>
              <button type="button" className="icon-button" onClick={() => void loadExperiments()} title="刷新实验">
                <RefreshCw aria-hidden="true" />
              </button>
            </div>
          </header>
        ) : (
          <header className="topbar">
            <div className="topbar-copy">
              <p className="eyebrow">管理控制台</p>
              <h1>{VIEW_META[view].title}</h1>
            </div>
            <div className="topbar-meta">
              <span className="meta-chip"><Clock3 aria-hidden="true" />{sessionId.slice(0, 8)}</span>
              <span className="meta-chip notice" aria-live="polite">{globalNotice}</span>
            </div>
          </header>
        )}

        <div className={view === 'assistant' ? 'workspace-grid' : 'workspace-grid single-column'}>
          <section className="primary-column">
            {view === 'assistant' && (
              <div className="chat-page">
                <section className="conversation" ref={conversationRef} aria-label="对话消息">
                  {turns.length === 0 ? (
                    <div className="chat-welcome">
                      <span className="welcome-mark"><Bot aria-hidden="true" /></span>
                      <h2>今天想确认什么实验问题？</h2>
                      <div className="prompt-suggestions" aria-label="示例问题">
                        {[
                          '生物安全柜使用前需要检查什么？',
                          '样本发生泄漏应该如何处置？',
                          '高压灭菌的关键参数有哪些？',
                        ].map((prompt) => (
                          <button key={prompt} type="button" onClick={() => setQuestion(prompt)}>{prompt}</button>
                        ))}
                      </div>
                    </div>
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

                <section className="chat-composer" aria-label="消息输入">
                  <div className="composer-mode" role="group" aria-label="提问方式">
                    <button
                      type="button"
                      className={composerMode === 'text' ? 'active' : ''}
                      onClick={() => setComposerMode('text')}
                      aria-pressed={composerMode === 'text'}
                      disabled={voicePhase !== 'idle'}
                    ><Keyboard aria-hidden="true" />文字</button>
                    <button
                      type="button"
                      className={composerMode === 'voice' ? 'active' : ''}
                      onClick={() => setComposerMode('voice')}
                      aria-pressed={composerMode === 'voice'}
                      disabled={voicePhase !== 'idle'}
                    ><Mic aria-hidden="true" />语音</button>
                  </div>

                  {composerMode === 'text' ? (
                    <div className="text-composer-row">
                      <textarea
                        value={question}
                        onChange={(event) => setQuestion(event.target.value)}
                        onKeyDown={handleQuestionKeyDown}
                        placeholder={`向${selectedExperiment.title}提问`}
                        rows={1}
                        aria-label="问题"
                      />
                      {activeTurnId !== null ? (
                        <button type="button" className="composer-action stop" onClick={() => void cancelCurrentQuery()} aria-label="取消">
                          <Square aria-hidden="true" />
                        </button>
                      ) : (
                        <button
                          type="button"
                          className="composer-action send"
                          onClick={() => void startQuestion()}
                          disabled={!question.trim() || textRequestPending}
                          aria-label="发送"
                        ><Send aria-hidden="true" /></button>
                      )}
                    </div>
                  ) : (
                    <div className="voice-input-row">
                      <button
                        type="button"
                        className={voicePhase === 'recording' ? 'voice-submit recording' : 'voice-submit'}
                        onClick={() => voicePhase === 'idle' ? void startVoiceSession() : finishVoiceRecording()}
                        disabled={textRequestPending || voicePhase === 'connecting' || voicePhase === 'processing'}
                        aria-label={voicePhase === 'recording' ? '停止录音' : '开始录音'}
                      >
                        {voicePhase === 'recording' ? <Square aria-hidden="true" /> : <Mic aria-hidden="true" />}
                        <span>{voicePhase === 'recording' ? '结束并发送' : '开始录音'}</span>
                      </button>
                      <div className="voice-inline-status" aria-live="polite">
                        <strong>{voiceMessage}</strong>
                        <span>{voiceError || voiceTranscript || '点击后开始讲话'}</span>
                      </div>
                      {voicePhase !== 'idle' && (
                        <button type="button" className="composer-action stop" onClick={() => void stopVoiceSession(true)} aria-label="取消">
                          <X aria-hidden="true" />
                        </button>
                      )}
                    </div>
                  )}
                  <div className="composer-foot">
                    <span aria-live="polite">{activeTurn ? stageLabel(activeTurn.timeline.at(-1)?.stage || activeTurn.status) : globalNotice}</span>
                    {composerMode === 'voice' && voiceSessionId ? <span>会话 {voiceSessionId.slice(0, 10)}</span> : null}
                  </div>
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
                              <p className="panel-kicker">自动修正</p>
                              <h2>模型复核</h2>
                            </div>
                            <div className="toolbar compact-toolbar">
                              {selectedHistory.auto_correction ? (
                                <Pill tone={correctionTone(selectedHistory.auto_correction.status)}>
                                  {correctionStatusLabel(selectedHistory.auto_correction.status)}
                                </Pill>
                              ) : null}
                              <button
                                type="button"
                                className="ghost-button"
                                onClick={() => void enqueueAutoCorrection()}
                                disabled={
                                  queueingCorrection
                                  || selectedHistory.auto_correction?.status === 'pending'
                                  || selectedHistory.auto_correction?.status === 'running'
                                  || selectedHistory.status !== 'completed'
                                  || !['direct', 'rag'].includes(selectedHistory.answer_source)
                                }
                              >
                                <RefreshCw aria-hidden="true" />
                                {selectedHistory.auto_correction ? '重新修正' : '提交修正'}
                              </button>
                            </div>
                          </div>
                          {selectedHistory.auto_correction ? (
                            <AutoCorrectionPanel
                              correction={selectedHistory.auto_correction}
                              onAdopt={(answer) => setHistoryCorrection(answer)}
                            />
                          ) : (
                            <p className="correction-message">暂无模型修正记录</p>
                          )}
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
              <div className="stack">
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
                </section>
              </div>
            )}

            {view === 'knowledge' && (
              <section className="knowledge-page">
                <KnowledgeAdminPanel
                  onNotice={setGlobalNotice}
                  onOpenRetrieval={() => navigate('retrieval')}
                />
              </section>
            )}

            {view === 'retrieval' && (
              <section className="knowledge-page">
                <KnowledgeRetrievalPanel
                  onNotice={setGlobalNotice}
                  onBack={() => navigate('knowledge')}
                />
              </section>
            )}
          </section>

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

export function TurnCard({
  turn,
  onOpenReference,
}: {
  turn: TurnRecord
  onOpenReference: (reference: CitationReference) => void
}) {
  const latestStage = turn.timeline.at(-1)
  const pending = turn.status === 'sending' || turn.status === 'recording'
  const voiceStreaming = turn.voicePlayback === 'buffering' || turn.voicePlayback === 'playing'
  const voiceSegments = [...turn.voiceSegments].sort((left, right) => left.sequence - right.sequence)
  const answerText = turn.inputMode === 'voice' && voiceStreaming
    ? voiceSegments.map((segment) => segment.text).join('')
    : turn.answer

  return (
    <article className="conversation-turn">
      <div className="message-row user-message">
        <div className="message-column">
          <div className="message-meta">
            <span>{turn.inputMode === 'voice' ? '语音提问' : '你'}</span>
            <time>{new Date(turn.createdAt).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}</time>
          </div>
          <div className="message-bubble user-bubble">
            <p>{turn.question || turn.transcript || '正在听取语音…'}</p>
          </div>
        </div>
        <span className="message-avatar user-avatar"><UserRound aria-hidden="true" /></span>
      </div>

      <div className="message-row assistant-message">
        <span className="message-avatar assistant-avatar"><Bot aria-hidden="true" /></span>
        <div className="message-column">
          <div className="message-meta">
            <span>实验助手</span>
            <Pill tone={toneForTurn(turn)}>{answerSourceLabel(turn.answerSource, turn.status)}</Pill>
          </div>
          <div className={turn.errorMessage ? 'message-bubble assistant-bubble error' : 'message-bubble assistant-bubble'}>
            {turn.inputMode === 'voice' && turn.voicePlayback !== 'none' ? (
              <VoicePlaybackBar state={turn.voicePlayback} segmentCount={voiceSegments.length} />
            ) : null}
            {turn.answerSource === 'instruction' ? (
              <div className="instruction-answer">
                <strong>{turn.funcCall?.command || '已识别实验指令'}</strong>
                <p>{formatInstructionAnswer(turn.funcCall)}</p>
              </div>
            ) : turn.inputMode === 'voice' && voiceStreaming && voiceSegments.length > 0 ? (
              <div className="voice-subtitles" aria-live="polite" aria-label="语音回答字幕">
                {voiceSegments.map((segment) => (
                  <p key={segment.sequence}>
                    {renderAnswerText(segment.text, turn.references, onOpenReference)}
                  </p>
                ))}
              </div>
            ) : answerText ? (
              <p>{renderAnswerText(answerText, turn.references, onOpenReference)}</p>
            ) : pending || voiceStreaming ? (
              <div className="typing-state" aria-live="polite">
                <span /><span /><span />
                <strong>{latestStage?.label || (turn.status === 'recording' ? '正在录音' : '正在思考')}</strong>
              </div>
            ) : (
              <p>本轮没有返回回答。</p>
            )}

            {turn.errorMessage ? (
              <p className="message-error">{turn.errorCode ? `${turn.errorCode}：` : ''}{turn.errorMessage}</p>
            ) : null}

            {turn.references.length > 0 ? (
              <div className="turn-references" aria-label="回答引用">
                {turn.references.map((reference) => (
                  <button
                    key={`${reference.chunk_id}-${reference.citation_index ?? 0}`}
                    type="button"
                    className="citation-chip"
                    onClick={() => onOpenReference(reference)}
                    aria-label={`${reference.citation_index ? `[${reference.citation_index}]` : '[?]'}${reference.document_name}`}
                  >
                    <FileText aria-hidden="true" />
                    {reference.citation_index ? `[${reference.citation_index}]` : '[?]'}
                    <span>{reference.document_name}</span>
                  </button>
                ))}
              </div>
            ) : null}
          </div>
          {turn.inputMode === 'voice' && turn.transcript ? (
            <span className="transcript-note">转写：{turn.transcript}</span>
          ) : null}
        </div>
      </div>
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

function AutoCorrectionPanel({
  correction,
  onAdopt,
}: {
  correction: AutoCorrection
  onAdopt: (answer: string) => void
}) {
  const active = correction.status === 'pending' || correction.status === 'running'
  const failed = ['parse_error', 'request_error', 'dropped'].includes(correction.status)
  return (
    <div className="auto-correction" aria-live="polite">
      <div className="correction-meta">
        <span>模型：{correction.model || '等待执行'}</span>
        <span>入队：{correction.enqueued_at}</span>
        {correction.finished_at ? <span>完成：{correction.finished_at}</span> : null}
      </div>
      {active ? (
        <p className="correction-message">
          {correction.status === 'pending' ? '等待模型复核' : '模型正在复核'}
        </p>
      ) : null}
      {correction.status === 'success' && correction.can_answer && correction.answer ? (
        <>
          <div className="correction-answer">
            <span className="mini-label">模型建议</span>
            <p>{correction.answer}</p>
          </div>
          <button
            type="button"
            className="ghost-button adopt-correction"
            onClick={() => onAdopt(correction.answer)}
          >
            <CheckCircle2 aria-hidden="true" />
            采用模型建议
          </button>
        </>
      ) : null}
      {correction.status === 'success' && correction.can_answer === false ? (
        <div className="correction-answer">
          <span className="mini-label">无法可靠回答</span>
          <p>{correction.cannot_answer_reason || '公开来源不足'}</p>
        </div>
      ) : null}
      {failed ? (
        <p className="correction-error">{correction.error || '模型修正失败'}</p>
      ) : null}
      {correction.citations.length > 0 ? (
        <div className="correction-sources">
          <span className="mini-label">公开来源</span>
          {correction.citations.map((citation, index) => (
            citation.url ? (
              <a
                key={`${citation.url}-${index}`}
                href={citation.url}
                target="_blank"
                rel="noreferrer"
              >
                <strong>{citation.title || `来源 ${index + 1}`}</strong>
                {citation.note ? <span>{citation.note}</span> : null}
              </a>
            ) : (
              <div key={`${citation.title}-${index}`} className="correction-source-text">
                <strong>{citation.title || `来源 ${index + 1}`}</strong>
                {citation.note ? <span>{citation.note}</span> : null}
              </div>
            )
          ))}
        </div>
      ) : null}
    </div>
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

function VoicePlaybackBar({
  state,
  segmentCount,
}: {
  state: VoicePlayback
  segmentCount: number
}) {
  const active = state === 'buffering' || state === 'playing'
  const label = state === 'buffering'
    ? '正在缓冲语音'
    : state === 'playing'
      ? '正在播放语音'
      : state === 'completed'
        ? '语音播放完成'
        : '语音播放失败，文字已保留'
  return (
    <div className={`voice-answer-stream ${active ? 'active' : state}`} aria-label={label}>
      <Volume2 aria-hidden="true" />
      <div className="voice-waveform" aria-hidden="true">
        {Array.from({ length: 18 }, (_, index) => <span key={index} />)}
      </div>
      <span className="voice-playback-label">{label}</span>
      {segmentCount > 0 ? <span className="voice-segment-count">{segmentCount} 段</span> : null}
    </div>
  )
}

function renderAnswerText(
  answer: string,
  references: CitationReference[] = [],
  onOpenReference?: (reference: CitationReference) => void,
) {
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
    const citationIndex = Number(match[1])
    const reference = references.find((item) => item.citation_index === citationIndex)
    nodes.push(reference && onOpenReference ? (
      <button
        key={`${match.index}-${match[1]}`}
        type="button"
        className="citation-inline"
        onClick={() => onOpenReference(reference)}
        title={`查看来源：${reference.document_name}`}
        aria-label={`引用 ${citationIndex}，${reference.document_name}`}
      >
        [{match[1]}]<span>{reference.document_name}</span>
      </button>
    ) : (
      <span key={`${match.index}-${match[1]}`} className="citation-inline missing">
        [{match[1]}]
      </span>
    ))
    lastIndex = match.index + match[0].length
  }
  if (lastIndex < answer.length) {
    nodes.push(answer.slice(lastIndex))
  }
  return nodes
}

function upsertVoiceSegment(segments: VoiceSegment[], next: VoiceSegment) {
  const bySequence = new Map(segments.map((segment) => [segment.sequence, segment]))
  bySequence.set(next.sequence, next)
  return [...bySequence.values()].sort((left, right) => left.sequence - right.sequence)
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
    recording: '正在录音',
    sending: '正在思考',
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

function answerSourceLabel(source: AnswerSource, status: TurnStatus) {
  const mapping: Record<AnswerSource, string> = {
    '': stageLabel(status),
    instruction: '实验指令',
    direct: '直接回答',
    rag: '知识库回答',
    error: status === 'cancelled' ? '已取消' : '回答失败',
  }
  return mapping[source]
}

function voiceStatusLabel(phase: string, fallback: string) {
  const labels: Record<string, string> = {
    recording_started: '正在录音',
    asr_started: '正在识别语音',
    query_started: '正在生成回答',
    tts_started: '正在合成语音',
  }
  return labels[phase] || fallback || phase
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

function correctionTone(status: string) {
  if (status === 'success') {
    return 'success'
  }
  if (status === 'pending' || status === 'running') {
    return 'warning'
  }
  return 'danger'
}

function correctionStatusLabel(status: string) {
  const labels: Record<string, string> = {
    pending: '等待中',
    running: '复核中',
    success: '已完成',
    parse_error: '解析失败',
    request_error: '请求失败',
    dropped: '队列已满',
  }
  return labels[status] || status
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
  const documentId = stringValue(source.document_id)
  return {
    citation_index: numberOrUndefined(source.citation_index),
    chunk_id: stringValue(source.chunk_id),
    dataset_id: stringValue(source.dataset_id),
    dataset_name: stringValue(source.dataset_name),
    document_id: documentId,
    document_name: stringValue(source.document_name) || documentId || '未命名文档',
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

async function fetchHistoryDetail(historyId: number, signal?: AbortSignal) {
  const response = await fetch(`/api/history/${historyId}`, { signal })
  if (!response.ok) {
    throw new Error(`history detail ${response.status}`)
  }
  return (await response.json()) as HistoryItem
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

function viewFromPath(pathname: string): ViewKey {
  const normalized = pathname.length > 1 ? pathname.replace(/\/+$/, '') : pathname
  if (normalized === '/history' || normalized === '/admin/history') {
    return 'history'
  }
  if (normalized === '/system' || normalized === '/admin/system') {
    return 'system'
  }
  if (
    normalized === '/admin/knowledge/retrieval'
  ) {
    return 'retrieval'
  }
  if (
    normalized === '/knowledge' ||
    normalized === '/admin' ||
    normalized === '/admin/knowledge'
  ) {
    return 'knowledge'
  }
  return 'assistant'
}

function isLegacyManagementPath(pathname: string) {
  const normalized = pathname.length > 1 ? pathname.replace(/\/+$/, '') : pathname
  return normalized === '/history' || normalized === '/system' || normalized === '/knowledge'
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

async function blobToWavBytes(blob: Blob, targetSampleRate: number) {
  const context = new AudioContext()
  try {
    const decoded = await context.decodeAudioData(await blob.arrayBuffer())
    const mono = new Float32Array(decoded.length)
    for (let channel = 0; channel < decoded.numberOfChannels; channel += 1) {
      const channelData = decoded.getChannelData(channel)
      for (let index = 0; index < channelData.length; index += 1) {
        mono[index] += channelData[index] / decoded.numberOfChannels
      }
    }
    const resampled = resampleAudio(mono, decoded.sampleRate, targetSampleRate)
    return encodeMonoWav(resampled, targetSampleRate)
  } finally {
    await context.close()
  }
}

function resampleAudio(input: Float32Array, sourceRate: number, targetRate: number) {
  if (sourceRate === targetRate) {
    return input
  }
  const ratio = sourceRate / targetRate
  const output = new Float32Array(Math.max(1, Math.round(input.length / ratio)))
  for (let index = 0; index < output.length; index += 1) {
    const sourcePosition = index * ratio
    const left = Math.floor(sourcePosition)
    const right = Math.min(left + 1, input.length - 1)
    const weight = sourcePosition - left
    output[index] = input[left] * (1 - weight) + input[right] * weight
  }
  return output
}

function encodeMonoWav(samples: Float32Array, sampleRate: number) {
  const bytesPerSample = 2
  const wav = new Uint8Array(44 + samples.length * bytesPerSample)
  const view = new DataView(wav.buffer)
  writeAscii(view, 0, 'RIFF')
  view.setUint32(4, wav.length - 8, true)
  writeAscii(view, 8, 'WAVE')
  writeAscii(view, 12, 'fmt ')
  view.setUint32(16, 16, true)
  view.setUint16(20, 1, true)
  view.setUint16(22, 1, true)
  view.setUint32(24, sampleRate, true)
  view.setUint32(28, sampleRate * bytesPerSample, true)
  view.setUint16(32, bytesPerSample, true)
  view.setUint16(34, 16, true)
  writeAscii(view, 36, 'data')
  view.setUint32(40, samples.length * bytesPerSample, true)
  for (let index = 0; index < samples.length; index += 1) {
    const sample = Math.max(-1, Math.min(1, samples[index]))
    view.setInt16(44 + index * bytesPerSample, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true)
  }
  return wav
}

function writeAscii(view: DataView, offset: number, value: string) {
  for (let index = 0; index < value.length; index += 1) {
    view.setUint8(offset + index, value.charCodeAt(index))
  }
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
