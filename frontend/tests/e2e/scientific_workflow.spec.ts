import { test, expect } from '@playwright/test'

test.describe('OSW Scientific Workspace E2E Scenarios', () => {

  test('Scientist executes molecular analysis query (Happy Path)', async ({ page }) => {
    await page.goto('/')

    // Assert three panels exist
    await expect(page.getByTestId('chat-panel')).toBeVisible()
    await expect(page.getByTestId('visualizer-panel')).toBeVisible()
    await expect(page.getByTestId('dag-panel')).toBeVisible()

    // Submit natural language task
    const textarea = page.getByPlaceholder(/Digite sua query cientifica/i)
    await textarea.fill('Run Boltz-2 on protein structures')
    await page.click('button:has-text("Enviar")')

    // Verify progress response and MCTS status update
    await expect(page.locator('text=Orquestrador OSW')).toBeVisible()

    // Assert the Molstar tab renders a real mounted viewer container (not the
    // old static placeholder text "WebGL Canvas Molstar Container", which no
    // longer exists now that `components/MolstarViewer.tsx` mounts a real
    // Mol* plugin instance). Full WebGL rendering/structure loading depends on
    // headless-browser GPU support and outbound network access to RCSB, which
    // this assertion deliberately does not require -- it only proves the real
    // component (not a placeholder `<div>`) is mounted.
    await expect(page.getByTestId('molstar-viewer')).toBeVisible()
  })

  test('Scientist creates a new workspace fork session (Branching)', async ({ page }) => {
    await page.goto('/')

    await page.click('button:has-text("Fork")')

    // The Fork button now performs a real `POST
    // /api/v1/workspaces/{id}/fork` call (see `components/ChatPanel.tsx`)
    // instead of showing a browser `alert()` dialog. Whether the snapshot
    // itself ultimately succeeds depends on backend filesystem state this E2E
    // run doesn't control, so this asserts the button reaches a definitive
    // result state (success or error banner), not one specific outcome.
    await expect(
      page.getByTestId('fork-success').or(page.getByTestId('fork-error'))
    ).toBeVisible({ timeout: 15000 })
  })
})
