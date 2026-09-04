import { useState } from 'react'
import { ArrowLeft, Database, FileSearch, LoaderCircle, Search } from 'lucide-react'
import { apiUrl } from './apiBase'

type RetrievalDataset = {
  id: string
  name: string
  chunk_method: string
}

type RetrievalChunk = {
  citation_index: number | null
  chunk_id: string
  dataset_id: string
  document_id: string
  document_name: string
  content: string
  page_numbers: number[]
  similarity: number | null
  vector_similarity: number | null
  term_similarity: number | null
}

type RetrievalMatchResponse = {
  question: string
  datasets: RetrievalDataset[]
  page_size: number
  similarity_threshold: number
  vector_similarity_weight: number
  chunks: RetrievalChunk[]
}

type Props = {
  onBack: () => void
  onNotice: (notice: string) => void
}

const STORAGE_KEY = 'biosafe-admin-token'

export function KnowledgeRetrievalPanel({ onBack, onNotice }: Props) {
  const [token] = useState(() => window.localStorage.getItem(STORAGE_KEY) ?? '')
  const [question, setQuestion] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<RetrievalMatchResponse | null>(null)

  async function retrieve() {
    const normalized = question.trim()
    if (!token || !normalized) return
    setLoading(true)
    setError('')
    try {
      const response = await fetch(apiUrl('/api/admin/knowledge/retrieval-match'), {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ question: normalized }),
      })
      if (!response.ok) throw await responseError(response)
      const payload = (await response.json()) as RetrievalMatchResponse
      setResult(payload)
      onNotice(`检索完成，共 ${payload.chunks.length} 条匹配`)
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : '检索请求失败'
      setError(message)
      setResult(null)
      onNotice(`检索失败：${message}`)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="admin-workbench retrieval-workbench">
      <div className="admin-header">
        <div className="retrieval-title-row">
          <button type="button" className="icon-button" onClick={onBack} aria-label="返回知识库" title="返回知识库">
            <ArrowLeft aria-hidden="true" />
          </button>
          <div className="admin-title">
            <p className="panel-kicker">知识检索</p>
            <h2>检索匹配</h2>
          </div>
        </div>
      </div>

      {!token ? (
        <section className="admin-panel retrieval-auth-state">
          <Database aria-hidden="true" />
          <h3>需要管理员登录</h3>
          <button type="button" className="primary-button" onClick={onBack}>返回知识库</button>
        </section>
      ) : (
        <>
          <form
            className="retrieval-query-band"
            onSubmit={(event) => {
              event.preventDefault()
              void retrieve()
            }}
          >
            <label className="field">
              <span>检索问题</span>
              <textarea
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                rows={3}
                placeholder="输入需要匹配的知识问题"
              />
            </label>
            <button type="submit" className="primary-button" disabled={loading || !question.trim()}>
              {loading ? <LoaderCircle className="spin" aria-hidden="true" /> : <Search aria-hidden="true" />}
              {loading ? '检索中' : '检索'}
            </button>
          </form>

          {error ? <div className="turn-error" role="alert">{error}</div> : null}

          {result ? (
            <>
              <section className="retrieval-config" aria-label="默认检索配置">
                <div>
                  <span>默认知识库</span>
                  <strong>{result.datasets.length}</strong>
                </div>
                <div>
                  <span>返回上限</span>
                  <strong>{result.page_size}</strong>
                </div>
                <div>
                  <span>相似度阈值</span>
                  <strong>{formatScore(result.similarity_threshold)}</strong>
                </div>
                <div>
                  <span>向量权重</span>
                  <strong>{formatScore(result.vector_similarity_weight)}</strong>
                </div>
                <div className="retrieval-dataset-list">
                  {result.datasets.map((dataset) => (
                    <span key={dataset.id} title={dataset.id}>
                      <Database aria-hidden="true" />
                      {dataset.name} · {methodLabel(dataset.chunk_method)}
                    </span>
                  ))}
                </div>
              </section>

              <section className="retrieval-results" aria-label="检索匹配结果">
                <div className="panel-header slim">
                  <div>
                    <p className="panel-kicker">匹配结果</p>
                    <h3>{result.chunks.length} 条 chunk</h3>
                  </div>
                </div>
                {result.chunks.length === 0 ? (
                  <div className="knowledge-empty">
                    <FileSearch aria-hidden="true" />
                    <span>当前默认配置没有返回匹配内容</span>
                  </div>
                ) : (
                  <div className="retrieval-chunk-list">
                    {result.chunks.map((chunk, index) => {
                      const dataset = result.datasets.find((item) => item.id === chunk.dataset_id)
                      return (
                        <article className="retrieval-chunk" key={chunk.chunk_id}>
                          <div className="retrieval-rank" aria-label={`排名 ${index + 1}`}>{index + 1}</div>
                          <div className="retrieval-chunk-body">
                            <div className="retrieval-chunk-head">
                              <div>
                                <strong>{chunk.document_name || chunk.document_id}</strong>
                                <span>{dataset?.name || chunk.dataset_id}</span>
                              </div>
                              <div className="retrieval-scores" aria-label="匹配分数">
                                <span>综合 {formatScore(chunk.similarity)}</span>
                                <span>向量 {formatScore(chunk.vector_similarity)}</span>
                                <span>关键词 {formatScore(chunk.term_similarity)}</span>
                              </div>
                            </div>
                            <p>{chunk.content}</p>
                            <div className="retrieval-chunk-foot">
                              <span>Chunk {chunk.chunk_id}</span>
                              <span>{chunk.page_numbers.length ? `页码 ${chunk.page_numbers.join(', ')}` : '无页码'}</span>
                            </div>
                          </div>
                        </article>
                      )
                    })}
                  </div>
                )}
              </section>
            </>
          ) : null}
        </>
      )}
    </div>
  )
}

async function responseError(response: Response) {
  const payload = await response.json().catch(() => null)
  const code = typeof payload?.detail?.code === 'string' ? payload.detail.code : `http_${response.status}`
  const message = typeof payload?.detail?.message === 'string' ? payload.detail.message : `HTTP ${response.status}`
  return new Error(`${code}: ${message}`)
}

function formatScore(value: number | null) {
  return value === null || !Number.isFinite(value) ? '—' : value.toFixed(3)
}

function methodLabel(method: string) {
  const labels: Record<string, string> = {
    laws: '法规标准',
    manual: 'SOP 与设备手册',
    table: '名录与表格',
    paper: '论文与报告',
    naive: '通用资料',
  }
  return labels[method] || method
}
