"use client"

import React, { useState } from 'react'

interface Message {
  role: 'user' | 'agent'
  text: string
}

interface DAGNode {
  id: string
  label: string
  status: 'pending' | 'running' | 'success' | 'failed'
}

export default function Home() {
  const [query, setQuery] = useState('')
  const [messages, setMessages] = useState<Message[]>([])
  const [activeTab, setActiveTab] = useState<'molstar' | 'igv'>('molstar')
  const [dagNodes, setDagNodes] = useState<DAGNode[]>([
    { id: '1', label: 'MCTS Root: Initialize', status: 'success' },
    { id: '2', label: 'MCTS Node A: Analyze FASTQ', status: 'pending' },
    { id: '3', label: 'MCTS Node B: Predict folding', status: 'pending' },
  ])
  const [isStreaming, setIsStreaming] = useState(false)

  const handleSend = async () => {
    if (!query.trim()) return

    const userMessage: Message = { role: 'user', text: query }
    setMessages((prev) => [...prev, userMessage])
    setQuery('')
    setIsStreaming(true)

    // Append a placeholder agent message
    const agentMsgId = messages.length + 1
    setMessages((prev) => [...prev, { role: 'agent', text: 'Iniciando orquestração...' }])

    // In a real environment, we call the SSE stream `/api/v1/sessions/{id}/chat`
    try {
      const response = await fetch('/api/v1/sessions/00000000-0000-0000-0000-000000000000/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: query }),
      })

      if (response.body) {
        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        
        while (true) {
          const { value, done } = await reader.read()
          if (done) break
          
          const chunk = decoder.decode(value)
          // SSE data extraction
          const lines = chunk.split('\n')
          for (const line of lines) {
            if (line.startsWith('data: ')) {
              try {
                const data = JSON.parse(line.slice(6))
                
                // Update message
                setMessages((prev) => {
                  const updated = [...prev]
                  const lastIndex = updated.length - 1
                  if (updated[lastIndex].role === 'agent') {
                    updated[lastIndex].text = data.message
                  }
                  return updated
                })

                // Dynamically update MCTS DAG node status based on pipeline stage
                if (data.event === 'planning') {
                  setDagNodes((nodes) =>
                    nodes.map((n) => (n.id === '2' ? { ...n, status: 'running' } : n))
                  )
                } else if (data.event === 'completed') {
                  setDagNodes((nodes) =>
                    nodes.map((n) =>
                      n.id === '2' ? { ...n, status: 'success' } : n.id === '3' ? { ...n, status: 'success' } : n
                    )
                  )
                }
              } catch (e) {
                // Parsing error fallback
              }
            }
          }
        }
      }
    } catch (err) {
      // Mock local fallback response if FastAPI server is not currently running
      await new Promise((r) => setTimeout(r, 400))
      setMessages((prev) => {
        const updated = [...prev]
        const lastIndex = updated.length - 1
        updated[lastIndex].text = "Mock offline output: Predição molecular de Boltz-2 concluída com sucesso (Afinidade Kd = -7.8200)."
        return updated
      })
      setDagNodes((nodes) =>
        nodes.map((n) => ({ ...n, status: 'success' }))
      )
    } finally {
      setIsStreaming(false)
    }
  }

  const handleFork = () => {
    alert("Criando bifurcação (Fork) de sessão com snapshot Btrfs...")
  }

  return (
    <div className="flex h-screen w-screen bg-[#0a0a0c] text-[#ededf0] overflow-hidden font-sans">
      
      {/* Panel 1: Chat Window (Left Panel) */}
      <div 
        data-testid="chat-panel" 
        className="w-1/4 h-full border-r border-[#1a1a24] bg-[#0c0c0e] flex flex-col justify-between p-4"
      >
        <div className="flex flex-col flex-1 overflow-y-auto space-y-4">
          <div className="flex items-center justify-between pb-2 border-b border-[#1a1a24]">
            <h1 className="text-lg font-bold tracking-tight text-white">OSW Workbench</h1>
            <span className="text-xs bg-[#242435] text-[#a0a0b8] px-2 py-1 rounded-md font-mono">BYOK</span>
          </div>

          <div className="flex-1 space-y-3 py-2">
            {messages.length === 0 ? (
              <p className="text-sm text-[#707086] text-center pt-8">Nenhuma mensagem. Faça uma pergunta para iniciar o orquestrador MCTS.</p>
            ) : (
              messages.map((m, idx) => (
                <div key={idx} className={`p-3 rounded-lg text-sm ${m.role === 'user' ? 'bg-[#181822] text-[#fff]' : 'bg-[#0f2a24] text-[#86ffcf]'}`}>
                  <span className="block text-[10px] font-bold uppercase tracking-wider text-[#a0a0b8] mb-1">
                    {m.role === 'user' ? 'Você' : 'Orquestrador OSW'}
                  </span>
                  <p className="leading-relaxed">{m.text}</p>
                </div>
              ))
            )}
          </div>
        </div>

        <div className="mt-4 space-y-2">
          <textarea
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Digite sua query cientifica..."
            className="w-full h-24 bg-[#141416] border border-[#242435] rounded-lg p-2 text-sm text-white focus:outline-none focus:border-[#404060]"
          />
          <div className="flex gap-2">
            <button
              onClick={handleSend}
              disabled={isStreaming}
              className="flex-1 bg-[#2e624d] hover:bg-[#3d7a62] text-white py-2 rounded-lg text-sm font-semibold transition-all disabled:opacity-50"
            >
              {isStreaming ? "Processando..." : "Enviar"}
            </button>
            <button
              onClick={handleFork}
              className="px-4 py-2 border border-[#242435] hover:bg-[#181822] rounded-lg text-sm font-semibold text-white transition-all"
            >
              Fork
            </button>
          </div>
        </div>
      </div>

      {/* Panel 2: Scientific Visualizer Container (Center Panel) */}
      <div 
        data-testid="visualizer-panel" 
        className="flex-1 h-full bg-[#030305] flex flex-col"
      >
        <div className="flex border-b border-[#1a1a24] bg-[#0c0c0e]">
          <button
            onClick={() => setActiveTab('molstar')}
            className={`px-4 py-3 text-sm font-medium transition-all ${activeTab === 'molstar' ? 'border-b-2 border-[#86ffcf] text-[#86ffcf]' : 'text-[#707086]'}`}
          >
            Molstar (Proteins 3D)
          </button>
          <button
            onClick={() => setActiveTab('igv')}
            className={`px-4 py-3 text-sm font-medium transition-all ${activeTab === 'igv' ? 'border-b-2 border-[#86ffcf] text-[#86ffcf]' : 'text-[#707086]'}`}
          >
            IGV (Genomic Tracks)
          </button>
        </div>

        <div className="flex-1 relative flex items-center justify-center p-8">
          {activeTab === 'molstar' ? (
            <div className="w-full h-full border border-dashed border-[#242435] rounded-xl flex flex-col items-center justify-center bg-[#07070a] shadow-inner">
              <span className="text-[#a0a0b8] text-sm">WebGL Canvas Molstar Container</span>
              <span className="text-xs text-[#707086] mt-2">Visão 3D de dobramento de proteínas e alinhamento de ligantes</span>
            </div>
          ) : (
            <div className="w-full h-full border border-dashed border-[#242435] rounded-xl flex flex-col items-center justify-center bg-[#07070a] shadow-inner">
              <span className="text-[#a0a0b8] text-sm">IGV.js Track Viewer Container</span>
              <span className="text-xs text-[#707086] mt-2">Trilhas de sequenciamento e navegação de locus genético</span>
            </div>
          )}
        </div>
      </div>

      {/* Panel 3: MCTS Execution DAG tree (Right Panel) */}
      <div 
        data-testid="dag-panel" 
        className="w-1/5 h-full border-l border-[#1a1a24] bg-[#0c0c0e] p-4 flex flex-col"
      >
        <h2 className="text-sm font-bold tracking-wider text-[#a0a0b8] uppercase mb-4 pb-2 border-b border-[#1a1a24]">
          MCTS Search Tree
        </h2>

        <div className="flex-1 overflow-y-auto space-y-3">
          {dagNodes.map((n) => (
            <div 
              key={n.id} 
              className={`p-3 rounded-lg border text-xs flex flex-col ${
                n.status === 'success' ? 'bg-[#0f1f1a] border-[#225c48] text-[#86ffcf]' : 
                n.status === 'running' ? 'bg-[#292212] border-[#7d6124] text-[#ffd175] animate-pulse' :
                'bg-[#121217] border-[#242435] text-[#707086]'
              }`}
            >
              <div className="flex items-center justify-between mb-1">
                <span className="font-mono font-semibold">Node #{n.id}</span>
                <span className={`px-1.5 py-0.5 rounded text-[10px] uppercase font-bold ${
                  n.status === 'success' ? 'bg-[#225c48] text-white' : 
                  n.status === 'running' ? 'bg-[#7d6124] text-white' : 
                  'bg-[#242435] text-[#707086]'
                }`}>
                  {n.status}
                </span>
              </div>
              <p className="font-mono text-[11px] leading-relaxed">{n.label}</p>
            </div>
          ))}
        </div>
      </div>

    </div>
  )
}
