import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  AlertCircle,
  CheckCircle2,
  Download,
  Eye,
  FileText,
  FilterX,
  LoaderCircle,
  LogIn,
  RefreshCw,
  RotateCcw,
  Search,
  Shield,
  Trash2,
  Upload,
  X,
} from 'lucide-react'

type KnowledgeCategory = 'laws' | 'manual' | 'table' | 'paper' | 'naive'
type KnowledgeFileStatus = 'uploaded' | 'parsing' | 'completed' | 'failed'

type KnowledgeFileItem = {
  id: string
  name: string
  category: KnowledgeCategory
  category_label: string
  status: KnowledgeFileStatus
  status_label: string
  progress: number | null
  status_message: string
  size: number
  created_at: string | null
  updated_at: string | null
  preview_kind: 'pdf' | 'image' | 'text' | 'download'
}

type KnowledgeFilePage = {
  items: KnowledgeFileItem[]
  total: number
}

type AdminLoginResponse = {
  access_token: string
  username: string
}

type Filters = {
  name: string
  category: '' | KnowledgeCategory
  status: '' | KnowledgeFileStatus
  dateFrom: string
  dateTo: string
}

type PreviewState = {
  file: KnowledgeFileItem
  url: string
} | null

type Props = {
  onNotice: (notice: string) => void
}

class AdminRequestError extends Error {
  code: string
  existing: KnowledgeFileItem | null

  constructor(code: string, message: string, existing: KnowledgeFileItem | null = null) {
    super(`${code}: ${message}`)
    this.code = code
    this.existing = existing
  }
}

const STORAGE_KEY = 'biosafe-admin-token'
const EMPTY_FILTERS: Filters = { name: '', category: '', status: '', dateFrom: '', dateTo: '' }
const CATEGORIES: Array<{ value: KnowledgeCategory; label: string }> = [
  { value: 'laws', label: '法规标准' },
  { value: 'manual', label: 'SOP 与设备手册' },
  { value: 'table', label: '名录与表格' },
  { value: 'paper', label: '论文与报告' },
  { value: 'naive', label: '通用资料' },
]
const STATUSES: Array<{ value: KnowledgeFileStatus; label: string }> = [
  { value: 'completed', label: '已完成' },
  { value: 'uploaded', label: '已上传' },
  { value: 'parsing', label: '解析中' },
  { value: 'failed', label: '失败' },
]

export function KnowledgeAdminPanel({ onNotice }: Props) {
  const [token, setToken] = useState(() => loadToken())
  const [loginUsername, setLoginUsername] = useState('admin')
  const [loginPassword, setLoginPassword] = useState('')
  const [loginLoading, setLoginLoading] = useState(false)
  const [loginError, setLoginError] = useState('')
  const [loggedInUsername, setLoggedInUsername] = useState('')
  const [files, setFiles] = useState<KnowledgeFileItem[]>([])
  const [total, setTotal] = useState(0)
  const [filesLoading, setFilesLoading] = useState(false)
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS)
  const [appliedFilters, setAppliedFilters] = useState<Filters>(EMPTY_FILTERS)
  const [uploadOpen, setUploadOpen] = useState(false)
  const [uploadFile, setUploadFile] = useState<File | null>(null)
  const [uploadCategory, setUploadCategory] = useState<KnowledgeCategory>('laws')
  const [uploading, setUploading] = useState(false)
  const [duplicateChecking, setDuplicateChecking] = useState(false)
  const [duplicateFile, setDuplicateFile] = useState<KnowledgeFileItem | null>(null)
  const [duplicateCheckError, setDuplicateCheckError] = useState('')
  const [preview, setPreview] = useState<PreviewState>(null)
  const [previewLoadingId, setPreviewLoadingId] = useState('')
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  const authReady = Boolean(token)
  const hasActiveFilters = Object.values(appliedFilters).some(Boolean)
  const parsingCount = useMemo(
    () => files.filter((file) => file.status === 'parsing').length,
    [files],
  )
  const failedCount = useMemo(
    () => files.filter((file) => file.status === 'failed').length,
    [files],
  )

  const reloadFiles = useCallback(async () => {
    if (!token) {
      return
    }
    setFilesLoading(true)
    try {
      const params = new URLSearchParams()
      if (appliedFilters.name.trim()) params.set('name', appliedFilters.name.trim())
      if (appliedFilters.category) params.set('category', appliedFilters.category)
      if (appliedFilters.status) params.set('status', appliedFilters.status)
      if (appliedFilters.dateFrom) params.set('date_from', appliedFilters.dateFrom)
      if (appliedFilters.dateTo) params.set('date_to', appliedFilters.dateTo)
      const suffix = params.size ? `?${params.toString()}` : ''
      const response = await adminFetch(token, `/api/admin/knowledge/files${suffix}`)
      const payload = await readJson<KnowledgeFilePage>(response)
      setFiles(payload.items ?? [])
      setTotal(payload.total ?? 0)
    } catch (error) {
      onNotice(`文件加载失败：${describeError(error)}`)
    } finally {
      setFilesLoading(false)
    }
  }, [appliedFilters, onNotice, token])

  useEffect(() => {
    if (!token) {
      localStorage.removeItem(STORAGE_KEY)
      onNotice('知识库管理未登录')
      return
    }
    localStorage.setItem(STORAGE_KEY, token)
    const timeoutId = window.setTimeout(() => void reloadFiles(), 0)
    return () => window.clearTimeout(timeoutId)
  }, [onNotice, reloadFiles, token])

  useEffect(() => {
    if (!token || parsingCount === 0) {
      return
    }
    const intervalId = window.setInterval(() => void reloadFiles(), 4000)
    return () => window.clearInterval(intervalId)
  }, [parsingCount, reloadFiles, token])

  useEffect(
    () => () => {
      if (preview?.url) URL.revokeObjectURL(preview.url)
    },
    [preview],
  )

  const login = useCallback(async () => {
    setLoginLoading(true)
    setLoginError('')
    try {
      const response = await fetch('/api/admin/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: loginUsername, password: loginPassword }),
      })
      if (!response.ok) throw await responseError(response)
      const payload = await readJson<AdminLoginResponse>(response)
      setLoggedInUsername(payload.username)
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
    if (preview?.url) URL.revokeObjectURL(preview.url)
    setPreview(null)
    setLoggedInUsername('')
    setFiles([])
    setTotal(0)
    setToken('')
    setLoginError('')
    onNotice('管理员已退出')
  }, [onNotice, preview])

  const applyFilters = useCallback(() => setAppliedFilters({ ...filters }), [filters])
  const clearFilters = useCallback(() => {
    setFilters(EMPTY_FILTERS)
    setAppliedFilters(EMPTY_FILTERS)
  }, [])

  const selectUploadFile = useCallback(async (file: File | null) => {
    setUploadFile(file)
    setDuplicateFile(null)
    setDuplicateCheckError('')
    if (!token || !file) return
    setDuplicateChecking(true)
    try {
      const response = await adminFetch(
        token,
        `/api/admin/knowledge/files?name=${encodeURIComponent(file.name)}`,
      )
      const payload = await readJson<KnowledgeFilePage>(response)
      const duplicate = payload.items.find(
        (item) => item.name.normalize('NFKC').toLocaleLowerCase() === file.name.normalize('NFKC').toLocaleLowerCase(),
      )
      setDuplicateFile(duplicate ?? null)
    } catch (error) {
      setDuplicateCheckError(describeError(error))
    } finally {
      setDuplicateChecking(false)
    }
  }, [token])

  const uploadDocument = useCallback(async () => {
    if (!token || !uploadFile) return
    setUploading(true)
    try {
      const formData = new FormData()
      formData.append('file', uploadFile)
      formData.append('category', uploadCategory)
      await adminFetch(token, '/api/admin/knowledge/files', { method: 'POST', body: formData })
      onNotice(`已上传 ${uploadFile.name}，正在解析`)
      setUploadOpen(false)
      setUploadFile(null)
      setDuplicateFile(null)
      setDuplicateCheckError('')
      if (fileInputRef.current) fileInputRef.current.value = ''
      await reloadFiles()
    } catch (error) {
      if (error instanceof AdminRequestError && error.existing) {
        setDuplicateFile(error.existing)
      }
      onNotice(`上传失败：${describeError(error)}`)
    } finally {
      setUploading(false)
    }
  }, [onNotice, reloadFiles, token, uploadCategory, uploadFile])

  const openPreview = useCallback(
    async (file: KnowledgeFileItem) => {
      if (!token) return
      if (file.preview_kind === 'download') {
        await downloadDocument(file, token, onNotice)
        return
      }
      setPreviewLoadingId(file.id)
      try {
        const response = await adminFetch(token, `/api/admin/knowledge/files/${file.id}/content`)
        const url = URL.createObjectURL(await response.blob())
        setPreview((current) => {
          if (current?.url) URL.revokeObjectURL(current.url)
          return { file, url }
        })
      } catch (error) {
        onNotice(`预览失败：${describeError(error)}`)
      } finally {
        setPreviewLoadingId('')
      }
    },
    [onNotice, token],
  )

  const retryDocument = useCallback(
    async (file: KnowledgeFileItem) => {
      if (!token) return
      try {
        await adminFetch(token, `/api/admin/knowledge/files/${file.id}/retry`, { method: 'POST' })
        onNotice(`${file.name} 已重新提交解析`)
        await reloadFiles()
      } catch (error) {
        onNotice(`重试失败：${describeError(error)}`)
      }
    },
    [onNotice, reloadFiles, token],
  )

  const deleteDocument = useCallback(
    async (file: KnowledgeFileItem) => {
      if (!token || !window.confirm(`删除文件 ${file.name}？`)) return
      try {
        await adminFetch(token, `/api/admin/knowledge/files/${file.id}`, { method: 'DELETE' })
        if (preview?.file.id === file.id) setPreview(null)
        onNotice(`已删除 ${file.name}`)
        await reloadFiles()
      } catch (error) {
        onNotice(`删除失败：${describeError(error)}`)
      }
    },
    [onNotice, preview, reloadFiles, token],
  )

  return (
    <div className="admin-workbench knowledge-workbench">
      <div className="admin-header">
        <div className="admin-title">
          <p className="panel-kicker">资料中心</p>
          <h2>知识库文件</h2>
        </div>
        <div className="admin-statusbar">
          <span className={authReady ? 'pill success' : 'pill warning'}>
            {authReady ? `已登录${loggedInUsername ? ` · ${loggedInUsername}` : ''}` : '未登录'}
          </span>
          {authReady ? (
            <>
              <button
                type="button"
                className="primary-button"
                onClick={() => {
                  setUploadFile(null)
                  setDuplicateFile(null)
                  setDuplicateCheckError('')
                  setUploadOpen(true)
                }}
              >
                <Upload aria-hidden="true" />
                上传文件
              </button>
              <button type="button" className="ghost-button" onClick={logout}>
                <X aria-hidden="true" />
                退出
              </button>
              <button
                type="button"
                className="icon-button"
                onClick={() => void reloadFiles()}
                aria-label="刷新文件"
                title="刷新"
              >
                <RefreshCw aria-hidden="true" />
              </button>
            </>
          ) : null}
        </div>
      </div>

      {!authReady ? (
        <section className="admin-panel knowledge-login">
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
                onKeyDown={(event) => event.key === 'Enter' && void login()}
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
          {loginError ? <div className="turn-error admin-error">{loginError}</div> : null}
        </section>
      ) : (
        <>
          <section className="knowledge-filter-band" aria-label="文件筛选">
            <label className="field knowledge-search-field">
              <span>文件名</span>
              <div className="input-with-icon">
                <Search aria-hidden="true" />
                <input
                  value={filters.name}
                  onChange={(event) => setFilters((current) => ({ ...current, name: event.target.value }))}
                  onKeyDown={(event) => event.key === 'Enter' && applyFilters()}
                  placeholder="搜索文件"
                />
              </div>
            </label>
            <label className="field">
              <span>类别</span>
              <select
                value={filters.category}
                onChange={(event) =>
                  setFilters((current) => ({
                    ...current,
                    category: event.target.value as Filters['category'],
                  }))
                }
              >
                <option value="">全部类别</option>
                {CATEGORIES.map((item) => (
                  <option key={item.value} value={item.value}>{item.label}</option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>状态</span>
              <select
                value={filters.status}
                onChange={(event) =>
                  setFilters((current) => ({
                    ...current,
                    status: event.target.value as Filters['status'],
                  }))
                }
              >
                <option value="">全部状态</option>
                {STATUSES.map((item) => (
                  <option key={item.value} value={item.value}>{item.label}</option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>开始日期</span>
              <input
                type="date"
                value={filters.dateFrom}
                onChange={(event) => setFilters((current) => ({ ...current, dateFrom: event.target.value }))}
              />
            </label>
            <label className="field">
              <span>结束日期</span>
              <input
                type="date"
                value={filters.dateTo}
                onChange={(event) => setFilters((current) => ({ ...current, dateTo: event.target.value }))}
              />
            </label>
            <div className="knowledge-filter-actions">
              <button type="button" className="primary-button" onClick={applyFilters}>
                <Search aria-hidden="true" />
                筛选
              </button>
              <button
                type="button"
                className="icon-button"
                onClick={clearFilters}
                disabled={!hasActiveFilters && !Object.values(filters).some(Boolean)}
                aria-label="清除筛选"
                title="清除筛选"
              >
                <FilterX aria-hidden="true" />
              </button>
            </div>
          </section>

          <div className="knowledge-summary" aria-label="文件统计">
            <span><strong>{total}</strong> 个文件</span>
            <span><LoaderCircle aria-hidden="true" /> {parsingCount} 个解析中</span>
            <span><AlertCircle aria-hidden="true" /> {failedCount} 个失败</span>
          </div>

          <section className="knowledge-file-panel">
            <div className="knowledge-table" role="table" aria-label="知识库文件列表">
              <div className="knowledge-table-head" role="row">
                <span role="columnheader">文件</span>
                <span role="columnheader">类别</span>
                <span role="columnheader">上传时间</span>
                <span role="columnheader">大小</span>
                <span role="columnheader">状态</span>
                <span role="columnheader">操作</span>
              </div>
              {filesLoading ? (
                <div className="knowledge-empty">
                  <LoaderCircle className="spin" aria-hidden="true" />
                  <span>正在加载文件</span>
                </div>
              ) : files.length === 0 ? (
                <div className="knowledge-empty">
                  <FileText aria-hidden="true" />
                  <span>{hasActiveFilters ? '没有符合筛选条件的文件' : '暂无文件'}</span>
                </div>
              ) : (
                files.map((file) => (
                  <article className="knowledge-file-row" role="row" key={file.id}>
                    <div className="knowledge-file-name" role="cell">
                      <FileText aria-hidden="true" />
                      <div>
                        <strong>{file.name}</strong>
                        {file.status_message ? <small>{file.status_message}</small> : null}
                      </div>
                    </div>
                    <span role="cell" data-label="类别">{file.category_label}</span>
                    <span role="cell" data-label="上传时间">{formatDate(file.created_at)}</span>
                    <span role="cell" data-label="大小">{formatBytes(file.size)}</span>
                    <div role="cell" data-label="状态">
                      <StatusBadge file={file} />
                    </div>
                    <div className="knowledge-row-actions" role="cell">
                      <button
                        type="button"
                        className="icon-button"
                        onClick={() => void openPreview(file)}
                        disabled={previewLoadingId === file.id}
                        aria-label={`${file.preview_kind === 'download' ? '下载' : '预览'} ${file.name}`}
                        title={file.preview_kind === 'download' ? '下载' : '预览'}
                      >
                        {file.preview_kind === 'download' ? <Download aria-hidden="true" /> : <Eye aria-hidden="true" />}
                      </button>
                      {(file.status === 'failed' || file.status === 'uploaded') ? (
                        <button
                          type="button"
                          className="icon-button"
                          onClick={() => void retryDocument(file)}
                          aria-label={`重试 ${file.name}`}
                          title="重试解析"
                        >
                          <RotateCcw aria-hidden="true" />
                        </button>
                      ) : null}
                      <button
                        type="button"
                        className="icon-button danger-action"
                        onClick={() => void deleteDocument(file)}
                        aria-label={`删除 ${file.name}`}
                        title="删除"
                      >
                        <Trash2 aria-hidden="true" />
                      </button>
                    </div>
                  </article>
                ))
              )}
            </div>
          </section>
        </>
      )}

      {uploadOpen ? (
        <div className="knowledge-modal-backdrop" role="presentation" onMouseDown={() => !uploading && setUploadOpen(false)}>
          <section className="knowledge-upload-dialog" role="dialog" aria-modal="true" aria-labelledby="upload-title" onMouseDown={(event) => event.stopPropagation()}>
            <div className="panel-header">
              <div>
                <p className="panel-kicker">添加资料</p>
                <h3 id="upload-title">上传文件</h3>
              </div>
              <button type="button" className="icon-button" onClick={() => setUploadOpen(false)} disabled={uploading} aria-label="关闭上传">
                <X aria-hidden="true" />
              </button>
            </div>
            <label className="field">
              <span>资料类别</span>
              <select value={uploadCategory} onChange={(event) => setUploadCategory(event.target.value as KnowledgeCategory)}>
                {CATEGORIES.map((item) => (
                  <option key={item.value} value={item.value}>{item.label}</option>
                ))}
              </select>
            </label>
            <label className="knowledge-file-picker">
              <Upload aria-hidden="true" />
              <strong>{uploadFile?.name || '选择文件'}</strong>
              {uploadFile ? <span>{formatBytes(uploadFile.size)}</span> : null}
              <input
                ref={fileInputRef}
                type="file"
                onChange={(event) => void selectUploadFile(event.target.files?.[0] ?? null)}
              />
            </label>
            {duplicateChecking ? (
              <div className="knowledge-duplicate-checking">
                <LoaderCircle className="spin" aria-hidden="true" />
                正在检查同名文件
              </div>
            ) : duplicateFile ? (
              <div className="knowledge-duplicate-warning" role="alert">
                <AlertCircle aria-hidden="true" />
                <div>
                  <strong>同名文件已存在</strong>
                  <p>
                    {formatDate(duplicateFile.created_at)} 已上传过 {duplicateFile.name} · {duplicateFile.category_label} · {duplicateFile.status_label}
                  </p>
                </div>
              </div>
            ) : duplicateCheckError ? (
              <div className="knowledge-duplicate-warning" role="alert">
                <AlertCircle aria-hidden="true" />
                <div>
                  <strong>无法完成同名检查</strong>
                  <p>{duplicateCheckError}</p>
                </div>
              </div>
            ) : null}
            <div className="knowledge-dialog-actions">
              <button type="button" className="ghost-button" onClick={() => setUploadOpen(false)} disabled={uploading}>取消</button>
              <button
                type="button"
                className="primary-button"
                onClick={() => void uploadDocument()}
                disabled={!uploadFile || uploading || duplicateChecking || Boolean(duplicateFile) || Boolean(duplicateCheckError)}
              >
                {uploading ? <LoaderCircle className="spin" aria-hidden="true" /> : <Upload aria-hidden="true" />}
                {uploading ? '上传中' : '上传'}
              </button>
            </div>
          </section>
        </div>
      ) : null}

      {preview ? (
        <aside className="knowledge-preview-drawer" aria-label="文件预览">
          <div className="knowledge-preview-header">
            <div>
              <span>{preview.file.category_label}</span>
              <h3>{preview.file.name}</h3>
            </div>
            <div className="knowledge-row-actions">
              <button type="button" className="icon-button" onClick={() => void downloadDocument(preview.file, token, onNotice)} aria-label={`下载 ${preview.file.name}`} title="下载">
                <Download aria-hidden="true" />
              </button>
              <button type="button" className="icon-button" onClick={() => setPreview(null)} aria-label="关闭文件预览" title="关闭">
                <X aria-hidden="true" />
              </button>
            </div>
          </div>
          {preview.file.preview_kind === 'image' ? (
            <div className="knowledge-image-preview"><img src={preview.url} alt={preview.file.name} /></div>
          ) : preview.file.preview_kind === 'pdf' ? (
            <iframe src={preview.url} title={preview.file.name} />
          ) : (
            <iframe src={preview.url} title={preview.file.name} sandbox="" />
          )}
        </aside>
      ) : null}
    </div>
  )
}

function StatusBadge({ file }: { file: KnowledgeFileItem }) {
  const Icon = file.status === 'completed' ? CheckCircle2 : file.status === 'failed' ? AlertCircle : LoaderCircle
  return (
    <span className={`knowledge-status ${file.status}`}>
      <Icon className={file.status === 'parsing' ? 'spin' : ''} aria-hidden="true" />
      {file.status_label}
      {file.status === 'parsing' && file.progress !== null ? ` ${Math.round(file.progress * 100)}%` : ''}
    </span>
  )
}

async function downloadDocument(file: KnowledgeFileItem, token: string, onNotice: Props['onNotice']) {
  try {
    const response = await adminFetch(token, `/api/admin/knowledge/files/${file.id}/content?download=true`)
    const url = URL.createObjectURL(await response.blob())
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = file.name
    anchor.click()
    URL.revokeObjectURL(url)
  } catch (error) {
    onNotice(`下载失败：${describeError(error)}`)
  }
}

async function adminFetch(token: string, path: string, init: RequestInit = {}) {
  const headers = new Headers(init.headers || {})
  headers.set('Authorization', `Bearer ${token}`)
  if (init.body && !(init.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  const response = await fetch(path, { ...init, headers })
  if (!response.ok) throw await responseError(response)
  return response
}

async function responseError(response: Response) {
  const detail = await response.json().catch(() => null)
  const code = typeof detail?.detail?.code === 'string' ? detail.detail.code : `http_${response.status}`
  const message = typeof detail?.detail?.message === 'string' ? detail.detail.message : `HTTP ${response.status}`
  const existing = detail?.detail?.existing as KnowledgeFileItem | undefined
  return new AdminRequestError(code, message, existing ?? null)
}

async function readJson<T>(response: Response): Promise<T> {
  return (await response.json()) as T
}

function loadToken() {
  if (typeof window === 'undefined') return ''
  return window.localStorage.getItem(STORAGE_KEY) ?? ''
}

function describeError(error: unknown) {
  return error instanceof Error ? error.message : '请求失败'
}

function formatDate(value: string | null) {
  if (!value) return '未知'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(parsed)
}

function formatBytes(size: number) {
  if (!size) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  const index = Math.min(Math.floor(Math.log(size) / Math.log(1024)), units.length - 1)
  const value = size / 1024 ** index
  return `${value >= 10 || index === 0 ? value.toFixed(0) : value.toFixed(1)} ${units[index]}`
}
