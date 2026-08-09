import { defineConfig, devices } from '@playwright/test';

// Der Browser ist in dieser Umgebung vorinstalliert (PLAYWRIGHT_BROWSERS_PATH=
// /opt/pw-browsers); NICHT `playwright install` aufrufen. Passt die pinned
// @playwright/test-Version nicht zur vorinstallierten Version, greift der
// explizite executablePath auf den vorhandenen Chromium.
const PREINSTALLED_CHROMIUM = '/opt/pw-browsers/chromium';
import { existsSync } from 'fs';
const useSystemChromium = existsSync(PREINSTALLED_CHROMIUM);

export default defineConfig({
  testDir: './e2e/tests',
  // Der Django-Dev-Server rendert die schweren /neu/-Seiten in dieser Umgebung
  // langsam (viele Queries, grosses Base-Template) — 60 s Test-Budget gibt den
  // mehrstufigen Flows Luft und vermeidet Umgebungs-Flakes.
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['github'], ['html', { open: 'never' }]] : [['list']],
  use: {
    baseURL: 'http://127.0.0.1:8811',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    ...(useSystemChromium ? { launchOptions: { executablePath: PREINSTALLED_CHROMIUM } } : {}),
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
  webServer: {
    command: './e2e/run-server.sh',
    url: 'http://127.0.0.1:8811/login/',
    timeout: 120_000,
    reuseExistingServer: !process.env.CI,
    stdout: 'pipe',
    stderr: 'pipe',
  },
});
