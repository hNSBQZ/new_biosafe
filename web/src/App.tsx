import { Activity, BookOpen, History, MessageSquareText } from 'lucide-react'

export function App() {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand"><Activity aria-hidden="true" /> 生物安全助手</div>
        <nav aria-label="主导航">
          <a className="active" href="#assistant"><MessageSquareText />助手</a>
          <a href="#history"><History />历史</a>
          <a href="#knowledge"><BookOpen />知识库</a>
        </nav>
      </aside>
      <main>
        <header>
          <div>
            <p className="eyebrow">实验训练工作台</p>
            <h1>语音与文本助手</h1>
          </div>
          <span className="status"><i /> 服务就绪</span>
        </header>
        <section className="empty-state" aria-label="会话区域">
          <Activity aria-hidden="true" />
          <h2>选择实验后开始提问</h2>
          <p>回答与可核查来源会显示在这里。</p>
        </section>
      </main>
    </div>
  )
}
