import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  ChevronRight,
  FileText,
  LogIn,
  Plus,
  RefreshCw,
  RotateCcw,
  Search,
  Shield,
  Trash2,
  Upload,
  X,
} from 'lucide-react'

type JsonRecord = Record<string, unknown>

type KnowledgeDatasetItem = {
  id: string
  name: string
  chunk_method: string
  document_count: number
  embedding_model: string
  permission: string
  status: string
  parser_config: JsonRecord
  raw_metadata: JsonRecord
}

type KnowledgeDocumentItem = {
  id: string
  dataset_id: string
  name: string
  status: string
  chunk_count: number
  progress: number | null
  progress_message: string
  location: string
  size: number
  source_type: string
  document_type: string
  raw_metadata: JsonRecord
}

type KnowledgeChunkItem = {
  citation_index?: number | null
  chunk_id: string
  dataset_id: string
  dataset_name: string
  document_id: string
  document_name: string
  content: string
  page_numbers: number[]
  positions: Array<string | number | Record<string, unknown>>
  image_id?: string | null
  similarity?: number | null
  vector_similarity?: number | null
  term_similarity?: number | null
  source_url?: string | null
  raw_metadata?: JsonRecord
}

type AdminLoginResponse = {
  access_token: string
  token_type: string
  username: string
  expires_at: string
}

type DatasetPage = {
  items: KnowledgeDatasetItem[]
}

type DocumentPage = {
  items: KnowledgeDocumentItem[]
}

type PreviewResponse = {
  question: string
  dataset_ids: string[]
  chunks: KnowledgeChunkItem[]
}

type Props = {
  onNotice: (notice: string) => void
}

const STORAGE_KEY = 'biosafe-admin-token'
const DEFAULT_PREVIEW_QUESTION = 'P4实验室穿什么防护服，需要戴口罩吗'

const CHUNK_METHODS = [
  { value: 'laws', label: 'laws' },
  { value: 'manual', label: 'manual' },
  { value: 'table', label: 'table' },
  { value: 'paper', label: 'paper' },
  { value: 'naive', label: 'naive' },
] as const

export function KnowledgeAdminPanel({ onNotice }: Props) {
  const [token, setToken] = useState(() => loadToken())
  const [loginUsername, setLoginUsername] = useState('admin')
  const [loginPassword, setLoginPassword] = useState('')
  const [loginLoading, setLoginLoading] = useState(false)
  const [loginError, setLoginError] = useState('')
  const [loggedInUsername, setLoggedInUsername] = useState('')

  const [datasets, setDatasets] = useState<KnowledgeDatasetItem[]>([])
  const [datasetsLoading, setDatasetsLoading] = useState(false)
  const [selectedDatasetId, setSelectedDatasetId] = useState('')

  const [documents, setDocuments] = useState<KnowledgeDocumentItem[]>([])
  const [documentsLoading, setDocumentsLoading] = useState(false)
  const [documentFile, setDocumentFile] = useState<File | null>(null)

  const [datasetName, setDatasetName] = useState('')
  const [chunkMethod, setChunkMethod] = useState<(typeof CHUNK_METHODS)[number]['value']>('laws')
  const [savingDataset, setSavingDataset] = useState(false)

  const [previewQuestion, setPreviewQuestion] = useState(DEFAULT_PREVIEW_QUESTION)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewChunks, setPreviewChunks] = useState<KnowledgeChunkItem[]>([])

  const selectedDataset = useMemo(
    () => datasets.find((dataset) => dataset.id === selectedDatasetId) ?? null,
    [datasets, selectedDatasetId],
  )

  const authReady = Boolean(token)
  const reloadDatasets = useCallback(
    async (preferredDatasetId = '') => {
      if (!token) {
        return
      }
      setDatasetsLoading(true)
      try {
        const payload = await fetchDatasets(token)
        const items = payload.items ?? []
        setDatasets(items)
        const nextSelected =
          preferredDatasetId && items.some((item) => item.id === preferredDatasetId)
            ? preferredDatasetId
            : items[0]?.id ?? ''
        setSelectedDatasetId(nextSelected)
        if (!nextSelected) {
          setDocuments([])
          setPreviewChunks([])
        }
      } catch (error) {
        onNotice(`数据集加载失败：${describeError(error)}`)
      } finally {
        setDatasetsLoading(false)
      }
    },
    [onNotice, token],
  )
  const reloadDocuments = useCallback(
    async (datasetId: string) => {
      if (!token || !datasetId) {
        return
      }
      setDocumentsLoading(true)
      try {
        const payload = await fetchDocuments(token, datasetId)
        setDocuments(payload.items ?? [])
      } catch (error) {
        onNotice(`文档加载失败：${describeError(error)}`)
      } finally {
        setDocumentsLoading(false)
      }
    },
    [onNotice, token],
  )

  useEffect(() => {
    if (!token) {
      localStorage.removeItem(STORAGE_KEY)
      onNotice('知识库管理未登录')
      return
    }
    localStorage.setItem(STORAGE_KEY, token)
    const timeoutId = window.setTimeout(() => {
      void reloadDatasets()
    }, 0)
    return () => window.clearTimeout(timeoutId)
  }, [onNotice, reloadDatasets, token])

  useEffect(() => {
    if (!token || !selectedDatasetId) {
      return
    }
    const timeoutId = window.setTimeout(() => {
      void reloadDocuments(selectedDatasetId)
    }, 0)
    return () => window.clearTimeout(timeoutId)
  }, [reloadDocuments, selectedDatasetId, token])

  const login = useCallback(async () => {
    setLoginLoading(true)
    setLoginError('')
    try {
      const response = await fetch('/api/admin/login', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          username: loginUsername,
          password: loginPassword,
        }),
      })
      if (!response.ok) {
        const detail = await response.json().catch(() => null)
        const code =
          typeof detail?.detail?.code === 'string' ? detail.detail.code : `http_${response.status}`
        const message =
          typeof detail?.detail?.message === 'string'
            ? detail.detail.message
            : typeof detail?.detail === 'string'
              ? detail.detail
              : `HTTP ${response.status}`
        throw new Error(`${code}: ${message}`)
      }
      const payload = await readJson<AdminLoginResponse>(response)
      setLoggedInUsername(payload.username)
      setDatasets([])
      setDocuments([])
      setSelectedDatasetId('')
      setPreviewChunks([])
      setDocumentFile(null)
      setDatasetName('')
      setPreviewQuestion(DEFAULT_PREVIEW_QUESTION)
      setToken(payload.access_token)
      setLoginPassword('')
      onNotice('管理员登录成功')
    } catch (error) {
      setLoginError(describeError(error))
      onNotice('管理员登录失败')
    } finally {
      setLoginLoading(false)
    }
  }, [loginPassword, loginUsername, onNotice])

  const logout = useCallback(() => {
    setLoggedInUsername('')
    setDatasets([])
    setDocuments([])
    setSelectedDatasetId('')
    setPreviewChunks([])
    setDocumentFile(null)
    setDatasetName('')
    setPreviewQuestion(DEFAULT_PREVIEW_QUESTION)
    setToken('')
    setLoginError('')
    onNotice('管理员已退出')
  }, [onNotice])

  const refreshDatasets = useCallback(() => {
    if (!token) {
      return
    }
    void reloadDatasets(selectedDatasetId)
  }, [reloadDatasets, selectedDatasetId, token])

  const createDataset = useCallback(async () => {
    if (!token || !datasetName.trim()) {
      return
    }
    setSavingDataset(true)
    try {
      const response = await adminFetch(token, '/api/admin/knowledge/datasets', {
        method: 'POST',
        body: JSON.stringify({
          name: datasetName.trim(),
          chunk_method: chunkMethod,
        }),
      })
      const dataset = await readJson<KnowledgeDatasetItem>(response)
      setDatasetName('')
      onNotice(`已创建数据集 ${dataset.name}`)
      await reloadDatasets(dataset.id)
    } catch (error) {
      onNotice(`创建数据集失败：${describeError(error)}`)
    } finally {
      setSavingDataset(false)
    }
  }, [chunkMethod, datasetName, onNotice, reloadDatasets, token])

  const deleteDataset = useCallback(
    async (dataset: KnowledgeDatasetItem) => {
      if (!token || !window.confirm(`删除数据集 ${dataset.name}？`)) {
        return
      }
      try {
        await adminFetch(token, `/api/admin/knowledge/datasets/${dataset.id}`, {
          method: 'DELETE',
        })
        onNotice(`已删除数据集 ${dataset.name}`)
        await reloadDatasets(selectedDatasetId === dataset.id ? '' : selectedDatasetId)
      } catch (error) {
        onNotice(`删除数据集失败：${describeError(error)}`)
      }
    },
    [onNotice, reloadDatasets, selectedDatasetId, token],
  )

  const uploadDocument = useCallback(async () => {
    if (!token || !selectedDatasetId || !documentFile) {
      return
    }
    try {
      const formData = new FormData()
      formData.append('file', documentFile)
      await adminFetch(token, `/api/admin/knowledge/datasets/${selectedDatasetId}/documents`, {
        method: 'POST',
        body: formData,
      })
      setDocumentFile(null)
      onNotice(`已上传 ${documentFile.name}`)
      await reloadDocuments(selectedDatasetId)
      await reloadDatasets(selectedDatasetId)
    } catch (error) {
      onNotice(`上传失败：${describeError(error)}`)
    }
  }, [documentFile, onNotice, reloadDatasets, reloadDocuments, selectedDatasetId, token])

  const parseDocument = useCallback(
    async (document: KnowledgeDocumentItem, endpoint: 'parse' | 'retry' | 'cancel') => {
      if (!token) {
        return
      }
      try {
        await adminFetch(
          token,
          `/api/admin/knowledge/datasets/${document.dataset_id}/documents/${document.id}/${endpoint}`,
          { method: 'POST' },
        )
        onNotice(`${document.name} 已执行 ${endpoint}`)
        await reloadDocuments(document.dataset_id)
        await reloadDatasets(document.dataset_id)
      } catch (error) {
        onNotice(`${document.name} 操作失败：${describeError(error)}`)
      }
    },
    [onNotice, reloadDatasets, reloadDocuments, token],
  )

  const deleteDocument = useCallback(
    async (document: KnowledgeDocumentItem) => {
      if (!token || !window.confirm(`删除文档 ${document.name}？`)) {
        return
      }
      try {
        await adminFetch(
          token,
          `/api/admin/knowledge/datasets/${document.dataset_id}/documents/${document.id}`,
          { method: 'DELETE' },
        )
        onNotice(`已删除文档 ${document.name}`)
        await reloadDocuments(document.dataset_id)
        await reloadDatasets(document.dataset_id)
      } catch (error) {
        onNotice(`删除文档失败：${describeError(error)}`)
      }
    },
    [onNotice, reloadDatasets, reloadDocuments, token],
  )

  const previewRetrieval = useCallback(async () => {
    if (!token || !selectedDatasetId || !previewQuestion.trim()) {
      return
    }
    setPreviewLoading(true)
    try {
      const response = await adminFetch(token, '/api/admin/knowledge/retrieval-preview', {
        method: 'POST',
        body: JSON.stringify({
          question: previewQuestion.trim(),
          dataset_ids: [selectedDatasetId],
        }),
      })
      const payload = await readJson<PreviewResponse>(response)
      setPreviewChunks(payload.chunks ?? [])
      onNotice(`检索预览返回 ${payload.chunks?.length ?? 0} 个片段`)
    } catch (error) {
      onNotice(`检索预览失败：${describeError(error)}`)
    } finally {
      setPreviewLoading(false)
    }
  }, [onNotice, previewQuestion, selectedDatasetId, token])

  return (
    <div className="admin-workbench">
      <div className="admin-header">
        <div className="admin-title">
          <p className="panel-kicker">系统</p>
          <h2>知识库管理</h2>
        </div>
        <div className="admin-statusbar">
          <span className={authReady ? 'pill success' : 'pill warning'}>
            {authReady ? `已登录${loggedInUsername ? ` · ${loggedInUsername}` : ''}` : '未登录'}
          </span>
          {authReady ? (
            <button type="button" className="ghost-button" onClick={logout}>
              <X aria-hidden="true" />
              退出
            </button>
          ) : null}
          <button type="button" className="icon-button" onClick={refreshDatasets} disabled={!authReady}>
            <RefreshCw aria-hidden="true" />
          </button>
        </div>
      </div>

      {!authReady ? (
        <section className="admin-panel">
          <div className="panel-header">
            <div>
              <p className="panel-kicker">登录</p>
              <h3>管理员认证</h3>
            </div>
            <Shield aria-hidden="true" />
          </div>
          <div className="controls-grid">
            <label className="field">
              <span>用户名</span>
              <input value={loginUsername} onChange={(event) => setLoginUsername(event.target.value)} />
            </label>
            <label className="field">
              <span>密码</span>
              <input
                type="password"
                value={loginPassword}
                onChange={(event) => setLoginPassword(event.target.value)}
              />
            </label>
          </div>
          <p className="admin-auth-hint">
            账号由服务端 .env 中的 BIOSAFE_ADMIN_USERNAME 和 BIOSAFE_ADMIN_PASSWORD 配置。
          </p>
          <div className="toolbar">
            <button
              type="button"
              className="primary-button"
              onClick={() => void login()}
              disabled={loginLoading || !loginUsername.trim() || !loginPassword}
            >
              <LogIn aria-hidden="true" />
              登录
            </button>
          </div>
          {loginError ? (
            <div className="turn-error admin-error">
              <span className="mini-label">错误</span>
              <p>{loginError}</p>
            </div>
          ) : null}
        </section>
      ) : (
        <div className="admin-grid">
          <section className="admin-panel">
            <div className="panel-header">
              <div>
                <p className="panel-kicker">数据集</p>
                <h3>模板与状态</h3>
              </div>
              <button type="button" className="icon-button" onClick={() => void reloadDatasets(selectedDatasetId)}>
                <RefreshCw aria-hidden="true" />
              </button>
            </div>
            <div className="controls-grid">
              <label className="field grow">
                <span>数据集名</span>
                <input
                  value={datasetName}
                  onChange={(event) => setDatasetName(event.target.value)}
                  placeholder="biosafe-dev-..."
                />
              </label>
              <label className="field">
                <span>chunk method</span>
                <select value={chunkMethod} onChange={(event) => setChunkMethod(event.target.value as typeof chunkMethod)}>
                  {CHUNK_METHODS.map((item) => (
                    <option key={item.value} value={item.value}>
                      {item.label}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <div className="toolbar">
              <button
                type="button"
                className="primary-button"
                onClick={() => void createDataset()}
                disabled={savingDataset || !datasetName.trim()}
              >
                <Plus aria-hidden="true" />
                创建
              </button>
            </div>

            <div className="admin-list" role="list" aria-label="数据集列表">
              {datasetsLoading ? (
                <div className="empty-state compact">
                  <RefreshCw aria-hidden="true" />
                  <h3>加载中</h3>
                  <p>正在读取 RAGFlow 数据集。</p>
                </div>
              ) : datasets.length === 0 ? (
                <div className="empty-state compact">
                  <Shield aria-hidden="true" />
                  <h3>暂无数据集</h3>
                  <p>先创建一个开发数据集。</p>
                </div>
              ) : (
                datasets.map((dataset) => (
                  <div
                    key={dataset.id}
                    className={dataset.id === selectedDatasetId ? 'admin-list-row active' : 'admin-list-row'}
                  >
                    <button
                      type="button"
                      className="admin-list-main"
                      onClick={() => setSelectedDatasetId(dataset.id)}
                    >
                      <div className="admin-list-head">
                        <strong>{dataset.name}</strong>
                        <ChevronRight aria-hidden="true" />
                      </div>
                      <p>
                        {dataset.chunk_method} · {dataset.document_count} 文档 · {dataset.status || 'unknown'}
                      </p>
                    </button>
                    <button
                      type="button"
                      className="icon-button admin-list-action"
                      onClick={() => void deleteDataset(dataset)}
                      aria-label={`删除 ${dataset.name}`}
                    >
                      <Trash2 aria-hidden="true" />
                    </button>
                  </div>
                ))
              )}
            </div>
          </section>

          <section className="admin-panel">
            <div className="panel-header">
              <div>
                <p className="panel-kicker">文档</p>
                <h3>{selectedDataset?.name || '未选择数据集'}</h3>
              </div>
              <span className="pill neutral">{selectedDataset?.chunk_method || 'n/a'}</span>
            </div>

            <div className="controls-grid">
              <label className="field grow">
                <span>上传文件</span>
                <input type="file" onChange={(event) => setDocumentFile(event.target.files?.[0] ?? null)} />
              </label>
            </div>
            <div className="toolbar">
              <button
                type="button"
                className="primary-button"
                onClick={() => void uploadDocument()}
                disabled={!selectedDatasetId || !documentFile}
              >
                <Upload aria-hidden="true" />
                上传
              </button>
            </div>

            <div className="admin-list" role="list" aria-label="文档列表">
              {documentsLoading ? (
                <div className="empty-state compact">
                  <RefreshCw aria-hidden="true" />
                  <h3>加载中</h3>
                  <p>正在读取文档状态。</p>
                </div>
              ) : documents.length === 0 ? (
                <div className="empty-state compact">
                  <FileText aria-hidden="true" />
                  <h3>暂无文档</h3>
                  <p>上传后会显示解析状态。</p>
                </div>
              ) : (
                documents.map((document) => (
                  <article key={document.id} className="admin-doc-row">
                    <div className="admin-doc-copy">
                      <div className="admin-doc-head">
                        <strong>{document.name}</strong>
                        <span className="pill neutral">{document.status}</span>
                      </div>
                      <p>
                        {document.chunk_count} chunks · {document.progress_message || '等待状态'}
                      </p>
                    </div>
                    <div className="admin-doc-actions">
                      <button
                        type="button"
                        className="icon-button"
                        onClick={() => void parseDocument(document, 'parse')}
                        title="解析"
                      >
                        <RefreshCw aria-hidden="true" />
                      </button>
                      <button
                        type="button"
                        className="icon-button"
                        onClick={() => void parseDocument(document, 'retry')}
                        title="重试"
                      >
                        <RotateCcw aria-hidden="true" />
                      </button>
                      <button
                        type="button"
                        className="icon-button"
                        onClick={() => void parseDocument(document, 'cancel')}
                        title="取消"
                      >
                        <X aria-hidden="true" />
                      </button>
                      <button
                        type="button"
                        className="icon-button"
                        onClick={() => void deleteDocument(document)}
                        title="删除"
                      >
                        <Trash2 aria-hidden="true" />
                      </button>
                    </div>
                  </article>
                ))
              )}
            </div>

            <div className="admin-preview">
              <div className="panel-header slim">
                <div>
                  <p className="panel-kicker">预览</p>
                  <h3>检索片段</h3>
                </div>
              </div>
              <div className="controls-grid">
                <label className="field grow">
                  <span>问题</span>
                  <textarea
                    value={previewQuestion}
                    onChange={(event) => setPreviewQuestion(event.target.value)}
                    rows={3}
                  />
                </label>
              </div>
              <div className="toolbar">
                <button
                  type="button"
                  className="primary-button"
                  onClick={() => void previewRetrieval()}
                  disabled={previewLoading || !selectedDatasetId || !previewQuestion.trim()}
                >
                  <Search aria-hidden="true" />
                  预览
                </button>
              </div>
              {previewChunks.length === 0 ? (
                <div className="empty-state compact">
                  <Search aria-hidden="true" />
                  <h3>等待预览</h3>
                  <p>点击预览后展示检索片段。</p>
                </div>
              ) : (
                <div className="preview-list">
                  {previewChunks.map((chunk) => (
                    <article key={chunk.chunk_id} className="preview-row">
                      <div className="preview-row-head">
                        <strong>{chunk.citation_index ? `[${chunk.citation_index}]` : '[?]'}</strong>
                        <span>{chunk.document_name || chunk.chunk_id}</span>
                      </div>
                      <p>{chunk.content}</p>
                      <div className="preview-row-foot">
                        <span>{formatSimilarity(chunk)}</span>
                        <span>{chunk.dataset_name || chunk.dataset_id}</span>
                      </div>
                    </article>
                  ))}
                </div>
              )}
            </div>
          </section>
        </div>
      )}
    </div>
  )
}

async function fetchDatasets(token: string) {
  const response = await adminFetch(token, '/api/admin/knowledge/datasets?include_parsing_status=true')
  return await readJson<DatasetPage>(response)
}

async function fetchDocuments(token: string, datasetId: string) {
  const response = await adminFetch(token, `/api/admin/knowledge/datasets/${datasetId}/documents`)
  return await readJson<DocumentPage>(response)
}

async function adminFetch(token: string, path: string, init: RequestInit = {}) {
  const headers = new Headers(init.headers || {})
  headers.set('Authorization', `Bearer ${token}`)
  if (init.body && !(init.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  const response = await fetch(path, {
    ...init,
    headers,
  })
  if (!response.ok) {
    const detail = await response.json().catch(() => null)
    const code = typeof detail?.detail?.code === 'string' ? detail.detail.code : `http_${response.status}`
    const message =
      typeof detail?.detail?.message === 'string'
        ? detail.detail.message
        : typeof detail?.detail === 'string'
          ? detail.detail
          : `HTTP ${response.status}`
    throw new Error(`${code}: ${message}`)
  }
  return response
}

async function readJson<T>(response: Response): Promise<T> {
  return (await response.json()) as T
}

function loadToken() {
  if (typeof window === 'undefined') {
    return ''
  }
  return window.localStorage.getItem(STORAGE_KEY) ?? ''
}

function describeError(error: unknown) {
  if (error instanceof Error) {
    return error.message
  }
  return '请求失败'
}

function formatSimilarity(chunk: KnowledgeChunkItem) {
  const value = chunk.similarity ?? chunk.vector_similarity ?? chunk.term_similarity
  return value === undefined || value === null ? 'n/a' : value.toFixed(3)
}
