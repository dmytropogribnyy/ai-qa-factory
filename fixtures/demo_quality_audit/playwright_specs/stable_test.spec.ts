import { test, expect } from '@playwright/test';

/**
 * Demo fixture — stable test patterns.
 * Uses semantic locators, web-first assertions, and proper goto options.
 * This file is used by the Phase 5O flaky test analyzer as a "good patterns" baseline.
 */

const BASE = 'https://demo.playwright.dev/todomvc';

test.describe('TodoMVC — stable examples', () => {

  test('homepage loads and has correct title', async ({ page }) => {
    await page.goto(BASE, { waitUntil: 'domcontentloaded' });
    await expect(page).toHaveTitle(/TodoMVC/);
  });

  test('add a todo item using getByRole', async ({ page }) => {
    await page.goto(BASE, { waitUntil: 'domcontentloaded' });
    const input = page.getByRole('textbox', { name: 'What needs to be done?' });
    await expect(input).toBeVisible();
    await input.fill('Buy groceries');
    await input.press('Enter');
    await expect(page.getByText('Buy groceries')).toBeVisible();
  });

  test('mark todo as complete using getByLabel', async ({ page }) => {
    await page.goto(BASE, { waitUntil: 'domcontentloaded' });
    const input = page.getByRole('textbox', { name: 'What needs to be done?' });
    await input.fill('Write tests');
    await input.press('Enter');
    const checkbox = page.getByLabel('Write tests');
    await expect(checkbox).not.toBeChecked();
    await checkbox.check();
    await expect(checkbox).toBeChecked();
  });

  test('filter todos by active using getByRole link', async ({ page }) => {
    await page.goto(BASE, { waitUntil: 'domcontentloaded' });
    const input = page.getByRole('textbox', { name: 'What needs to be done?' });
    await input.fill('Task one');
    await input.press('Enter');
    await input.fill('Task two');
    await input.press('Enter');
    await page.getByLabel('Task one').check();
    await page.getByRole('link', { name: 'Active' }).click();
    await expect(page.getByText('Task two')).toBeVisible();
    await expect(page.getByText('Task one')).not.toBeVisible();
  });

  test('clear completed todos using getByRole button', async ({ page }) => {
    await page.goto(BASE, { waitUntil: 'domcontentloaded' });
    const input = page.getByRole('textbox', { name: 'What needs to be done?' });
    await input.fill('Done task');
    await input.press('Enter');
    await page.getByLabel('Done task').check();
    const clearBtn = page.getByRole('button', { name: 'Clear completed' });
    await expect(clearBtn).toBeVisible();
    await clearBtn.click();
    await expect(page.getByText('Done task')).not.toBeVisible();
  });

});
