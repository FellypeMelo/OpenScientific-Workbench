import { test, expect } from '@playwright/test'

test.describe('OSW Scientific Workspace E2E Scenarios', () => {
  
  test('Scientist executes molecular analysis query (Happy Path)', async ({ page }) => {
    await page.goto('/')

    // Assert three panels exist
    await expect(page.getByTestId('chat-panel')).toBeVisible()
    await expect(page.getByTestId('visualizer-panel')).toBeVisible()
    await expect(page.getByTestId('dag-panel')).toBeVisible()

    // Submit natural language task
    const textarea = page.getByPlaceholderText(/Digite sua query cientifica/i)
    await textarea.fill('Run Boltz-2 on protein structures')
    await page.click('button:has-text("Enviar")')

    // Verify progress response and MCTS status update
    await expect(page.locator('text=Orquestrador OSW')).toBeVisible()
    
    // Assert visualizer contains Molstar tab active
    await expect(page.locator('text=WebGL Canvas Molstar Container')).toBeVisible()
  })

  test('Scientist creates a new workspace fork session (Branching)', async ({ page }) => {
    await page.goto('/')

    // Trigger fork session
    page.on('dialog', async (dialog) => {
      expect(dialog.message()).toContain('snapshot Btrfs')
      await dialog.accept()
    })
    
    await page.click('button:has-text("Fork")')
  })
})
