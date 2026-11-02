import { defineConfig, devices } from '@playwright/test';
export default defineConfig({
  testDir: './tests', testMatch: '**/*.spec.ts', fullyParallel: false, workers: 1, timeout: 60000,
  use: { baseURL: process.env.DOSYM_TEST_BASE_URL || 'http://127.0.0.1:3000', trace: 'retain-on-failure', reducedMotion: 'reduce', // the home demo gesture is skipped under reduced motion
    // Most specs assert Russian strings; the Kazakh default is covered in locales.spec.ts.
    storageState: { cookies: [], origins: [{ origin: process.env.DOSYM_TEST_BASE_URL || 'http://127.0.0.1:3000', localStorage: [{ name: 'dosym-locale', value: 'ru' }] }] } },
  projects: [{ name: 'desktop', use: { ...devices['Desktop Chrome'], channel: 'msedge' } }],
});
