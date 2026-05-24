import { test, expect } from '@playwright/test';

test('login works', async ({ page }) => {
  await page.goto('https://example.com/login');
  await page.waitForTimeout(3000);
  await page.locator('.input:nth-child(1)').fill('user@example.com');
  await page.locator('.input:nth-child(2)').fill('password');
  await page.locator('.btn').click();
  expect(await page.url()).toContain('dashboard');
});
