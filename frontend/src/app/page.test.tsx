import { render, screen } from '@testing-library/react'
import { expect, test } from 'vitest'
import Home from './page'

test('renders three-panel layout containers', () => {
  render(<Home />)
  
  // Assert existence of the three primary scientific panels
  const chatPanel = screen.getByTestId('chat-panel')
  const visualizerPanel = screen.getByTestId('visualizer-panel')
  const dagPanel = screen.getByTestId('dag-panel')
  
  expect(chatPanel).toBeInTheDocument()
  expect(visualizerPanel).toBeInTheDocument()
  expect(dagPanel).toBeInTheDocument()
})

test('renders chat input textarea and submit button', () => {
  render(<Home />)
  
  const textarea = screen.getByPlaceholderText(/Digite sua query cientifica/i)
  const submitButton = screen.getByRole('button', { name: /Enviar/i })
  
  expect(textarea).toBeInTheDocument()
  expect(submitButton).toBeInTheDocument()
})

test('renders fork session button', () => {
  render(<Home />)
  
  const forkButton = screen.getByRole('button', { name: /Fork/i })
  expect(forkButton).toBeInTheDocument()
})
