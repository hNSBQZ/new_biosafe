import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { App } from './App'

describe('App', () => {
  it('renders the assistant workspace shell', () => {
    render(<App />)
    expect(screen.getByRole('heading', { name: '语音与文本助手' })).toBeInTheDocument()
    expect(screen.getByRole('navigation', { name: '主导航' })).toBeInTheDocument()
  })
})
