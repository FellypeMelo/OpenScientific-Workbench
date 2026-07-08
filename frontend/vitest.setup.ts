import '@testing-library/jest-dom'

// `@xyflow/react` (used by `components/MCTSGraph.tsx`) observes container size
// via `ResizeObserver`, which jsdom does not implement. A minimal no-op stub is
// enough for component tests that don't assert on layout/measurement, only on
// node/edge presence.
if (typeof globalThis.ResizeObserver === 'undefined') {
  class ResizeObserverStub {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  globalThis.ResizeObserver = ResizeObserverStub
}
