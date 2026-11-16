import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

afterEach(() => cleanup())

// jsdom has no layout: scrolling a box into view is a no-op in tests.
Element.prototype.scrollIntoView = function scrollIntoView() {}
